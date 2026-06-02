import json
from datetime import datetime
from contextlib import contextmanager
import pymysql
import pymysql.cursors
from core.tools.utils import retry_on_exception
from core.config import (
    DB_DIR, DB_TYPE, MYSQL_HOST, MYSQL_PORT, 
    MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB
)

DB_PATH = DB_DIR / "investments.db"

@retry_on_exception(tries=3, delay=1, backoff=2, exceptions=(pymysql.Error, ConnectionError))
def _get_mysql_connection_raw():
    """Establishes raw MySQL connection with exponential retries."""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

@contextmanager
def db_session():
    """
    Unified database context manager.
    Automatically handles connection, commits, rollbacks, and clean-up 
    for both SQLite and MySQL based on DB_TYPE.
    Integrates 3-trial connection retries and auto-reconnect ping for MySQL.
    """
    is_mysql = (DB_TYPE == "mysql")
    conn = None
    try:
        if is_mysql:
            conn = _get_mysql_connection_raw()
            # Proactively ping with reconnect=True to restore any dead sockets silently
            conn.ping(reconnect=True)
        else:
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise e
    finally:
        if conn:
            conn.close()

def execute_sql(cursor, query_sqlite: str, query_mysql: str, params: tuple = ()):
    """Executes the correct SQL dialect query based on the active DB_TYPE."""
    if DB_TYPE == "mysql":
        return cursor.execute(query_mysql, params)
    else:
        return cursor.execute(query_sqlite, params)

