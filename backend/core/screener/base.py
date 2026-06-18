import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from core.config import DATA_DIR, REGIONS

# Dynamically construct the constituents cache from config.py to ensure a Single Source of Truth
ETF_CONSTITUENTS_CACHE = {}
for region_code, region_info in REGIONS.items():
    for etf, etf_info in region_info.get("sector_etfs", {}).items():
        if isinstance(etf_info, dict) and "constituents" in etf_info:
            ETF_CONSTITUENTS_CACHE[etf] = etf_info["constituents"]

class BaseScreener:
    session_history = []
    
    def __init__(self):
        pass

    def clear_history(self):
        self.session_history.clear()

    def fetch_etf_constituents(self, etf_ticker: str) -> list:
        """
        Fetches constituents of the given ETF/sector code.
        Prioritizes local database definition and local cache configurations as the primary source of truth.
        Only falls back to scraping Yahoo Finance if no local definition exists (e.g. for new ETFs).
        """
        etf_ticker = etf_ticker.strip().upper()
        
        # 1. First Source of Truth: Database
        try:
            import core.db_manager as db
            with db.db_session() as conn:
                cursor = conn.cursor()
                db.execute_sql(cursor,
                    "SELECT id FROM sector_registry WHERE sector_code = ? AND is_active = 1",
                    "SELECT id FROM sector_registry WHERE sector_code = %s AND is_active = 1",
                    (etf_ticker,)
                )
                row = cursor.fetchone()
                if row:
                    sector_id = row["id"] if isinstance(row, dict) else (row[0] if isinstance(row, tuple) else row)
                    db.execute_sql(cursor,
                        "SELECT ticker FROM sector_constituents WHERE sector_id = ?",
                        "SELECT ticker FROM sector_constituents WHERE sector_id = %s",
                        (sector_id,)
                    )
                    rows = cursor.fetchall()
                    if rows:
                        db_constituents = [r["ticker"] if isinstance(r, dict) else (r[0] if isinstance(r, tuple) else r) for r in rows]
                        print(f"\033[96m[*]\033[0m [Screener] 從資料庫載入 {etf_ticker} 成分股清單 (共 {len(db_constituents)} 檔標的)。")
                        return db_constituents
        except Exception as db_ex:
            print(f"\033[93m[!]\033[0m [Screener] 從資料庫載入 {etf_ticker} 成分股失敗 ({db_ex})。")

        # 2. Second Source of Truth: Local cache (pre-seeded from sectors_config.json)
        cache_list = ETF_CONSTITUENTS_CACHE.get(etf_ticker)
        if cache_list is not None:
            print(f"\033[96m[*]\033[0m [Screener] 載入 {etf_ticker} 成分股快取清單 (共 {len(cache_list)} 檔標的)。")
            return cache_list
            
        # 3. Handle sector proxy mapping fallback
        resolved_key = None
        custom_proxy_keys = ["2881.TW", "1301.TW"]
        for key in custom_proxy_keys:
            if key in ETF_CONSTITUENTS_CACHE and etf_ticker in ETF_CONSTITUENTS_CACHE[key]:
                resolved_key = key
                break
        if not resolved_key:
            for key, val_list in ETF_CONSTITUENTS_CACHE.items():
                if etf_ticker in val_list:
                    resolved_key = key
                    break
        if resolved_key:
            cache_list = ETF_CONSTITUENTS_CACHE[resolved_key]
            print(f"\033[96m[*]\033[0m [Screener] 偵測到 {etf_ticker} 為板塊代理人，自動映射至 {resolved_key} 的成分股清單。")
            return cache_list

        # 4. Third Source of Truth (Fallback): Scrape Yahoo Finance for undefined/new ETFs
        is_taiwan = (etf_ticker.endswith(".TW") or etf_ticker.endswith(".TWO"))
        is_real_etf = True
        if is_taiwan and not etf_ticker.startswith("00"):
            is_real_etf = False
            
        if is_real_etf:
            print(f"\033[96m[*]\033[0m [Screener] 本地無 {etf_ticker} 定義，嘗試從 Yahoo Finance 動態爬取成分股...")
            try:
                url = f"https://finance.yahoo.com/quote/{etf_ticker}/holdings/"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    tickers = []
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if "/quote/" in href:
                            parts = href.split("/quote/")
                            if len(parts) > 1:
                                sym = parts[1].split("?")[0].split("/")[0].strip().upper()
                                
                                # Validate region to prevent cross-region bleeding
                                if is_taiwan:
                                    if not (sym.endswith(".TW") or sym.endswith(".TWO")):
                                        continue
                                else:
                                    if sym.endswith(".TW") or sym.endswith(".TWO"):
                                        continue
                                        
                                if sym and sym != etf_ticker and all(c.isalnum() or c in ".-" for c in sym) and len(sym) <= 10:
                                    if sym not in tickers:
                                        tickers.append(sym)
                    if len(tickers) >= 5:
                        print(f"\033[96m[*]\033[0m [Screener] 動態成功抓取 {etf_ticker} 的 {len(tickers)} 檔成分股代號。")
                        return tickers
            except Exception as e:
                print(f"\033[93m[!]\033[0m [Screener] 動態抓取 {etf_ticker} 成分股失敗 ({e})。")
                
        # 5. Last resort fallback
        print(f"\033[93m[!]\033[0m [Screener] 無法為 {etf_ticker} 載入任何成分股。將其視為單一個股。")
        return [etf_ticker]

    def _get_projected_volume(self, hist: pd.DataFrame, region: str) -> float:
        """Projects intraday volume to full-day volume if the market is open."""
        try:
            from datetime import datetime, time
            import pytz
            
            last_row = hist.iloc[-1]
            last_volume = float(last_row["Volume"])
            last_date = hist.index[-1]
            
            if region == "US":
                tz = pytz.timezone("America/New_York")
                market_open_time = time(9, 30)
                market_close_time = time(16, 0)
                total_minutes = 390.0
            else:  # Taiwan
                tz = pytz.timezone("Asia/Taipei")
                market_open_time = time(9, 0)
                market_close_time = time(13, 30)
                total_minutes = 270.0
                
            now = datetime.now(tz)
            if last_date.strftime("%Y-%m-%d") == now.strftime("%Y-%m-%d"):
                market_open = tz.localize(datetime.combine(now.date(), market_open_time))
                market_close = tz.localize(datetime.combine(now.date(), market_close_time))
                
                if now < market_open:
                    if len(hist) >= 2:
                        return float(hist["Volume"].iloc[-2])
                    return last_volume
                elif now >= market_close:
                    return last_volume
                else:
                    elapsed = (now - market_open).total_seconds() / 60.0
                    if elapsed < 15.0:
                        if len(hist) >= 2:
                            return float(hist["Volume"].iloc[-2])
                        return last_volume
                    projected = last_volume * (total_minutes / elapsed)
                    return float(projected)
        except Exception as e:
            print(f"\033[93m[!]\033[0m [Screener] Volume projection error: {e}")
        return float(hist["Volume"].iloc[-1])

    def record_proxy_etf(self, etf_ticker: str, region: str, financials: dict = None, weekly_return: float = 0.0):
        """Records a proxy ETF selection into session history."""
        etf_ticker = etf_ticker.strip().upper()
        name = etf_ticker
        try:
            import core.db_manager as db
            active_sec = db.get_active_sectors(region).get(etf_ticker)
            if active_sec:
                name = active_sec["name"]
            else:
                name = yf.Ticker(etf_ticker).info.get("longName", etf_ticker)
        except Exception:
            try:
                name = yf.Ticker(etf_ticker).info.get("longName", etf_ticker)
            except Exception:
                pass
        self.session_history.append({
            "etf": etf_ticker,
            "name": name,
            "region": region,
            "is_proxy": True,
            "picks": [],
            "financials": financials,
            "weekly_return": weekly_return
        })
        print(f"\033[93m[✓]\033[0m [Screener] 已成功將 ETF 代理標的 {etf_ticker} 寫入選股報告記錄。")

    def screen_stocks(self, etf_ticker: str, region: str, limit: int = 5, macro_regime: str = None) -> list:
        """Abstract method to be implemented by subclass strategies."""
        raise NotImplementedError("Subclasses must implement screen_stocks")

    def generate_report(self, report_date: str, sector_rankings: list = None) -> tuple:
        """Generates a beautiful Markdown and HTML report from the session history."""
            
        # De-duplicate session history records by ETF and strategy name to prevent duplicate sections
        unique_history = []
        seen = set()
        for item in self.session_history:
            key = (item.get("etf"), item.get("strategy"), item.get("is_proxy"), item.get("region"))
            if key not in seen:
                seen.add(key)
                unique_history.append(item)
        self.session_history[:] = unique_history
        
        from core.config import REPORT_LANGUAGE
        import markdown
        is_zh = (REPORT_LANGUAGE == "ZH")
        
        if is_zh:
            title = f"# 量化動態選股掃描決策報告 ({report_date})"
            note_content = "本報告由「量化動態掃描選股引擎」自動生成。系統分析了當週資金流入最強的行業 ETF / 板塊代理人，依據量化策略模型進行綜合評分篩選，排除流動性不足與空頭排列個股，精選出具備主力大單進駐與爆發潛力的個股。"
            rank_title = "產業板塊動能與熱點排行榜"
            sec_title = "各板塊強勢個股動態篩選明細"
        else:
            title = f"# Quantamental Dynamic Stock Selection Report ({report_date})"
            note_content = "This report is automatically generated by the Quantamental Dynamic Stock Scanner Engine. The system analyzes the constituents of the strongest performing sector ETFs / proxies of the week, screening them using a combined quantitative score based on selected market strategy, filtering out low-liquidity assets."
            rank_title = "Sector Momentum and Heat Rankings"
            sec_title = "Selected Sector Strong Stock Screening Details"
            
        lines = [title, "\n---", f"\n> [!NOTE]\n> {note_content}\n", "\n---"]
        
        # Add Sector Rankings if provided
        if sector_rankings:
            lines.append(f"\n## {rank_title}")
            if is_zh:
                lines.append("| 排名 | 板塊代碼 | 板塊名稱 | 本週回報率 | 當前價格 |")
                lines.append("| :---: | :--- | :--- | :---: | :---: |")
            else:
                lines.append("| Rank | Sector Ticker | Sector Name | Weekly Return | Price |")
                lines.append("| :---: | :--- | :--- | :---: | :---: |")
                
            for idx, r in enumerate(sector_rankings, 1):
                ticker = r.get("ticker", "N/A")
                label = r.get("label", r.get("name", ticker))
                ret = r.get("weekly_return", 0.0) * 100
                price = r.get("current_price", 0.0)
                price_symbol = "$" if (".TW" not in ticker and ".TWO" not in ticker) else "NT$"
                lines.append(f"| {idx} | `{ticker}` | {label} | {ret:+.2f}% | {price_symbol}{price:.2f} |")
                
            if is_zh:
                explanation = (
                    "\n> [!TIP]\n"
                    "> **選股引導演算法與板塊遞補說明**：\n"
                    "> 系統會優先從上方「產業板塊動能排行榜」最前方的強勢板塊開始篩選成分股。若排名靠前的強勢板塊中所有成分股皆未通過量化篩選門檻（例如技術指標過熱、流動性不足或處於空頭趨勢），系統將自動向下遞補篩選次要（排名較後）的強勢板塊，直至滿足個股推薦額度為止。這能確保投資組合在維持動能的同時，兼顧安全邊際與交易可行性，這也是為何某些強勢板塊在下方無推薦標的、而系統轉而選擇次要板塊的原因。\n"
                )
            else:
                explanation = (
                    "\n> [!TIP]\n"
                    "> **Screener Logic & Sector Fallback Explanation**:\n"
                    "> The system prioritizes screening constituents from the top-ranked sectors. If all constituents in a top-ranked sector fail the quantitative filters (e.g. overbought, lack of liquidity, or downtrend), the system automatically falls back to screen the next sector in the ranking until the stock recommendation quota is filled. This explains why some top-ranked sectors have no recommendations below and the system falls back to secondary sectors, ensuring we prioritize momentum while maintaining safety and execution feasibility.\n"
                )
            lines.append(explanation)
            lines.append("\n---")
            
        lines.append(f"\n## {sec_title}\n")
        
        if not self.session_history:
            if is_zh:
                lines.append("> [!WARNING]\n> **本週所有行業板塊成分股均未通過量化篩選門檻，或無防禦性持股（如避險/代理等）配置。**\n")
            else:
                lines.append("> [!WARNING]\n> **No industry sector constituents passed the quantitative screening filters, and no defensive/proxy asset allocations were triggered this week.**\n")
            
        for item in self.session_history:
            etf = item["etf"]
            etf_name = item.get("name", etf)
            region = item["region"]
            picks = item["picks"]
            is_proxy = item.get("is_proxy", False)
            weekly_return = item.get("weekly_return", 0.0) * 100
            
            from core.tools.yahoo_finance import is_etf_ticker
            is_etf = is_etf_ticker(etf)
            
            region_lbl = "美股" if region == "US" else "台股"
            if not is_zh:
                region_lbl = "US Market" if region == "US" else "Taiwan Market"
                
            if not picks and not is_proxy:
                strategy = item.get("strategy", "reversion")
                stats = item.get("stats", {})
                total = stats.get("total", 0)
                
                if is_zh:
                    if is_etf:
                        lines.append(f"\n### 焦點行業板塊 ETF：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}%\n")
                    else:
                        lines.append(f"\n### 焦點行業板塊代理股：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}%\n")
                    if strategy == "reversion":
                        lines.append(
                            f"> [!WARNING]\n"
                            f"> **本板塊在此期選股中被排除**，原因在於所採用的「均值回歸 (Reversion) 拉回策略」過濾了所有成分股：\n"
                            f"> \n"
                            f"> - 成分股總數：{total} 檔\n"
                            f"> - 未達流動性或市值門檻被過濾：{stats.get('failed_liquidity', 0)} 檔\n"
                            f"> - 處於長期空頭走勢 (低於 200MA) 被過濾：{stats.get('failed_downtrend', 0)} 檔\n"
                            f"> - 價格過度延伸 (未處於 50MA 附近支撐區) 被過濾：{stats.get('failed_overextended', 0)} 檔\n"
                            f"> - 短期技術指標過熱 (RSI-14 > 55) 被過濾：{stats.get('failed_overbought', 0)} 檔\n"
                            f"> \n"
                            f"> *解讀：該板塊目前短線已過熱或處於長期空頭趨勢中，無拉回之安全均值回歸交易機會，基於風控考量予以排除。*\n"
                        )
                    else:
                        lines.append(
                            f"> [!WARNING]\n"
                            f"> **本板塊在此期選股中被排除**，原因在於所採用的「趨勢動能 (Momentum) 策略」過濾了所有成分股：\n"
                            f"> \n"
                            f"> - 成分股總數：{total} 檔\n"
                            f"> - 未達流動性或市值門檻被過濾：{stats.get('failed_liquidity', 0)} 檔\n"
                            f"> - 短期趨勢偏弱 (低於 20MA) 被過濾：{stats.get('failed_trend', 0)} 檔\n"
                            f"> \n"
                            f"> *解讀：該板塊目前技術面仍偏弱，缺乏強勢買盤推升，基於順勢交易與防禦考量予以排除。*\n"
                        )
                else:
                    if is_etf:
                        lines.append(f"\n### Focus Sector ETF: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}%\n")
                    else:
                        lines.append(f"\n### Focus Sector Proxy Stock: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}%\n")
                    if strategy == "reversion":
                        lines.append(
                            f"> [!WARNING]\n"
                            f"> **This sector was omitted from the stock selection** because all its constituents failed the 'Pullback / Mean Reversion Strategy' filters:\n"
                            f"> \n"
                            f"> - Total Constituents: {total}\n"
                            f"> - Filtered out by size/liquidity: {stats.get('failed_liquidity', 0)}\n"
                            f"> - Filtered out by downtrend (below 200MA): {stats.get('failed_downtrend', 0)}\n"
                            f"> - Filtered out by overextension (outside 50MA range): {stats.get('failed_overextended', 0)}\n"
                            f"> - Filtered out by overbought conditions (RSI-14 > 55): {stats.get('failed_overbought', 0)}\n"
                            f"> \n"
                            f"> *Note: This sector is currently either overbought or in a long-term downtrend, presenting no safe pullback entry. Omitted for risk control.*\n"
                        )
                    else:
                        lines.append(
                            f"> [!WARNING]\n"
                            f"> **This sector was omitted from the stock selection** because all its constituents failed the 'Trend-Following / Momentum Strategy' filters:\n"
                            f"> \n"
                            f"> - Total Constituents: {total}\n"
                            f"> - Filtered out by size/liquidity: {stats.get('failed_liquidity', 0)}\n"
                            f"> - Filtered out by weak trend (below 20MA): {stats.get('failed_trend', 0)}\n"
                            f"> \n"
                            f"> *Note: This sector is currently in a weak trend with lack of buyers. Omitted for defensive purposes.*\n"
                        )
                lines.append("\n---")
                continue
                
            if is_proxy:
                f_data = item.get("financials") or {}
                
                def f_val(key, suffix="", prefix="", divisor=1.0, fmt=".2f"):
                    val = f_data.get(key)
                    if val is None:
                        return "N/A"
                    if isinstance(val, (int, float)):
                        return f"{prefix}{val / divisor:{fmt}}{suffix}"
                    return f"{prefix}{val}{suffix}"
                
                price_symbol = "$" if region == "US" else "NT$"
                
                is_etf_proxy = f_data.get("is_etf_proxy", True)
                
                if is_zh:
                    if is_etf_proxy:
                        lines.append(f"\n### 焦點行業板塊 ETF：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}% - 【直接投資 ETF 模式】\n")
                        lines.append("> [!IMPORTANT]\n"
                                     f"> 本板塊在第一階段量化動能篩選中成功被評選為**當週最強勢焦點板塊**。\n"
                                     "> \n"
                                     f"> 依據系統配置，此板塊投資策略設定為 **`proxy` (直接投資 ETF 本身)** 模式。系統已跳過底層成分股量化篩選，直接調度 **總經分析師** 與 **技術動能分析師** 對該 ETF 本身進行評估與持倉分配。\n")
                        
                        lines.append("\n#### ETF 特徵與技術指標定量分析")
                        lines.append("| 指標名稱 | 數值 / 位階 | 財務與技術意義解讀 |")
                        lines.append("| :--- | :--- | :--- |")
                        lines.append(f"| **當前交易現價** | {price_symbol}{f_val('current_price')} | ETF 目前在次級市場之最新成交價格。 |")
                        lines.append(f"| **5日動能回報** | {weekly_return:+.2f}% | 反映過去 5 個交易日之強勢資金推升力道。 |")
                        lines.append(f"| **資產管理規模 (AUM)** | {f_val('total_assets', divisor=10**9, suffix=' B')} | 代表此 ETF 之市場流動性與防禦深度。 |")
                        lines.append(f"| **配息率 / 收益率** | {f_val('dividend_yield', suffix='%', divisor=0.01)} | 提供穩健持股之防守現金流回報。 |")
                        lines.append(f"| **淨值價 (NAV)** | {price_symbol}{f_val('nav_price')} | ETF 本身代表的實際淨資產價值。 |")
                    else:
                        lines.append(f"\n### 焦點行業板塊代理股：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}% - 【直接投資個股模式】\n")
                        lines.append("> [!IMPORTANT]\n"
                                     f"> 本板塊在第一階段量化動能篩選中成功被評選為**當週最強勢焦點板塊**。\n"
                                     "> \n"
                                     f"> 依據系統配置，此板塊投資策略設定為 **`proxy` (直接投資板塊代理個股本身)** 模式。系統已跳過底層成分股量化篩選，直接調度 **總經分析師** 與 **個股基本面分析師** 對該個股本身進行評估與持倉分配。\n")
                        
                        lines.append("\n#### 個股特徵與技術指標定量分析")
                        lines.append("| 指標名稱 | 數值 / 位階 | 財務與技術意義解讀 |")
                        lines.append("| :--- | :--- | :--- |")
                        lines.append(f"| **當前交易現價** | {price_symbol}{f_val('current_price')} | 個股目前之市場成交價格。 |")
                        lines.append(f"| **5日動能回報** | {weekly_return:+.2f}% | 反映過去 5 個交易日之強勢資金推升力道。 |")
                        lines.append(f"| **企業市值 (Market Cap)** | {f_val('market_cap', divisor=10**9, suffix=' B')} | 代表此個股之市值規模與市場防禦深度。 |")
                        lines.append(f"| **歷史本益比 (PE)** | {f_val('pe_ratio')} | 判定目前股價之估值性價比（越低通常越具安全邊際）。 |")
                        lines.append(f"| **股價淨值比 (PB)** | {f_val('price_to_book')} | 評估企業帳面價值之溢價狀態。 |")

                    lines.append(f"| **14天強弱指標 (RSI)** | {f_val('rsi_14', fmt='.1f')} | 判定目前動能位階（低於 30 為超賣，高於 70 為超買）。 |")
                    lines.append(f"| **20日均線 (20MA)** | {price_symbol}{f_val('sma_20')} | 短期生命線（現價高於 20MA 代表短線多頭確立）。 |")
                    lines.append(f"| **50日均線 (50MA)** | {price_symbol}{f_val('fifty_day_sma')} | 中期季線位階（確認中線波段防禦支撐點）。 |")
                    lines.append(f"| **200日均線 (200MA)** | {price_symbol}{f_val('two_hundred_day_sma')} | 長期牛熊分界線（提供極強的長線牛市安全邊際）。 |")
                else:
                    if is_etf_proxy:
                        lines.append(f"\n### Focus Sector ETF: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}% - [Direct ETF Mode]\n")
                        lines.append("> [!IMPORTANT]\n"
                                     f"> This sector was successfully selected as one of the **strongest performing focus sectors of the week** during the first-stage quantitative momentum screening.\n"
                                     "> \n"
                                     f"> According to the system configuration, the investment strategy for this sector is set to **`proxy` (Direct ETF Investment)**. The system bypassed quantitative screening of individual constituent stocks and directly routed to **Macro & Technical Dynamic Analysts** to evaluate and allocate budget for the ETF itself.\n")
                        
                        lines.append("\n#### ETF Quantitative & Technical Characteristics")
                        lines.append("| Metric | Value | Financial & Technical Significance |")
                        lines.append("| :--- | :--- | :--- |")
                        lines.append(f"| **Current Price** | {price_symbol}{f_val('current_price')} | Live secondary market trading price. |")
                        lines.append(f"| **5-Day Momentum** | {weekly_return:+.2f}% | Reflects short-term institutional momentum strength. |")
                        lines.append(f"| **Assets Under Management (AUM)** | {f_val('total_assets', divisor=10**9, suffix=' B')} | Indicates liquidity and market capital depth. |")
                        lines.append(f"| **Dividend Yield** | {f_val('dividend_yield', suffix='%', divisor=0.01)} | Standard dividend-paying defensive return rate. |")
                        lines.append(f"| **NAV Price** | {price_symbol}{f_val('nav_price')} | Net Asset Value representing underlying holdings. |")
                    else:
                        lines.append(f"\n### Focus Sector Proxy Stock: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}% - [Direct Stock Mode]\n")
                        lines.append("> [!IMPORTANT]\n"
                                     f"> This sector was successfully selected as one of the **strongest performing focus sectors of the week** during the first-stage quantitative momentum screening.\n"
                                     "> \n"
                                     f"> According to the system configuration, the investment strategy for this sector is set to **`proxy` (Direct Stock Investment)**. The system bypassed quantitative screening of individual constituent stocks and directly routed to **Macro & Fundamental Analysts** to evaluate and allocate budget for the stock itself.\n")
                        
                        lines.append("\n#### Stock Quantitative & Technical Characteristics")
                        lines.append("| Metric | Value | Financial & Technical Significance |")
                        lines.append("| :--- | :--- | :--- |")
                        lines.append(f"| **Current Price** | {price_symbol}{f_val('current_price')} | Live market trading price. |")
                        lines.append(f"| **5-Day Momentum** | {weekly_return:+.2f}% | Reflects short-term institutional momentum strength. |")
                        lines.append(f"| **Market Capitalization** | {f_val('market_cap', divisor=10**9, suffix=' B')} | Indicates enterprise size and market defense depth. |")
                        lines.append(f"| **PE Ratio** | {f_val('pe_ratio')} | Valuation multiplier to gauge price attractiveness. |")
                        lines.append(f"| **Price to Book (PB)** | {f_val('price_to_book')} | Valuation metric relative to book value. |")

                    lines.append(f"| **14-Day RSI** | {f_val('rsi_14', fmt='.1f')} | Identifies technical momentum level (<30 Oversold, >70 Overbought). |")
                    lines.append(f"| **20-Day SMA** | {price_symbol}{f_val('sma_20')} | Short-term trend confirmation baseline. |")
                    lines.append(f"| **50-Day SMA** | {price_symbol}{f_val('fifty_day_sma')} | Mid-term wave support price level. |")
                    lines.append(f"| **200-Day SMA** | {price_symbol}{f_val('two_hundred_day_sma')} | Long-term bull/bear baseline. |")
                lines.append("\n---")
            else:
                if is_zh:
                    if is_etf:
                        lines.append(f"\n### 焦點行業板塊 ETF：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}%\n")
                    else:
                        lines.append(f"\n### 焦點行業板塊代理股：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}%\n")
                    lines.append("| 排名 | 標的代碼 | 企業名稱 | 當前價格 | 5日漲跌幅 | 成交量增幅 | 量化評分 | 市值 |")
                    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                else:
                    if is_etf:
                        lines.append(f"\n### Focus Sector ETF: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}%\n")
                    else:
                        lines.append(f"\n### Focus Sector Proxy Stock: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}%\n")
                    lines.append("| Rank | Ticker | Company Name | Price | 5-Day Return | Vol Spike | Quant Score | Market Cap |")
                    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                    
                for idx, pick in enumerate(picks, 1):
                    ticker = pick["ticker"]
                    name = pick["name"]
                    price = pick["current_price"]
                    ret = pick["weekly_return"] * 100
                    spike = pick["volume_spike"]
                    score = pick["score"]
                    mcap = pick["market_cap"]
                    
                    if mcap >= 10**12:
                        mcap_str = f"{mcap / 10**12:.2f}T"
                    elif mcap >= 10**9:
                        mcap_str = f"{mcap / 10**9:.2f}B"
                    else:
                        mcap_str = f"{mcap / 10**6:.2f}M"
                        
                    price_symbol = "$" if region == "US" else "NT$"
                    lines.append(f"| {idx} | `{ticker}` | {name} | {price_symbol}{price:.2f} | {ret:+.2f}% | {spike:.2f}x | {score:.2f} | {mcap_str} |")
                lines.append("\n---")
            
        lines.append("\n## 免責聲明 (Disclaimer)")
        if is_zh:
            lines.append("本報告僅供參考，不構成任何投資建議。投資人應獨立評估市場風險，並承擔交易之最終盈虧。")
        else:
            lines.append("This report is for informational purposes only and does not constitute investment advice. Investors should evaluate market risks independently and bear full responsibility for their trades.")
            
        final_markdown = "\n".join(lines)
        final_html = markdown.markdown(final_markdown, extensions=['fenced_code', 'tables'])
        return final_markdown, final_html
