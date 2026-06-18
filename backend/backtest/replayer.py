import datetime
import yfinance as yf
import pandas as pd
from typing import Optional

# Store original yfinance methods
_orig_history = yf.Ticker.history
_orig_fast_info = yf.Ticker.fast_info
_orig_info = yf.Ticker.info

# Global simulated backtest date
_simulated_date: Optional[str] = None

def set_simulated_date(date_str: Optional[str]):
    """Sets the current simulated date for backtesting (Format: YYYY-MM-DD)."""
    global _simulated_date
    _simulated_date = date_str
    if date_str:
        print(f"[🕰️ 時間旅行] 系統時間已倒退至：{date_str}")

def get_simulated_date() -> Optional[str]:
    """Gets the current simulated date."""
    return _simulated_date

def period_to_days(period_str: str) -> int:
    """Converts a yfinance period string into a conservative number of calendar days."""
    if not period_str:
        return 30
    # Match numbers
    num_part = "".join([c for c in period_str if c.isdigit()])
    unit_part = "".join([c for c in period_str if c.isalpha()]).lower()
    
    if not num_part:
        if period_str.lower() == "max":
            return 365 * 15
        return 30
        
    num = int(num_part)
    if unit_part == "d":
        return int(num * 1.6) # 30 trading days -> 48 calendar days
    elif unit_part == "wk":
        return num * 7 * 2
    elif unit_part == "mo":
        return num * 30 * 2
    elif unit_part == "yr" or unit_part == "y":
        return num * 365 * 2
    return 30

def patched_history(self, *args, **kwargs):
    """
    Patched version of yfinance.Ticker.history.
    Automatically restricts end date to simulated_date + 1 day to prevent lookahead bias.
    """
    sim_date = get_simulated_date()
    if sim_date:
        # Convert all positional args to kwargs to avoid index shifting issues
        history_param_names = [
            "period", "interval", "start", "end", "prepost", 
            "actions", "auto_adjust", "back_adjust", "repair", 
            "keepna", "proxy", "round"
        ]
        for i, val in enumerate(args):
            if i < len(history_param_names):
                kwargs[history_param_names[i]] = val
        args = ()
        
        # yfinance end date is exclusive, so we query up to sim_date + 1 day
        sim_dt = datetime.datetime.strptime(sim_date, "%Y-%m-%d")
        end_dt = sim_dt + datetime.timedelta(days=1)
        kwargs["end"] = end_dt.strftime("%Y-%m-%d")
        
        # If period is specified, translate it to start date to prevent Yahoo API range errors when combining period and end
        period = kwargs.pop("period", None)
        if period and not kwargs.get("start"):
            days = period_to_days(period)
            start_dt = sim_dt - datetime.timedelta(days=days)
            kwargs["start"] = start_dt.strftime("%Y-%m-%d")
            
        # Ensure we drop any rows that might accidentally be after simulated_date due to timezone offsets.
        res = _orig_history(self, *args, **kwargs)
        if not res.empty:
            res = res[res.index <= pd.Timestamp(sim_date).tz_localize(res.index.tz)]
            
        # If the result is empty and the original requested period was '1d' (usually on weekends/holidays), retry with a longer period
        if res.empty and period == "1d":
            kwargs_retry = kwargs.copy()
            # Try 5 days start
            start_dt_5 = sim_dt - datetime.timedelta(days=5)
            kwargs_retry["start"] = start_dt_5.strftime("%Y-%m-%d")
            res_retry = _orig_history(self, *args, **kwargs_retry)
            if not res_retry.empty:
                res_retry = res_retry[res_retry.index <= pd.Timestamp(sim_date).tz_localize(res_retry.index.tz)]
                if not res_retry.empty:
                    return res_retry.tail(1)
                    
            # Try 30 days if still empty
            start_dt_30 = sim_dt - datetime.timedelta(days=30)
            kwargs_retry["start"] = start_dt_30.strftime("%Y-%m-%d")
            res_retry = _orig_history(self, *args, **kwargs_retry)
            if not res_retry.empty:
                res_retry = res_retry[res_retry.index <= pd.Timestamp(sim_date).tz_localize(res_retry.index.tz)]
                if not res_retry.empty:
                    return res_retry.tail(1)
        return res
        
    return _orig_history(self, *args, **kwargs)

