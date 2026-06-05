import sys
from pathlib import Path
import json

# Add current directory to path
sys.path.append(str(Path(__file__).resolve().parent))

from core.config import REGIONS
import core.db_manager as db

def import_config_to_db():
    print("[*] 正在從 core/config.py 導入板塊設定至資料庫...")
    
    with db.db_session() as conn:
        cursor = conn.cursor()
        
        for region_code, region_info in REGIONS.items():
            sector_etfs = region_info.get("sector_etfs", {})
            
            for sector_code, sector_info in sector_etfs.items():
                sector_name = sector_info.get("name", sector_code)
                target_type = sector_info.get("target_type", "constituents")
                is_etf = 0 if sector_info.get("is_etf", True) is False else 1
                
                # 1. 寫入或更新板塊登記表 (利用 db.execute_sql 原生支援雙模)
                sqlite_sql = """
                    INSERT INTO sector_registry (region, sector_code, sector_name, target_type, is_etf, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(sector_code) DO UPDATE SET sector_name=excluded.sector_name, target_type=excluded.target_type, is_etf=excluded.is_etf
                """
                mysql_sql = """
                    INSERT INTO sector_registry (region, sector_code, sector_name, target_type, is_etf, is_active)
                    VALUES (%s, %s, %s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE sector_name=VALUES(sector_name), target_type=VALUES(target_type), is_etf=VALUES(is_etf)
                """
                db.execute_sql(cursor, sqlite_sql, mysql_sql, (region_code, sector_code, sector_name, target_type, is_etf))
                
                # 獲取剛才寫入的 sector_id
                db.execute_sql(cursor,
                    "SELECT id FROM sector_registry WHERE sector_code = ?",
                    "SELECT id FROM sector_registry WHERE sector_code = %s",
                    (sector_code,)
                )
                row = cursor.fetchone()
                if isinstance(row, dict):
                    sector_id = row["id"]
                elif isinstance(row, tuple):
                    sector_id = row[0]
                else:
                    sector_id = row
                
                # 2. 寫入成分股
                constituents = sector_info.get("constituents", [])
                
                # 獲取目前 DB 中該板塊已有的 constituents 進行比對
                db.execute_sql(cursor,
                    "SELECT ticker FROM sector_constituents WHERE sector_id = ?",
                    "SELECT ticker FROM sector_constituents WHERE sector_id = %s",
                    (sector_id,)
                )
                rows = cursor.fetchall()
                db_tickers = set()
                for r in rows:
                    if isinstance(r, dict):
                        db_tickers.add(r["ticker"])
                    elif isinstance(r, tuple):
                        db_tickers.add(r[0])
                    else:
                        db_tickers.add(r)
                
                # 插入/更新新名單中的成分股
                for ticker in constituents:
                    db.execute_sql(cursor,
                        "INSERT OR IGNORE INTO sector_constituents (sector_id, ticker) VALUES (?, ?)",
                        "INSERT IGNORE INTO sector_constituents (sector_id, ticker) VALUES (%s, %s)",
                        (sector_id, ticker)
                    )
                
                # 刪除已不在 config.py 名單中的成分股
                for old_ticker in db_tickers:
                    if old_ticker and old_ticker not in constituents:
                        db.execute_sql(cursor,
                            "DELETE FROM sector_constituents WHERE sector_id = ? AND ticker = ?",
                            "DELETE FROM sector_constituents WHERE sector_id = %s AND ticker = %s",
                            (sector_id, old_ticker)
                        )
                
                print(f"[✓] 已同步板塊: {sector_name} ({sector_code}) - 共 {len(constituents)} 檔成分股。")
                
    print("[✓] 同步完成！所有 config.py 設定已寫入資料庫。")

def export_db_to_json(filepath: str):
    print(f"[*] 正在從資料庫導出板塊配置至 {filepath}...")
    config_data = {}
    
    with db.db_session() as conn:
        cursor = conn.cursor()
        
        db.execute_sql(cursor,
            "SELECT id, region, sector_code, sector_name, target_type, is_etf FROM sector_registry WHERE is_active = 1",
            "SELECT id, region, sector_code, sector_name, target_type, is_etf FROM sector_registry WHERE is_active = 1"
        )
        sectors = cursor.fetchall()
        
        for sec in sectors:
            if isinstance(sec, dict):
                sec_id, region, code, name, t_type, is_etf = sec["id"], sec["region"], sec["sector_code"], sec["sector_name"], sec["target_type"], sec["is_etf"]
            else:
                sec_id, region, code, name, t_type, is_etf = sec
                
            if region not in config_data:
                config_data[region] = {}
                
            # 獲取成分股
            db.execute_sql(cursor,
                "SELECT ticker FROM sector_constituents WHERE sector_id = ?",
                "SELECT ticker FROM sector_constituents WHERE sector_id = %s",
                (sec_id,)
            )
            rows = cursor.fetchall()
            constituents = []
            for r in rows:
                if isinstance(r, dict):
                    constituents.append(r["ticker"])
                elif isinstance(r, tuple):
                    constituents.append(r[0])
                else:
                    constituents.append(r)
            
            config_data[region][code] = {
                "name": name,
                "target_type": t_type,
                "is_etf": True if is_etf == 1 else False,
            }
            if constituents:
                config_data[region][code]["constituents"] = constituents
                
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)
        
    print(f"[✓] 導出成功！已儲存至 {filepath}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Aegis-MAQS 板塊配置與資料庫雙向同步工具")
    parser.add_argument("--import", dest="import_action", action="store_true", help="讀取目前最新的 core/config.py，一鍵寫入資料庫（建立初始資料 Seed）")
    parser.add_argument("--export", dest="export_action", action="store_true", help="當您在資料庫手動修改成分股後，可一鍵將資料庫的配置更新回 core/config.py")
    args = parser.parse_args()
    
    from core.config import DATA_DIR
    json_path = str(DATA_DIR / "sectors_config.json")
    
    if args.export_action:
        export_db_to_json(json_path)
    elif args.import_action:
        import_config_to_db()
    else:
        # Default behavior: Print help if no action is specified
        parser.print_help()
