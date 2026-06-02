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
    """
    import os
    import json
    from datetime import datetime, timedelta
    from pathlib import Path
    
    cache_file = Path(cache_dir) / f"{cache_key}.json"
    if not cache_file.exists():
        return None
        
    try:
        # Check mtime (modification time)
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
    """
    import json
    from pathlib import Path
    
    try:
        target_dir = Path(cache_dir)
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
