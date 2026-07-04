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

    def get_ticker_sector(self, ticker: str, region: str) -> str:
        """
        Returns the sector code (e.g. XLK, XLF) of a given ticker.
        """
        try:
            import core.db_manager as db
            sectors = db.get_active_sectors(region)
            if ticker.upper() in sectors:
                return ticker.upper()
            for sec_code, sec_info in sectors.items():
                if ticker in sec_info.get("constituents", []):
                    return sec_code
        except Exception:
            pass
        return "UNKNOWN"

    def allocate_budget(self, ticker: str, region: str, recommend_price: float, custom_weight: float = None, report_date: str = None) -> tuple:
        """
        根據當前可用資金與分配比例，為單一推薦個股分配可投資總額與計算股數。
        優先採用 AI 代理人建議的權重，若無則採用預設比例。
        :return: (invested_amount, shares) - 分配金額與購買股數
        """
        currency = self.get_currency_by_region(region)
        state = self.get_capital_state(currency)
        available = state["available_capital"]
        original_available = available
        
        # Check if the risk circuit breaker is active for this currency (Circuit Breaker block)
        from core.db_manager import get_risk_circuit_breaker
        if get_risk_circuit_breaker(currency):
            print(f"[🛑 熔斷機制] 偵測到 {currency} 帳戶已啟動風控熔斷！全面凍結新標的 {ticker} 的買入預算配發。")
            return 0.0, 0.0
            
        # Check if the ticker is an ETF itself (skip earnings blocker for ETFs)
        is_etf = False
        try:
            from core.tools.yahoo_finance import is_etf_ticker
            is_etf = is_etf_ticker(ticker)
        except Exception:
            pass

        if not is_etf:
            # Check if the earnings announcement blocker is active (Earnings announcement block)
            from core.risk.earnings_blocker import is_earnings_block_active
            check_date = report_date or datetime.now().strftime("%Y-%m-%d")
            is_blocked, next_earnings_date, biz_days = is_earnings_block_active(ticker, check_date)
            if is_blocked:
                print(f"[🛡️ Wind 風控] 偵測到 {ticker} 即將於 {next_earnings_date} 公布財報 (距離檢測日 {check_date} 僅 {biz_days} 個交易日)。")
                print(f"            已啟動財報前交易禁令，凍結該標的新增買入預算。")
                return 0.0, 0.0
            
        # 安全下限閥值：若可用資金過低，則不予分配新交易
        min_threshold = 100.0 if currency == "USD" else 3000.0
        if available < min_threshold:
            print(f"[!] 預算代理人提示：{currency} 可用資金過低 ({available:.2f})，無法為 {ticker} 分配新預算。")
            return 0.0, 0.0

        # --- 🕵️‍♂️ 流動性偵察與防禦機制 (Liquidity Scout Integration) ---
        is_backtest_mode = False
        query_date = report_date or datetime.now().strftime("%Y-%m-%d")
        try:
            from backtest.replayer import get_simulated_date
            sim_date = get_simulated_date()
            if sim_date:
                is_backtest_mode = True
                query_date = sim_date
        except Exception:
            pass
            
        cls_score = 0.5
        try:
            from core.tools.liquidity_loader import get_liquidity_state
            liq_state = get_liquidity_state(query_date, is_backtest=is_backtest_mode)
            cls_score = liq_state.get("composite_score", 0.5)
        except Exception as liq_ex:
            print(f"[!] 預算代理人警告：無法獲取流動性狀態，預設中性。錯誤: {liq_ex}")
            
        # 套用流動性緊縮防禦 (CLS >= 0.70 視為緊縮)
        is_liquidity_stressed = cls_score >= 0.70
        if is_liquidity_stressed:
            # 1. 鎖定 15% 資金作為流動性安全緩衝金 (Liquidity Buffer)
            total_pocket = available + state.get("reserved_cash", 0.0)
            liq_buffer = total_pocket * 0.15
            available = max(0.0, available - liq_buffer)
            print(f"[🛡️ 流動性防禦] 偵測到市場流動性緊縮 (CLS: {cls_score:.2f})！")
            print(f"            暫時鎖定 {liq_buffer:.2f} {currency} 安全緩衝金。可用計算資金調降至 {available:.2f}。")

        # 決定分配權重 (優先採用 AI 建議權重)
        ratio = custom_weight if custom_weight is not None and custom_weight > 0.0 else self.allocation_ratio
        
        # 獲取第二層 Meso Regime 與自適應板塊權重限制
        from core.regime.multi_factor import detect_meso_regime
        try:
            meso_info = detect_meso_regime(region_code=region)
            meso_regime = meso_info.get("regime", "BULL_GROWTH_ON")
        except Exception:
            meso_regime = "BULL_GROWTH_ON"
            
        # 決定此標的板塊的最大配置比率
        sector_code = self.get_ticker_sector(ticker, region)
        
        # 美股板塊定義 (作為降級備用)
        is_tech_us = sector_code in ["XLK", "XLC"]
        is_defensive_us = sector_code in ["XLP", "XLU", "XLV"]
        
        # 台股板塊定義 (作為降級備用，對應 0050.TW 技術成分股與防守股)
        tech_tw_tickers = {"2330.TW", "2454.TW", "2317.TW", "2308.TW", "2357.TW", "2382.TW", "3231.TW", "3711.TW"}
        defensive_tw_tickers = {"1216.TW", "2412.TW", "2912.TW"}
        is_tech_tw = ticker in tech_tw_tickers
        is_defensive_tw = ticker in defensive_tw_tickers
        
        is_tech = is_tech_us or is_tech_tw
        is_defensive = is_defensive_us or is_defensive_tw
        
        # 動態獲取板塊週績效排名
        sector_tier = "medium"
        ranking_success = False
        try:
            from core.tools.yahoo_finance import get_sector_rankings
            rankings = get_sector_rankings(region)
            if rankings:
                ranked_sectors = [item["ticker"].upper() for item in rankings if "ticker" in item]
                if sector_code.upper() in ranked_sectors:
                    idx = ranked_sectors.index(sector_code.upper())
                    num_sectors = len(ranked_sectors)
                    
                    if idx < 3: # 前 3 名強勢
                        sector_tier = "top"
                    elif idx >= max(3, num_sectors - 3): # 後 3 名弱勢
                        sector_tier = "bottom"
                    else:
                        sector_tier = "medium"
                    ranking_success = True
                    print(f"[*] 預算代理人：{ticker} 所屬板塊 {sector_code} 週績效排名第 {idx + 1}/{num_sectors} (歸類為 {sector_tier.upper()} 級)。")
        except Exception as e:
            print(f"[!] 預算代理人提示：動態獲取板塊排行失敗，將降級套用靜態板塊限制。錯誤: {e}")
            
        # 三層自適應決策漏斗 —— 預算限制矩陣
        max_ratio = 0.40  # 預設上限
        
        if ranking_success:
            # A. 動態板塊評級預算限制
            if meso_regime in ["BULL_GROWTH_ON", "BULL_VALUE_ON"]:
                if sector_tier == "top":
                    max_ratio = 0.40
                elif sector_tier == "medium":
                    max_ratio = 0.25
                else: # bottom
                    max_ratio = 0.10
            elif meso_regime == "VOLATILE_PANIC":
                if sector_tier == "top":
                    max_ratio = 0.25
                elif sector_tier == "medium":
                    max_ratio = 0.15
                else: # bottom
                    max_ratio = 0.05
            elif meso_regime == "BEAR_RISK_OFF":
                if sector_tier == "top":
                    max_ratio = 0.20
                elif sector_tier == "medium":
                    max_ratio = 0.10
                else: # bottom
                    max_ratio = 0.00  # 凍結買入
            else:
                if sector_tier == "top":
                    max_ratio = 0.35
                elif sector_tier == "medium":
                    max_ratio = 0.20
                else: # bottom
                    max_ratio = 0.10
        else:
            # B. 降級 Fallback: 原始靜態板塊限制
            if meso_regime == "BULL_GROWTH_ON":
                # 科技多頭：科技股上限為 40%，非科技股上限縮至 20%
                max_ratio = 0.40 if is_tech else 0.20
            elif meso_regime == "BULL_VALUE_ON":
                # 傳統多頭：傳統股/價值股上限為 40%，科技股上限縮至 20%
                max_ratio = 0.20 if is_tech else 0.40
            elif meso_regime == "VOLATILE_PANIC":
                # 高波震盪：全域上限降低至 20% 防禦
                max_ratio = 0.20
            elif meso_regime == "BEAR_RISK_OFF":
                # 系統性空頭：防禦性板塊上限為 30%，進攻性板塊上限為 10%
                max_ratio = 0.30 if is_defensive else 0.10
            
        ratio = min(ratio, max_ratio)
        
        # 如果處於流動性緊縮狀態，強制將單檔持倉權重上限砍半，最高不超過 12%
        if is_liquidity_stressed:
            ratio = min(ratio, 0.12)
            print(f"            [🛡️ 流動性防禦] 已強制將 {ticker} 的最大配置權重下修至 12% 以分散風險。")
        
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
        new_available = original_available - invested_amount
        
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
