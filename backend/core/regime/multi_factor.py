import json
import time
from pathlib import Path
import pandas as pd
import yfinance as yf
from core.config import CACHE_DIR

MESO_CACHE_FILE = CACHE_DIR / "meso_regime.json"

def get_meso_cache_file(region_code: str) -> Path:
    return CACHE_DIR / f"meso_regime_{region_code}.json"

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

def fetch_taiwan_index_data(period: str = "60d") -> dict:
    """
    Downloads historical data for ^TWII, 2330.TW (TSMC), and 2881.TW (Fubon).
    Returns a dictionary of pandas Series or DataFrames.
    """
    tickers = {
        "TWII": "^TWII",
        "TSMC": "2330.TW",
        "FUBON": "2881.TW"
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

def detect_meso_regime(region_code: str = "US", force_refresh: bool = False) -> dict:
    """
    Detects the Meso-level (middle-tier) market regime using multi-index data.
    Classifies the market into:
      - BULL_GROWTH_ON  (Technology-led Bull)
      - BULL_VALUE_ON   (Traditional/Value-led Bull)
      - VOLATILE_PANIC  (High Volatility Panic/Rangebound)
      - BEAR_RISK_OFF   (Systemic Downtrend)
    """
    cache_file = get_meso_cache_file(region_code)
    
    # Check cache first
    if not force_refresh and cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if time.time() - mtime < 300:  # 5 minutes cache
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    if region_code == "Taiwan":
        default_result = {
            "regime": "BULL_GROWTH_ON",
            "vix": 16.0,
            "vix_scale": 1.0,
            "growth_ratio": 1.0,
            "risk_appetite": 1.0,
            "gspc_trend": "UP"
        }
        
        data = fetch_taiwan_index_data(period="60d")
        
        # Check if we have enough data for calculation
        for key in ["TWII", "TSMC", "FUBON"]:
            if data[key].empty or len(data[key]) < 20:
                return default_result
                
        # Align data by Date to prevent off-by-one errors on holidays
        aligned = pd.concat([
            data["TWII"]["Close"],
            data["TSMC"]["Close"],
            data["FUBON"]["Close"]
        ], axis=1).dropna()
        aligned.columns = ["TWII", "TSMC", "FUBON"]
        
        if len(aligned) < 20:
            return default_result
            
        twii_close = aligned["TWII"]
        tsmc_close = aligned["TSMC"]
        fubon_close = aligned["FUBON"]
        
        # 1. Volatility Calculation (rolling 20-day annualized realized return volatility)
        returns = twii_close.pct_change()
        latest_vol = float(returns.iloc[-20:].std() * (252 ** 0.5) * 100.0)
        vix_scale = float(max(0.3, min(15.0 / latest_vol if latest_vol > 0.0 else 15.0, 1.2)))
        
        # 2. TAIEX Trend: Compare to 50-day moving average
        latest_twii = float(twii_close.iloc[-1])
        ma_period = min(50, len(twii_close))
        twii_ma = float(twii_close.rolling(window=ma_period).mean().iloc[-1])
        twii_trend = "UP" if latest_twii >= twii_ma else "DOWN"
        
        # 3. Growth Ratio: TSMC / TWII
        growth_ratio = tsmc_close / twii_close
        latest_growth = float(growth_ratio.iloc[-1])
        growth_ma = float(growth_ratio.rolling(window=20).mean().iloc[-1])
        growth_trend = "UP" if latest_growth >= growth_ma else "DOWN"
        
        # 4. Risk Appetite (Value proxy): FUBON / TWII
        risk_appetite = fubon_close / twii_close
        latest_appetite = float(risk_appetite.iloc[-1])
        
        # Classification Logic
        # Keep 25% annualized return volatility as panic threshold confirmed by user
        if latest_vol > 25.0:
            regime = "VOLATILE_PANIC"
        elif twii_trend == "DOWN" and latest_vol > 20.0:
            regime = "BEAR_RISK_OFF"
        else:
            if growth_trend == "UP":
                regime = "BULL_GROWTH_ON"
            else:
                regime = "BULL_VALUE_ON"
                
        result = {
            "regime": regime,
            "vix": latest_vol,  # We use calculated realized volatility as the VIX equivalent
            "vix_scale": vix_scale,
            "growth_ratio": latest_growth,
            "risk_appetite": latest_appetite,
            "gspc_trend": twii_trend  # Keep key name "gspc_trend" consistent for schema compatibility
        }
    else:
        # Default to US
        default_result = {
            "regime": "BULL_GROWTH_ON",
            "vix": 15.0,
            "vix_scale": 1.0,
            "growth_ratio": 1.0,
            "risk_appetite": 1.0,
            "gspc_trend": "UP"
        }
        
        data = fetch_multi_index_data(period="60d")
        
        for key in ["GSPC", "IXIC", "RUT", "VIX"]:
            if data[key].empty or len(data[key]) < 20:
                return default_result
                
        # Align US data
        aligned = pd.concat([
            data["GSPC"]["Close"],
            data["IXIC"]["Close"],
            data["RUT"]["Close"],
            data["VIX"]["Close"]
        ], axis=1).dropna()
        aligned.columns = ["GSPC", "IXIC", "RUT", "VIX"]
        
        if len(aligned) < 20:
            return default_result
            
        gspc_close = aligned["GSPC"]
        ixic_close = aligned["IXIC"]
        rut_close = aligned["RUT"]
        vix_close = aligned["VIX"]
        
        latest_gspc = float(gspc_close.iloc[-1])
        latest_vix = float(vix_close.iloc[-1])
        
        vix_scale = get_vix_scale(latest_vix)
        
        ma_period = min(50, len(gspc_close))
        gspc_ma = float(gspc_close.rolling(window=ma_period).mean().iloc[-1])
        gspc_trend = "UP" if latest_gspc >= gspc_ma else "DOWN"
        
        growth_ratio = ixic_close / gspc_close
        latest_growth = float(growth_ratio.iloc[-1])
        growth_ma = float(growth_ratio.rolling(window=20).mean().iloc[-1])
        growth_trend = "UP" if latest_growth >= growth_ma else "DOWN"
        
        risk_appetite = rut_close / gspc_close
        latest_appetite = float(risk_appetite.iloc[-1])
        
        if latest_vix > 25.0:
            regime = "VOLATILE_PANIC"
        elif gspc_trend == "DOWN" and latest_vix > 20.0:
            regime = "BEAR_RISK_OFF"
        else:
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
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            
        # Also write to default file for backward compatibility
        if region_code == "US":
            with open(MESO_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Warning: Failed to write meso regime cache: {e}")
        
    return result
