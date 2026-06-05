import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from core.config import REGIONS, CACHE_DIR
from core.tools.utils import retry_on_exception, get_cached_data, save_to_cache

# All configured sector ETFs and constituents are loaded dynamically from config.py to maintain a Single Source of Truth!

@retry_on_exception(tries=3, delay=2, backoff=2)
def _get_stock_price_raw(ticker: str) -> float:
    """Internal raw function with robust retries for fetching current price."""
    t = yf.Ticker(ticker)
    # Try fast lookup
    price = t.fast_info.get("lastPrice")
    if price is not None:
        return float(price)
    # Fallback to history
    hist = t.history(period="1d")
    if not hist.empty:
        return float(hist["Close"].iloc[-1])
    raise ValueError(f"No price data available for {ticker}")

def get_stock_price(ticker: str) -> float:
    """Fetches the current market price for a given stock ticker (safe fallback)."""
    try:
        return _get_stock_price_raw(ticker)
    except Exception as e:
        print(f"[!] Permanent failure fetching price for {ticker} after retries: {e}")
        return 0.0

@retry_on_exception(tries=3, delay=2, backoff=2)
def _get_benchmark_performance_raw(region_code: str) -> dict:
    """Internal raw benchmark performance fetcher with retries."""
    region_info = REGIONS.get(region_code)
    if not region_info:
        return {}
        
    benchmark_ticker = region_info["benchmark"]
    t = yf.Ticker(benchmark_ticker)
    hist = t.history(period="3mo")
    if hist.empty or len(hist) < 22:
        raise ValueError(f"Insufficient historical data for benchmark {benchmark_ticker}")
        
    current_price = hist["Close"].iloc[-1]
    
    # Weekly (exactly 5 trading days ago, comparing -1 to -6)
    weekly_prev = hist["Close"].iloc[-6] if len(hist) >= 6 else hist["Close"].iloc[0]
    weekly_return = (current_price - weekly_prev) / weekly_prev
    
    # Monthly (exactly 20 trading days ago, comparing -1 to -21)
    monthly_prev = hist["Close"].iloc[-21] if len(hist) >= 21 else hist["Close"].iloc[0]
    monthly_return = (current_price - monthly_prev) / monthly_prev
    
    # Retrieve precise trading dates for transparency
    start_date_str = hist.index[-6].strftime("%Y-%m-%d") if len(hist) >= 6 else hist.index[0].strftime("%Y-%m-%d")
    end_date_str = hist.index[-1].strftime("%Y-%m-%d")
    
    return {
        "ticker": benchmark_ticker,
        "name": region_info["name"] + "大盤",
        "current_price": float(current_price),
        "weekly_return": float(weekly_return),
        "monthly_return": float(monthly_return),
        "start_date": start_date_str,
        "end_date": end_date_str
    }

def get_benchmark_performance(region_code: str) -> dict:
    """Calculates weekly and monthly ROI for regional benchmarks (safe fallback)."""
    try:
        return _get_benchmark_performance_raw(region_code)
    except Exception as e:
        print(f"Error fetching benchmark performance for {region_code}: {e}")
        return {"current_price": 0, "weekly_return": 0, "monthly_return": 0}

@retry_on_exception(tries=3, delay=2, backoff=2)
def _get_single_etf_performance(etf_ticker: str, label_name: str) -> dict:
    """Fetches single ETF weekly performance with robust retries."""
    t = yf.Ticker(etf_ticker)
    hist = t.history(period="10d")  # Pull slightly more to ensure enough days
    if hist.empty or len(hist) < 6:
        raise ValueError(f"No sufficient history data for ETF {etf_ticker}")
        
    close_now = hist["Close"].iloc[-1]
    close_5d_ago = hist["Close"].iloc[-6]  # Exactly 5 trading days difference
    
    weekly_return = (close_now - close_5d_ago) / close_5d_ago
    
    # Retrieve precise trading dates for calculations
    start_date_str = hist.index[-6].strftime("%Y-%m-%d")
    end_date_str = hist.index[-1].strftime("%Y-%m-%d")
    
    return {
        "ticker": etf_ticker,
        "label": label_name,
        "weekly_return": float(weekly_return),
        "current_price": float(close_now),
        "start_date": start_date_str,
        "end_date": end_date_str
    }

def get_sector_rankings(region_code: str) -> list:
    """Fetches weekly returns for configured sector ETFs and ranks them by performance (safe fallback)."""
    region_info = REGIONS.get(region_code)
    if not region_info:
        return []
        
    rankings = []
    
    # Load sectors dynamically from database (Phase 5 Dynamic Config)
    try:
        import core.db_manager as db
        sector_etfs = db.get_active_sectors(region_code)
    except Exception:
        sector_etfs = region_info.get("sector_etfs", {})
    
    # Calculate performance for each sector ETF using retried helper
    for etf_ticker, info_val in sector_etfs.items():
        try:
            # Extract sector label name safely from integrated config structure
            label_name = info_val["name"] if isinstance(info_val, dict) else info_val
            perf = _get_single_etf_performance(etf_ticker, label_name)
            rankings.append(perf)
        except Exception as e:
            print(f"Error ranking sector {etf_ticker} after permanent failures: {e}")
            
    # Sort in descending order (highest return first)
    rankings.sort(key=lambda x: x["weekly_return"], reverse=True)
    return rankings

