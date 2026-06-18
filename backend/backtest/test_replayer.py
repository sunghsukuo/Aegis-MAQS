import sys
from pathlib import Path

# Add backend directory to path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(BACKEND_ROOT))

import yfinance as yf
from backtest.replayer import set_simulated_date, apply_backtest_replayer_sandbox
from core.tools.yahoo_finance import get_stock_price, calculate_technical_metrics

def test_time_travel():
    print("[*] 正在載入歷史重播沙盒補丁...")
    apply_backtest_replayer_sandbox()
    
    # Target ticker: AAPL (Apple)
    ticker = "AAPL"
    
    # Set simulated date to a known historical date: 2022-06-15
    # On 2022-06-15, AAPL closed at $135.43
    set_simulated_date("2022-06-15")
    
    # 1. Test get_stock_price
    price_2022 = get_stock_price(ticker)
    print(f"[*] {ticker} 於 2022-06-15 的模擬收盤價: ${price_2022:.2f}")
    
    # AAPL closed around $135.43 on 2022-06-15 (due to stock splits/adjustments, it should be close, roughly $130-$140 range)
    assert 120.0 <= price_2022 <= 150.0, f"價格 {price_2022} 超出 2022-06-15 的合理區間！"
    
    # 2. Test calculate_technical_metrics
    print("[*] 正在計算 2022-06-15 的技術面指標...")
    tech_2022 = calculate_technical_metrics(ticker)
    print(f"[*] RSI_14: {tech_2022['rsi_14']} | ATR_14: {tech_2022['atr_14']} | Beta: {tech_2022['beta']}")
    
    assert tech_2022['rsi_14'] is not None, "RSI_14 計算失敗！"
    assert tech_2022['atr_14'] is not None, "ATR_14 計算失敗！"
    
    # 3. Reset simulated date and check if it returns current price (which should be > $150 in 2026)
    set_simulated_date(None)
    current_price = get_stock_price(ticker)
    print(f"[*] {ticker} 目前實時價格: ${current_price:.2f}")
    assert current_price > price_2022, "實時價格未回復（仍是歷史價格）！"
    
    print("[✓] 歷史重播與時間旅行測試成功！指標計算與防洩漏機制運作良好。")

if __name__ == "__main__":
    test_time_travel()
