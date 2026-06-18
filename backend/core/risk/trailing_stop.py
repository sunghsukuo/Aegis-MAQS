import math
import yfinance as yf
import core.db_manager as db

def check_and_apply_breakeven_stop(rec: dict, current_price: float, atr_14: float) -> bool:
    """
    Checks if an active recommendation has reached the profit milestone (e.g., recommend_price + 1.0 * ATR).
    If it has, updates the stop_loss price to the recommend_price (breakeven point) in the database
    to lock in a 0% risk profile and protect against mean reversion.
    
    Returns:
        bool: True if the stop_loss was updated, False otherwise.
    """
    if not rec or not current_price or not atr_14:
        return False
        
    rec_price = rec.get("recommend_price", 0.0)
    current_stop = rec.get("stop_loss", 0.0)
    
    if rec_price <= 0.0:
        return False
        
    # Check if price has touched/exceeded the breakeven milestone: recommend_price + 1.0 * ATR
    milestone = rec_price + (1.0 * atr_14)
    
    # If the current price is above the milestone, and our stop loss is still below the entry price (breakeven)
    if current_price >= milestone and current_stop < rec_price:
        rec_id = rec.get("id")
        if not rec_id:
            return False
            
        print(f"[🛡️ Wind 風控] {rec['ticker']} 已觸發保本里程碑 (現價 {current_price:.2f} >= 買入價 {rec_price:.2f} + 1.0*ATR {atr_14:.2f})。")
        print(f"            將停損點從 {current_stop:.2f} 上移至保本價 {rec_price:.2f} 元。")
        
        # Update stop_loss in the database
        try:
            with db.db_session() as conn:
                cursor = conn.cursor()
                db.execute_sql(cursor,
                    "UPDATE recommendations SET stop_loss = ? WHERE id = ?",
                    "UPDATE recommendations SET stop_loss = %s WHERE id = %s",
                    (rec_price, rec_id)
                )
                conn.commit()
            return True
        except Exception as e:
            print(f"[!] Warning: 無法在資料庫中更新 {rec['ticker']} 的保本停損點: {e}")
            
    return False


def check_and_apply_chandelier_stop(rec: dict, current_price: float, atr_14: float, beta: float, macro_regime: str = None) -> bool:
    """
    Calculates the Chandelier Trailing Stop: Trailing Stop = Peak Price - (k * ATR).
    Uses yfinance to dynamically query historical prices of the active target since its
    recommendation date (to determine peak price) without schema changes.
    Only updates the stop_loss price in the database if the new trailing stop price is 
    higher than the current stop_loss.
    
    Returns:
        bool: True if the stop_loss was updated, False otherwise.
    """
    if not rec or not current_price or not atr_14:
        return False
        
    ticker = rec.get("ticker")
    report_date = rec.get("report_date") # Format: YYYY-MM-DD
    rec_id = rec.get("id")
    current_stop = rec.get("stop_loss", 0.0)
    
    if not ticker or not report_date or not rec_id:
        return False

    try:
        # 1. Fetch history since recommendation date to get the peak price
        t = yf.Ticker(ticker)
        hist = t.history(start=report_date).dropna(subset=["High"])
        if hist.empty:
            return False
            
        peak_price = float(hist["High"].max())
    except Exception as e:
        print(f"[!] Warning: 無法透過 yfinance 獲取 {ticker} 的歷史最高價: {e}")
        return False

    # 2. Determine volatility multiplier k using regime-aware logic (matching risk_manager.py)
    beta_bounded = max(0.3, min(beta or 1.0, 3.0))
    beta_adj = math.sqrt(beta_bounded)
    regime = (macro_regime or "VOLATILE_RANGEBOUND").upper()
    
    if "BEAR" in regime or "RISK_OFF" in regime:
        # Tight trailing stop in bear market to lock in quick gains
        k = 1.2 * beta_adj
    elif "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
        k = 1.5 * beta_adj
    else:
        # Standard alpha seeking multiplier in bull/trending market
        k = 2.0 * beta_adj
        
    # 3. Calculate Chandelier Trailing Stop
    chandelier_stop = peak_price - (k * atr_14)
    
    # 4. Only move the stop up, never down!
    if chandelier_stop > current_stop:
        # Check that we do not set stop loss above current price (which would trigger immediate sale)
        if chandelier_stop >= current_price:
            # Cap it slightly below current price (e.g. 1% below current_price) to prevent instant trigger
            chandelier_stop = current_price * 0.99
            
        if chandelier_stop > current_stop:
            print(f"[🛡️ Wind 風控] {ticker} 觸發吊燈移動停損上移 (最高價: {peak_price:.2f} | 乘數: {k:.2f}x | ATR: {atr_14:.2f})。")
            print(f"            將停損點從 {current_stop:.2f} 上移至 {chandelier_stop:.2f} 元。")
            
            # Update stop_loss in the database
            try:
                with db.db_session() as conn:
                    cursor = conn.cursor()
                    db.execute_sql(cursor,
                        "UPDATE recommendations SET stop_loss = ? WHERE id = ?",
                        "UPDATE recommendations SET stop_loss = %s WHERE id = %s",
                        (chandelier_stop, rec_id)
                    )
                    conn.commit()
                rec["stop_loss"] = chandelier_stop
                return True
            except Exception as db_err:
                print(f"[!] Warning: 無法在資料庫中更新 {ticker} 的吊燈移動停損點: {db_err}")
                
    return False
