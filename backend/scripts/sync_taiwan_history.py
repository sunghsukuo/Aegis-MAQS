"""
Aegis-MAQS (Aegis Multi-Agent Quantmental System)
Script: scripts/sync_taiwan_history.py
Description:
    One-time historical synchronization script for Taiwan market chip data.
    Scrapes TWSE and TAIFEX daily data for the past N days to pre-populate 
    the local database, ensuring the system has a robust historical dataset 
    to fall back on during intraday runs (before 15:00 Taipei Time).
"""

import sys
from pathlib import Path

# Dynamic path bootstrapping: Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from datetime import datetime, timedelta
import time
from core.tools.liquidity_loader import fetch_taiwan_net_buy, fetch_taiwan_futures_oi
import core.db_manager as db

def sync_taiwan_history(days: int = 14):
    print("\033[93m==================================================\033[0m")
    print(f"🧪 歷史籌碼同步：同步過去 {days} 天的台股三大法人與期指數據")
    print("\033[93m==================================================\033[0m")
    
    today = datetime.now()
    synced_count = 0
    
    # We loop from 'days' ago up to yesterday/today
    for i in range(days, -1, -1):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        print(f"[*] 正在檢查 {target_date} 的數據...")
        
        try:
            # 1. Fetch daily institutional net buy from TWSE
            chip_data = fetch_taiwan_net_buy(target_date)
            
            # If all values are 0, it's a weekend or holiday (no trading)
            if (chip_data.get("foreign_net_buy", 0.0) == 0.0 and 
                chip_data.get("dealers_net_buy", 0.0) == 0.0 and 
                chip_data.get("investment_trust_net_buy", 0.0) == 0.0):
                print(f"   [-] {target_date} 為非交易日（週末或國定假日），跳過。")
                continue
                
            # 2. Fetch foreign futures net Open Interest from TAIFEX
            futures_oi = fetch_taiwan_futures_oi(target_date)
            
            # 3. Save to local database
            db.save_taiwan_chip(
                record_date=target_date,
                foreign_futures_net_oi=futures_oi,
                foreign_net_buy=chip_data["foreign_net_buy"],
                dealers_net_buy=chip_data["dealers_net_buy"],
                investment_trust_net_buy=chip_data["investment_trust_net_buy"]
            )
            print(f"   \033[92m[✓] 成功同步並寫入資料庫：{target_date}\033[0m")
            print(f"       - 外資現貨買賣超: {chip_data['foreign_net_buy']/100000000.0:+.2f} 億元")
            print(f"       - 投信現貨買賣超: {chip_data['investment_trust_net_buy']/100000000.0:+.2f} 億元")
            print(f"       - 自營商現貨買賣超: {chip_data['dealers_net_buy']/100000000.0:+.2f} 億元")
            print(f"       - 外資期指淨部位: {futures_oi:+,} 口")
            
            synced_count += 1
            
            # Sleep 2 seconds between requests to be polite to exchange APIs and avoid IP bans
            time.sleep(5.0)
            
        except Exception as e:
            print(f"   \033[91m[✗] 同步 {target_date} 失敗: {e}\033[0m")
            time.sleep(5.0)
            
    print("\033[93m==================================================\033[0m")
    print(f"\033[92m✓ 歷史數據同步完成！共成功寫入 {synced_count} 個交易日的真實數據。\033[0m")
    print("\033[93m==================================================\033[0m")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="台股歷史籌碼數據同步與清空工具")
    parser.add_argument("--days", type=int, default=14, help="指定同步過去的天數 (預設 14 天)")
    parser.add_argument("--clean", action="store_true", help="同步前先清空資料庫中現有的台灣籌碼歷史紀錄")
    
    args = parser.parse_args()
    
    if args.clean:
        print("\033[93m[*] 偵測到 --clean 參數。正在清空資料庫中的台股歷史籌碼紀錄...\033[0m")
        try:
            db.clear_taiwan_chip_history()
            print("\033[92m[✓] 資料表 'taiwan_chip_history' 已成功清空。\033[0m")
        except Exception as e:
            print(f"\033[91m[✗] 清空資料庫失敗: {e}\033[0m")
            sys.exit(1)
            
    sync_taiwan_history(days=args.days)
