"""
Aegis-MAQS (Aegis Multi-Agent Quantmental System)
Module: core.tools.liquidity_loader
Description: 
    Consolidated macroeconomic liquidity and capital flow data loader.
    Fetches US Fed Net Liquidity from FRED API (via FredClient)
    and Taiwan Institutional Capital Flows from TWSE/TAIFEX APIs.
    Supports both real-time fetching (for Sandbox Live) and time-travel querying (for Backtesting).
    Features a robust Composite Liquidity Score (CLS) calculation and fail-safe database/simulation fallbacks.
    Designed with single-feature testability and Autonomous Computing alignment.
"""

import os
import sys
from pathlib import Path

# Dynamic path bootstrapping: Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import json
import csv
import urllib.request
from datetime import datetime, timedelta


# Import database manager for storing and retrieving historical liquidity records
import core.db_manager as db
# Import the newly created FRED API client
from core.tools.fred_client import FredClient

# Base paths
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BACKEND_ROOT / "core" / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Global execution-level caching flag to prevent redundant API syncs in the same run
_has_synced_this_run = False


# --- Section 1: US Macro Liquidity Fetcher (FRED) ---

def sync_us_liquidity_history(start_date: str = "2018-01-01") -> None:
    """
    Fetches historical US Fed Assets (WALCL), Treasury General Account (WTGANN),
    and Reverse Repurchase Agreements (RRPONTSYD) from the FRED API using FredClient.
    Calculates US Net Liquidity and syncs the records to the database table 'macro_liquidity_history'.
    
    Net Liquidity Equation:
        Net Liquidity = Fed Total Assets - TGA Balance - Reverse Repos
    This represents the actual bank reserves flowing into the financial system.
    
    Args:
        start_date (str): Start date for the historical synchronization. Default is '2018-01-01'
                          to cover pre-pandemic and post-pandemic macroeconomic cycles.
    """
    print(f"[*] Synchronizing US Macro Liquidity history from FRED starting from {start_date}...")
    
    try:
        client = FredClient()
    except Exception as e:
        print(f"[✗] Failed to initialize FredClient for synchronization: {e}")
        return
        
    # Fetch the 3 essential components of Fed Liquidity
    # WALCL: Fed Total Assets (Weekly Wednesday, reported in Millions of USD)
    assets = client.fetch_observations("WALCL", start_date=start_date)
    # WDTGAL: Treasury General Account Balance (Weekly Wednesday, reported in Millions of USD)
    tga = client.fetch_observations("WDTGAL", start_date=start_date)
    # RRPONTSYD: Overnight Reverse Repurchase Agreements (Daily, reported in Billions of USD)
    rrp = client.fetch_observations("RRPONTSYD", start_date=start_date)
    
    if not assets or not tga or not rrp:
        print("[✗] Error: Failed to retrieve complete FRED datasets. Synchronization aborted.")
        return
        
    synced_count = 0
    
    # We use WALCL (weekly Wednesdays) as our anchor dates.
    # We match TGA and RRP to these Wednesdays using interpolation/nearest-previous-date lookup.
    for date_str, asset_val in assets.items():
        # 1. Convert WALCL from Millions to Billions to match other units
        fed_assets_bil = asset_val / 1000.0
        
        # 2. Match TGA (in Millions, convert to Billions). If Wednesday is missing, find the nearest previous day (up to 7 days).
        tga_val = tga.get(date_str)
        if tga_val is None:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            for offset in range(1, 8):
                prev_date = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
                if prev_date in tga:
                    tga_val = tga[prev_date]
                    break
        tga_val_bil = (tga_val / 1000.0) if tga_val is not None else 0.0
                
        # 3. Match RRP (in Billions). If Wednesday is missing, find the nearest previous day (up to 7 days).
        rrp_val_bil = rrp.get(date_str)
        if rrp_val_bil is None:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            for offset in range(1, 8):
                prev_date = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
                if prev_date in rrp:
                    rrp_val_bil = rrp[prev_date]
                    break
            if rrp_val_bil is None:
                rrp_val_bil = 0.0
                
        # 4. Calculate Net Liquidity: Assets - TGA - RRP
        net_liq = fed_assets_bil - tga_val_bil - rrp_val_bil
        
        # Write to local database (SQLite/MySQL)
        db.save_macro_liquidity(
            record_date=date_str,
            fed_assets=float(fed_assets_bil),
            tga_balance=float(tga_val_bil),
            reverse_repos=float(rrp_val_bil),
            net_liquidity=float(net_liq)
        )
        synced_count += 1
        
    print(f"[✓] Successfully synchronized {synced_count} US Net Liquidity records to database.")


