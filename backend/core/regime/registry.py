import json
from pathlib import Path
from core.config import CACHE_DIR

REGIME_CACHE_FILE = CACHE_DIR / "macro_regime.json"

_in_memory_regimes = {}

def save_macro_regime(region_code: str, regime_info: dict):
    """
    Saves the detected macro regime info for a region into the cache file.
    """
    import os
    import sys
    is_testing = "pytest" in sys.modules or "unittest" in sys.modules
    is_backtest = os.environ.get("AEGIS_IN_BACKTEST") == "1"
    
    if is_testing or is_backtest:
        _in_memory_regimes[region_code] = regime_info
        return
        
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
        print(f"[!] Warning: Failed to write macro regime cache: {e}")


def get_macro_regime(region_code: str) -> dict:
    """
    Retrieves the cached macro regime for a region.
    Defaults to VOLATILE_RANGEBOUND if not cached or failed.
    """
    import os
    import sys
    is_testing = "pytest" in sys.modules or "unittest" in sys.modules
    is_backtest = os.environ.get("AEGIS_IN_BACKTEST") == "1"
    
    if is_testing or is_backtest:
        if region_code in _in_memory_regimes:
            return _in_memory_regimes[region_code]
            
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
        "regime": "VOLATILE_RANGEBOUND",
        "adx": 20.0,
        "hurst": 0.50,
        "ticker": "^GSPC" if region_code == "US" else "^TWII"
    }
