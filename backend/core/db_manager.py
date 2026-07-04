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
                    macro_regime VARCHAR(50) DEFAULT NULL, -- Market macro environment tag
                    price_regime VARCHAR(50) DEFAULT NULL, -- Market price behavior tag
                    source_track VARCHAR(50) DEFAULT NULL, -- Track origin label
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
                    macro_regime TEXT DEFAULT NULL,
                    price_regime TEXT DEFAULT NULL,
                    source_track TEXT DEFAULT NULL,
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
                    risk_circuit_breaker TINYINT DEFAULT 0,
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
                    risk_circuit_breaker INTEGER DEFAULT 0,
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
            
            cursor.execute("SHOW COLUMNS FROM recommendations LIKE 'macro_regime'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE recommendations ADD COLUMN macro_regime VARCHAR(50) DEFAULT NULL;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN price_regime VARCHAR(50) DEFAULT NULL;")
                print("[✓] MySQL recommendations table upgraded with regime logging columns.")
                
            cursor.execute("SHOW COLUMNS FROM recommendations LIKE 'source_track'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE recommendations ADD COLUMN source_track VARCHAR(50) DEFAULT NULL;")
                print("[✓] MySQL recommendations table upgraded with source_track column.")
                
            cursor.execute("SHOW COLUMNS FROM capital_ledger LIKE 'risk_circuit_breaker'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE capital_ledger ADD COLUMN risk_circuit_breaker TINYINT DEFAULT 0;")
                print("[✓] MySQL capital_ledger table upgraded with risk_circuit_breaker column.")
        else:
            cursor.execute("PRAGMA table_info(recommendations)")
            cols = [row[1] for row in cursor.fetchall()]
            if "invested_amount" not in cols:
                cursor.execute("ALTER TABLE recommendations ADD COLUMN invested_amount REAL DEFAULT 0.0;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN shares REAL DEFAULT 0.0;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN pnl REAL DEFAULT 0.0;")
                print("[✓] SQLite recommendations table upgraded with capital tracking columns.")
                
            if "macro_regime" not in cols:
                cursor.execute("ALTER TABLE recommendations ADD COLUMN macro_regime TEXT DEFAULT NULL;")
                cursor.execute("ALTER TABLE recommendations ADD COLUMN price_regime TEXT DEFAULT NULL;")
                print("[✓] SQLite recommendations table upgraded with regime logging columns.")
                
            if "source_track" not in cols:
                cursor.execute("ALTER TABLE recommendations ADD COLUMN source_track TEXT DEFAULT NULL;")
                print("[✓] SQLite recommendations table upgraded with source_track column.")
            
            cursor.execute("PRAGMA table_info(capital_ledger)")
            ledger_cols = [row[1] for row in cursor.fetchall()]
            if "risk_circuit_breaker" not in ledger_cols:
                cursor.execute("ALTER TABLE capital_ledger ADD COLUMN risk_circuit_breaker INTEGER DEFAULT 0;")
                print("[✓] SQLite capital_ledger table upgraded with risk_circuit_breaker column.")

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

        # Check if taiwan_stock_names needs upgrade to include industry_type
        try:
            if DB_TYPE == "mysql":
                cursor.execute("SHOW COLUMNS FROM taiwan_stock_names LIKE 'industry_type'")
                if not cursor.fetchone():
                    cursor.execute("DROP TABLE IF EXISTS taiwan_stock_names;")
                    print("[✓] MySQL taiwan_stock_names table dropped for industry_type upgrade.")
            else:
                cursor.execute("PRAGMA table_info(taiwan_stock_names)")
                cols = [row[1] for row in cursor.fetchall()]
                if cols and "industry_type" not in cols:
                    cursor.execute("DROP TABLE IF EXISTS taiwan_stock_names;")
                    print("[✓] SQLite taiwan_stock_names table dropped for industry_type upgrade.")
        except Exception as e:
            pass

        # 8. Taiwan Stock Names Registry Table DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS taiwan_stock_names (
                    stock_code VARCHAR(20) PRIMARY KEY,
                    chinese_name VARCHAR(100) NOT NULL,
                    market_type VARCHAR(10) NOT NULL DEFAULT 'TW',
                    industry_type VARCHAR(100) DEFAULT ''
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS taiwan_stock_names (
                    stock_code TEXT PRIMARY KEY,
                    chinese_name TEXT NOT NULL,
                    market_type TEXT NOT NULL DEFAULT 'TW',
                    industry_type TEXT DEFAULT ''
                )
            """)

        # 9. Sector Registry & Constituents Tables DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sector_registry (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    region VARCHAR(20) NOT NULL,
                    sector_code VARCHAR(50) NOT NULL UNIQUE,
                    sector_name VARCHAR(100) NOT NULL,
                    target_type VARCHAR(20) NOT NULL,
                    is_etf TINYINT NOT NULL DEFAULT 1,
                    is_active TINYINT NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sector_constituents (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    sector_id INT NOT NULL,
                    ticker VARCHAR(20) NOT NULL,
                    company_name VARCHAR(100) DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_sector_ticker (sector_id, ticker),
                    FOREIGN KEY (sector_id) REFERENCES sector_registry(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sector_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region TEXT NOT NULL,
                    sector_code TEXT NOT NULL UNIQUE,
                    sector_name TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    is_etf INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sector_constituents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sector_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    company_name TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (sector_id, ticker),
                    FOREIGN KEY (sector_id) REFERENCES sector_registry(id) ON DELETE CASCADE
                );
            """)

        # 10. Thematic Registry & Constituents Tables DDL
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thematic_registry (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    theme_name VARCHAR(100) NOT NULL UNIQUE,       -- e.g., 'AI Infrastructure', 'GLP-1 Obesity'
                    description TEXT,                              -- Theme description
                    expected_horizon_months INT DEFAULT 12,        -- Expected horizon
                    news_heat_score FLOAT DEFAULT 0.0,             -- Heat score
                    is_active TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thematic_constituents (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    theme_id INT NOT NULL,
                    ticker VARCHAR(20) NOT NULL,
                    purity_score FLOAT DEFAULT 1.0,               -- Theme relevance
                    supply_chain_role VARCHAR(100),                -- Supply chain role
                    registered_reason TEXT,                        -- Selection reason
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_theme_ticker (theme_id, ticker),
                    FOREIGN KEY (theme_id) REFERENCES thematic_registry(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thematic_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme_name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    expected_horizon_months INTEGER DEFAULT 12,
                    news_heat_score REAL DEFAULT 0.0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thematic_constituents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    purity_score REAL DEFAULT 1.0,
                    supply_chain_role TEXT,
                    registered_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (theme_id, ticker),
                    FOREIGN KEY (theme_id) REFERENCES thematic_registry(id) ON DELETE CASCADE
                );
            """)

        # 11. Macro Liquidity History Table DDL (FRED)
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS macro_liquidity_history (
                    record_date VARCHAR(50) PRIMARY KEY,
                    fed_assets DOUBLE NOT NULL,
                    tga_balance DOUBLE NOT NULL,
                    reverse_repos DOUBLE NOT NULL,
                    net_liquidity DOUBLE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS macro_liquidity_history (
                    record_date TEXT PRIMARY KEY,
                    fed_assets REAL NOT NULL,
                    tga_balance REAL NOT NULL,
                    reverse_repos REAL NOT NULL,
                    net_liquidity REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

        # 12. Taiwan Chip/Capital Flow History Table DDL (TWSE / TAIFEX)
        if DB_TYPE == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS taiwan_chip_history (
                    record_date VARCHAR(50) PRIMARY KEY,
                    foreign_futures_net_oi INT NOT NULL,
                    foreign_net_buy DOUBLE NOT NULL,
                    dealers_net_buy DOUBLE NOT NULL,
                    investment_trust_net_buy DOUBLE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS taiwan_chip_history (
                    record_date TEXT PRIMARY KEY,
                    foreign_futures_net_oi INTEGER NOT NULL,
                    foreign_net_buy REAL NOT NULL,
                    dealers_net_buy REAL NOT NULL,
                    investment_trust_net_buy REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

        # Seed capital_ledger with default starting balances if empty
        execute_sql(cursor,
            "SELECT COUNT(*) FROM capital_ledger",
            "SELECT COUNT(*) FROM capital_ledger"
        )
        row = cursor.fetchone()
        if isinstance(row, tuple):
            count = row[0]
        else:
            row_dict = dict(row)
            count = row_dict.get("COUNT(*)") or row_dict.get("count(*)") or list(row_dict.values())[0]
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

# --- Sector Registry Helpers ---

def get_active_sectors(region_code: str) -> dict:
    """Gets active sectors and their configurations from the database. Falls back to config.py if empty."""
    config_data = {}
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor,
                "SELECT id, sector_code, sector_name, target_type, is_etf FROM sector_registry WHERE region = ? AND is_active = 1",
                "SELECT id, sector_code, sector_name, target_type, is_etf FROM sector_registry WHERE region = %s AND is_active = 1",
                (region_code,)
            )
            rows = cursor.fetchall()
            for row in rows:
                if isinstance(row, dict):
                    sec_id, code, name, t_type, is_etf = row["id"], row["sector_code"], row["sector_name"], row["target_type"], row["is_etf"]
                else:
                    sec_id, code, name, t_type, is_etf = row
                
                # Fetch constituents for constituents mode
                execute_sql(cursor,
                    "SELECT ticker FROM sector_constituents WHERE sector_id = ?",
                    "SELECT ticker FROM sector_constituents WHERE sector_id = %s",
                    (sec_id,)
                )
                c_rows = cursor.fetchall()
                constituents = []
                for cr in c_rows:
                    if isinstance(cr, dict):
                        constituents.append(cr["ticker"])
                    elif isinstance(cr, tuple):
                        constituents.append(cr[0])
                    else:
                        constituents.append(cr)
                
                config_data[code] = {
                    "name": name,
                    "target_type": t_type,
                    "is_etf": True if is_etf == 1 else False,
                }
                if t_type == "constituents":
                    config_data[code]["constituents"] = constituents
    except Exception as e:
        print(f"[!] Warning: Failed to load sectors from database ({e}). Falling back to config.py.")
        
    if not config_data:
        # Fallback to config.py if database is empty or connection fails
        try:
            from core.config import REGIONS
            config_data = REGIONS.get(region_code, {}).get("sector_etfs", {})
        except Exception as config_ex:
            print(f"[!] Warning: Fallback to config.py failed ({config_ex})")
            
    return config_data

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
                        invested_amount: float = 0.0, shares: float = 0.0,
                        macro_regime: str = None, price_regime: str = None,
                        source_track: str = None) -> int:
    """Inserts a new stock recommendation for weekly tracking, returning the inserted row ID."""
    is_act = 1 if shares > 0.0 else 0
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite:
            """
            INSERT INTO recommendations (
                report_date, region, ticker, company_name, recommend_price,
                recommend_reason, target_price, stop_loss, rating, is_active,
                invested_amount, shares, pnl, macro_regime, price_regime, source_track
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?)
            """,
            # MySQL:
            """
            INSERT INTO recommendations (
                report_date, region, ticker, company_name, recommend_price,
                recommend_reason, target_price, stop_loss, rating, is_active,
                invested_amount, shares, pnl, macro_regime, price_regime, source_track
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0.0, %s, %s, %s)
            """,
            (report_date, region, ticker.upper(), company_name, recommend_price,
             recommend_reason, target_price, stop_loss, rating, is_act, invested_amount, shares,
             macro_regime, price_regime, source_track)
        )
        return cursor.lastrowid

def get_active_recommendations(region: str = None):
    """Fetches all recommendations currently active and needing price checks (actual holdings only)."""
    with db_session() as conn:
        cursor = conn.cursor()
        if region:
            execute_sql(cursor,
                "SELECT * FROM recommendations WHERE is_active = 1 AND region = ? AND shares > 0",
                "SELECT * FROM recommendations WHERE is_active = 1 AND region = %s AND shares > 0",
                (region,)
            )
        else:
            execute_sql(cursor,
                "SELECT * FROM recommendations WHERE is_active = 1 AND shares > 0",
                "SELECT * FROM recommendations WHERE is_active = 1 AND shares > 0"
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
    """Calculates high-level win rates and returns across all closed recommendations (actual holdings only)."""
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            "SELECT * FROM recommendations WHERE is_active = 0 AND shares > 0",
            "SELECT * FROM recommendations WHERE is_active = 0 AND shares > 0"
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

def save_agent_inference_log(rec_id: int, agent_name: str, ticker: str, input_prompt: str, output_response: str, prompt_version: str, report_date: str = None):
    """Saves a detailed LLM inference log into the database with aligned created_at timestamp."""
    from datetime import datetime
    time_suffix = datetime.now().strftime("%H:%M:%S")
    if report_date:
        created_at = f"{report_date} {time_suffix}"
    else:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor,
            # SQLite
            """
            INSERT INTO agent_inference_logs (rec_id, agent_name, ticker, input_prompt, output_response, prompt_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            # MySQL
            """
            INSERT INTO agent_inference_logs (rec_id, agent_name, ticker, input_prompt, output_response, prompt_version, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (rec_id, agent_name, ticker, input_prompt, output_response, prompt_version, created_at)
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
            SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version, r.macro_regime, r.price_regime
            FROM agent_inference_logs l
            JOIN recommendations r ON l.rec_id = r.id
            WHERE l.agent_name = ? AND r.performance IS NOT NULL
            ORDER BY r.id DESC
            LIMIT ?
        """
        query_mysql = """
            SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version, r.macro_regime, r.price_regime
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
                    "prompt_version": r[4],
                    "macro_regime": r[5],
                    "price_regime": r[6]
                })
        return results


def get_extreme_inference_logs_with_roi(agent_name: str, limit_success: int = 5, limit_failure: int = 5) -> list:
    """Fetches high-contrast historical trade logs (top performing and worst performing) from a sliding window of the last 30 closed recommendations."""
    with db_session() as conn:
        cursor = conn.cursor()
        query_sqlite = """
            SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version, r.macro_regime, r.price_regime
            FROM agent_inference_logs l
            JOIN recommendations r ON l.rec_id = r.id
            WHERE l.agent_name = ? AND r.performance IS NOT NULL
            ORDER BY r.id DESC
            LIMIT 30
        """
        query_mysql = """
            SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version, r.macro_regime, r.price_regime
            FROM agent_inference_logs l
            INNER JOIN recommendations r ON l.rec_id = r.id
            WHERE l.agent_name = %s AND r.performance IS NOT NULL
            ORDER BY r.id DESC
            LIMIT 30
        """
        execute_sql(cursor, query_sqlite, query_mysql, (agent_name,))
        rows = cursor.fetchall()
        
        parsed_rows = []
        for r in rows:
            if isinstance(r, dict):
                parsed_rows.append(r)
            else:
                parsed_rows.append({
                    "ticker": r[0],
                    "roi": r[1],
                    "input_prompt": r[2],
                    "output_response": r[3],
                    "prompt_version": r[4],
                    "macro_regime": r[5],
                    "price_regime": r[6]
                })
        
        # Split into successes and failures
        success_cases = [r for r in parsed_rows if (r["roi"] or 0.0) > 0.0]
        failure_cases = [r for r in parsed_rows if (r["roi"] or 0.0) <= 0.0]
        
        # Sort in-memory to get absolute best and worst within the window
        success_cases.sort(key=lambda x: x["roi"], reverse=True)
        failure_cases.sort(key=lambda x: x["roi"], reverse=False)
        
        # Take the top N of each
        return success_cases[:limit_success] + failure_cases[:limit_failure]


def get_risk_circuit_breaker(currency: str) -> bool:
    """
    Checks if the risk circuit breaker is triggered (1) for a specific currency pocket (USD/TWD).
    Returns True if triggered, False otherwise.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        query = "SELECT risk_circuit_breaker FROM capital_ledger WHERE currency = %s" if DB_TYPE == "mysql" else "SELECT risk_circuit_breaker FROM capital_ledger WHERE currency = ?"
        cursor.execute(query, (currency.upper(),))
        row = cursor.fetchone()
        if not row:
            return False
        if isinstance(row, dict):
            val = row.get("risk_circuit_breaker", 0)
        else:
            val = row[0]
        return int(val or 0) == 1


def update_risk_circuit_breaker(currency: str, state: int) -> None:
    """
    Updates the risk circuit breaker state (0 = Normal, 1 = Triggered) for a specific currency.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        query = "UPDATE capital_ledger SET risk_circuit_breaker = %s WHERE currency = %s" if DB_TYPE == "mysql" else "UPDATE capital_ledger SET risk_circuit_breaker = ? WHERE currency = ?"
        cursor.execute(query, (state, currency.upper()))
        conn.commit()


def rollback_reports_and_recommendations(report_date: str) -> None:
    """
    Safely rolls back recommendations, transactions, inference logs, and reports 
    for a specific report date. Restores cash balances for any BUY transactions 
    associated with recommendations from that day to ensure database consistency.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Get today's recommendation IDs
        execute_sql(
            cursor,
            "SELECT id, ticker, shares, invested_amount, region FROM recommendations WHERE report_date = ?",
            "SELECT id, ticker, shares, invested_amount, region FROM recommendations WHERE report_date = %s",
            (report_date,)
        )
        recs = cursor.fetchall()
        
        rec_ids = []
        if recs:
            rec_ids = [r["id"] if isinstance(r, dict) else r[0] for r in recs]
            
        # 2. Get BUY transactions to refund
        if rec_ids:
            rec_ids_str = ",".join(map(str, rec_ids))
            tx_query_sqlite = f"SELECT currency, amount FROM transaction_history WHERE action = 'BUY' AND rec_id IN ({rec_ids_str})"
            execute_sql(cursor, tx_query_sqlite, tx_query_sqlite)
            txs = cursor.fetchall()
            
            refunds = {"USD": 0.0, "TWD": 0.0}
            for tx in txs:
                curr = tx["currency"] if isinstance(tx, dict) else tx[0]
                amt = tx["amount"] if isinstance(tx, dict) else tx[1]
                refunds[curr] += amt
                
            # 3. Apply refunds to capital ledger
            for curr, amt in refunds.items():
                if amt > 0.0:
                    execute_sql(
                        cursor,
                        "SELECT available_capital FROM capital_ledger WHERE currency = ?",
                        "SELECT available_capital FROM capital_ledger WHERE currency = %s",
                        (curr,)
                    )
                    row = cursor.fetchone()
                    current_available = row["available_capital"] if isinstance(row, dict) else row[0]
                    new_available = current_available + amt
                    
                    execute_sql(
                        cursor,
                        "UPDATE capital_ledger SET available_capital = ? WHERE currency = ?",
                        "UPDATE capital_ledger SET available_capital = %s WHERE currency = %s",
                        (new_available, curr)
                    )
                    print(f"[*] [DB Consistency] Refunded {amt:.2f} {curr} to capital ledger. New balance: {new_available:.2f}")
                    
            # 4. Delete transaction history
            del_tx_sqlite = f"DELETE FROM transaction_history WHERE rec_id IN ({rec_ids_str})"
            execute_sql(cursor, del_tx_sqlite, del_tx_sqlite)
            
            # 5. Delete agent inference logs
            del_log_sqlite = f"DELETE FROM agent_inference_logs WHERE rec_id IN ({rec_ids_str})"
            execute_sql(cursor, del_log_sqlite, del_log_sqlite)
            
            # 6. Delete recommendations
            execute_sql(
                cursor,
                "DELETE FROM recommendations WHERE report_date = ?",
                "DELETE FROM recommendations WHERE report_date = %s",
                (report_date,)
            )
            print(f"[*] [DB Consistency] Purged recommendations and logs for {report_date}.")

        # 7. Delete report metadata using LIKE
        execute_sql(
            cursor,
            "DELETE FROM reports WHERE date LIKE ?",
            "DELETE FROM reports WHERE date LIKE %s",
            (f"{report_date}%",)
        )
        print(f"[*] [DB Consistency] Purged reports matching {report_date}% from DB.")

        # 8. Delete orphan agent inference logs created on this report date (rec_id is NULL)
        execute_sql(
            cursor,
            "DELETE FROM agent_inference_logs WHERE rec_id IS NULL AND created_at LIKE ?",
            "DELETE FROM agent_inference_logs WHERE rec_id IS NULL AND created_at LIKE %s",
            (f"{report_date}%",)
        )
        print(f"[*] [DB Consistency] Purged orphan agent inference logs matching {report_date}% from DB.")


# --- Macro Liquidity and Taiwan Chip Data Access Helpers ---

def save_macro_liquidity(record_date: str, fed_assets: float, tga_balance: float, reverse_repos: float, net_liquidity: float) -> None:
    """
    Inserts or updates a macro liquidity record (FRED data) in the database.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql":
            query = """
                INSERT INTO macro_liquidity_history (record_date, fed_assets, tga_balance, reverse_repos, net_liquidity)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    fed_assets = VALUES(fed_assets), 
                    tga_balance = VALUES(tga_balance), 
                    reverse_repos = VALUES(reverse_repos), 
                    net_liquidity = VALUES(net_liquidity)
            """
            cursor.execute(query, (record_date, fed_assets, tga_balance, reverse_repos, net_liquidity))
        else:
            query = """
                INSERT INTO macro_liquidity_history (record_date, fed_assets, tga_balance, reverse_repos, net_liquidity)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(record_date) DO UPDATE SET 
                    fed_assets = excluded.fed_assets, 
                    tga_balance = excluded.tga_balance, 
                    reverse_repos = excluded.reverse_repos, 
                    net_liquidity = excluded.net_liquidity
            """
            cursor.execute(query, (record_date, fed_assets, tga_balance, reverse_repos, net_liquidity))


def get_macro_liquidity(sim_date: str = None) -> dict:
    """
    Retrieves the latest macro liquidity record.
    If sim_date is provided (Backtesting mode), filters to return the latest record where record_date <= sim_date.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        if sim_date:
            execute_sql(cursor,
                "SELECT record_date, fed_assets, tga_balance, reverse_repos, net_liquidity FROM macro_liquidity_history WHERE record_date <= ? ORDER BY record_date DESC LIMIT 1",
                "SELECT record_date, fed_assets, tga_balance, reverse_repos, net_liquidity FROM macro_liquidity_history WHERE record_date <= %s ORDER BY record_date DESC LIMIT 1",
                (sim_date,)
            )
        else:
            execute_sql(cursor,
                "SELECT record_date, fed_assets, tga_balance, reverse_repos, net_liquidity FROM macro_liquidity_history ORDER BY record_date DESC LIMIT 1",
                "SELECT record_date, fed_assets, tga_balance, reverse_repos, net_liquidity FROM macro_liquidity_history ORDER BY record_date DESC LIMIT 1"
            )
        row = cursor.fetchone()
        if not row:
            return {}
        if isinstance(row, dict):
            return dict(row)
        return {
            "record_date": row[0],
            "fed_assets": row[1],
            "tga_balance": row[2],
            "reverse_repos": row[3],
            "net_liquidity": row[4]
        }


def save_taiwan_chip(record_date: str, foreign_futures_net_oi: int, foreign_net_buy: float, dealers_net_buy: float, investment_trust_net_buy: float) -> None:
    """
    Inserts or updates a Taiwan chip/capital flow record in the database.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql":
            query = """
                INSERT INTO taiwan_chip_history (record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    foreign_futures_net_oi = VALUES(foreign_futures_net_oi), 
                    foreign_net_buy = VALUES(foreign_net_buy), 
                    dealers_net_buy = VALUES(dealers_net_buy), 
                    investment_trust_net_buy = VALUES(investment_trust_net_buy)
            """
            cursor.execute(query, (record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy))
        else:
            query = """
                INSERT INTO taiwan_chip_history (record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(record_date) DO UPDATE SET 
                    foreign_futures_net_oi = excluded.foreign_futures_net_oi, 
                    foreign_net_buy = excluded.foreign_net_buy, 
                    dealers_net_buy = excluded.dealers_net_buy, 
                    investment_trust_net_buy = excluded.investment_trust_net_buy
            """
            cursor.execute(query, (record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy))


def get_taiwan_chip(sim_date: str = None) -> dict:
    """
    Retrieves the latest Taiwan chip/capital flow record.
    If sim_date is provided (Backtesting mode), filters to return the latest record where record_date <= sim_date.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        if sim_date:
            execute_sql(cursor,
                "SELECT record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy FROM taiwan_chip_history WHERE record_date <= ? ORDER BY record_date DESC LIMIT 1",
                "SELECT record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy FROM taiwan_chip_history WHERE record_date <= %s ORDER BY record_date DESC LIMIT 1",
                (sim_date,)
            )
        else:
            execute_sql(cursor,
                "SELECT record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy FROM taiwan_chip_history ORDER BY record_date DESC LIMIT 1",
                "SELECT record_date, foreign_futures_net_oi, foreign_net_buy, dealers_net_buy, investment_trust_net_buy FROM taiwan_chip_history ORDER BY record_date DESC LIMIT 1"
            )
        row = cursor.fetchone()
        if not row:
            return {}
        if isinstance(row, dict):
            return dict(row)
        return {
            "record_date": row[0],
            "foreign_futures_net_oi": row[1],
            "foreign_net_buy": row[2],
            "dealers_net_buy": row[3],
            "investment_trust_net_buy": row[4]
        }

def clear_taiwan_chip_history() -> None:
    """
    Clears all records from the 'taiwan_chip_history' table.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM taiwan_chip_history")

def get_historical_futures_oi(sim_date: str, limit: int = 60) -> list:
    """
    Retrieves the last N historical records of foreign_futures_net_oi strictly before sim_date.
    Used for calculating dynamic rolling thresholds.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        if DB_TYPE == "mysql":
            query = "SELECT foreign_futures_net_oi FROM taiwan_chip_history WHERE record_date < %s ORDER BY record_date DESC LIMIT %s"
        else:
            query = "SELECT foreign_futures_net_oi FROM taiwan_chip_history WHERE record_date < ? ORDER BY record_date DESC LIMIT ?"
        cursor.execute(query, (sim_date, limit))
        rows = cursor.fetchall()
        # Handle different row formats (tuple vs dict) depending on connector
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [r["foreign_futures_net_oi"] for r in rows]
        return [r[0] for r in rows]





