import numpy as np
import pandas as pd
import yfinance as yf
from core.config import REGIONS

def calculate_hurst(ts) -> float:
    """
    Calculates the Hurst Exponent of a time series.
    H < 0.5: Mean Reverting (Range-bound)
    H > 0.5: Trending (Persistent)
    H = 0.5: Random Walk
    """
    ts_arr = np.asarray(ts)
    if len(ts_arr) < 20:
        return 0.5 # Default to random walk
    
    lags = range(2, 15)
    # Standard deviation of differences is proportional to lag^H
    tau = []
    for lag in lags:
        diffs = ts_arr[lag:] - ts_arr[:-lag]
        std = np.std(diffs)
        # Avoid zero std to prevent log errors
        tau.append(std if std > 1e-8 else 1e-8)
        
    reg = np.polyfit(np.log(lags), np.log(tau), 1)
    return float(reg[0])


def calculate_adx(high, low, close, period=14) -> float:
    """
    Calculates the Average Directional Index (ADX-14).
    ADX > 25: Strong trend
    ADX < 20: Weak trend / range-bound
    """
    if len(close) < period * 2:
        return 20.0 # Default to range-bound if not enough data
        
    # True Range (TR)
    h_l = high - low
    h_pc = (high - close.shift(1)).abs()
    l_pc = (low - close.shift(1)).abs()
    tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    
    # Directional Movement (DM)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # Wilders smoothing or rolling mean
    tr_smooth = tr.rolling(window=period).mean()
    pos_di = 100 * (pd.Series(pos_dm, index=close.index).rolling(window=period).mean() / tr_smooth)
    neg_di = 100 * (pd.Series(neg_dm, index=close.index).rolling(window=period).mean() / tr_smooth)
    
    # Directional Index (DX)
    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di + 1e-8)
    
    # ADX
    adx = dx.rolling(window=period).mean()
    return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 20.0


def detect(region_code: str) -> dict:
    """
    Determines if the regional market is currently in a MOMENTUM_TREND or MEAN_REVERSION_RANGE regime.
    """
    region_info = REGIONS.get(region_code)
    if not region_info:
        return {"regime": "MOMENTUM_TREND", "adx": 20.0, "hurst": 0.50}
        
    benchmark_ticker = region_info["benchmark"]
    try:
        t = yf.Ticker(benchmark_ticker)
        # Fetch 60 trading days (approx 3 months)
        hist = t.history(period="60d").dropna(subset=["Close"])
        if hist.empty or len(hist) < 30:
            return {"regime": "MOMENTUM_TREND", "adx": 20.0, "hurst": 0.50}
            
        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        
        adx_val = calculate_adx(high, low, close, period=14)
        hurst_val = calculate_hurst(close)
        
        # Classification criteria
        # If ADX is high or Hurst is high, it is trending
        # If ADX is very low or Hurst is low, it is mean reverting
        if adx_val > 23.0 or hurst_val > 0.52:
            regime = "MOMENTUM_TREND"
        elif adx_val < 18.0 or hurst_val < 0.48:
            regime = "MEAN_REVERSION_RANGE"
        else:
            # Default fallback: check direction of ADX/Hurst or default to trending
            regime = "MOMENTUM_TREND"
            
        return {
            "regime": regime,
            "adx": adx_val,
            "hurst": hurst_val,
            "ticker": benchmark_ticker
        }
    except Exception as e:
        print(f"[!] Error detecting market regime for {region_code}: {e}")
        return {"regime": "MOMENTUM_TREND", "adx": 20.0, "hurst": 0.50}
