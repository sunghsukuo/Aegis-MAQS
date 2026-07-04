"""
Aegis-MAQS (Aegis Multi-Agent Quantmental System)
Module: core.tools.fred_client
Description:
    Federal Reserve Economic Data (FRED) API client.
    Enables reliable online fetching of US macroeconomic indicators 
    (e.g., Fed Assets WALCL, TGA WTGANN, RRP RRPONTSYD) using a valid FRED API Key.
    Designed with standalone testability and clean fallbacks for high maintainability.
"""

import sys
from pathlib import Path

# Dynamic path bootstrapping: Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import json
import urllib.request
import urllib.parse
from datetime import datetime
import core.config as config


class FredClient:
    """
    FredClient handles communication with the St. Louis Fed's FRED API.
    Provides methods to query economic time series data directly.
    """
    def __init__(self, api_key: str = None):
        # Use provided key or fall back to the project configuration
        self.api_key = api_key if api_key else config.FRED_API_KEY
        if not self.api_key:
            raise ValueError(
                "FRED API Key is missing. Please set FRED_API_KEY in your .env file "
                "or pass it directly to the FredClient constructor."
            )
        self.base_url = "https://api.stlouisfed.org/fred/series/observations"

    def fetch_observations(self, series_id: str, start_date: str = None) -> dict:
        """
        Fetch historical observations for a specific FRED series.
        
        Args:
            series_id (str): FRED series identifier (e.g., 'WALCL', 'WTGANN', 'RRPONTSYD').
            start_date (str): Optional. Fetch data starting from this date (format: 'YYYY-MM-DD').
            
        Returns:
            dict: A dictionary mapping date strings (YYYY-MM-DD) to float values.
                  Returns an empty dictionary if the request fails.
        """
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json"
        }
        if start_date:
            params["observation_start"] = start_date

        # Encode parameters and build final API URL
        url_params = urllib.parse.urlencode(params)
        url = f"{self.base_url}?{url_params}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AegisMAQS/1.0",
            "Accept": "application/json"
        }
        
        print(f"[*] Querying FRED API for series '{series_id}'...")
        
        try:
            req = urllib.request.Request(url, headers=headers)
            # Fetch with a 20-second timeout to handle slow connections
            with urllib.request.urlopen(req, timeout=20) as response:
                content = response.read().decode("utf-8")
                res_data = json.loads(content)
                
                observations = res_data.get("observations", [])
                data_map = {}
                
                for obs in observations:
                    date_str = obs.get("date")
                    val_str = obs.get("value")
                    
                    # Skip missing or placeholder data
                    if not date_str or not val_str or val_str == ".":
                        continue
                        
                    try:
                        data_map[date_str] = float(val_str)
                    except ValueError:
                        continue
                
                print(f"[✓] Successfully fetched {len(data_map)} observations for '{series_id}'.")
                return data_map
                
        except Exception as e:
            print(f"[✗] Failed to fetch series '{series_id}' from FRED API: {e}")
            return {}

# --- Standalone Self-Testing Block ---

if __name__ == "__main__":
    print("\033[93m==================================================\033[0m")
    print("\033[93m🧪 單獨功能測試：FRED API 資料取得物件 (fred_client.py)\033[0m")
    print("\033[93m==================================================\033[0m")
    
    try:
        # Initialize client (will load from config/env)
        client = FredClient()
        print(f"[✓] FredClient 成功初始化。API Key: {client.api_key[:6]}...{client.api_key[-4:]}")
        
        # We will fetch a small slice of WALCL (Fed Total Assets) for testing
        # Limit start_date to recent history to minimize payload size and speed up test
        test_series = "WALCL"
        start_date = "2026-01-01"
        
        print(f"\n[*] 測試動作：取得 {test_series} 自 {start_date} 起的數據...")
        data = client.fetch_observations(test_series, start_date=start_date)
        
        if data:
            print(f"\n[✓] 測試成功！共取得 {len(data)} 筆數據。")
            # Print the first 5 records as a sample
            sorted_dates = sorted(data.keys())
            print("\n🔍 數據範本 (前 5 筆):")
            for d in sorted_dates[:5]:
                print(f"   - {d}: {data[d]:,.2f} Millions")
            
            # Print the last 5 records as a sample
            print("\n🔍 數據範本 (後 5 筆):")
            for d in sorted_dates[-5:]:
                print(f"   - {d}: {data[d]:,.2f} Millions")
        else:
            print("\n[✗] 測試失敗：未取得任何數據，請檢查網路連線或 API Key 有效性。")
            
    except Exception as e:
        print(f"\n[✗] 測試執行期間發生錯誤: {e}")
        
    print("\033[93m==================================================\033[0m")
    print("\033[93m✓ FRED API 資料取得物件測試完畢。\033[0m")
    print("\033[93m==================================================\033[0m")
