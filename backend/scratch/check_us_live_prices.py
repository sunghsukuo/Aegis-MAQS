import sys
from pathlib import Path

# Add backend root to sys.path
backend_root = str(Path(__file__).resolve().parent.parent)
sys.path.append(backend_root)

import core.tools.yahoo_finance as yf_tool

tickers = ["NOW", "MU", "NUE", "MLM", "2881.TW", "2885.TW", "0050.TW", "0056.TW"]

print("==================================================")
print(" 🔍 測試：實時獲取股票價格與資料庫欄位對比")
print("==================================================")

for t in tickers:
    try:
        price = yf_tool.get_stock_price(t)
        print(f"Ticker: {t:8} | yfinance 實時價格: {price:,.2f}")
    except Exception as e:
        print(f"Ticker: {t:8} | Error: {e}")