def init_db():
    """Initializes database schema and handles automatic DDL generation for SQLite/MySQL."""
    if DB_TYPE == "mysql":
        # Ensure database existence prior to establishing direct schema connection
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            with conn.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[!] Warning: Failed to pre-create MySQL database '{MYSQL_DB}': {e}. Attempting direct tables creation...")

    with db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Reports Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    date VARCHAR(50) UNIQUE NOT NULL,
                    regions TEXT NOT NULL,          -- JSON string of analyzed regions
                    markdown_content LONGTEXT NOT NULL,
                    html_content LONGTEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    regions TEXT NOT NULL,          -- JSON string of analyzed regions
                    markdown_content TEXT NOT NULL,
                    html_content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
        # 2. Recommendations Table DDL (for closed-loop backtesting)
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    report_date VARCHAR(50) NOT NULL,      -- Link to report date
                    region VARCHAR(50) NOT NULL,           -- e.g., 'US', 'Taiwan'
                    ticker VARCHAR(50) NOT NULL,           -- e.g., 'AAPL', '2330.TW'
                    company_name VARCHAR(255) NOT NULL,
                    recommend_price DOUBLE NOT NULL,       -- Stock price at recommendation time
                    recommend_reason TEXT,                 -- Bullet points of key thesis
                    target_price DOUBLE,                   -- Bull target price
                    stop_loss DOUBLE,                      -- Stop loss protection
                    rating VARCHAR(50),                    -- e.g., 'Buy', 'Strong Buy'
                    is_active INT DEFAULT 1,               -- 1 = Active, 0 = Completed
                    close_price DOUBLE,                    -- Price when closed
                    close_date VARCHAR(50),                -- Date when closed
                    performance DOUBLE,                    -- ROI (e.g. 0.05 for +5%)
                    invested_amount DOUBLE DEFAULT 0.0,    -- Capital allocated for this stock
                    shares DOUBLE DEFAULT 0.0,             -- Total shares bought
                    pnl DOUBLE DEFAULT 0.0,                -- Realized/Unrealized P&L in currency
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_report_date (report_date),
                    INDEX idx_ticker (ticker)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT NOT NULL,      -- Link to report date
                    region TEXT NOT NULL,           -- e.g., 'US', 'Taiwan'
                    ticker TEXT NOT NULL,           -- e.g., 'AAPL', '2330.TW'
                    company_name TEXT NOT NULL,
                    recommend_price REAL NOT NULL,  -- Stock price at recommendation time
                    recommend_reason TEXT,          -- Bullet points of key thesis
                    target_price REAL,              -- Bull target price
                    stop_loss REAL,                 -- Stop loss protection
                    rating TEXT,                    -- e.g., 'Buy', 'Strong Buy'
                    is_active INTEGER DEFAULT 1,    -- 1 = Active, 0 = Completed
                    close_price REAL,               -- Price when closed
                    close_date TEXT,                -- Date when closed
                    performance REAL,               -- ROI (e.g. 0.05 for +5%)
                    invested_amount REAL DEFAULT 0.0,
                    shares REAL DEFAULT 0.0,
                    pnl REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # 3. Capital Ledger Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS capital_ledger (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    currency VARCHAR(10) UNIQUE NOT NULL, -- 'USD' or 'TWD'
                    available_capital DOUBLE NOT NULL,
                    reserved_cash DOUBLE NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS capital_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    currency TEXT UNIQUE NOT NULL,
                    available_capital REAL NOT NULL,
                    reserved_cash REAL NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # 4. Transaction History Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transaction_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    rec_id INT NOT NULL,
                    action VARCHAR(50) NOT NULL,          -- 'BUY', 'SELL_PROFIT_TARGET', 'SELL_STOP_LOSS'
                    ticker VARCHAR(50) NOT NULL,
                    currency VARCHAR(10) NOT NULL,
                    shares DOUBLE NOT NULL,
                    price DOUBLE NOT NULL,
                    amount DOUBLE NOT NULL,               -- shares * price
                    roi DOUBLE DEFAULT 0.0,
                    pnl DOUBLE DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ticker_tx (ticker)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transaction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rec_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    roi REAL DEFAULT 0.0,
                    pnl REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # Check and alter recommendations table if columns are missing in existing tables
        if DB_TYPE == "mysql":
            cursor.execute("SHOW COLUMNS FROM recommendations LIKE 'invested_amount'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE recommendations ADD COLUMN invested_amount DOUBLE DEFAULT 0.0;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN shares DOUBLE DEFAULT 0.0;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN pnl DOUBLE DEFAULT 0.0;")
                print("[✓] MySQL recommendations table upgraded with capital tracking columns.")
        else:
            cursor.execute("PRAGMA table_info(recommendations)")
            cols = [row[1] for row in cursor.fetchall()]
            if "invested_amount" not in cols:
                cursor.execute("ALTER TABLE recommendations ADD COLUMN invested_amount REAL DEFAULT 0.0;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN shares REAL DEFAULT 0.0;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN pnl REAL DEFAULT 0.0;")
                print("[✓] SQLite recommendations table upgraded with capital tracking columns.")

        # 5. Portfolio NAV History Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_nav_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    date VARCHAR(50) NOT NULL,
                    currency VARCHAR(10) NOT NULL,
                    total_nav DOUBLE NOT NULL,
                    available_capital DOUBLE NOT NULL,
                    active_value DOUBLE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY idx_date_currency (date, currency)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_nav_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    total_nav REAL NOT NULL,
                    available_capital REAL NOT NULL,
                    active_value REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, currency)
                )
            """)

        # 6. Prompt Registry Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prompt_registry (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    agent_name VARCHAR(50) NOT NULL,
                    system_prompt LONGTEXT NOT NULL,
                    version VARCHAR(20) NOT NULL,
                    is_active INT DEFAULT 1,
                    performance_score DOUBLE DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY idx_agent_version (agent_name, version)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prompt_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    version TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    performance_score REAL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_name, version)
                )
            """)

        # 7. Agent Inference Logs Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_inference_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    rec_id INT,
                    agent_name VARCHAR(50) NOT NULL,
                    ticker VARCHAR(20),
                    input_prompt LONGTEXT NOT NULL,
                    output_response LONGTEXT NOT NULL,
                    prompt_version VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (rec_id) REFERENCES recommendations(id) ON DELETE SET NULL,
                    INDEX idx_agent_ticker (agent_name, ticker)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_inference_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rec_id INTEGER,
                    agent_name TEXT NOT NULL,
                    ticker TEXT,
                    input_prompt TEXT NOT NULL,
                    output_response TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (rec_id) REFERENCES recommendations(id) ON DELETE SET NULL
                )
            """)

        # Seed capital_ledger with default starting balances if empty
        execute_sql(cursor,
            "SELECT COUNT(*) FROM capital_ledger",
            "SELECT COUNT(*) FROM capital_ledger"
        )
        row = cursor.fetchone()
        count = row[0] if isinstance(row, tuple) else row.get("COUNT(*)") or row.get("count(*)") or list(row.values())[0]
        if count == 0:
            # Seed USD: Available 100k, Reserved 20k
            execute_sql(cursor,
                "INSERT INTO capital_ledger (currency, available_capital, reserved_cash) VALUES ('USD', 100000.0, 20000.0)",
                "INSERT INTO capital_ledger (currency, available_capital, reserved_cash) VALUES ('USD', 100000.0, 20000.0)"
            )
            # Seed TWD: Available 1M, Reserved 200k
            execute_sql(cursor,
                "INSERT INTO capital_ledger (currency, available_capital, reserved_cash) VALUES ('TWD', 1000000.0, 200000.0)",
                "INSERT INTO capital_ledger (currency, available_capital, reserved_cash) VALUES ('TWD', 1000000.0, 200000.0)"
            )
            print("[✓] Database seeded with starting capital: USD 120,000 and TWD 1,200,000.")

# Proactively trigger DB initialization on module import
init_db()

# --- Report Helpers ---

def save_report(date_str: str, regions: list, markdown_content: str, html_content: str):
    """Saves or updates a weekly investment report in the database."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite upsert
            """
            INSERT INTO reports (date, regions, markdown_content, html_content)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                regions = excluded.regions,
                markdown_content = excluded.markdown_content,
                html_content = excluded.html_content
            """,
            # MySQL upsert
            """
            INSERT INTO reports (date, regions, markdown_content, html_content)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                regions = VALUES(regions),
                markdown_content = VALUES(markdown_content),
                html_content = VALUES(html_content)
            """,
            (date_str, json.dumps(regions), markdown_content, html_content)
        )

