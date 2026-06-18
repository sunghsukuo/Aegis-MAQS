import re
import os
import time
import requests
from bs4 import BeautifulSoup
from core.db_manager import db_session, execute_sql

# File path to store the last synchronization timestamp
LAST_SYNC_FILE = os.path.join(os.path.dirname(__file__), ".last_twse_sync")

def _should_sync() -> bool:
    """
    Checks if a week (7 days) has passed since the last sync.
    7 days = 604,800 seconds.
    """
    if not os.path.exists(LAST_SYNC_FILE):
        return True
    try:
        with open(LAST_SYNC_FILE, "r") as f:
            last_sync_time = float(f.read().strip())
        return (time.time() - last_sync_time) >= 604800
    except Exception:
        return True

def _update_sync_time():
    """
    Updates the last sync timestamp to LAST_SYNC_FILE.
    """
    try:
        with open(LAST_SYNC_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        print(f"[!] Warning: Failed to write sync time file: {e}")

def _is_potential_taiwan_query(query_str: str) -> bool:
    """
    Determines if the query string could potentially be a Taiwan stock.
    A potential Taiwan query must satisfy at least one of the following:
    1. Be entirely numeric (e.g., "2330", "3293", "0050")
    2. End with ".TW" or ".TWO" (case-insensitive)
    3. Contain at least one Chinese character
    """
    # 1. Alphanumeric stock code format (e.g., "2330", "00988A", "2330A")
    if re.match(r"^[0-9A-Z]{4,6}$", query_str, re.IGNORECASE):
        return True
    
    # 2. Ends with .TW or .TWO
    if re.search(r"\.(tw|two)$", query_str, re.IGNORECASE):
        return True
        
    # 3. Contains Chinese characters (Unicode range for CJK Unified Ideographs)
    if re.search(r"[\u4e00-\u9fff]", query_str):
        return True
        
    return False

def get_taiwan_stock_name(ticker_or_code: str) -> str:
    """
    Retrieves the Chinese official name of a Taiwan stock by its ticker (e.g. 3293.TWO) or code (e.g. 3293).
    First checks the local database. If not found, runs a TWSE/TPEx ISIN sync (subject to weekly cooldown),
    then queries again.
    """
    # Clean code: extract stock code (e.g. "3293.TWO" -> "3293", "00988A.TW" -> "00988A")
    match = re.match(r"^([0-9A-Za-z]+)", ticker_or_code.strip())
    if not match:
        return None
    code = match.group(1).upper()

    # 1. Query local database
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT chinese_name FROM taiwan_stock_names WHERE stock_code = ?",
            "SELECT chinese_name FROM taiwan_stock_names WHERE stock_code = %s",
            (code,)
        )
        row = cursor.fetchone()
        if row:
            return row[0] if isinstance(row, tuple) else row.get("chinese_name")

    # 2. Not found: trigger sync of TWSE/TPEx lists (checks weekly limit)
    if not hasattr(get_taiwan_stock_name, "_sync_attempted"):
        get_taiwan_stock_name._sync_attempted = False

    if not get_taiwan_stock_name._sync_attempted:
        get_taiwan_stock_name._sync_attempted = True
        print(f"[*] Stock code {code} not found in database. Triggering dynamic TWSE/TPEx sync...")
        try:
            sync_taiwan_stock_names()
            # Query again after sync
            with db_session() as conn:
                cursor = conn.cursor()
                execute_sql(cursor,
                    "SELECT chinese_name FROM taiwan_stock_names WHERE stock_code = ?",
                    "SELECT chinese_name FROM taiwan_stock_names WHERE stock_code = %s",
                    (code,)
                )
                row = cursor.fetchone()
                if row:
                    return row[0] if isinstance(row, tuple) else row.get("chinese_name")
        except Exception as e:
            print(f"[!] Warning: Failed to sync Taiwan stock names from TWSE: {e}")
        
    return None

def sync_taiwan_stock_names(force=False):
    """
    Scrapes the TWSE public ISIN pages for all listed and OTC companies
    and updates/inserts them into the taiwan_stock_names database table.
    """
    if not force and not _should_sync():
        print("[*] Taiwan stock names sync skipped (already synced within 7 days).")
        return

    print("[*] Starting TWSE/TPEx public listing sync...")
    # Map each URL to its market type (TW for listed, TWO for OTC)
    market_configs = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),  # TWSE listed
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")   # TPEx OTC
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    scraped_data = []
    
    for url, market_type in market_configs:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.encoding = "big5"  # TWSE uses Big5 encoding
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", {"class": "h4"})
            if not table:
                continue
                
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if not cols:
                    continue
                text = cols[0].get_text(strip=True)
                # Match code and name (e.g., "1101　台泥", "00988A  國泰債")
                m = re.match(r"^([0-9A-Za-z]+)[\s\u3000]+(.+)$", text)
                if m:
                    code = m.group(1).upper()
                    name = m.group(2).strip()
                    industry_type = ""
                    if len(cols) > 4:
                        industry_type = cols[4].get_text(strip=True)
                    if len(code) >= 4 and len(name) > 0:
                        scraped_data.append((code, name, market_type, industry_type))
        except Exception as e:
            print(f"[!] Error loading {url}: {e}")
                    
    if scraped_data:
        # Batch insert to database
        with db_session() as conn:
            cursor = conn.cursor()
            for code, name, market_type, industry_type in scraped_data:
                execute_sql(cursor,
                    # SQLite
                    "INSERT OR REPLACE INTO taiwan_stock_names (stock_code, chinese_name, market_type, industry_type) VALUES (?, ?, ?, ?)",
                    # MySQL
                    "INSERT INTO taiwan_stock_names (stock_code, chinese_name, market_type, industry_type) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE chinese_name = VALUES(chinese_name), market_type = VALUES(market_type), industry_type = VALUES(industry_type)",
                    (code, name, market_type, industry_type)
                )
        print(f"[✓] Taiwan stock names database synced successfully. Registered {len(scraped_data)} companies.")
        _update_sync_time()