_global_screener = None

def get_screener_instance():
    """Initializes and returns a cached global instance of QuantScreener to decouple screener dependency."""
    global _global_screener
    if _global_screener is None:
        from core.tools.screener import QuantScreener
        _global_screener = QuantScreener()
    return _global_screener

def get_etf_holdings(etf_ticker: str, region: str = None, market_regime: str = None) -> list:
    """
    Exposes a unified dynamic constituent scanning interface for both screener scans 
    and sector evaluations. Resolves Single Source of Truth by referencing config.py.
    """
    etf_ticker = etf_ticker.strip().upper()
    if region is None:
        region = "Taiwan" if (".TW" in etf_ticker) else "US"
    screener = get_screener_instance()
    
    # Delegate to the regime-aware dynamic screener
    return screener.screen_stocks(etf_ticker, region=region, market_regime=market_regime)

@retry_on_exception(tries=3, delay=2, backoff=2)
def _calculate_technical_metrics_raw(ticker: str) -> dict:
    """Internal technical indicator calculator with retries."""
    t = yf.Ticker(ticker)
    # Pull 60 days history to ensure enough data for 14-day RSI, 20-day SMA, 14-day ATR, and Beta
    hist = t.history(period="60d")
    if hist.empty or len(hist) < 20:
        raise ValueError(f"Insufficient technical history for {ticker}")
        
    close = hist["Close"]
    sma_20 = float(close.iloc[-20:].mean())
    
    # 14-day RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    
    # Avoid division by zero
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi_14 = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
    
    # Calculate 14-day ATR (Average True Range)
    atr_14 = None
    try:
        high = hist["High"]
        low = hist["Low"]
        close_prev = hist["Close"].shift(1)
        
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_14 = float(tr.rolling(window=14).mean().iloc[-1])
        if pd.isna(atr_14):
            atr_14 = None
    except Exception:
        pass
        
    # Calculate Beta vs benchmark index
    beta = 1.0
    try:
        region = "Taiwan" if (ticker.endswith(".TW") or ticker.endswith(".TWO")) else "US"
        benchmark_ticker = "^TWII" if region == "Taiwan" else "^GSPC"
        
        # Nested network request also protected with a single try block
        bench_hist = yf.Ticker(benchmark_ticker).history(period="60d")
        if not bench_hist.empty and len(hist) >= 20:
            stock_returns = close.pct_change().dropna()
            bench_returns = bench_hist["Close"].pct_change().dropna()
            aligned = pd.concat([stock_returns, bench_returns], axis=1).dropna()
            aligned.columns = ["stock", "bench"]
            if len(aligned) >= 15:
                cov = aligned["stock"].cov(aligned["bench"])
                var = aligned["bench"].var()
                if var > 0:
                    beta = float(cov / var)
                    beta = max(0.3, min(beta, 3.0))
    except Exception:
        pass
        
    return {"rsi_14": rsi_14, "sma_20": sma_20, "atr_14": atr_14, "beta": beta}

def calculate_technical_metrics(ticker: str) -> dict:
    """Calculates basic technical indicators (safe fallback)."""
    try:
        return _calculate_technical_metrics_raw(ticker)
    except Exception as e:
        print(f"Error calculating technical metrics for {ticker}: {e}")
        return {"rsi_14": None, "sma_20": None, "atr_14": None, "beta": 1.0}

