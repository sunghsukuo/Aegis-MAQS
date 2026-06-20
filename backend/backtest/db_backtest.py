import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

# Define the isolated database path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = BACKEND_ROOT / "core" / "data" / "db"
BACKTEST_DB_PATH = DB_DIR / "backtest_investment.db"

# Ensure database directory exists
DB_DIR.mkdir(parents=True, exist_ok=True)

@contextmanager
def backtest_db_session():
    """
    Context manager for isolated backtest database connection.
    Automatically commits on success and rolls back on exception.
    """
    conn = sqlite3.connect(BACKTEST_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise e
    finally:
        conn.close()


def init_backtest_database(initial_usd: float = 100000.0, initial_twd: float = 3000000.0):
    """
    Initializes ALL 11 tables for backtesting and seeds static configs from the production database.
    This ensures complete database isolation and eliminates database table errors.
    """
    with backtest_db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Reports Table DDL (matches production SQLite schema exactly)
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
        
        # 2. Recommendations Table DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                region TEXT NOT NULL,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                recommend_price REAL NOT NULL,
                recommend_reason TEXT,
                target_price REAL,
                stop_loss REAL,
                rating TEXT,
                is_active INTEGER DEFAULT 1,
                close_price REAL,
                close_date TEXT,
                performance REAL,
                invested_amount REAL DEFAULT 0.0,
                shares REAL DEFAULT 0.0,
                pnl REAL DEFAULT 0.0,
                macro_regime TEXT DEFAULT NULL,
                price_regime TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 3. Capital Ledger Table DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capital_ledger (
                currency TEXT PRIMARY KEY,
                available_capital REAL NOT NULL,
                reserved_cash REAL DEFAULT 0.0,
                risk_circuit_breaker INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 4. Transaction History Table DDL
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
                transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 5. Portfolio NAV History Table DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_nav_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                currency TEXT NOT NULL,
                total_nav REAL NOT NULL,
                available_capital REAL NOT NULL,
                active_value REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (date, currency)
            )
        """)
        
        # 6. Prompt Registry Table DDL
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
        
        # 8. Taiwan Stock Names Table DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS taiwan_stock_names (
                stock_code TEXT PRIMARY KEY,
                chinese_name TEXT NOT NULL,
                market_type TEXT NOT NULL DEFAULT 'TW',
                industry_type TEXT DEFAULT ''
            )
        """)
        
        # 9. Sector Registry Table DDL
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
            )
        """)
        
        # 10. Sector Constituents Table DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sector_constituents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                company_name TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (sector_id, ticker),
                FOREIGN KEY (sector_id) REFERENCES sector_registry(id) ON DELETE CASCADE
            )
        """)
        
        # 11. Risk Circuit Breaker Table DDL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS risk_circuit_breaker (
                currency TEXT PRIMARY KEY,
                triggered INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        
        # Seed initial mock capital and reset transient databases
        cursor.execute("SELECT COUNT(*) as count FROM capital_ledger")
        row = cursor.fetchone()
        if row["count"] == 0:
            cursor.execute(
                "INSERT INTO capital_ledger (currency, available_capital, reserved_cash) VALUES (?, ?, ?)",
                ("USD", initial_usd, 0.0)
            )
            cursor.execute(
                "INSERT INTO capital_ledger (currency, available_capital, reserved_cash) VALUES (?, ?, ?)",
                ("TWD", initial_twd, 0.0)
            )
            cursor.execute("INSERT OR IGNORE INTO risk_circuit_breaker (currency, triggered) VALUES (?, 0)", ("USD",))
            cursor.execute("INSERT OR IGNORE INTO risk_circuit_breaker (currency, triggered) VALUES (?, 0)", ("TWD",))
            conn.commit()
        else:
            cursor.execute("UPDATE capital_ledger SET available_capital = ?, reserved_cash = 0.0 WHERE currency = ?", (initial_usd, "USD"))
            cursor.execute("UPDATE capital_ledger SET available_capital = ?, reserved_cash = 0.0 WHERE currency = ?", (initial_twd, "TWD"))
            cursor.execute("UPDATE risk_circuit_breaker SET triggered = 0")
            cursor.execute("DELETE FROM recommendations")
            cursor.execute("DELETE FROM transaction_history")
            cursor.execute("DELETE FROM portfolio_nav_history")
            cursor.execute("DELETE FROM reports")
            cursor.execute("DELETE FROM agent_inference_logs")
            conn.commit()
            
        # Seed Static Configurations from the Production Database
        seed_static_configurations(conn)
        print(f"[🛡️ 回測沙盒] 隔離資料庫(11張表)重設與 Seeding 完成！已注資虛擬本金：USD ${initial_usd:,.2f} | TWD ${initial_twd:,.2f}")

