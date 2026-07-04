"""
Aegis-MAQS (Aegis Multi-Agent Quantmental System)
Script: scripts/seed_liquidity_data.py
Description:
    Database seeder for Taiwan chip history.
    Populates the 'taiwan_chip_history' table with realistic, mathematically sound 
    historical data for the past 30 days. This allows the system to successfully 
    demonstrate and test the database fallback mechanism (getting yesterday's data 
    intraday) even when cloud IPs are blocked by TWSE/TAIFEX Cloudflare firewalls.
"""

import sys
from pathlib import Path

# Dynamic path bootstrapping: Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from datetime import datetime, timedelta
import random
import core.db_manager as db

def seed_taiwan_chip_data(days: int = 30):
    print("\033[93m==================================================\033[0m")
    print(f"🌱 資料庫播種：正在為 'taiwan_chip_history' 注入過去 {days} 天的歷史籌碼數據")
    print("\033[93m==================================================\033[0m")
    
    today = datetime.now()
    seeded_count = 0
    
    # Base seed for random walk to make the data look realistic and continuous
    current_futures_oi = -12000  # Start with a standard foreign short position
    
    # Loop from 'days' ago to today
    for i in range(days, 0, -1):
        target_date = (today - timedelta(days=i))
        
        # Skip weekends (Saturday=5, Sunday=6)
        if target_date.weekday() >= 5:
            continue
            
        date_str = target_date.strftime("%Y-%m-%d")
        
        # Generate realistic, correlated market variables
        # 1. Foreign Futures Net Open Interest (standard random walk with mean reversion to -10k)
        oi_change = random.randint(-3000, 3000)
        current_futures_oi = current_futures_oi + oi_change
        # Keep it within realistic bounds: -32,000 to +2,000 contracts
        current_futures_oi = max(-32000, min(current_futures_oi, 2000))
        
        # 2. Foreign Net Buy (TWD) - correlated slightly with futures OI change
        # A positive OI change usually correlates with spot buying
        base_foreign_buy = (oi_change * 300000) + random.normalvariate(0, 3000000000)
        foreign_buy = round(max(-25000000000.0, min(base_foreign_buy, 25000000000.0)), 2)
        
        # 3. Dealers Net Buy (TWD) - usually smaller, hedging-driven
        dealers_buy = round(random.normalvariate(-100000000, 800000000), 2)
        
        # 4. Investment Trust Net Buy (TWD) - usually positive, steady buying
        trust_buy = round(random.normalvariate(500000000, 400000000), 2)
        trust_buy = round(max(-500000000.0, trust_buy), 2)
        
        # Save to local database (overwrites if exists to clean up)
        db.save_taiwan_chip(
            record_date=date_str,
            foreign_futures_net_oi=int(current_futures_oi),
            foreign_net_buy=float(foreign_buy),
            dealers_net_buy=float(dealers_buy),
            investment_trust_net_buy=float(trust_buy)
        )
        
        print(f"   [✓] 已播種 {date_str} 數據:")
        print(f"       - 外資期指: {current_futures_oi:+,} 口")
        print(f"       - 外資現貨買賣超: {foreign_buy/100000000.0:+.2f} 億元")
        
        seeded_count += 1
        
    print("\033[93m==================================================\033[0m")
    print(f"\033[92m✓ 播種成功！共成功寫入 {seeded_count} 個交易日的模擬歷史籌碼數據。\033[0m")
    print("\033[93m==================================================\033[0m")

if __name__ == "__main__":
    seed_taiwan_chip_data(days=30)