def get_latest_report():
    """Fetches the most recent weekly report from the database."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT * FROM reports ORDER BY date DESC LIMIT 1",
            "SELECT * FROM reports ORDER BY date DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row) if row else None

def get_report_by_date(date_str: str):
    """Fetches a report by its specific date string (YYYY-MM-DD)."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT * FROM reports WHERE date = ?",
            "SELECT * FROM reports WHERE date = %s",
            (date_str,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

def list_all_reports():
    """Returns a list of all historical reports, excluding heavy text content for index views."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT id, date, regions, created_at FROM reports ORDER BY date DESC",
            "SELECT id, date, regions, created_at FROM reports ORDER BY date DESC"
        )
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            regions_data = r["regions"]
            # MySQL sometimes handles strings or json fields natively, let's load it safely
            if isinstance(regions_data, str):
                regions_list = json.loads(regions_data)
            else:
                regions_list = regions_data
            
            created_val = r["created_at"]
            if hasattr(created_val, "isoformat"):
                created_str = created_val.isoformat()
            else:
                created_str = str(created_val)
                
            results.append({
                "id": r["id"],
                "date": r["date"],
                "regions": regions_list,
                "created_at": created_str
            })
        return results

# --- Recommendation Helpers ---

def save_recommendation(report_date: str, region: str, ticker: str, company_name: str,
                        recommend_price: float, recommend_reason: str,
                        target_price: float = None, stop_loss: float = None, rating: str = "Buy",
                        invested_amount: float = 0.0, shares: float = 0.0) -> int:
    """Inserts a new stock recommendation for weekly tracking, returning the inserted row ID."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite:
            """
            INSERT INTO recommendations (
                report_date, region, ticker, company_name, recommend_price,
                recommend_reason, target_price, stop_loss, rating, is_active,
                invested_amount, shares, pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 0.0)
            """,
            # MySQL:
            """
            INSERT INTO recommendations (
                report_date, region, ticker, company_name, recommend_price,
                recommend_reason, target_price, stop_loss, rating, is_active,
                invested_amount, shares, pnl
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, 0.0)
            """,
            (report_date, region, ticker.upper(), company_name, recommend_price,
             recommend_reason, target_price, stop_loss, rating, invested_amount, shares)
        )
        return cursor.lastrowid