# --- Section 2: Taiwan Capital Flows Fetcher (TWSE / TAIFEX) ---

def fetch_taiwan_net_buy(date_str: str) -> dict:
    """
    Scrapes the TWSE Daily Institutional Buy/Sell Net API for a specific date (YYYYMMDD).
    Returns net buy values in TWD for Foreign Investors, Dealers, and Investment Trusts.
    
    Args:
        date_str (str): Target date in 'YYYY-MM-DD' format.
    """
    formatted_date = date_str.replace("-", "").replace("/", "")
    # Fixed critical typo: Changed from BFT41U (盤後定價交易) to BFI82U (三大法人買賣金額統計表)
    url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&dayDate={formatted_date}&type=day"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    result = {
        "foreign_net_buy": 0.0,
        "dealers_net_buy": 0.0,
        "investment_trust_net_buy": 0.0
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            
            # Check if there is valid data for this trading day
            if res_data.get("stat") == "OK" and "data" in res_data:
                for row in res_data["data"]:
                    # Row index 0: Institutional Investor Name (e.g. 外資及陸資, 自營商, 投信)
                    # Row index 3: Net Buy / Sell Amount (買賣差額)
                    investor_name = row[0].strip()
                    net_buy_str = row[3].replace(",", "").strip()
                    net_buy_val = float(net_buy_str)
                    
                    if "外資" in investor_name:
                        result["foreign_net_buy"] += net_buy_val
                    elif "自營商" in investor_name:
                        result["dealers_net_buy"] += net_buy_val
                    elif "投信" in investor_name:
                        result["investment_trust_net_buy"] += net_buy_val
    except Exception as e:
        # Graceful logging, let get_liquidity_state handle fallback
        print(f"[*] Note: TWSE net buy scraping encountered a silent exception on {date_str}: {e}")
        
    return result