@retry_on_exception(tries=3, delay=2, backoff=2)
def _get_stock_financials_raw(ticker: str) -> dict:
    """Internal raw fundamentals fetcher with retries."""
    t = yf.Ticker(ticker)
    info = t.info
    fast_info = t.fast_info
    
    current_price = fast_info.get("lastPrice") or info.get("currentPrice") or info.get("regularMarketPrice")
    if not current_price:
        # Fallback to daily history
        hist = t.history(period="1d")
        if not hist.empty:
            current_price = hist["Close"].iloc[-1]
            
    if not current_price:
        raise ValueError(f"No current price available for fundamentals of {ticker}")
        
    # Determine if this ticker is an ETF or index proxy
    is_etf = False
    quote_type = info.get("quoteType")
    
    # Check if the sector config explicitly flags this as a stock (is_etf: False)
    is_etf_in_config = True
    try:
        import core.db_manager as db
        for r_code in REGIONS.keys():
            sec_config = db.get_active_sectors(r_code).get(ticker.upper())
            if isinstance(sec_config, dict) and sec_config.get("is_etf") is False:
                is_etf_in_config = False
                break
    except Exception:
        for r_info in REGIONS.values():
            sec_config = r_info.get("sector_etfs", {}).get(ticker.upper())
            if isinstance(sec_config, dict) and sec_config.get("is_etf") is False:
                is_etf_in_config = False
                break
            
    if quote_type == "ETF":
        is_etf = True
    elif quote_type == "EQUITY":
        is_etf = False
    else:
        # Fallback if yfinance quote_type is missing/rate-limited
        configured_etfs = set()
        try:
            import core.db_manager as db
            for r_code in REGIONS.keys():
                configured_etfs.update(k.upper() for k in db.get_active_sectors(r_code).keys())
        except Exception:
            configured_etfs = {etf.upper() for r in REGIONS.values() for etf in r.get("sector_etfs", {}).keys()}
            
        if ticker.upper() in configured_etfs and is_etf_in_config:
            is_etf = True
        
    # Get company name
    raw_name = info.get("longName") or info.get("shortName") or ticker
    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        ticker_num = ticker.split(".")[0]
        from core.tools.taiwan_stock_names import get_taiwan_stock_name
        db_name = get_taiwan_stock_name(ticker_num)
        if db_name:
            raw_name = f"{db_name} ({raw_name})"
            
    # Parse financials safely
    financials = {
        "ticker": ticker,
        "company_name": raw_name,
        "current_price": float(current_price),
        "is_etf_proxy": is_etf,
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "profit_margin": info.get("profitMargins"),
        "operating_margin": info.get("operatingMargins"),
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "revenue_growth": info.get("revenueGrowth"),
        "eps_growth": info.get("earningsGrowth"),
        "free_cash_flow": info.get("freeCashflow"),
        "fifty_day_sma": fast_info.get("fiftyDayAverage") or info.get("fiftyDayAverage"),
        "two_hundred_day_sma": fast_info.get("twoHundredDayAverage") or info.get("twoHundredDayAverage"),
        "recommendation_consensus": info.get("recommendationKey"),  # e.g., 'buy', 'strong_buy'
        # Wall Street Analyst Targets
        "analyst_target_mean": info.get("targetMeanPrice"),
        "analyst_target_high": info.get("targetHighPrice"),
        "analyst_target_low": info.get("targetLowPrice"),
        "analyst_count": info.get("numberOfAnalystOpinions"),
        "analyst_mean_score": info.get("recommendationMean"),
        # ETF specific fields
        "total_assets": info.get("totalAssets") or info.get("navPrice"),
        "dividend_yield": info.get("yield") or info.get("trailingAnnualDividendYield"),
        "nav_price": info.get("navPrice"),
        "rsi_14": None,
        "sma_20": None
    }
    
    # Calculate technical indicators
    tech = calculate_technical_metrics(ticker)
    financials["rsi_14"] = tech["rsi_14"]
    financials["sma_20"] = tech["sma_20"]
    financials["atr_14"] = tech.get("atr_14")
    financials["beta"] = tech.get("beta", 1.0)
    
    # Clean null values to standard Python None
    for k, v in financials.items():
        if pd.isna(v):
            financials[k] = None
            
    return financials

def get_stock_financials(ticker: str) -> dict:
    """Retrieves extensive fundamental metrics for the target stock ticker (safe fallback). Adapts automatically for ETFs."""
    ticker_clean = ticker.strip().upper()
    cache_key = f"financials_{ticker_clean}"
    
    # 1. Try to fetch from 12-hour local file cache
    cached = get_cached_data(CACHE_DIR, cache_key, ttl_hours=12)
    if cached:
        print(f"[✓] [Cache Hit] 成功載入 {ticker_clean} 的本地 12 小時財務與技術快取指標。")
        return cached
        
    # 2. Cache Miss: Fetch from network with retries, then cache it
    try:
        data = _get_stock_financials_raw(ticker)
        if data:
            save_to_cache(CACHE_DIR, cache_key, data)
        return data
    except Exception as e:
        print(f"Error fetching stock financials for {ticker} after permanent failures: {e}")
        return {}

@retry_on_exception(tries=3, delay=2, backoff=2)
def _calculate_roi_since_raw(ticker: str, purchase_date_str: str) -> dict:
    """Internal ROI calculator with retries."""
    t = yf.Ticker(ticker)
    # Pull historical data from purchase date onwards
    start_date = datetime.strptime(purchase_date_str, "%Y-%m-%d")
    # Pull up to current date (end date is exclusive in yfinance, so add 3 days buffer)
    end_date = datetime.now() + timedelta(days=3)
    
    hist = t.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
    if hist.empty:
        raise ValueError(f"No history data since {purchase_date_str} for {ticker}")
        
    purchase_price = hist["Close"].iloc[0]
    current_price = hist["Close"].iloc[-1]
    roi = (current_price - purchase_price) / purchase_price
    
    return {
        "purchase_price": float(purchase_price),
        "current_price": float(current_price),
        "roi": float(roi)
    }

def calculate_roi_since(ticker: str, purchase_date_str: str) -> dict:
    """Calculates ROI from a specific historical date to today (safe fallback)."""
    try:
        return _calculate_roi_since_raw(ticker, purchase_date_str)
    except Exception as e:
        print(f"Error calculating ROI for {ticker} since {purchase_date_str}: {e}")
        return {"purchase_price": 0.0, "current_price": 0.0, "roi": 0.0}