def get_active_recommendations(region: str = None):
    """Fetches all recommendations currently active and needing price checks."""
    with db_session() as conn:
        cursor = conn.cursor()
        if region:
            execute_sql(cursor,
                "SELECT * FROM recommendations WHERE is_active = 1 AND region = ?",
                "SELECT * FROM recommendations WHERE is_active = 1 AND region = %s",
                (region,)
            )
        else:
            execute_sql(cursor,
                "SELECT * FROM recommendations WHERE is_active = 1",
                "SELECT * FROM recommendations WHERE is_active = 1"
            )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def close_recommendation(rec_id: int, close_price: float, close_date: str, performance: float):
    """Marks a recommendation as closed due to hitting targets/stop-losses or manual adjustment."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite:
            """
            UPDATE recommendations
            SET is_active = 0,
                close_price = ?,
                close_date = ?,
                performance = ?
            WHERE id = ?
            """,
            # MySQL:
            """
            UPDATE recommendations
            SET is_active = 0,
                close_price = %s,
                close_date = %s,
                performance = %s
            WHERE id = %s
            """,
            (close_price, close_date, performance, rec_id)
        )

def update_recommendation_performance(rec_id: int, performance: float, pnl: float = 0.0):
    """Updates the current unrealized performance (ROI) and PnL for an active recommendation."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite:
            """
            UPDATE recommendations
            SET performance = ?, pnl = ?
            WHERE id = ?
            """,
            # MySQL:
            """
            UPDATE recommendations
            SET performance = %s, pnl = %s
            WHERE id = %s
            """,
            (performance, pnl, rec_id)
        )

def get_historical_performance():
    """Calculates high-level win rates and returns across all closed recommendations."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT * FROM recommendations WHERE is_active = 0",
            "SELECT * FROM recommendations WHERE is_active = 0"
        )
        closed_recs = [dict(row) for row in cursor.fetchall()]
        
        if not closed_recs:
            return {"win_rate": 0.0, "avg_roi": 0.0, "total_recommendations": 0}
            
        wins = sum(1 for r in closed_recs if r["performance"] > 0)
        total = len(closed_recs)
        avg_roi = sum(r["performance"] for r in closed_recs) / total
        
        return {
            "win_rate": wins / total,
            "avg_roi": avg_roi,
            "total_recommendations": total,
            "closed": closed_recs
        }

def save_portfolio_nav(date: str, currency: str, total_nav: float, available_capital: float, active_value: float):
    """Inserts or updates the daily Portfolio Net Asset Value (NAV) record."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite:
            """
            INSERT INTO portfolio_nav_history (date, currency, total_nav, available_capital, active_value)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date, currency) DO UPDATE SET
                total_nav=excluded.total_nav,
                available_capital=excluded.available_capital,
                active_value=excluded.active_value
            """,
            # MySQL:
            """
            INSERT INTO portfolio_nav_history (date, currency, total_nav, available_capital, active_value)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                total_nav=VALUES(total_nav),
                available_capital=VALUES(available_capital),
                active_value=VALUES(active_value)
            """,
            (date, currency, total_nav, available_capital, active_value)
        )

