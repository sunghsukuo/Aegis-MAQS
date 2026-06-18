import datetime
from typing import Optional, Tuple
import yfinance as yf

def get_upcoming_earnings_date(ticker: str) -> Optional[datetime.date]:
    """
    Fetches the upcoming earnings date for a given ticker using yfinance.
    Returns datetime.date if found, else None.
    """
    import os
    from contextlib import redirect_stderr
    from core.tools.yahoo_finance import is_etf_ticker

    try:
        if is_etf_ticker(ticker):
            return None
            
        t = yf.Ticker(ticker)
        with open(os.devnull, "w") as devnull:
            with redirect_stderr(devnull):
                calendar = t.calendar
        if isinstance(calendar, dict) and "Earnings Date" in calendar:
            dates = calendar["Earnings Date"]
            if isinstance(dates, list) and len(dates) > 0:
                # Return the earliest date that is today or in the future
                today = datetime.date.today()
                future_dates = [d for d in dates if isinstance(d, datetime.date) and d >= today]
                if future_dates:
                    return min(future_dates)
                # If no future date is in the list, default to the first one
                if isinstance(dates[0], datetime.date):
                    return dates[0]
    except Exception as e:
        print(f"[!] Warning: 無法透過 yfinance 獲取 {ticker} 的財報公布日: {e}")
    return None

def get_business_days_diff(d1: datetime.date, d2: datetime.date) -> int:
    """
    Counts the number of business days (Monday to Friday) between d1 and d2.
    If d2 <= d1, returns 0.
    """
    if d2 <= d1:
        return 0
    days = 0
    curr = d1
    while curr < d2:
        curr += datetime.timedelta(days=1)
        if curr.weekday() < 5:
            days += 1
    return days

def is_earnings_block_active(ticker: str, current_date_str: str) -> Tuple[bool, Optional[datetime.date], int]:
    """
    Checks if buying a stock is blocked because of an upcoming earnings announcement
    within 5 trading days.
    
    Returns:
        (is_blocked, upcoming_earnings_date, business_days_diff)
    """
    try:
        current_date = datetime.datetime.strptime(current_date_str, "%Y-%m-%d").date()
    except Exception:
        current_date = datetime.date.today()
        
    earnings_date = get_upcoming_earnings_date(ticker)
    if not earnings_date:
        return False, None, 0
        
    # Check if earnings date has already passed relative to our current check date
    if earnings_date < current_date:
        return False, earnings_date, 0
        
    biz_days = get_business_days_diff(current_date, earnings_date)
    # Block if earnings date is today or within 5 trading days
    is_blocked = (biz_days <= 5)
    
    return is_blocked, earnings_date, biz_days
