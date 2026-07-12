import time
import functools
import sys

def retry_on_exception(tries=3, delay=2, backoff=2, exceptions=(Exception,)):
    """
    Pure-Python Exponential Backoff Retry Decorator.
    Tries to execute the decorated function. If it raises an exception in `exceptions`,
    it sleeps for `delay` seconds, multiplies `delay` by `backoff`, and retries up to `tries` times.
    Useful for defensive coding against network turbulence or API rate limiting.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            mdelay = delay
            for attempt in range(1, tries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == tries:
                        print(f"\033[91m[✗] {func.__name__} failed permanently after {tries} attempts. Error: {e}\033[0m")
                        raise e
                    print(f"\033[93m[!] {func.__name__} failed (attempt {attempt}/{tries}). Retrying in {mdelay}s... Error: {e}\033[0m")
                    time.sleep(mdelay)
                    mdelay *= backoff
            return None
        return wrapper
    return decorator

def get_cached_data(cache_dir, cache_key: str, ttl_hours: int = 12) -> dict:
    """
    Retrieves cached data from a local JSON file if it exists and is newer than ttl_hours.
    Returns None if cache is expired, invalid, or missing.
    Supports date-isolated backtest caching to prevent network rate limits and lookahead bias.
    """
    import os
    import sys
    import json
    from datetime import datetime, timedelta
    from pathlib import Path
    
    sim_date = None
    is_backtest = os.environ.get("AEGIS_IN_BACKTEST") == "1"
    if is_backtest:
        try:
            from backtest.replayer import get_simulated_date
            sim_date = get_simulated_date()
        except Exception:
            pass

    is_testing = "pytest" in sys.modules or "unittest" in sys.modules
    
    # Standard testing check (no simulated date)
    if is_testing and not sim_date:
        return None
        
    # If in backtest mode but no simulated date is set, bypass cache
    if is_backtest and not sim_date:
        return None
        
    if sim_date:
        # Route to date-isolated backtest cache folder
        target_dir = Path(cache_dir) / f"backtest_{sim_date}"
        ttl_hours = 999999  # Infinite TTL for historical static backtest data
    else:
        target_dir = Path(cache_dir)
        
    cache_file = target_dir / f"{cache_key}.json"
    if not cache_file.exists():
        return None
        
    try:
        # Check mtime (modification time) if not in backtest
        if not sim_date:
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
            if datetime.now() - mtime > timedelta(hours=ttl_hours):
                # Cache expired
                return None
            
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Warning: Failed to read local cache {cache_key}: {e}")
        return None


def save_to_cache(cache_dir, cache_key: str, data: dict):
    """
    Saves a dictionary as a local JSON file to act as database/network cache.
    Supports date-isolated backtest caching.
    """
    import os
    import sys
    import json
    from pathlib import Path
    
    sim_date = None
    is_backtest = os.environ.get("AEGIS_IN_BACKTEST") == "1"
    if is_backtest:
        try:
            from backtest.replayer import get_simulated_date
            sim_date = get_simulated_date()
        except Exception:
            pass

    is_testing = "pytest" in sys.modules or "unittest" in sys.modules
    
    # Standard testing check (no simulated date)
    if is_testing and not sim_date:
        return
        
    # If in backtest mode but no simulated date is set, bypass cache
    if is_backtest and not sim_date:
        return
        
    if sim_date:
        target_dir = Path(cache_dir) / f"backtest_{sim_date}"
    else:
        target_dir = Path(cache_dir)
        
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        cache_file = target_dir / f"{cache_key}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[!] Warning: Failed to save to local cache {cache_key}: {e}")

def rotate_log_file(log_file_path, max_bytes=10*1024*1024, backup_count=3):
    """
    Defensively rotates a log file if it exceeds max_bytes.
    Keeps up to backup_count historical rotated logs (e.g., log.1, log.2).
    Designed to prevent disk space exhaustion for crontab redirected outputs.
    """
    from pathlib import Path
    import os
    import shutil
    
    log_path = Path(log_file_path)
    if not log_path.exists() or log_path.stat().st_size < max_bytes:
        return
        
    try:
        # Rotate existing backups: log.2 -> log.3, log.1 -> log.2
        for i in range(backup_count - 1, 0, -1):
            s_file = log_path.with_name(f"{log_path.name}.{i}")
            d_file = log_path.with_name(f"{log_path.name}.{i+1}")
            if s_file.exists():
                if d_file.exists():
                    d_file.unlink()
                shutil.move(str(s_file), str(d_file))
                
        # Move current log to log.1
        backup_one = log_path.with_name(f"{log_path.name}.1")
        if backup_one.exists():
            backup_one.unlink()
            
        shutil.move(str(log_path), str(backup_one))
        
        # Create a fresh empty log file
        log_path.touch()
        print(f"[✓] Log Rotator: Successfully rotated legacy log file: {log_path.name}")
    except Exception as e:
        print(f"[!] Log Rotator Warning: Failed to rotate log file {log_path.name}: {e}")

def log_error_details(module_name: str, message: str, exception: Exception):
    """
    Defensively logs full exception traceback details to logs/error_details.log
    to allow fast diagnosing without dirtying stdout/stderr logs.
    """
    import traceback
    from datetime import datetime
    from core.config import LOGS_DIR
    
    error_log_file = LOGS_DIR / "error_details.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb_str = traceback.format_exc()
    
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(error_log_file, "a", encoding="utf-8") as f:
            f.write(f"=== [{timestamp}] [{module_name}] {message} ===\n")
            f.write(f"Exception Type: {type(exception).__name__}\n")
            f.write(f"Error Message: {str(exception)}\n")
            f.write(f"Traceback:\n{tb_str}")
            f.write("=" * 60 + "\n\n")
    except Exception as le:
        sys.stderr.write(f"[!] Warning: Failed to write to error_details.log: {le}\n")

def clean_expired_cache(cache_dir, max_age_days=7):
    """
    Periodically cleans up old cache files from the cache directory.
    Deletes files older than max_age_days:
    - agent_cache_*.json
    - financials_*.json
    - price_regime_*.json
    - pipeline_state_*.json
    """
    import os
    import time
    from pathlib import Path
    import sys
    
    # Bypass during backtests or unit tests
    is_testing = "pytest" in sys.modules or "unittest" in sys.modules
    is_backtest = os.environ.get("AEGIS_IN_BACKTEST") == "1"
    if is_testing or is_backtest:
        return
        
    try:
        cache_path = Path(cache_dir)
        if not cache_path.exists():
            return
            
        now = time.time()
        max_age_seconds = max_age_days * 24 * 3600
        deleted_count = 0
        
        # Target specific temporary cache prefixes to avoid deleting config files
        target_prefixes = [
            "agent_cache_", 
            "financials_", 
            "price_regime_", 
            "pipeline_state_"
        ]
        
        for file in cache_path.glob("*.json"):
            if any(file.name.startswith(pref) for pref in target_prefixes):
                try:
                    mtime = file.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        file.unlink()
                        deleted_count += 1
                except Exception as e:
                    print(f"[!] Warning: Failed to delete old cache file {file.name}: {e}")
                    
        if deleted_count > 0:
            print(f"[✓] Cache Cleanup: Automatically purged {deleted_count} expired cache files (> {max_age_days} days old).")
    except Exception as e:
        print(f"[!] Warning: Failed to run cache cleanup: {e}")
