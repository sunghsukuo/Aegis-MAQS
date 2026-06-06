import os
from pathlib import Path
from dotenv import load_dotenv

# Load local environment variables from .env file
# Root of backend is parent of core
BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env", override=True)

# Core Paths
CORE_DIR = BACKEND_ROOT / "core"
DATA_DIR = CORE_DIR / "data"
DB_DIR = DATA_DIR / "db"

# Configurable reports directory with fallback
DEFAULT_REPORTS_DIR = "/mnt/p/linux/Aegis-MAQS/data/reports"
REPORTS_DIR_PATH = os.getenv("REPORTS_DIR", DEFAULT_REPORTS_DIR)
REPORTS_DIR = Path(REPORTS_DIR_PATH)

# Ensure directories exist
DB_DIR.mkdir(parents=True, exist_ok=True)
try:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    # Fallback to local core/data/reports if path is unavailable/unmounted
    fallback_path = DATA_DIR / "reports"
    print(f"[!] Warning: Failed to create REPORTS_DIR at {REPORTS_DIR}. Falling back to local: {fallback_path}. Error: {e}")
    REPORTS_DIR = fallback_path
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Logs Directory
LOGS_DIR = BACKEND_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Cache Directory
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# LINE Messaging API Configuration
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

# Database Configuration
DB_TYPE = os.getenv("DB_TYPE", "sqlite")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "your_mysql_password_here")
# If the password is still the template default, treat it as empty or use a blank string
if MYSQL_PASSWORD == "your_mysql_password_here":
    MYSQL_PASSWORD = ""
MYSQL_DB = os.getenv("MYSQL_DB", "investment_db")

# Report Language Configuration
REPORT_LANGUAGE = os.getenv("REPORT_LANGUAGE", "EN").upper()


# Supported Regions & Benchmarks
import json

# Supported Regions & Benchmarks (Base Structural Configuration)
REGIONS = {
    "US": {
        "name": "美股",
        "benchmark": "^GSPC",  # S&P 500
        "currency": "USD",
        "sector_etfs": {}
    },
    "Taiwan": {
        "name": "台股",
        "benchmark": "^TWII",  # TAIEX
        "currency": "TWD",
        "sector_etfs": {}
    }
}

# Dynamically load sector ETFs and constituents configurations from JSON file
SECTORS_JSON_PATH = DATA_DIR / "sectors_config.json"
if SECTORS_JSON_PATH.exists():
    try:
        with open(SECTORS_JSON_PATH, "r", encoding="utf-8") as f:
            json_sectors = json.load(f)
            for r_code, sector_etfs in json_sectors.items():
                if r_code in REGIONS:
                    REGIONS[r_code]["sector_etfs"] = sector_etfs
    except Exception as e:
        print(f"[!] Warning: Failed to load dynamic sectors config from JSON: {e}")
else:
    print(f"[!] Warning: {SECTORS_JSON_PATH} not found. Running with empty sector list.")

# AI Settings
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"  # Highly efficient for agent loops
WRITER_GEMINI_MODEL = "gemini-2.5-flash"   # Standardized to Flash to respect free tier daily limits
TEMPERATURE = 0.2

# Pipeline Limits (for API quota management)
MAX_SECTORS_PER_REGION = 2  # Default to scan top 2 performing sectors
MAX_STOCKS_PER_REGION = 4   # Default to deep-dive top 4 representative stocks per region


# Dynamic Wind-Down / Drawdown Watchdog Settings
DEFAULT_MDD_LIMIT = float(os.getenv("DEFAULT_MDD_LIMIT", "0.03"))
DEFAULT_TWD_MDD_LIMIT = float(os.getenv("DEFAULT_TWD_MDD_LIMIT", "0.03"))        # Taiwan stock MDD default limit (3%)
DEFAULT_USD_MDD_LIMIT = float(os.getenv("DEFAULT_USD_MDD_LIMIT", "0.06"))        # US stock MDD default limit (6%) due to no price limits

# Regime-based MDD Warning Limit Multipliers (applied to DEFAULT_MDD_LIMIT)
BULL_MDD_MULTIPLIER = float(os.getenv("BULL_MDD_MULTIPLIER", "1.50"))            # e.g. 0.03 * 1.50 = 0.045
BEAR_MDD_MULTIPLIER = float(os.getenv("BEAR_MDD_MULTIPLIER", "0.70"))            # e.g. 0.03 * 0.70 = 0.021
RANGEBOUND_MDD_MULTIPLIER = float(os.getenv("RANGEBOUND_MDD_MULTIPLIER", "1.00")) # e.g. 0.03 * 1.00 = 0.03