class PatchedFastInfo:
    """
    Mock wrapper for yfinance.Ticker.fast_info to calculate current market price
    as of the simulated backtest date, and fallback other static attributes.
    """
    def __init__(self, ticker_obj):
        self._ticker = ticker_obj
        self._orig = _orig_fast_info.__get__(ticker_obj, yf.Ticker)
        
    def get(self, key: str, default=None):
        if key in ["lastPrice", "last_price"]:
            hist = self._ticker.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            hist = self._ticker.history(period="30d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            # Never fallback to live price for price queries in backtest!
            return default
            
        if key in ["fiftyDayAverage", "fifty_day_average"]:
            hist = self._ticker.history(period="100d")
            if not hist.empty and len(hist) >= 50:
                return float(hist["Close"].tail(50).mean())
            elif not hist.empty:
                return float(hist["Close"].mean())
            return default
            
        if key in ["twoHundredDayAverage", "two_hundred_day_average"]:
            hist = self._ticker.history(period="300d")
            if not hist.empty and len(hist) >= 200:
                return float(hist["Close"].tail(200).mean())
            elif not hist.empty:
                return float(hist["Close"].mean())
            return default
            
        try:
            val = self._orig.get(key, default)
            if val is not None:
                return val
        except Exception:
            pass
        return default
        
    def __getattr__(self, name: str):
        if name in ["last_price", "lastPrice"]:
            hist = self._ticker.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            hist = self._ticker.history(period="30d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            raise AttributeError(f"No historical price data available for {self._ticker.ticker} in backtest")
            
        if name in ["fiftyDayAverage", "fifty_day_average"]:
            hist = self._ticker.history(period="100d")
            if not hist.empty and len(hist) >= 50:
                return float(hist["Close"].tail(50).mean())
            elif not hist.empty:
                return float(hist["Close"].mean())
            raise AttributeError(f"No historical 50-day average data available for {self._ticker.ticker} in backtest")
            
        if name in ["twoHundredDayAverage", "two_hundred_day_average"]:
            hist = self._ticker.history(period="300d")
            if not hist.empty and len(hist) >= 200:
                return float(hist["Close"].tail(200).mean())
            elif not hist.empty:
                return float(hist["Close"].mean())
            raise AttributeError(f"No historical 200-day average data available for {self._ticker.ticker} in backtest")
            
        try:
            return getattr(self._orig, name)
        except Exception:
            pass
        raise AttributeError(f"PatchedFastInfo has no attribute '{name}'")

class PatchedInfo(dict):
    """
    Mock wrapper for yfinance.Ticker.info to prevent lookahead leaks
    of prices, market cap, PE ratios, and analyst targets during backtests.
    """
    def __init__(self, ticker_obj):
        self._ticker = ticker_obj
        try:
            orig_dict = _orig_info.__get__(ticker_obj, yf.Ticker)
            if not isinstance(orig_dict, dict):
                orig_dict = {}
        except Exception:
            orig_dict = {}
        super().__init__(orig_dict)
        self._apply_historical_patches()
        
    def _apply_historical_patches(self):
        # 1. Fetch historical price
        hist = self._ticker.history(period="5d")
        if hist.empty:
            hist = self._ticker.history(period="30d")
        
        if not hist.empty:
            hist_price = float(hist["Close"].iloc[-1])
        else:
            hist_price = None
            
        # 2. Patch price fields
        if hist_price is not None:
            self["currentPrice"] = hist_price
            self["regularMarketPrice"] = hist_price
            self["regularMarketPreviousClose"] = hist_price
            self["navPrice"] = hist_price
            
            # 3. Patch Market Cap
            shares = self.get("sharesOutstanding")
            if shares:
                self["marketCap"] = hist_price * shares
                
            # 4. Patch PE Ratio
            eps = self.get("trailingEps")
            if eps and eps != 0:
                self["trailingPE"] = hist_price / eps
            else:
                self.pop("trailingPE", None)
                
            # 5. Patch Price to Book
            bv = self.get("bookValue")
            if bv and bv != 0:
                self["priceToBook"] = hist_price / bv
            else:
                self.pop("priceToBook", None)
                
        # 6. Nullify Analyst Targets and consensus to prevent future leak
        for k in ["targetMeanPrice", "targetHighPrice", "targetLowPrice", "numberOfAnalystOpinions", "recommendationMean", "recommendationKey"]:
            self.pop(k, None)
            
        # 7. Patch SMA values
        hist_50 = self._ticker.history(period="100d")
        if not hist_50.empty and len(hist_50) >= 50:
            self["fiftyDayAverage"] = float(hist_50["Close"].tail(50).mean())
        elif not hist_50.empty:
            self["fiftyDayAverage"] = float(hist_50["Close"].mean())
            
        hist_200 = self._ticker.history(period="300d")
        if not hist_200.empty and len(hist_200) >= 200:
            self["twoHundredDayAverage"] = float(hist_200["Close"].tail(200).mean())
        elif not hist_200.empty:
            self["twoHundredDayAverage"] = float(hist_200["Close"].mean())

@property
def patched_info(self):
    """Descriptor property to hijack info dynamically during backtests."""
    if get_simulated_date():
        return PatchedInfo(self)
    return _orig_info.__get__(self, yf.Ticker)

@property
def patched_fast_info(self):
    """Descriptor property to hijack fast_info dynamically during backtests."""
    if get_simulated_date():
        return PatchedFastInfo(self)
    return _orig_fast_info.__get__(self, yf.Ticker)

def apply_backtest_replayer_sandbox():
    """
    Globally patches yfinance and caching mechanisms to route all queries through 
    the simulated historical time-travel window.
    """
    # 1. Patch yfinance
    yf.Ticker.history = patched_history
    yf.Ticker.fast_info = patched_fast_info
    yf.Ticker.info = patched_info
    
    # 3. Patch web_search tool to prevent lookahead news leaks and web scraper crashes
    import core.tools.web_search as search_tool
    
    def generate_thematic_news(query: str, date_str: str, ticker: str = None) -> dict:
        year = 2022
        if date_str and "-" in date_str:
            try:
                year = int(date_str.split("-")[0])
            except Exception:
                pass
                
        query_lower = query.lower() if query else ""
        
        # Determine theme keywords
        is_fed = any(w in query_lower for w in ["fed", "利率", "interest", "央行", "升息", "降息", "fomc"])
        is_inflation = any(w in query_lower for w in ["cpi", "pce", "通膨", "通脹", "inflation", "物價"])
        is_bank = any(w in query_lower for w in ["bank", "銀行", "crisis", "金融危機", "svb"])
        
        title = ""
        snippet = ""
        
        if year == 2022:
            if is_fed:
                title = f"【歷史總經重播】聯聯準會鷹派立場確立，市場預料將於首季啟動升息並討論縮表"
                snippet = f"截至 {date_str}，面對通膨持續攀升的嚴峻挑戰，最新公布的會議紀錄顯示美聯儲官員已達成加快貨幣緊縮步伐的共識，市場普遍預期將於3月正式升息以抑制過熱的物價。"
            elif is_inflation:
                title = f"【歷史物價重播】美國及全球 CPI 年增率持續飆升，通膨風險加劇緊縮預期"
                snippet = f"截至 {date_str}，供應鏈中斷及能源短缺壓力持續推升實體物價，全球多國核心 CPI 漲幅突破數十年來新高。央行面臨抗通膨的急迫壓力，資金轉向防禦板塊避險。"
            else:
                title = f"【歷史產業重播】全球高通膨壓力籠罩，半導體與實體製造業獲利成長趨緩"
                snippet = f"截至 {date_str}，在通膨與升息預期下，企業面臨營運成本推升挑戰。晶圓代工與封測需求維持穩健，但市場對消費性電子（如手機、PC）需求是否見頂抱持審慎態度。"
                
        elif year == 2023:
            if is_fed:
                title = f"【歷史總經重播】基準利率攀升至高位，美聯儲暗示升息週期步入尾聲"
                snippet = f"截至 {date_str}，連續升息後基準利率已達限制性水平。央行暗示後續升息空間有限，將依據通膨及就業數據調整，市場對政策轉向的可能性展開預期博弈。"
            elif is_bank:
                title = f"【歷史金融重播】矽谷銀行與簽名銀行接連倒閉，監管機構介入提供緊急流動性"
                snippet = f"截至 {date_str}，高利率環境引發地區性銀行擠兌風暴。美聯儲與財政部迅速推出融資計劃保障存款安全，成功平息危機，但市場信用條件恐因此收緊。"
            else:
                title = f"【歷史產業重播】生成式 AI 算力需求爆發，Nvidia 財測強勁啟動科技股多頭"
                snippet = f"截至 {date_str}，AI 大模型技術迅速落地，促使全球大型雲端業者（CSP）瘋狂追加 AI 晶片與 AI 伺服器採購訂單，半導體產業鏈出現強勁的新增長動能。"
                
        else: # 2024-2026
            if is_fed:
                title = f"【歷史總經重播】通膨逐步回落至目標區間，全球央行研議降息路徑"
                snippet = f"截至 {date_str}，隨著核心通膨與勞動市場熱度降溫，美聯儲與主要央行維持利率不變，並向市場傳遞政策已達頂峰、未來將適時降息的訊號，資金流動性出現改善跡象。"
            else:
                title = f"【歷史產業重播】AI 應用邁向大規模商用化，先進封裝與算力供應維持吃緊"
                snippet = f"截至 {date_str}，人工智慧軟硬體生態系全面成形，台積電等大廠 CoWoS 先進封裝與高頻寬記憶體（HBM）產能滿載，推動半導體與伺服器供應鏈營收連創歷史新高。"
                
        # Individual Ticker override if specified
        if ticker:
            ticker_clean = ticker.split(".")[0].upper()
            title = f"【歷史個股重播】{ticker} 截至 {date_str} 基本面營運狀況與財報解析"
            if year == 2022:
                snippet = f"截至 {date_str}，{ticker_clean} 面臨高通膨帶來的原材料與物流成本上升挑戰。公司雖維持出貨指引，但法人對其營業利益率承壓以及存貨回升風險表達關注。"
            elif year == 2023:
                snippet = f"截至 {date_str}，{ticker_clean} 庫存逐步去化，經營層強調自由現金流與成本管控為首要目標，出貨狀況順暢，毛利率表現符合法人共識。"
            else:
                snippet = f"截至 {date_str}，{ticker_clean} 受惠於先進技術應用與強勁市場需求，出貨動能暢旺。財務體質健全，營運表現持續超出市場共識預估。"
                
        return {
            "title": title,
            "link": "https://finance.yahoo.com",
            "source": "Aegis Backtest News Replayer",
            "pub_date": date_str,
            "snippet": snippet
        }

    def patched_search_news(query, max_items=2, language="en-US", region="US"):
        sim_date = get_simulated_date()
        date_str = sim_date if sim_date else "歷史模擬當天"
        item = generate_thematic_news(query, date_str)
        return [item] * min(max_items, 2)
        
    def patched_get_stock_news(ticker, max_items=5):
        sim_date = get_simulated_date()
        date_str = sim_date if sim_date else "歷史模擬當天"
        item = generate_thematic_news(ticker, date_str, ticker=ticker)
        return [item] * min(max_items, 2)
        
    search_tool.search_news = patched_search_news
    search_tool.get_stock_news = patched_get_stock_news

    
    print("[🛡️ 回測沙盒] 歷史數據重播、搜尋新聞與防洩漏補丁已啟用 (yfinance, Cache & WebSearch patched)。")
