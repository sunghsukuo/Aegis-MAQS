import json
import time
import pandas as pd
import yfinance as yf
from core.config import CACHE_DIR

MESO_CACHE_FILE = CACHE_DIR / "meso_regime.json"

def fetch_multi_index_data(period: str = "60d") -> dict:
    """
    Downloads historical data for ^GSPC, ^IXIC, ^RUT, and ^VIX.
    Returns a dictionary of pandas Series or DataFrames.
    """
    tickers = {
        "GSPC": "^GSPC",
        "IXIC": "^IXIC",
        "RUT": "^RUT",
        "VIX": "^VIX"
    }
    data = {}
    for key, ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period).dropna(subset=["Close"])
            data[key] = hist
        except Exception as e:
            print(f"[!] Error fetching {ticker} data: {e}")
            data[key] = pd.DataFrame()
    return data

def get_vix_scale(vix_val: float) -> float:
    """
    Calculates the VIX panic correction scale.
    Base VIX is 15.0. If VIX rises above 15.0, scale decreases.
    Scale is clamped between 0.3 (maximum tightening) and 1.2 (slight relaxation when VIX is extremely low).
    """
    if vix_val <= 0.0:
        return 1.0
    scale = 15.0 / vix_val
    return float(max(0.3, min(scale, 1.2)))

def detect_meso_regime(force_refresh: bool = False) -> dict:
    """
    Detects the Meso-level (middle-tier) market regime using multi-index data.
    Classifies the market into:
      - BULL_GROWTH_ON  (Technology-led Bull)
      - BULL_VALUE_ON   (Traditional/Value-led Bull)
      - VOLATILE_PANIC  (High Volatility Panic/Rangebound)
      - BEAR_RISK_OFF   (Systemic Downtrend)
    """
    # Check cache first
    if not force_refresh and MESO_CACHE_FILE.exists():
        try:
            mtime = MESO_CACHE_FILE.stat().st_mtime
            if time.time() - mtime < 300:  # 5 minutes cache
                with open(MESO_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    default_result = {
        "regime": "BULL_GROWTH_ON",
        "vix": 15.0,
        "vix_scale": 1.0,
        "growth_ratio": 1.0,
        "risk_appetite": 1.0,
        "gspc_trend": "UP"
    }
    
    data = fetch_multi_index_data(period="60d")
    
    # Check if we have enough data for calculation
    for key in ["GSPC", "IXIC", "RUT", "VIX"]:
        if data[key].empty or len(data[key]) < 20:
            return default_result
            
    # Extract Close series
    gspc_close = data["GSPC"]["Close"]
    ixic_close = data["IXIC"]["Close"]
    rut_close = data["RUT"]["Close"]
    vix_close = data["VIX"]["Close"]
    
    # 1. Get latest values
    latest_gspc = float(gspc_close.iloc[-1])
    latest_vix = float(vix_close.iloc[-1])
    
    # 2. VIX scale calculation
    vix_scale = get_vix_scale(latest_vix)
    
    # 3. GSPC Trend: Compare to 50-day moving average (fallback to 20-day if less than 50 days available)
    ma_period = min(50, len(gspc_close))
    gspc_ma = float(gspc_close.rolling(window=ma_period).mean().iloc[-1])
    gspc_trend = "UP" if latest_gspc >= gspc_ma else "DOWN"
    
    # 4. Growth Ratio: IXIC / GSPC
    growth_ratio = ixic_close / gspc_close
    latest_growth = float(growth_ratio.iloc[-1])
    growth_ma = float(growth_ratio.rolling(window=20).mean().iloc[-1])
    growth_trend = "UP" if latest_growth >= growth_ma else "DOWN"
    
    # 5. Risk Appetite: RUT / GSPC
    risk_appetite = rut_close / gspc_close
    latest_appetite = float(risk_appetite.iloc[-1])
    
    # Classification Logic
    if latest_vix > 25.0:
        regime = "VOLATILE_PANIC"
    elif gspc_trend == "DOWN" and latest_vix > 20.0:
        regime = "BEAR_RISK_OFF"
    else:
        # Market is relatively healthy (GSPC UP or low VIX)
        if growth_trend == "UP":
            regime = "BULL_GROWTH_ON"
        else:
            regime = "BULL_VALUE_ON"
            
    result = {
        "regime": regime,
        "vix": latest_vix,
        "vix_scale": vix_scale,
        "growth_ratio": latest_growth,
        "risk_appetite": latest_appetite,
        "gspc_trend": gspc_trend
    }
    
    try:
        with open(MESO_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Warning: Failed to write meso regime cache: {e}")
        
    return result