def get_portfolio_nav_history(currency: str) -> list:
    """Fetches all daily NAV records for the given currency sorted by date ascending."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT date, total_nav, available_capital, active_value FROM portfolio_nav_history WHERE currency = ? ORDER BY date ASC",
            "SELECT date, total_nav, available_capital, active_value FROM portfolio_nav_history WHERE currency = %s ORDER BY date ASC",
            (currency,)
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            if isinstance(r, dict):
                results.append(r)
            else:
                results.append({
                    "date": r[0],
                    "total_nav": r[1],
                    "available_capital": r[2],
                    "active_value": r[3]
                })
        return results

# --- Self-Reflective Prompt Optimization Engine Helpers ---

def get_active_prompt(agent_name: str) -> dict:
    """Fetches the currently active system prompt for the given agent from the database."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT system_prompt, version FROM prompt_registry WHERE agent_name = ? AND is_active = 1 LIMIT 1",
            "SELECT system_prompt, version FROM prompt_registry WHERE agent_name = %s AND is_active = 1 LIMIT 1",
            (agent_name,)
        )
        row = cursor.fetchone()
        if row:
            if isinstance(row, dict):
                return {"system_prompt": row["system_prompt"], "version": row["version"]}
            else:
                return {"system_prompt": row[0], "version": row[1]}
        return None

def save_agent_inference_log(rec_id: int, agent_name: str, ticker: str, input_prompt: str, output_response: str, prompt_version: str):
    """Saves a detailed LLM inference log into the database."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite
            """
            INSERT INTO agent_inference_logs (rec_id, agent_name, ticker, input_prompt, output_response, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            # MySQL
            """
            INSERT INTO agent_inference_logs (rec_id, agent_name, ticker, input_prompt, output_response, prompt_version)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (rec_id, agent_name, ticker, input_prompt, output_response, prompt_version)
        )

def save_prompt_registry(agent_name: str, system_prompt: str, version: str, is_active: int = 1):
    """Saves a new prompt version into the database and deactivates any existing version for this agent if is_active=1."""
    with db_session() as conn:
        cursor = conn.cursor()
        if is_active == 1:
            # Deactivate existing active prompts for this agent
            execute_sql(cursor,
                "UPDATE prompt_registry SET is_active = 0 WHERE agent_name = ?",
                "UPDATE prompt_registry SET is_active = 0 WHERE agent_name = %s",
                (agent_name,)
            )
        # Insert the new version
        execute_sql(cursor,
            # SQLite
            """
            INSERT OR REPLACE INTO prompt_registry (agent_name, system_prompt, version, is_active)
            VALUES (?, ?, ?, ?)
            """,
            # MySQL
            """
            INSERT INTO prompt_registry (agent_name, system_prompt, version, is_active)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE system_prompt=VALUES(system_prompt), is_active=VALUES(is_active)
            """,
            (agent_name, system_prompt, version, is_active)
        )

def get_recent_inference_logs_with_roi(agent_name: str, limit: int = 6) -> list:
    """Fetches recent inference logs matched with their actual trade performance (ROI) from recommendations."""
    with db_session() as conn:
        cursor = conn.cursor()
        query_sqlite = """
            SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version
            FROM agent_inference_logs l
            JOIN recommendations r ON l.rec_id = r.id
            WHERE l.agent_name = ? AND r.performance IS NOT NULL
            ORDER BY r.id DESC
            LIMIT ?
        """
        query_mysql = """
            SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version
            FROM agent_inference_logs l
            INNER JOIN recommendations r ON l.rec_id = r.id
            WHERE l.agent_name = %s AND r.performance IS NOT NULL
            ORDER BY r.id DESC
            LIMIT %s
        """
        execute_sql(cursor, query_sqlite, query_mysql, (agent_name, limit))
        rows = cursor.fetchall()
        results = []
        for r in rows:
            if isinstance(r, dict):
                results.append(r)
            else:
                results.append({
                    "ticker": r[0],
                    "roi": r[1],
                    "input_prompt": r[2],
                    "output_response": r[3],
                    "prompt_version": r[4]
                })
        return results
