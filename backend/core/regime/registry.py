import json
from pathlib import Path
from core.config import CACHE_DIR

REGIME_CACHE_FILE = CACHE_DIR / "market_regime.json"

def save_market_regime(region_code: str, regime_info: dict):
    """
    Saves the detected market regime info for a region into the cache file.
    """
    data = {}
    if REGIME_CACHE_FILE.exists():
        try:
            with open(REGIME_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
            
    data[region_code] = regime_info
    
    try:
        with open(REGIME_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Warning: Failed to write market regime cache: {e}")


def get_market_regime(region_code: str) -> dict:
    """
    Retrieves the cached market regime for a region.
    Defaults to MOMENTUM_TREND if not cached or failed.
    """
    if REGIME_CACHE_FILE.exists():
        try:
            with open(REGIME_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if region_code in data:
                    return data[region_code]
        except Exception:
            pass
            
    # Default fallback if cache is empty or missing
    return {
        "regime": "MOMENTUM_TREND",
        "adx": 20.0,
        "hurst": 0.50,
        "ticker": "^GSPC" if region_code == "US" else "^TWII"
    }
