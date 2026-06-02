import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from core.config import DATA_DIR, REGIONS

# Dynamically construct the constituents cache from config.py to ensure a Single Source of Truth!
# This decouples screener.py completely from the sector configuration details.
ETF_CONSTITUENTS_CACHE = {}
for region_code, region_info in REGIONS.items():
    for etf, etf_info in region_info.get("sector_etfs", {}).items():
        if isinstance(etf_info, dict) and "constituents" in etf_info:
            ETF_CONSTITUENTS_CACHE[etf] = etf_info["constituents"]


class QuantScreener:
    def __init__(self):
        self.session_history = []

    def fetch_etf_constituents(self, etf_ticker: str) -> list:
        """
        Dynamically fetches constituents of the given ETF from Yahoo Finance.
        Falls back to a high-quality pre-seeded cache if scraping fails or gets blocked.
        Supports automatic sector proxy resolution to decouple config.py settings.
        """
        etf_ticker = etf_ticker.strip().upper()
        
        try:
            url = f"https://finance.yahoo.com/quote/{etf_ticker}/holdings/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                tickers = []
                
                # Scan all links containing "/quote/" which represents tickers
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/quote/" in href:
                        parts = href.split("/quote/")
                        if len(parts) > 1:
                            # Strip out parameters like ?p=MSFT or sub-paths
                            sym = parts[1].split("?")[0].split("/")[0].strip().upper()
                            # Clean symbols and filter out the parent ETF symbol
                            if sym and sym != etf_ticker and all(c.isalnum() or c in ".-" for c in sym) and len(sym) <= 10:
                                if sym not in tickers:
                                    tickers.append(sym)
                                    
                if len(tickers) >= 5:
                    print(f"[*] [Screener] 動態成功抓取 {etf_ticker} 的 {len(tickers)} 檔成分股代號。")
                    return tickers
        except Exception as e:
            print(f"[!] [Screener] 動態抓取 {etf_ticker} 成分股失敗 ({e})。將切換至靜態高品質快取。")
            
        # Fallback to local cache with automatic proxy resolver
        cache_list = ETF_CONSTITUENTS_CACHE.get(etf_ticker)
        if cache_list is None:
            # Smart automatic classifier for regional sector proxies
            resolved_key = None
            
            custom_proxy_keys = ["2881.TW", "1301.TW"]
            for key in custom_proxy_keys:
                if key in ETF_CONSTITUENTS_CACHE and etf_ticker in ETF_CONSTITUENTS_CACHE[key]:
                    resolved_key = key
                    break
            
            # If not found in custom proxies, search standard ETF lists as fallback
            if not resolved_key:
                for key, val_list in ETF_CONSTITUENTS_CACHE.items():
                    if etf_ticker in val_list:
                        resolved_key = key
                        break
            
            if resolved_key:
                cache_list = ETF_CONSTITUENTS_CACHE[resolved_key]
                print(f"[*] [Screener] 偵測到 {etf_ticker} 為板塊代理人，自動映射至 {resolved_key} 的成分股清單。")
            else:
                # Absolute fallback: If not found anywhere, treat as single stock to prevent empty sector failure
                cache_list = [etf_ticker]
                print(f"[!] [Screener] 無法自動映射 {etf_ticker} 的板塊。將其視為單一獨立個股進行後續評估。")
        else:
            print(f"[*] [Screener] 載入 {etf_ticker} 成分股快取清單 (共 {len(cache_list)} 檔標的)。")
            
        return cache_list

    def _get_projected_volume(self, hist: pd.DataFrame, region: str) -> float:
        """
        Dynamically projects intraday volume to full-day volume if the market is open.
        Provides a stable fallback to previous close volume during pre-market or early trading.
        """
        try:
            from datetime import datetime, time
            import pytz
            
            last_row = hist.iloc[-1]
            last_volume = float(last_row["Volume"])
            
            # Retrieve the timestamp of the last data row
            # If yfinance history has a timezone-aware DatetimeIndex, use its timezone
            last_date = hist.index[-1]
            
            # Setup timezone and trading hours
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
                
            # Get current time in the local timezone of the market
            now = datetime.now(tz)
            
            # Check if the last row's date matches today (meaning it is a live trading day)
            if last_date.strftime("%Y-%m-%d") == now.strftime("%Y-%m-%d"):
                # Market is today. Check if trading hours have started
                market_open = tz.localize(datetime.combine(now.date(), market_open_time))
                market_close = tz.localize(datetime.combine(now.date(), market_close_time))
                
                if now < market_open:
                    # Pre-market: use previous day's completed volume (iloc[-2]) as a stable indicator
                    if len(hist) >= 2:
                        return float(hist["Volume"].iloc[-2])
                    return last_volume
                elif now >= market_close:
                    # Post-market or market closed: use today's actual volume
                    return last_volume
                else:
                    # Market is currently trading: project volume based on elapsed minutes
                    elapsed = (now - market_open).total_seconds() / 60.0
                    
                    # If it's the first 15 minutes of trading, projection can be extremely noisy.
                    # Fallback to previous day's completed volume to maintain stability!
                    if elapsed < 15.0:
                        if len(hist) >= 2:
                            return float(hist["Volume"].iloc[-2])
                        return last_volume
                        
                    projected = last_volume * (total_minutes / elapsed)
                    return float(projected)
        except Exception as e:
            print(f"[!] [Screener] Volume projection error: {e}")
            
        # Standard fallback on any error: return today's volume as-is
        return float(hist["Volume"].iloc[-1])

    def screen_stocks(self, etf_ticker: str, region: str, limit: int = 5, market_regime: str = None) -> list:
        """
        Calculates 5-day return momentum, volume surge factor, and applies liquidity/trend filters
        to dynamically select the top 'limit' candidates from the ETF's constituents, adapting
        the factor weights and applying volatility penalties based on the macro market regime.
        """
        tickers = self.fetch_etf_constituents(etf_ticker)
        if not tickers:
            return []
            
        print(f"[*] [Screener] 開始對 {etf_ticker} 的成分股進行量化因子計算與篩選...")
        screened_results = []
        
        # Configure regional liquidity limits
        # US: min market cap $2B, min avg volume 200,000 shares
        # Taiwan: min market cap NT$8B, min avg volume 300,000 shares (300張)
        min_mcap = 2 * 10**9 if region == "US" else 8 * 10**9
        min_vol = 200000 if region == "US" else 300000
        
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                
                # Fetch historical price data (1 month history is perfect to calculate 20-day averages)
                hist = t.history(period="1mo")
                if hist.empty or len(hist) < 20:
                    continue
                
                # Retrieve fast_info indicators (fast & robust)
                fast = t.fast_info
                market_cap = fast.get("marketCap", 0.0)
                # Fallback to calculated market cap if fast_info fails
                if not market_cap:
                    market_cap = hist["Close"].iloc[-1] * fast.get("shares", 0.0)
                    
                # 1. Liquidity filter
                avg_volume = hist["Volume"].iloc[-20:].mean()
                if market_cap < min_mcap or avg_volume < min_vol:
                    # Skip highly illiquid small caps
                    continue
                    
                # 2. Trend filter (Price must be above 20-day MA to avoid catching falling knives)
                close_now = hist["Close"].iloc[-1]
                ma20 = hist["Close"].iloc[-20:].mean()
                if close_now < ma20:
                    # Stock is in a downtrend, skip
                    continue
                    
                # 3. Momentum Factor (5-day return)
                close_5d_ago = hist["Close"].iloc[-6] if len(hist) >= 6 else hist["Close"].iloc[0]
                weekly_return = (close_now - close_5d_ago) / close_5d_ago
                
                # 4. Volume Spike Factor (current volume vs 20-day average) with Dynamic Intraday Projection!
                volume_now = self._get_projected_volume(hist, region)
                volume_spike = volume_now / avg_volume if avg_volume > 0 else 1.0
                
                # Get the company name
                name = ticker
                # Try to retrieve name from yfinance fast info or ticker info
                try:
                    name = t.info.get("longName", ticker)
                except Exception:
                    pass
                
                # Override with Chinese name for Taiwan stocks to prevent translation hallucinations
                if region == "Taiwan" or ticker.endswith(".TW") or ticker.endswith(".TWO"):
                    ticker_num = ticker.split(".")[0]
                    from core.config import TAIWAN_NAMES
                    if ticker_num in TAIWAN_NAMES:
                        name = f"{TAIWAN_NAMES[ticker_num]} ({name})"
                
                # 5. Combined Score
                # Return score is weekly return in % (e.g. 8.5% is 8.5)
                return_score = weekly_return * 100
                # Volume spike is capped at 3x for scoring stability
                volume_score = min(volume_spike, 3.0) / 3.0 * 10.0
                
                # Dynamic scoring based on Market Regime for Adaptive Risk Management!
                if market_regime == "BEAR_RISK_OFF":
                    # Bear Market: Prioritize institutional accumulation (Volume Spike) over momentum, and penalize high volatility
                    daily_returns = hist["Close"].pct_change()
                    daily_vol = float(daily_returns.iloc[-20:].std() * 100)
                    if pd.isna(daily_vol): 
                        daily_vol = 0.0
                    vol_penalty = min(daily_vol * 1.5, 5.0)
                    combined_score = (return_score * 0.3) + (volume_score * 0.7) - vol_penalty
                elif market_regime == "VOLATILE_RANGEBOUND":
                    # Rangebound: Balanced momentum & volume, with a moderate volatility penalty
                    daily_returns = hist["Close"].pct_change()
                    daily_vol = float(daily_returns.iloc[-20:].std() * 100)
                    if pd.isna(daily_vol): 
                        daily_vol = 0.0
                    vol_penalty = min(daily_vol * 0.75, 2.5)
                    combined_score = (return_score * 0.5) + (volume_score * 0.5) - vol_penalty
                else:
                    # Bull Market / Default: Heavy momentum chasing (Alpha-seeking)
                    combined_score = (return_score * 0.7) + (volume_score * 0.3)
                
                screened_results.append({
                    "ticker": ticker,
                    "name": name,
                    "weekly_return": float(weekly_return),
                    "volume_spike": float(volume_spike),
                    "current_price": float(close_now),
                    "market_cap": float(market_cap),
                    "score": float(combined_score)
                })
                
            except Exception as e:
                # Silently catch and proceed for individual stock failures to ensure pipeline robustness
                continue
                
        # Sort by combined score in descending order (highest score first)
        screened_results.sort(key=lambda x: x["score"], reverse=True)
        
        final_picks = screened_results[:limit]
        print(f"[✓] [Screener] {etf_ticker} 動態量化篩選完成！挑選出前 {len(final_picks)} 強勢飆股：")
        for i, pick in enumerate(final_picks, 1):
            print(f"    {i}. {pick['name']} ({pick['ticker']}) - 5日漲幅: {pick['weekly_return']*100:.2f}%, 量能增幅: {pick['volume_spike']:.2f}x, 評分: {pick['score']:.2f}")
            
        # Calculate ETF's own weekly return for comparative reporting in section headers
        etf_weekly_return = 0.0
        try:
            etf_ticker_obj = yf.Ticker(etf_ticker)
            etf_hist = etf_ticker_obj.history(period="1mo")
            if not etf_hist.empty and len(etf_hist) >= 6:
                etf_close_now = etf_hist["Close"].iloc[-1]
                etf_close_5d_ago = etf_hist["Close"].iloc[-6]
                etf_weekly_return = float((etf_close_now - etf_close_5d_ago) / etf_close_5d_ago)
        except Exception as e:
            print(f"[!] 計算 ETF {etf_ticker} 自身週報酬率失敗: {e}")

        self.session_history.append({
            "etf": etf_ticker,
            "region": region,
            "picks": final_picks,
            "weekly_return": etf_weekly_return
        })
        return final_picks

    def record_proxy_etf(self, etf_ticker: str, region: str, financials: dict = None, weekly_return: float = 0.0):
        """
        Records a proxy ETF selection along with its quantitative and technical features
        into the session history for high-fidelity reporting.
        """
        etf_ticker = etf_ticker.strip().upper()
        name = etf_ticker
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
        print(f"[✓] [Screener] 已成功將 ETF 代理標的 {etf_ticker} (含技術/定量特徵) 寫入選股報告記錄。")

    def generate_report(self, report_date: str) -> tuple:
        """
        Generates a beautiful Markdown and HTML report from the session screening history.
        """
        if not self.session_history:
            return "", ""
            
        from core.config import REPORT_LANGUAGE
        import markdown
        
        is_zh = (REPORT_LANGUAGE == "ZH")
        
        if is_zh:
            title = f"# 📈 量化動態選股掃描決策報告 ({report_date})"
            note_content = "本報告由「量化動態掃描選股引擎」自動生成。系統分析了當週資金流入最強的行業 ETF 成分股，依據 **5日動能因子（70% 權重）** 與 **20日成交量爆發因子（30% 權重）** 進行綜合評分篩選，排除流動性不足與空頭排列個股，精選出最具主力大單進駐與爆發潛力的個股。"
            sec_title = "🎯 各板塊強勢個股動態篩選明細"
        else:
            title = f"# 📈 Quantamental Dynamic Stock Selection Report ({report_date})"
            note_content = "This report is automatically generated by the Quantamental Dynamic Stock Scanner Engine. The system analyzes the constituents of the strongest performing sector ETFs of the week, screening them using a combined quantitative score of **5-day momentum (70% weight)** and **20-day volume spike (30% weight)**, filtering out low-liquidity assets and downtrend stocks, selecting targets with robust institutional buying footprints."
            sec_title = "🎯 Selected Sector Strong Stock Screening Details"
            
        lines = []
        lines.append(title)
        lines.append("\n---")
        lines.append(f"\n> [!NOTE]\n> {note_content}\n")
        lines.append("\n---")
        lines.append(f"\n## {sec_title}\n")
        
        for item in self.session_history:
            etf = item["etf"]
            region = item["region"]
            picks = item["picks"]
            is_proxy = item.get("is_proxy", False)
            weekly_return = item.get("weekly_return", 0.0) * 100
            
            if not picks and not is_proxy:
                continue
                
            region_lbl = "美股" if region == "US" else "台股"
            if not is_zh:
                region_lbl = "US Market" if region == "US" else "Taiwan Market"
                
            if is_proxy:
                # Render a beautiful explanatory box and a quantitative characteristics table!
                etf_name = item.get("name", etf)
                f_data = item.get("financials") or {}
                
                # Format quantitative fields safely
                def f_val(key, suffix="", prefix="", divisor=1.0, fmt=".2f"):
                    val = f_data.get(key)
                    if val is None:
                        return "N/A"
                    if isinstance(val, (int, float)):
                        return f"{prefix}{val / divisor:{fmt}}{suffix}"
                    return f"{prefix}{val}{suffix}"
                
                price_symbol = "$" if region == "US" else "NT$"
                
                if is_zh:
                    lines.append(f"\n### 🔍 焦點行業板塊 ETF：{etf_name} ({etf}) ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}% - 【直接投資 ETF 模式】\n")
                    lines.append("> [!IMPORTANT]\n"
                                 f"> 本板塊在第一階段量化動能篩選中成功被評選為**當週最強勢焦點板塊**。\n"
                                 "> \n"
                                 f"> 依據系統配置，此板塊投資策略設定為 **`proxy` (直接投資 ETF 本身)** 模式。系統已跳過底層成分股量化篩選，直接調度 **總經分析師** 與 **技術動能分析師** 對該 ETF 本身進行評估與持倉分配。\n")
                    
                    # Add Quantitative Table
                    lines.append("\n#### 📊 ETF 特徵與技術指標定量分析")
                    lines.append("| 指標名稱 | 數值 / 位階 | 財務與技術意義解讀 |")
                    lines.append("| :--- | :--- | :--- |")
                    lines.append(f"| **當前交易現價** | {price_symbol}{f_val('current_price')} | ETF 目前在次級市場之最新成交價格。 |")
                    lines.append(f"| **5日動能回報** | {weekly_return:+.2f}% | 反映過去 5 個交易日之強勢資金推升力道。 |")
                    lines.append(f"| **資產管理規模 (AUM)** | {f_val('total_assets', divisor=10**9, suffix=' B')} | 代表此 ETF 之市場流動性與防禦深度。 |")
                    lines.append(f"| **配息率 / 收益率** | {f_val('dividend_yield', suffix='%', divisor=0.01)} | 提供穩健持股之防守現金流回報。 |")
                    lines.append(f"| **淨值價 (NAV)** | {price_symbol}{f_val('nav_price')} | ETF 本身代表的實際底層裝產價值。 |")
                    lines.append(f"| **14天強弱指標 (RSI)** | {f_val('rsi_14', fmt='.1f')} | 判定目前動能位階（低於 30 為超賣，高於 70 為超買）。 |")
                    lines.append(f"| **20日均線 (20MA)** | {price_symbol}{f_val('sma_20')} | 短期生命線（現價高於 20MA 代表短線多頭確立）。 |")
                    lines.append(f"| **50日均線 (50MA)** | {price_symbol}{f_val('fifty_day_sma')} | 中期季線位階（確認中線波段防禦支撐點）。 |")
                    lines.append(f"| **200日均線 (200MA)** | {price_symbol}{f_val('two_hundred_day_sma')} | 長期牛熊分界線（提供極強的長線牛市安全邊際）。 |")
                else:
                    lines.append(f"\n### 🔍 Focus Sector ETF: {etf_name} ({etf}) ({region_lbl}) - Weekly Return: {weekly_return:+.2f}% - [Direct ETF Mode]\n")
                    lines.append("> [!IMPORTANT]\n"
                                 f"> This sector was successfully selected as one of the **strongest performing focus sectors of the week** during the first-stage quantitative momentum screening.\n"
                                 "> \n"
                                 f"> According to the system configuration, the investment strategy for this sector is set to **`proxy` (Direct ETF Investment)**. The system bypassed quantitative screening of individual constituent stocks and directly routed to **Macro & Technical Dynamic Analysts** to evaluate and allocate budget for the ETF itself.\n")
                    
                    # Add Quantitative Table
                    lines.append("\n#### 📊 ETF Quantitative & Technical Characteristics")
                    lines.append("| Metric | Value | Financial & Technical Significance |")
                    lines.append("| :--- | :--- | :--- |")
                    lines.append(f"| **Current Price** | {price_symbol}{f_val('current_price')} | Live secondary market trading price. |")
                    lines.append(f"| **5-Day Momentum** | {weekly_return:+.2f}% | Reflects short-term institutional momentum strength. |")
                    lines.append(f"| **Assets Under Management (AUM)** | {f_val('total_assets', divisor=10**9, suffix=' B')} | Indicates liquidity and market capital depth. |")
                    lines.append(f"| **Dividend Yield** | {f_val('dividend_yield', suffix='%', divisor=0.01)} | Standard dividend-paying defensive return rate. |")
                    lines.append(f"| **NAV Price** | {price_symbol}{f_val('nav_price')} | Net Asset Value representing underlying holdings. |")
                    lines.append(f"| **14-Day RSI** | {f_val('rsi_14', fmt='.1f')} | Identifies technical momentum level (<30 Oversold, >70 Overbought). |")
                    lines.append(f"| **20-Day SMA** | {price_symbol}{f_val('sma_20')} | Short-term trend confirmation baseline. |")
                    lines.append(f"| **50-Day SMA** | {price_symbol}{f_val('fifty_day_sma')} | Mid-term wave support price level. |")
                    lines.append(f"| **200-Day SMA** | {price_symbol}{f_val('two_hundred_day_sma')} | Long-term bull/bear baseline. |")
                lines.append("\n---")
            else:
                if is_zh:
                    lines.append(f"\n### 🔍 焦點行業板塊 ETF：{etf} ({region_lbl}) - 本週報酬率: {weekly_return:+.2f}%\n")
                    lines.append("| 排名 | 標的代碼 | 企業名稱 | 當前價格 | 5日漲跌幅 | 成交量增幅 | 量化評分 | 市值 |")
                    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                else:
                    lines.append(f"\n### 🔍 Focus Sector ETF: {etf} ({region_lbl}) - Weekly Return: {weekly_return:+.2f}%\n")
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
                    
                    # Format Market Cap
                    if mcap >= 10**12:
                        mcap_str = f"{mcap / 10**12:.2f}T"
                    elif mcap >= 10**9:
                        mcap_str = f"{mcap / 10**9:.2f}B"
                    else:
                        mcap_str = f"{mcap / 10**6:.2f}M"
                        
                    price_symbol = "$" if region == "US" else "NT$"
                    
                    lines.append(f"| {idx} | `{ticker}` | {name} | {price_symbol}{price:.2f} | {ret:+.2f}% | {spike:.2f}x | {score:.2f} | {mcap_str} |")
                    
                lines.append("\n---")
            
        lines.append("\n## ⚠️ 免責聲明 (Disclaimer)")
        if is_zh:
            lines.append("本報告僅供參考，不構成任何投資建議。投資人應獨立評估市場風險，並承擔交易之最終盈虧。")
        else:
            lines.append("This report is for informational purposes only and does not constitute investment advice. Investors should evaluate market risks independently and bear full responsibility for their trades.")
            
        final_markdown = "\n".join(lines)
        final_html = markdown.markdown(final_markdown, extensions=['fenced_code', 'tables'])
        return final_markdown, final_html