def seed_static_configurations(backtest_conn):
    """
    Seeds static configuration data from the production database to the backtest database.
    Static tables include: taiwan_stock_names, sector_registry, sector_constituents, and prompt_registry.
    """
    import core.db_manager as prod_db
    backtest_cursor = backtest_conn.cursor()
    
    # Empty existing configurations in backtest to prevent duplicate key errors
    backtest_cursor.execute("DELETE FROM taiwan_stock_names")
    backtest_cursor.execute("DELETE FROM sector_constituents")
    backtest_cursor.execute("DELETE FROM sector_registry")
    backtest_cursor.execute("DELETE FROM prompt_registry")
    backtest_conn.commit()
    
    # Temporarily restore DB_TYPE to production configuration to load configurations from the correct database (e.g. MySQL)
    import os
    old_db_type = prod_db.DB_TYPE
    prod_db.DB_TYPE = os.getenv("DB_TYPE", "sqlite")
    
    try:
        # Load from production
        with prod_db.db_session() as prod_conn:
            prod_cursor = prod_conn.cursor()
            
            # A. Seed taiwan_stock_names
            prod_db.execute_sql(prod_cursor, "SELECT * FROM taiwan_stock_names", "SELECT * FROM taiwan_stock_names")
            rows = prod_cursor.fetchall()
            for r in rows:
                row_dict = dict(r)
                backtest_cursor.execute(
                    "INSERT INTO taiwan_stock_names (stock_code, chinese_name, market_type, industry_type) VALUES (?, ?, ?, ?)",
                    (row_dict["stock_code"], row_dict["chinese_name"], row_dict.get("market_type", "TW"), row_dict.get("industry_type", ""))
                )
                
            # B. Seed sector_registry
            prod_db.execute_sql(prod_cursor, "SELECT * FROM sector_registry", "SELECT * FROM sector_registry")
            rows = prod_cursor.fetchall()
            for r in rows:
                row_dict = dict(r)
                backtest_cursor.execute(
                    """INSERT INTO sector_registry (id, region, sector_code, sector_name, target_type, is_etf, is_active)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (row_dict["id"], row_dict["region"], row_dict["sector_code"],
                     row_dict["sector_name"], row_dict["target_type"], row_dict["is_etf"], row_dict["is_active"])
                )
                
            # C. Seed sector_constituents
            prod_db.execute_sql(prod_cursor, "SELECT * FROM sector_constituents", "SELECT * FROM sector_constituents")
            rows = prod_cursor.fetchall()
            for r in rows:
                row_dict = dict(r)
                backtest_cursor.execute(
                    "INSERT INTO sector_constituents (id, sector_id, ticker, company_name) VALUES (?, ?, ?, ?)",
                    (row_dict["id"], row_dict["sector_id"], row_dict["ticker"], row_dict.get("company_name", ""))
                )
                
            # D. Seed prompt_registry (only the active prompts)
            prod_db.execute_sql(prod_cursor, "SELECT * FROM prompt_registry WHERE is_active = 1", "SELECT * FROM prompt_registry WHERE is_active = 1")
            rows = prod_cursor.fetchall()
            for r in rows:
                row_dict = dict(r)
                backtest_cursor.execute(
                    """INSERT INTO prompt_registry (id, agent_name, system_prompt, version, is_active, performance_score)
                       VALUES (?, ?, ?, ?, 1, ?)""",
                    (row_dict["id"], row_dict["agent_name"], row_dict["system_prompt"], row_dict["version"], row_dict.get("performance_score", 0.0))
                )
                
            backtest_conn.commit()
            print("[🛡️ 回測沙盒] 已成功同步實戰資料庫配置 (板塊/台股名稱/Prompt) 至回測資料庫。")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[!] Warning: 無法同步實戰資料庫設定，回測將使用空設定運行。錯誤: {e}")
    finally:
        prod_db.DB_TYPE = old_db_type

def get_backtest_capital_state(currency: str) -> dict:
    """Helper to retrieve capital state from backtest ledger."""
    currency = currency.upper()
    with backtest_db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM capital_ledger WHERE currency = ?", (currency,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return {"currency": currency, "available_capital": 0.0, "reserved_cash": 0.0}

def apply_backtest_db_sandbox():
    """
    Globally patches core.db_manager and core.config to redirect all database operations
    to the backtest database and force SQLite dialect usage.
    This guarantees 0% production database pollution.
    """
    import core.config as config
    import core.db_manager as prod_db
    
    # 1. Force SQLite mode globally
    config.DB_TYPE = "sqlite"
    prod_db.DB_TYPE = "sqlite"
    
    # 2. Redirect DB Path to backtest DB file
    prod_db.DB_PATH = BACKTEST_DB_PATH
    
    # 3. Override db_session context manager
    prod_db.db_session = backtest_db_session
    
    print("[🛡️ 回測沙盒] 已啟動資料庫安全隔離猴子補丁 (Monkey-Patch)。")
    print(f"            - 所有的 db_session() 連線皆已導向：{BACKTEST_DB_PATH}")
    print("            - DB_TYPE 已強制設為 SQLITE（防止 MySQL 寫入及 SQL 語法解析錯誤）。")
