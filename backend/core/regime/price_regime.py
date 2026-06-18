import numpy as np
import pandas as pd
import yfinance as yf
from core.config import REGIONS, CACHE_DIR
from core.tools.utils import get_cached_data, save_to_cache

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


def calculate_adx_series(high, low, close, period=14) -> pd.Series:
    """
    Calculates the full series of Average Directional Index (ADX-14).
    """
    if len(close) < period * 2:
        return pd.Series(20.0, index=close.index)
        
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
    return adx.fillna(20.0)


def detect_ticker(ticker: str) -> dict:
    """
    Determines if the ticker is currently in a MOMENTUM_TREND, MEAN_REVERSION_RANGE, or VOLATILE_RANGEBOUND regime.
    """
    ticker_clean = ticker.strip().upper()
    cache_key = f"price_regime_{ticker_clean}"
    
    # Try to fetch from 12-hour local file cache
    cached = get_cached_data(CACHE_DIR, cache_key, ttl_hours=12)
    if cached:
        print(f"[✓] [Cache Hit] 成功載入大盤價格氣候快取 ({ticker_clean})：{cached.get('regime')}")
        return cached

    try:
        t = yf.Ticker(ticker)
        # Fetch 2y history to get enough data for a stable 1-year rolling window of indicators
        hist = t.history(period="2y").dropna(subset=["Close"])
        if hist.empty or len(hist) < 30:
            return {"regime": "MOMENTUM_TREND", "adx": 20.0, "hurst": 0.50}
            
        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        
        # If we have less than 100 days of data, fallback to static thresholds (e.g. for unit tests)
        if len(close) < 100:
            adx_val = calculate_adx(high, low, close, period=14)
            hurst_val = calculate_hurst(close)
            if adx_val > 23.0 or hurst_val > 0.52:
                regime = "MOMENTUM_TREND"
            elif adx_val < 18.0 or hurst_val < 0.48:
                regime = "MEAN_REVERSION_RANGE"
            else:
                regime = "MOMENTUM_TREND"
                
            res = {
                "regime": regime,
                "adx": adx_val,
                "hurst": hurst_val,
                "ticker": ticker
            }
            try:
                save_to_cache(CACHE_DIR, cache_key, res)
            except Exception:
                pass
            return res
            
        # 1-year historical calibration window (approx 250 trading days)
        num_eval_days = min(250, len(close) - 60)
        
        # Calculate Hurst exponent series for the last num_eval_days
        hurst_series = []
        for i in range(len(close) - num_eval_days, len(close)):
            window = close.iloc[i - 59 : i + 1]
            hurst_series.append(calculate_hurst(window))
            
        adx_all = calculate_adx_series(high, low, close, period=14)
        adx_series = adx_all.iloc[-num_eval_days:]
        
        adx_val = float(adx_series.iloc[-1])
        hurst_val = float(hurst_series[-1])
        
        # Calculate percentile ranks (0.0 to 1.0)
        adx_pct = float((adx_series <= adx_val).sum() / len(adx_series))
        hurst_pct = float((pd.Series(hurst_series) <= hurst_val).sum() / len(hurst_series))
        
        # Classification criteria based on 1-year historical distribution
        if adx_pct >= 0.60 or hurst_pct >= 0.60:
            regime = "MOMENTUM_TREND"
        elif adx_pct <= 0.35 or hurst_pct <= 0.35:
            regime = "MEAN_REVERSION_RANGE"
        else:
            regime = "VOLATILE_RANGEBOUND"
            
        res = {
            "regime": regime,
            "adx": adx_val,
            "hurst": hurst_val,
            "adx_percentile": adx_pct,
            "hurst_percentile": hurst_pct,
            "ticker": ticker
        }
        try:
            save_to_cache(CACHE_DIR, cache_key, res)
        except Exception:
            pass
        return res
    except Exception as e:
        print(f"[!] Error detecting price regime for {ticker}: {e}")
        return {"regime": "MOMENTUM_TREND", "adx": 20.0, "hurst": 0.50}


def detect_region(region_code: str) -> dict:
    """
    Determines if the regional market is currently in a MOMENTUM_TREND, MEAN_REVERSION_RANGE, or VOLATILE_RANGEBOUND regime.
    """
    region_info = REGIONS.get(region_code)
    if not region_info:
        return {"regime": "MOMENTUM_TREND", "adx": 20.0, "hurst": 0.50}
        
    return detect_ticker(region_info["benchmark"])

    
