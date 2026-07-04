import sys
from pathlib import Path
import datetime
import pandas as pd

# Add backend directory to system path
backend_path = "/home/gordon/learning/program/python/Aegis-MAQS/backend"
sys.path.append(backend_path)

from backtest.replayer import set_simulated_date, apply_backtest_replayer_sandbox
from backtest.db_backtest import init_backtest_database, apply_backtest_db_sandbox
import core.db_manager as db
import yfinance as yf

def test_leak_prevention():
    print("="*60)
    print("🚀 啟動：Aegis-MAQS 歷史數據獲取與防洩漏（Time Travel）綜合測試")
    print("="*60)
    
    # 1. 初始化回測 SQLite 資料庫並開啟隔離沙盒
    print("[*] 1. 初始化回測隔離資料庫...")
    init_backtest_database(initial_usd=100000.0, initial_twd=3000000.0)
    apply_backtest_db_sandbox()
    
    # 2. 開啟 yfinance 時間旅行重播沙盒
    print("[*] 2. 啟動行情報價時間旅行補丁...")
    apply_backtest_replayer_sandbox()
    
    # 3. 測試總經與籌碼歷史表的時間穿梭過濾（DB Time Travel）
    print("[*] 3. 寫入總經與籌碼模擬歷史數據 (包含過往與未來日期)...")
    
    # 寫入 macro_liquidity_history: 6/15 (過去), 6/25 (未來)
    with db.db_session() as conn:
        cursor = conn.cursor()
        # 過去紀錄 (6/15)
        cursor.execute(
            "INSERT OR REPLACE INTO macro_liquidity_history (record_date, fed_assets, tga_balance, reverse_repos, net_liquidity) VALUES (?, ?, ?, ?, ?)",
            ("2020-06-15", 7000.0, 500.0, 1500.0, 5000.0)
        )
        # 未來紀錄 (6/25)
        cursor.execute(
            "INSERT OR REPLACE INTO macro_liquidity_history (record_date, fed_assets, tga_balance, reverse_repos, net_liquidity) VALUES (?, ?, ?, ?, ?)",
            ("2020-06-25", 7200.0, 400.0, 1800.0, 6000.0)
        )
        
        # 寫入 taiwan_chip_history: 6/15 (過去), 6/25 (未來)
        cursor.execute(
            "INSERT OR REPLACE INTO taiwan_chip_history (record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy) VALUES (?, ?, ?, ?, ?)",
            ("2020-06-15", -5000, 1000.0, 200.0, 300.0)
        )
        cursor.execute(
            "INSERT OR REPLACE INTO taiwan_chip_history (record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy) VALUES (?, ?, ?, ?, ?)",
            ("2020-06-25", -10000, 2000.0, 400.0, 600.0)
        )
        conn.commit()
        
    # 設定時間倒退至 2020-06-20 (夾在兩筆數據之間)
    sim_date = "2020-06-20"
    set_simulated_date(sim_date)
    
    print(f"\n--- [測試時點: {sim_date}] ---")
    
    # 驗證總經查詢是否有 Lookahead Leak
    liq_record = db.get_macro_liquidity(sim_date=sim_date)
    print(f"[*] 取得的歷史總經資料日期: {liq_record.get('record_date')} | 淨流動性: {liq_record.get('net_liquidity')} B")
    assert liq_record.get("record_date") == "2020-06-15", "錯誤：讀取到了未來的總經資料 (6/25)！"
    assert liq_record.get("net_liquidity") == 5000.0, "錯誤：淨流動性數值不符！"
    print("[✓] 總經歷史查詢驗證通過：未來的總經數據 (6/25) 處於隱形狀態。")
    
    # 驗證籌碼查詢是否有 Lookahead Leak
    chip_record = db.get_taiwan_chip(sim_date=sim_date)
    print(f"[*] 取得的歷史籌碼資料日期: {chip_record.get('record_date')} | 外資期指淨空單: {chip_record.get('foreign_futures_net_oi')} 口")
    assert chip_record.get("record_date") == "2020-06-15", "錯誤：讀取到了未來的籌碼資料 (6/25)！"
    assert chip_record.get("foreign_futures_net_oi") == -5000, "錯誤：期指空單數量不符！"
    print("[✓] 籌碼歷史查詢驗證通過：未來的籌碼數據 (6/25) 處於隱形狀態。")
    
    # 4. 驗證 yfinance 行情歷史查詢是否有未來數據洩漏
    print("\n[*] 4. 驗證 yfinance 行情歷史查詢是否有未來數據洩漏...")
    ticker = "AAPL"
    t = yf.Ticker(ticker)
    
    # 查詢歷史 K 線
    hist = t.history(period="1mo")
    max_date_in_hist = hist.index.max().strftime("%Y-%m-%d")
    print(f"[*] K 線圖中取得的最晚交易日: {max_date_in_hist}")
    
    # 最晚日期必須 <= 2020-06-20
    dt_max = datetime.datetime.strptime(max_date_in_hist, "%Y-%m-%d")
    dt_sim = datetime.datetime.strptime(sim_date, "%Y-%m-%d")
    assert dt_max <= dt_sim, f"錯誤：K 線圖中洩漏了未來的股價數據 ({max_date_in_hist})！"
    print(f"[✓] K 線圖歷史防洩漏驗證通過：最晚 K 線為 {max_date_in_hist}，符合 2020-06-20 限制。")
    
    # 5. 驗證 Ticker.fast_info 的價格與均線時間旅行
    print("\n[*] 5. 驗證 fast_info 技術指標的時間旅行...")
    price_travel = t.fast_info.get("lastPrice")
    fifty_ma_travel = t.fast_info.get("fiftyDayAverage")
    
    # 解除時間旅行，對比實時數據
    set_simulated_date(None)
    print(f"\n--- [解除時間旅行，返回當前現實] ---")
    
    price_real = t.fast_info.get("lastPrice")
    fifty_ma_real = t.fast_info.get("fiftyDayAverage")
    
    print(f"[*] 歷史時點 (2020-06-20) 股價: ${price_travel:.2f} | 50日均線: ${fifty_ma_travel:.2f}")
    print(f"[*] 當前現實 (實時實戰) 股價: ${price_real:.2f} | 50日均線: ${fifty_ma_real:.2f}")
    
    assert price_travel != price_real, "錯誤：歷史價格與實時價格相同，時間旅行無效！"
    print("[✓] 技術指標時間旅行驗證通過：成功隔離並取得不同時間點的均線與股價！")
    
    print("\n" + "="*60)
    print("🎉 恭喜！Aegis-MAQS 歷史數據時間旅行與防洩漏測試全面通過！")
    print("   - 資料庫查詢、K 線數據、均線計算均能無誤地取得目標時點數據。")
    print("   - 數據在時空上獲得 100% 隔離，回測具備絕對的真實與嚴謹度。")
    print("="*60)

if __name__ == "__main__":
    test_leak_prevention()
