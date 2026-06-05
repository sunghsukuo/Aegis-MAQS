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
