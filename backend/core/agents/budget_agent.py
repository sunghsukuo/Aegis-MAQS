import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.db_manager import db_session, execute_sql, DB_TYPE

class BudgetAgent:
    """
    預算管理代理人 (Budget Management Agent)
    - 負責在資料庫中管理總資金 (可投資資金及保留現金)。
    - 動態計算個股推薦時的資金分配比例與股數。
    - 管理交易紀錄 (Transaction History) 與雙向簿記 (Double-Entry Bookkeeping) 資金流轉。
    """
    
    def __init__(self, allocation_ratio: float = 0.10):
        """
        初始化預算管理代理人。
        :param allocation_ratio: 預設單次交易佔可用資金的比例 (10%)，用於風險控管與部位控制。
        """
        self.allocation_ratio = allocation_ratio

    def get_currency_by_region(self, region: str) -> str:
        """根據市場區域回傳對應的貨幣單位。"""
        return "USD" if region.upper() == "US" else "TWD"

    def get_capital_state(self, currency: str) -> dict:
        """
        獲取特定貨幣的資金狀態。
        """
        currency = currency.upper()
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor,
                "SELECT * FROM capital_ledger WHERE currency = ?",
                "SELECT * FROM capital_ledger WHERE currency = %s",
                (currency,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return {"currency": currency, "available_capital": 0.0, "reserved_cash": 0.0}

    def allocate_budget(self, ticker: str, region: str, recommend_price: float, custom_weight: float = None) -> tuple:
        """
        根據當前可用資金與分配比例，為單一推薦個股分配可投資總額與計算股數。
        優先採用 AI 代理人建議的權重，若無則採用預設比例。
        :return: (invested_amount, shares) - 分配金額與購買股數
        """
        currency = self.get_currency_by_region(region)
        state = self.get_capital_state(currency)
        available = state["available_capital"]
        
        # Check if the risk circuit breaker is active for this currency (Circuit Breaker block)
        from core.db_manager import get_risk_circuit_breaker
        if get_risk_circuit_breaker(currency):
            print(f"[🛑 熔斷機制] 偵測到 {currency} 帳戶已啟動風控熔斷！全面凍結新標的 {ticker} 的買入預算配發。")
            return 0.0, 0.0
            
        # 安全下限閥值：若可用資金過低，則不予分配新交易
        min_threshold = 100.0 if currency == "USD" else 3000.0
        if available < min_threshold:
            print(f"[!] 預算代理人提示：{currency} 可用資金過低 ({available:.2f})，無法為 {ticker} 分配新預算。")
            return 0.0, 0.0
            
        # 決定分配權重 (優先採用 AI 建議權重，限制最大權重為 40% 以進行風險防護)
        ratio = custom_weight if custom_weight is not None and custom_weight > 0.0 else self.allocation_ratio
        ratio = min(ratio, 0.40)
        
        # 計算分配金額 (可用資金 * 權重)
        target_budget = available * ratio
        
        # 計算買入股數 (無條件捨去至整數股)
        import math
        shares = math.floor(target_budget / recommend_price)
        
        # 確保最低 1 股防線 (只要剩餘可用資金足夠買 1 股即可)
        if shares < 1:
            if available >= recommend_price:
                shares = 1
                print(f"[!] 預算代理人提示：為符合最低買入 1 股限制，將 {ticker} 股數調整為 1 股。")
            else:
                print(f"[!] 預算代理人提示：{currency} 可用資金 ({available:.2f}) 不足購買 {ticker} 的 1 股 (現價 {recommend_price:.2f})，不予分配。")
                return 0.0, 0.0
                
        # 實際投入金額 = 股數 * 單價 (整數股買入後，金額會有精確小數點)
        invested_amount = shares * recommend_price
        
        # 扣減 capital_ledger 中的可用資金
        new_available = available - invested_amount
        
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor,
                # SQLite
                "UPDATE capital_ledger SET available_capital = ? WHERE currency = ?",
                # MySQL
                "UPDATE capital_ledger SET available_capital = %s WHERE currency = %s",
                (new_available, currency)
            )
            
        print(f"[✓] 預算代理人：已為 {ticker} 動態分配預算 {invested_amount:.2f} {currency} (購買整數股：{shares} 股，現價：{recommend_price:.2f})。")
        return invested_amount, float(shares)

    def record_purchase(self, rec_id: int, ticker: str, region: str, price: float, amount: float, shares: float):
        """
        記錄一筆買入交易至歷史明細，扣減資金已在 allocate_budget 中執行。
        """
        if amount <= 0.0 or shares <= 0.0:
            return
            
        currency = self.get_currency_by_region(region)
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor,
                # SQLite
                """
                INSERT INTO transaction_history (rec_id, action, ticker, currency, shares, price, amount, roi, pnl)
                VALUES (?, 'BUY', ?, ?, ?, ?, ?, 0.0, 0.0)
                """,
                # MySQL
                """
                INSERT INTO transaction_history (rec_id, action, ticker, currency, shares, price, amount, roi, pnl)
                VALUES (%s, 'BUY', %s, %s, %s, %s, %s, 0.0, 0.0)
                """,
                (rec_id, ticker.upper(), currency, shares, price, amount)
            )
        print(f"[✓] 預算代理人：已成功將 {ticker} 的買入交易紀錄寫入流水帳本。")

    def record_sale(self, rec_id: int, ticker: str, region: str, close_price: float, close_date: str, roi: float):
        """
        記錄一筆平倉交易，計算實現損益 (PnL)，並將收回資金與獲利全數歸還至可用資金。
        """
        currency = self.get_currency_by_region(region)
        
        # 1. 查詢該筆 recommendations 以取得當初投入的本金與股數
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor,
                "SELECT invested_amount, shares FROM recommendations WHERE id = ?",
                "SELECT invested_amount, shares FROM recommendations WHERE id = %s",
                (rec_id,)
            )
            rec = cursor.fetchone()
            
        if not rec or rec["invested_amount"] <= 0.0:
            print(f"[!] 預算代理人警告：找不到 ID 為 {rec_id} 的原始投資紀錄，跳過資金回籠。")
            return
            
        invested_amount = rec["invested_amount"]
        shares = rec["shares"]
        
        # 2. 計算回籠總金額與實現損益 (PnL)
        close_value = invested_amount * (1 + roi)
        pnl = close_value - invested_amount
        
        # 3. 更新可用資金 (回籠本金 + 實現盈虧)
        state = self.get_capital_state(currency)
        new_available = state["available_capital"] + close_value
        
        action = "SELL_PROFIT_TARGET" if roi >= 0 else "SELL_STOP_LOSS"
        
        with db_session() as conn:
            cursor = conn.cursor()
            # A. 歸還資金
            execute_sql(cursor,
                "UPDATE capital_ledger SET available_capital = ? WHERE currency = ?",
                "UPDATE capital_ledger SET available_capital = %s WHERE currency = %s",
                (new_available, currency)
            )
            # B. 寫入平倉交易流水帳
            execute_sql(cursor,
                # SQLite
                """
                INSERT INTO transaction_history (rec_id, action, ticker, currency, shares, price, amount, roi, pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                # MySQL
                """
                INSERT INTO transaction_history (rec_id, action, ticker, currency, shares, price, amount, roi, pnl)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (rec_id, action, ticker.upper(), currency, shares, close_price, close_value, roi, pnl)
            )
            # C. 更新原 recommendations 表中的平倉數據與 PnL 欄位
            execute_sql(cursor,
                # SQLite
                """
                UPDATE recommendations
                SET is_active = 0,
                    close_price = ?,
                    close_date = ?,
                    performance = ?,
                    pnl = ?
                WHERE id = ?
                """,
                # MySQL
                """
                UPDATE recommendations
                SET is_active = 0,
                    close_price = %s,
                    close_date = %s,
                    performance = %s,
                    pnl = %s
                WHERE id = %s
                """,
                (close_price, close_date, roi, pnl, rec_id)
            )
            
        print(f"[✓] 預算代理人：交易已平倉歸檔！本金與損益成功回籠 {close_value:.2f} {currency} (實現 P&L: {pnl:+.2f} {currency})。")