def _query_local_db(query_str: str) -> dict:
    """
    Performs local database lookup for a clean code or Chinese name.
    """
    # 1. Check if query is a stock code (e.g. "3293", "00988A")
    if re.match(r"^[0-9A-Z]{4,6}$", query_str, re.IGNORECASE):
        code_upper = query_str.upper()
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor,
                "SELECT chinese_name, market_type FROM taiwan_stock_names WHERE stock_code = ?",
                "SELECT chinese_name, market_type FROM taiwan_stock_names WHERE stock_code = %s",
                (code_upper,)
            )
            row = cursor.fetchone()
            if row:
                name_zh = row[0] if isinstance(row, tuple) else row.get("chinese_name")
                mtype = row[1] if isinstance(row, tuple) else row.get("market_type")
                return {
                    "ticker": f"{query_str}.{mtype}",
                    "region": "Taiwan",
                    "company_name": name_zh,
                    "company_name_zh": name_zh
                }

    # 2. Check if query is Chinese name (exact match first)
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT stock_code, market_type, chinese_name FROM taiwan_stock_names WHERE chinese_name = ?",
            "SELECT stock_code, market_type, chinese_name FROM taiwan_stock_names WHERE chinese_name = %s",
            (query_str,)
        )
        row = cursor.fetchone()
        
        # If not exact match, try substring match (LIKE)
        if not row:
            if len(query_str) >= 2:
                execute_sql(cursor,
                    "SELECT stock_code, market_type, chinese_name FROM taiwan_stock_names WHERE chinese_name LIKE ?",
                    "SELECT stock_code, market_type, chinese_name FROM taiwan_stock_names WHERE chinese_name LIKE %s",
                    (f"%{query_str}%",)
                )
                rows = cursor.fetchall()
                if rows:
                    row = min(rows, key=lambda r: len(r[2] if isinstance(r, tuple) else r.get("chinese_name")))

        if row:
            code = row[0] if isinstance(row, tuple) else row.get("stock_code")
            mtype = row[1] if isinstance(row, tuple) else row.get("market_type")
            name_zh = row[2] if isinstance(row, tuple) else row.get("chinese_name")
            return {
                "ticker": f"{code}.{mtype}",
                "region": "Taiwan",
                "company_name": name_zh,
                "company_name_zh": name_zh
            }
            
    return None

def resolve_taiwan_ticker_locally(query_str: str) -> dict:
    """
    Attempts to resolve a Taiwan stock ticker locally using the cached DB table.
    Supports:
    1. "3293.TWO" or "2330.TW"
    2. "3293" (looks up DB to find market_type)
    3. "鈊象" or "台積電" or "台積" (looks up DB to find stock_code and market_type)
    If not found, triggers a weekly-cooldown-capped sync and tries one more time.
    Returns:
        dict: {"ticker": "3293.TWO", "region": "Taiwan", "company_name": "鈊象", "company_name_zh": "鈊象"}
        or None if not resolved.
    """
    query_str = query_str.strip()
    if not query_str:
        return None

    # 0. Pre-filter: skip if not a potential Taiwan query to avoid wasting sync cooldown on US stocks or English typos
    if not _is_potential_taiwan_query(query_str):
        return None

    # 1. Clean code format check (e.g. "3293.TWO" or "2330.TW")
    m = re.match(r"^(\d+)\.(TW|TWO)$", query_str, re.IGNORECASE)
    if m:
        code = m.group(1)
        suffix = m.group(2).upper()
        # Look up Chinese name
        name_zh = get_taiwan_stock_name(code)
        return {
            "ticker": f"{code}.{suffix}",
            "region": "Taiwan",
            "company_name": name_zh or f"Stock {code}",
            "company_name_zh": name_zh or f"Stock {code}"
        }

    # 2. Local database search
    result = _query_local_db(query_str)
    if result:
        return result

    # 3. Not found locally: trigger weekly sync
    if not hasattr(resolve_taiwan_ticker_locally, "_sync_attempted"):
        resolve_taiwan_ticker_locally._sync_attempted = False

    if not resolve_taiwan_ticker_locally._sync_attempted:
        resolve_taiwan_ticker_locally._sync_attempted = True
        print(f"[*] Query '{query_str}' not found in local registry. Checking TWSE for updates...")
        try:
            # If we synced within a week, this will print skip notice and return immediately
            sync_taiwan_stock_names()
            # Try local search again after sync
            return _query_local_db(query_str)
        except Exception as e:
            print(f"[!] Warning: Failed to dynamically sync TWSE names: {e}")
        
    return None