def fetch_taiwan_futures_oi(date_str: str) -> int:
    """
    Scrapes the TAIFEX Daily Three Major Institutional Investors Futures Position API.
    Returns the Net Open Interest (淨未平倉口數) of Foreign Investors (外資及陸資).
    
    Args:
        date_str (str): Target date in 'YYYY-MM-DD' format.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = dt.strftime("%Y/%m/%d")
    
    # Daily CSV download endpoint
    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    import urllib.parse
    # Correct parameters: queryStartDate, queryEndDate, and commodityId
    # commodityId is 'TXF' for TAIEX Futures (臺股期貨)
    params = {
        "queryStartDate": formatted_date,
        "queryEndDate": formatted_date,
        "commodityId": "TXF"
    }
    payload = urllib.parse.urlencode(params).encode("utf-8")
    net_oi = 0
    
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode("big5", errors="ignore")  # TAIFEX CSV uses Big5 CJK encoding
            reader = csv.reader(content.splitlines())
            
            for row in reader:
                if len(row) < 13:
                    continue
                # Row index 1: Contract Name (e.g. 臺股期貨)
                # Row index 2: Institutional Investor (e.g. 外資及陸資)
                # Row index 11: Long Open Interest, Row index 12: Short Open Interest
                contract_name = row[1].replace(" ", "").strip()
                investor_name = row[2].replace(" ", "").strip()
                
                # We specifically track the main TAIEX Futures (臺股期貨 / TX) for foreign investors
                if "臺股期貨" in contract_name and "外資" in investor_name:
                    try:
                        # Index 9: 多方未平倉口數 (Column 10)
                        long_oi = int(row[9].replace(",", "").strip())
                        # Index 11: 空方未平倉口數 (Column 12)
                        short_oi = int(row[11].replace(",", "").strip())
                        net_oi = long_oi - short_oi
                        break
                    except ValueError:
                        continue
    except Exception as e:
        # Graceful logging, let get_liquidity_state handle fallback
        print(f"[*] Note: TAIFEX futures OI scraping encountered a silent exception on {date_str}: {e}")
        
    return net_oi


def backfill_taiwan_chip_history(until_date_str: str, window_days: int = 60) -> None:
    """
    Checks the past window_days calendar days before until_date_str.
    For any trading days (Monday to Friday) that do not exist in taiwan_chip_history,
    fetches the institutional net buy and futures OI online and saves them to the DB.
    """
    from datetime import datetime, timedelta
    import time
    
    until_dt = datetime.strptime(until_date_str, "%Y-%m-%d")
    print(f"[*] Checking and backfilling Taiwan chip history for the past {window_days} days before {until_date_str}...")
    
    backfilled_count = 0
    # Loop backwards through the window
    for i in range(1, window_days + 1):
        check_dt = until_dt - timedelta(days=i)
        # Skip weekends (Saturday=5, Sunday=6)
        if check_dt.weekday() >= 5:
            continue
            
        check_date_str = check_dt.strftime("%Y-%m-%d")
        
        # Check if record already exists for this exact date
        with db.db_session() as conn:
            cursor = conn.cursor()
            db.execute_sql(
                cursor,
                "SELECT COUNT(*) FROM taiwan_chip_history WHERE record_date = ?",
                "SELECT COUNT(*) FROM taiwan_chip_history WHERE record_date = %s",
                (check_date_str,)
            )
            row = cursor.fetchone()
            count = row["COUNT(*)"] if isinstance(row, dict) else row[0]
            if count > 0:
                continue
                
        # Record does not exist, fetch it online
        print(f"    [-] Backfilling Taiwan chip data for {check_date_str}...")
        try:
            chip_data = fetch_taiwan_net_buy(check_date_str)
            
            # Skip if it is a holiday/non-trading day (all values 0)
            if chip_data and chip_data.get("foreign_net_buy", 0.0) == 0.0 and chip_data.get("dealers_net_buy", 0.0) == 0.0 and chip_data.get("investment_trust_net_buy", 0.0) == 0.0:
                # Save zeros to prevent querying this day again in the future
                db.save_taiwan_chip(
                    record_date=check_date_str,
                    foreign_futures_net_oi=0,
                    foreign_net_buy=0.0,
                    dealers_net_buy=0.0,
                    investment_trust_net_buy=0.0
                )
                time.sleep(1.0)
                continue
                
            futures_oi = fetch_taiwan_futures_oi(check_date_str)
            
            foreign_net_buy = float(chip_data.get("foreign_net_buy", 0.0)) if chip_data else 0.0
            dealers_net_buy = float(chip_data.get("dealers_net_buy", 0.0)) if chip_data else 0.0
            trust_net_buy = float(chip_data.get("investment_trust_net_buy", 0.0)) if chip_data else 0.0
            
            db.save_taiwan_chip(
                record_date=check_date_str,
                foreign_futures_net_oi=int(futures_oi),
                foreign_net_buy=foreign_net_buy,
                dealers_net_buy=dealers_net_buy,
                investment_trust_net_buy=trust_net_buy
            )
            backfilled_count += 1
            # Throttle requests to avoid rate limits
            time.sleep(1.0)
        except Exception as e:
            print(f"    [!] Failed to backfill {check_date_str}: {e}")
            
    if backfilled_count > 0:
        print(f"[✓] Backfilled {backfilled_count} missing Taiwan chip records.")
    else:
        print("[✓] Taiwan chip history is already fully populated.")


# --- Section 3: Unified Liquidity Loader Facade (with Backtesting Support) ---

def get_liquidity_state(report_date: str, is_backtest: bool = False, force_refresh: bool = False) -> dict:
    """
    Unified facade to load the liquidity state for a specific date.
    Supports backtesting time-travel and sandbox live operations.
    
    If is_backtest is True:
        Queries the database for historical records where record_date <= report_date
        to enforce the time-travel constraint and eliminate lookahead bias.
        If database records are missing, initiates a proxy simulation.
        
    If is_backtest is False:
        Attempts to fetch live real-time data from APIs using FredClient and TWSE/TAIFEX scrapers.
        If live fetching fails, or it is a holiday/weekend (all-zero return),
        gracefully falls back to the latest database records, and finally to a safe default.
    """
    state = {
        "record_date": report_date,
        "us_net_liquidity": 0.0,
        "us_liquidity_roc_4w": 0.0,      # US Liquidity 4-week Rate of Change (ROC)
        "tw_foreign_futures_oi": 0,      # Taiwan Foreign Futures Net Open Interest (contracts)
        "tw_foreign_net_buy": 0.0,       # Taiwan Foreign Net Buy (TWD)
        "tw_dealers_net_buy": 0.0,       # Taiwan Dealers Net Buy (TWD)
        "tw_trust_net_buy": 0.0,         # Taiwan Investment Trust Net Buy (TWD)
        "composite_score": 0.5,          # CLS: 0.0 (Abundant Liquidity) to 1.0 (Severe Tightening)
        "source": "live"
    }
    
    # ---------------------------------------------------------
    # CASE 1: BACKTESTING MODE (Read from DB with time constraint)
    # ---------------------------------------------------------
    if is_backtest:
        state["source"] = "backtest_db"
        
        # 1. Fetch US Macro Liquidity from DB
        us_data = db.get_macro_liquidity(sim_date=report_date)
        if us_data:
            state["us_net_liquidity"] = us_data["net_liquidity"]
            
            # Calculate 4-week ROC to detect liquidity acceleration/deceleration
            # Fetch WALCL from 4 weeks (approx 28 days) ago
            dt = datetime.strptime(report_date, "%Y-%m-%d")
            four_weeks_ago = (dt - timedelta(days=28)).strftime("%Y-%m-%d")
            us_data_prev = db.get_macro_liquidity(sim_date=four_weeks_ago)
            if us_data_prev and us_data_prev["net_liquidity"] > 0.0:
                state["us_liquidity_roc_4w"] = (us_data["net_liquidity"] - us_data_prev["net_liquidity"]) / us_data_prev["net_liquidity"]
        else:
            # Proxy Simulation: If DB is completely empty (e.g., distant history), simulate neutral to slightly negative ROC
            state["us_net_liquidity"] = 5500.0  # Average baseline in Billions
            state["us_liquidity_roc_4w"] = -0.01  # Slightly contracting
            state["source"] = "backtest_proxy_sim"
            
        # 2. Fetch Taiwan Capital Flows from DB
        tw_data = db.get_taiwan_chip(sim_date=report_date)
        if tw_data:
            state["tw_foreign_futures_oi"] = tw_data["foreign_futures_net_oi"]
            state["tw_foreign_net_buy"] = tw_data["foreign_net_buy"]
            state["tw_dealers_net_buy"] = tw_data["dealers_net_buy"]
            state["tw_trust_net_buy"] = tw_data["investment_trust_net_buy"]
        else:
            # Proxy Simulation for Taiwan: If DB lacks old TAIFEX/TWSE records, 
            # simulate a slightly short foreign position (standard hedging state)
            state["tw_foreign_futures_oi"] = -8000
            state["tw_foreign_net_buy"] = -2000000000.0  # -2 Billion TWD
            state["tw_dealers_net_buy"] = -500000000.0
            state["tw_trust_net_buy"] = 300000000.0
            if state["source"] == "backtest_db":
                state["source"] = "backtest_hybrid_sim"
                
        # 3. Calculate Composite Liquidity Score (CLS)
        state["composite_score"] = calculate_composite_liquidity_score(state)
        return state

    # ---------------------------------------------------------
    # CASE 2: REAL-TIME LIVE SANDBOX MODE (Fetch and Save)
    # ---------------------------------------------------------
    
    # Check if a cache file exists and is less than 12 hours old to prevent API rate-limiting
    # Bypass the cache if force_refresh is True or "--force" is present in command-line arguments
    cache_file = CACHE_DIR / f"liquidity_live_{report_date}.json"
    bypass_cache = force_refresh or ("--force" in sys.argv)
    if cache_file.exists() and not bypass_cache:
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_state = json.load(f)
                cached_state["source"] = "live_cache"
                return cached_state
        except Exception:
            pass
            
    # Try fetching US Liquidity from FRED online via FredClient, otherwise fall back to DB
    try:
        global _has_synced_this_run
        if not _has_synced_this_run:
            # Perform an on-the-fly FRED sync to ensure our DB is up-to-date
            sync_us_liquidity_history(start_date="2020-01-01")
            
            # Automatically check and backfill missing Taiwan chip data for the past 60 days
            try:
                backfill_taiwan_chip_history(report_date, window_days=60)
            except Exception as bf_ex:
                print(f"[!] Warning: Failed to backfill Taiwan chip history: {bf_ex}")
                
            _has_synced_this_run = True
        us_data = db.get_macro_liquidity()
        if us_data:
            state["us_net_liquidity"] = us_data["net_liquidity"]
            
            # Calculate 4-week ROC
            dt = datetime.strptime(report_date, "%Y-%m-%d")
            four_weeks_ago = (dt - timedelta(days=28)).strftime("%Y-%m-%d")
            us_data_prev = db.get_macro_liquidity(sim_date=four_weeks_ago)
            if us_data_prev and us_data_prev["net_liquidity"] > 0.0:
                state["us_liquidity_roc_4w"] = (us_data["net_liquidity"] - us_data_prev["net_liquidity"]) / us_data_prev["net_liquidity"]
    except Exception as us_ex:
        print(f"[!] Warning: Live FRED fetching failed, falling back to DB: {us_ex}")
        # DB Fallback
        us_data = db.get_macro_liquidity()
        if us_data:
            state["us_net_liquidity"] = us_data["net_liquidity"]
            
            # Calculate 4-week ROC from the latest available date in the database
            latest_date = us_data["record_date"]
            dt = datetime.strptime(latest_date, "%Y-%m-%d")
            four_weeks_ago = (dt - timedelta(days=28)).strftime("%Y-%m-%d")
            us_data_prev = db.get_macro_liquidity(sim_date=four_weeks_ago)
            if us_data_prev and us_data_prev["net_liquidity"] > 0.0:
                state["us_liquidity_roc_4w"] = (us_data["net_liquidity"] - us_data_prev["net_liquidity"]) / us_data_prev["net_liquidity"]
                
    # Fetch Taiwan Capital Flows from official TWSE/TAIFEX APIs
    try:
        # 1. Fetch daily Institutional Net Buy
        chip_data = fetch_taiwan_net_buy(report_date)
        
        # If all values are 0, it is highly likely a non-trading day (weekend/holiday) or API error.
        # We raise a ValueError to trigger the database fallback, ensuring historical continuity.
        if (chip_data.get("foreign_net_buy", 0.0) == 0.0 and 
            chip_data.get("dealers_net_buy", 0.0) == 0.0 and 
            chip_data.get("investment_trust_net_buy", 0.0) == 0.0):
            raise ValueError("No active institutional trading data returned from TWSE API (possibly weekend, holiday, or network error).")
            
        state["tw_foreign_net_buy"] = chip_data["foreign_net_buy"]
        state["tw_dealers_net_buy"] = chip_data["dealers_net_buy"]
        state["tw_trust_net_buy"] = chip_data["investment_trust_net_buy"]
        
        # 2. Fetch foreign futures net OI
        state["tw_foreign_futures_oi"] = fetch_taiwan_futures_oi(report_date)
        
        # If we successfully fetched real-time data, save it to the database table
        # to incrementally build up our historical dataset for future backtesting!
        if state["tw_foreign_futures_oi"] != 0 or state["tw_foreign_net_buy"] != 0.0:
            db.save_taiwan_chip(
                record_date=report_date,
                foreign_futures_net_oi=state["tw_foreign_futures_oi"],
                foreign_net_buy=state["tw_foreign_net_buy"],
                dealers_net_buy=state["tw_dealers_net_buy"],
                investment_trust_net_buy=state["tw_trust_net_buy"]
            )
    except Exception as tw_ex:
        print(f"[!] Warning: Live Taiwan chip scraping failed or returned no data, falling back to DB: {tw_ex}")
        # DB Fallback - fetch the latest available record
        tw_data = db.get_taiwan_chip()
        if tw_data:
            state["tw_foreign_futures_oi"] = tw_data["foreign_futures_net_oi"]
            state["tw_foreign_net_buy"] = tw_data["foreign_net_buy"]
            state["tw_dealers_net_buy"] = tw_data["dealers_net_buy"]
            state["tw_trust_net_buy"] = tw_data["investment_trust_net_buy"]
        else:
            print("[!] Warning: Database 'taiwan_chip_history' is empty. Injecting safe neutral proxy simulation.")
            state["tw_foreign_futures_oi"] = -8000
            state["tw_foreign_net_buy"] = -2000000000.0  # -2 Billion TWD
            state["tw_dealers_net_buy"] = -500000000.0
            state["tw_trust_net_buy"] = 300000000.0
            state["source"] = "live_proxy_sim"
            
    # Calculate Composite Score
    state["composite_score"] = calculate_composite_liquidity_score(state)
    
    # Save to local cache file
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    except Exception:
        pass
        
    return state

def calculate_dynamic_futures_thresholds(report_date: str, window_days: int = 60) -> tuple:
    """
    Dynamically calculates the bullish and bearish thresholds for Taiwan Foreign Futures Net OI
    based on the rolling historical window prior to report_date.
    
    Uses standard statistical formulas:
        - Bullish Threshold = Mean + 1.5 * StdDev (optimistic/heavy long bias)
        - Bearish Threshold = Mean - 2.0 * StdDev (extreme short/hedging bias)
        
    Includes safe physical fallbacks (clamping) to prevent statistical anomalies 
    on small or flat datasets.
    
    Returns:
        tuple: (bullish_threshold, bearish_threshold, mean, std)
    """
    # 1. Fetch rolling historical records strictly before report_date to avoid lookahead bias
    history = db.get_historical_futures_oi(sim_date=report_date, limit=window_days)
    
    # Fallback to static historical norms if history is too short for meaningful statistics (need at least 10 records)
    if len(history) < 10:
        return 10000.0, -30000.0, -8000.0, 5000.0
        
    # 2. Calculate Mean and Standard Deviation
    n = len(history)
    mean = sum(history) / n
    variance = sum((x - mean) ** 2 for x in history) / n
    std = variance ** 0.5
    
    # 3. Apply Volatility Floor (波動率下限)
    # Ensure std is at least 3,000 contracts to prevent oversensitivity in extremely quiet markets
    std_for_calc = max(std, 3000.0)
    
    # 4. Calculate Dynamic Thresholds based on standard deviations
    # Bullish Threshold = Mean + 1.5 * StdDev
    bullish_threshold = mean + 1.5 * std_for_calc
    # Bearish Threshold = Mean - 2.0 * StdDev
    bearish_threshold = mean - 2.0 * std_for_calc
    
    return float(bullish_threshold), float(bearish_threshold), float(mean), float(std)

def calculate_composite_liquidity_score(state: dict) -> float:
    """
    Core scoring algorithm.
    Combines US Net Liquidity 4-week ROC and Taiwan Foreign Futures Net OI
    to calculate a unified Composite Liquidity Score (CLS) between 0.0 and 1.0.
    
    Scoring Weight:
        - 50% US Liquidity Trend (Fed assets expansion vs. contraction)
        - 50% Taiwan Foreign Futures Position (large capital hedging attitude)
        
    Interpretation:
        - CLS < 0.35: Abundant liquidity (EXPANSION)
        - 0.35 <= CLS < 0.70: Neutral liquidity (NEUTRAL)
        - CLS >= 0.70: Liquidity stress (CONTRACTION) -> Triggers defensive budget scaling
    """
    # 1. Score US Net Liquidity Trend (ROC)
    # Target range: -5% (extremely tight, score 1.0) to +5% (extremely loose, score 0.0)
    roc = state.get("us_liquidity_roc_4w", 0.0)
    # Winsorize extreme growth/decline to prevent outliers
    roc_bounded = max(-0.05, min(roc, 0.05))
    # Normalize: -0.05 -> 1.0 (Stress), 0.05 -> 0.0 (Abundant)
    us_score = 0.5 - (roc_bounded / 0.10)
    
    # 2. Score Taiwan Foreign Futures Position (DYNAMICALLY)
    futures_oi = state.get("tw_foreign_futures_oi", 0)
    report_date = state.get("record_date", datetime.now().strftime("%Y-%m-%d"))
    
    # Dynamically calculate thresholds from database history (prevents lookahead bias)
    bull_thr, bear_thr, mean, std = calculate_dynamic_futures_thresholds(report_date, window_days=60)
    
    # Bounded between bear_thr (stress, score 1.0) and bull_thr (abundant, score 0.0)
    range_width = bull_thr - bear_thr
    if range_width <= 0:
        range_width = 40000.0  # Safe fallback to prevent division by zero
        
    oi_bounded = max(bear_thr, min(futures_oi, bull_thr))
    
    # Normalize: bear_thr -> 1.0 (Stress), bull_thr -> 0.0 (Abundant)
    # Formula: (oi - bull_thr) / -range_width
    tw_score = (oi_bounded - bull_thr) / -range_width
    
    # 3. Combine scores (50/50 weighted average)
    composite = (us_score * 0.5) + (tw_score * 0.5)
    
    # Store dynamic calculation details in the state dict for the agent's reference
    state["dynamic_bullish_threshold"] = bull_thr
    state["dynamic_bearish_threshold"] = bear_thr
    state["dynamic_futures_mean"] = mean
    state["dynamic_futures_std"] = std
    
    # Clamp final score between 0.0 and 1.0
    return float(max(0.0, min(composite, 1.0)))


# --- Section 4: Standalone Self-Testing Block ---

if __name__ == "__main__":
    print("\033[93m==================================================\033[0m")
    print("\033[93m🧪 單獨功能測試：流動性數據加載器 (liquidity_loader.py)\033[0m")
    print("\033[93m==================================================\033[0m")
    
    test_date = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Sync FRED data online via API
    print("[*] 步驟一：測試 FRED 美股流動性線上同步 (使用 FredClient)...")
    try:
        # Sync from recent history to save time
        sync_us_liquidity_history(start_date="2026-01-01")
    except Exception as e:
        print(f"[✗] FRED API 同步失敗: {e}")
        
    # 2. Fetch Live Liquidity State
    print(f"\n[*] 步驟二：獲取今日 ({test_date}) 實時流動性與籌碼狀態...")
    live_state = get_liquidity_state(test_date, is_backtest=False)
    print(json.dumps(live_state, ensure_ascii=False, indent=4))
    
    # 3. Fetch Historical Backtest State (Time-Travel)
    # We will query a known past Wednesday to test historical database lookup
    past_date = "2026-06-17"  # Known past Wednesday in database
    print(f"\n[*] 步驟三：模擬時間旅行 (Time-Travel) 獲取歷史日期 ({past_date}) 數據...")
    hist_state = get_liquidity_state(past_date, is_backtest=True)
    print(json.dumps(hist_state, ensure_ascii=False, indent=4))
    
    print("\n\033[93m==================================================\033[0m")
    print("\033[93m✓ 流動性數據加載器單獨功能測試完成。\033[0m")
    print("\033[93m==================================================\033[0m")
