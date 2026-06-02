import sys
from pathlib import Path
from datetime import datetime

# Add backend directory to path to ensure absolute imports work
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

import core.db_manager as db

def main():
    print("[*] 啟動昨日週報安全重構與數據庫重置工具...")
    target_date = "2026-05-30"
    
    try:
        with db.db_session() as conn:
            cursor = conn.cursor()
            
            # 1. 刪除昨日的交易歷史紀錄
            # 先取得昨日的 recommendation IDs
            db.execute_sql(cursor,
                "SELECT id FROM recommendations WHERE report_date = ?",
                "SELECT id FROM recommendations WHERE report_date = %s",
                (target_date,)
            )
            rows = cursor.fetchall()
            rec_ids = []
            for r in rows:
                if isinstance(r, dict):
                    rec_ids.append(r["id"])
                else:
                    rec_ids.append(r[0])
            
            if rec_ids:
                print(f"[*] 找到昨日的推薦 ID: {rec_ids}，正在清理對應的交易紀錄與推論日誌...")
                # 刪除 transaction_history 中與這些 ID 相關的紀錄
                placeholders_sqlite = ",".join(["?"] * len(rec_ids))
                placeholders_mysql = ",".join(["%s"] * len(rec_ids))
                
                db.execute_sql(cursor,
                    f"DELETE FROM transaction_history WHERE rec_id IN ({placeholders_sqlite})",
                    f"DELETE FROM transaction_history WHERE rec_id IN ({placeholders_mysql})",
                    tuple(rec_ids)
                )
                
                # 刪除可能殘留的 inference logs
                db.execute_sql(cursor,
                    f"DELETE FROM agent_inference_logs WHERE rec_id IN ({placeholders_sqlite})",
                    f"DELETE FROM agent_inference_logs WHERE rec_id IN ({placeholders_mysql})",
                    tuple(rec_ids)
                )
            
            # 2. 刪除昨日的 recommendations 紀錄
            db.execute_sql(cursor,
                "DELETE FROM recommendations WHERE report_date = ?",
                "DELETE FROM recommendations WHERE report_date = %s",
                (target_date,)
            )
            print("[✓] 已成功清除昨日 recommendations 與 transaction_history。")
            
            # 3. 重設 capital_ledger 資金水位回初始狀態
            db.execute_sql(cursor,
                "UPDATE capital_ledger SET available_capital = 100000.0, reserved_cash = 20000.0 WHERE currency = 'USD'",
                "UPDATE capital_ledger SET available_capital = 100000.0, reserved_cash = 20000.0 WHERE currency = 'USD'"
            )
            db.execute_sql(cursor,
                "UPDATE capital_ledger SET available_capital = 100000.0, reserved_cash = 20000.0 WHERE currency = 'USD'",
                "UPDATE capital_ledger SET available_capital = 100000.0, reserved_cash = 20000.0 WHERE currency = 'USD'" # Double-safeguard fallback
            )
            db.execute_sql(cursor,
                "UPDATE capital_ledger SET available_capital = 1000000.0, reserved_cash = 200000.0 WHERE currency = 'TWD'",
                "UPDATE capital_ledger SET available_capital = 1000000.0, reserved_cash = 200000.0 WHERE currency = 'TWD'"
            )
            print("[✓] 資金帳本（USD/TWD 可用資金與安全保留款）已成功恢復至沙盒初始值！")
            
        print("[*] 正在調度每週研報生成管線重新執行昨日週報...")
        # 執行 generate_report.py
        import subprocess
        # Run report generation for yesterday with --force
        cmd = [sys.executable, str(backend_dir / "aegis_cli.py"), "--force", "--date", target_date]
        print(f"[*] 執行指令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        print("\n=== 週報重置執行輸出 ===")
        print(result.stdout)
        if result.stderr:
            print("=== 錯誤輸出 ===")
            print(result.stderr)
            
        if result.returncode == 0:
            print("[✓] 昨日週報安全重構完成！所有持股已重新記帳，且 AI 分析推論日誌已完美入庫！")
        else:
            print("[✗] 重構失敗，週報管線執行出錯。")
            
    except Exception as e:
        print(f"[✗] 重構過程中發生嚴重異常: {e}")

if __name__ == "__main__":
    main()
