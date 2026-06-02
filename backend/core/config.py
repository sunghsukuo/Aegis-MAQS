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
REGIONS = {
    "US": {
        "name": "美股",
        "benchmark": "^GSPC",  # S&P 500
        "currency": "USD",
        # Sector ETFs with pre-seeded constituents backup cache integrated
        "sector_etfs": {
            "XLK": {
                "name": "科技 (Technology)",
                "constituents": [
                    "MSFT", "AAPL", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "QCOM", "NOW", "ADBE", 
                    "INTU", "TXN", "AMAT", "MU", "IBM", "LRCX", "PANW", "ADI", "KLAC", "SNPS"
                ]
            },
            "XLF": {
                "name": "金融 (Financials)",
                "target_type": "proxy",
                "constituents": [
                    "JPM", "BRK-B", "V", "MA", "BAC", "WFC", "MS", "GS", "SCHW", "C", 
                    "BLK", "AXP", "BX", "CB", "SPGI", "MMC", "PGR", "MET", "AON", "USB"
                ]
            },
            "XLE": {
                "name": "能源 (Energy)",
                "target_type": "proxy",
                "constituents": [
                    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "WMB", 
                    "HAL", "BKR", "HES", "KMI", "ONEOK", "DVN", "CTRA", "APA", "FANG", "MRO"
                ]
            },
            "XLV": {
                "name": "醫療保健 (Healthcare)",
                "constituents": [
                    "LLY", "UNH", "JNJ", "ABBV", "MRK", "AMGN", "HCA", "PFE", "ISRG", "SYK", 
                    "BSX", "MDT", "ABT", "GILD", "VRTX", "BMY", "REGN", "CI", "CVS", "ELV"
                ]
            },
            "XLY": {
                "name": "非必須消費 (Consumer Discretionary)",
                "constituents": [
                    "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "TJX", "SBUX", "BKNG", "CMG", 
                    "MAR", "F", "GM", "ORLY", "AZO", "HLT", "LVS", "YUM", "DHI", "PHM"
                ]
            },
            "XLI": {
                "name": "工業 (Industrial)",
                "constituents": [
                    "GE", "CAT", "RTX", "HON", "UNP", "LMT", "ETN", "DE", "WM", "BA", 
                    "CSX", "NSC", "ITW", "GD", "NOC", "EMR", "PH", "FDX", "UPS", "CPRT"
                ]
            },
            "XLP": {
                "name": "必須消費 (Consumer Staples)",
                "constituents": [
                    "PG", "COST", "KO", "PEP", "PM", "MO", "WMT", "EL", "MDLZ", "CL", 
                    "SYY", "KDP", "KR", "K", "GIS", "STZ", "HSY", "CHD", "ADM", "TSN"
                ]
            },
            "XLB": {
                "name": "原物料 (Materials)",
                "constituents": [
                    "LIN", "SHW", "APD", "FCX", "ECL", "NEM", "CTVA", "DOW", "DD", "PPG", 
                    "VMC", "MLM", "IFF", "ALB", "CF", "NUE", "MOS", "FMC"
                ]
            },
            "XLU": {
                "name": "公用事業 (Utilities)",
                "constituents": [
                    "NEE", "SO", "DUK", "CEG", "WEC", "D", "AEP", "PEG", "EXC", "PCG", 
                    "SRE", "ED", "XEL", "EIX", "FE", "AWK", "ES", "CNP", "ETR", "ATO"
                ]
            }
        }
    },
    "Taiwan": {
        "name": "台股",
        "benchmark": "^TWII",  # TAIEX
        "currency": "TWD",
        # Taiwan standard tracking ETFs & Sector proxies with constituents cache integrated
        "sector_etfs": {
            "0050.TW": {
                "name": "元大台灣50 (Broad Market)",
                "target_type": "constituents",
                "constituents": [
                    "2330.TW", "2317.TW", "2454.TW", "2382.TW", "2308.TW", "2881.TW", "2882.TW", "2303.TW", 
                    "2891.TW", "3711.TW", "2412.TW", "1216.TW", "2886.TW", "5871.TW", "2603.TW", "2884.TW", 
                    "2892.TW", "3231.TW", "2357.TW", "2324.TW", "2885.TW", "2880.TW", "2912.TW", "3045.TW"
                ]
            },
	    "0051.TW": {
                "name": "元大台灣中型100 (Mid-Cap Market)",
                "target_type": "constituents",
                "constituents": [
                    "3443.TW", "4958.TW", "3481.TW", "3665.TW", "2337.TW", "6770.TW", "2313.TW", "2379.TW",
                    "3034.TW", "6239.TW", "6446.TW", "3036.TW", "3189.TW", "3044.TW", "3533.TW", "6515.TW",
                    "2376.TW", "6415.TW", "1590.TW", "2404.TW", "2356.TW", "8046.TW", "3702.TW", "4938.TW",
                    "1326.TW"
                ]
            },
            "0052.TW": {
                "name": "富邦科技 (Tech Sector)",
                "target_type": "constituents",
                "constituents": [
                    "2330.TW", "2454.TW", "2317.TW", "2382.TW", "2308.TW", "2303.TW", "3711.TW", "2379.TW", 
                    "3231.TW", "2345.TW", "2408.TW", "3034.TW", "2357.TW", "2449.TW", "3044.TW", "2376.TW", 
                    "2301.TW", "6239.TW", "3008.TW", "2409.TW", "3481.TW", "8046.TW", "3532.TW", "2439.TW"
                ]
            },
            "0056.TW": {
                "name": "元大高股息 (High Dividend)",
                "target_type": "proxy",
                "constituents": [
                    "2382.TW", "3231.TW", "2301.TW", "2357.TW", "2603.TW", "3034.TW", "2454.TW", "2324.TW", 
                    "3711.TW", "2379.TW", "3044.TW", "2409.TW", "3481.TW", "2891.TW", "2886.TW", "2408.TW", 
                    "2303.TW", "2882.TW", "2881.TW", "1101.TW", "2002.TW", "2885.TW", "2892.TW", "2890.TW"
                ]
            },
            "00892.TW": {
                "name": "富邦台灣半導體 (Semiconductor Sector)",
                "target_type": "constituents",
                "constituents": [
                    "2330.TW", "2454.TW", "7769.TW", "3711.TW", "5274.TWO", "3034.TW", "6223.TWO", 
                    "2379.TW", "6515.TW", "3529.TWO", "6187.TWO", "2455.TW", "5434.TW", "3131.TWO", "6510.TWO"
                ]
            },
            "00947.TW": {
                "name": "台新臺灣IC設計 (IC Design Sector)",
                "target_type": "constituents",
                "constituents": [
                    "2454.TW", "2408.TW", "2344.TW", "2308.TW", "8299.TWO", "3443.TW", "5274.TWO", 
                    "3661.TW", "2337.TW", "3529.TWO", "6415.TW", "6531.TW", "2379.TW", "3034.TW", "5269.TW"
                ]
            },
            "2330.TW": {
                "name": "台積電 (TSMC Direct)",
                "target_type": "proxy",
                "is_etf": False
            },
            "2881.TW": {
                "name": "富邦金 (Financials Proxy)",
                "constituents": ["2881.TW", "2882.TW", "2891.TW", "2886.TW", "2884.TW", "2880.TW", "2885.TW", "2892.TW", "2890.TW", "5880.TW", "5876.TW", "2834.TW", "2883.TW", "2887.TW"]
            },
            "1301.TW": {
                "name": "台塑 (Materials/Old Economy Proxy)",
                "constituents": ["1301.TW", "1303.TW", "1326.TW", "6505.TW", "2002.TW", "1101.TW", "1402.TW", "2603.TW", "2609.TW", "2615.TW", "1102.TW", "2105.TW", "1304.TW", "1314.TW"]
            }
        }
    }
}

# AI Settings
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"  # Highly efficient for agent loops
WRITER_GEMINI_MODEL = "gemini-2.5-flash"   # Standardized to Flash to respect free tier daily limits
TEMPERATURE = 0.2

# Pipeline Limits (for API quota management)
MAX_SECTORS_PER_REGION = 2  # Default to scan top 2 performing sectors
MAX_STOCKS_PER_REGION = 4   # Default to deep-dive top 4 representative stocks per region

