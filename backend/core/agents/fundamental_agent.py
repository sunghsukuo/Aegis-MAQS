from pathlib import Path
from core.agents.base_agent import BaseAgent

def load_prompt_file(filename: str, fallback: str) -> str:
    try:
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[!] Failed to load external prompt {filename}: {e}")
    return fallback

FALLBACK_INSTRUCTION = "你是一位頂尖的「標的篩選與基本面分析師 (Target Selection & Fundamental Analyst)」。你的職責是深入解讀企業的財務報表與基本面經營數據，篩選出具備高勝率投資價值的優秀標的。"
SYSTEM_INSTRUCTION = load_prompt_file("fundamental_agent_baseline.txt", FALLBACK_INSTRUCTION)


class FundamentalAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="FundamentalAgent",
            role="Fundamental Analyst",
            system_instruction=SYSTEM_INSTRUCTION
        )

    def analyze(self, ticker: str, company_name: str, financials: dict, news_analysis: str, macro_context: str, macro_regime: str = None, price_regime: str = None) -> str:
        """Executes the fundamental valuation and investment recommendation for an asset, automatically routing between stock and ETF templates."""
        import math
        
        regime_instruction = ""
        if macro_regime == "BULL_RISK_ON":
            regime_instruction = """
【重要大盤情境性格引導 (BULL_RISK_ON)】：
目前大盤處於牛市積極進攻狀態（BULL_RISK_ON）。在評估標的時，請將分析焦點優先放在高成長性與獲利指標上。對於公司因研發、業務擴張而產生的短期股權稀釋或合理範圍內的債務，可給予適度寬容，著重發掘長線獲利爆發力。
"""
        elif macro_regime == "BEAR_RISK_OFF":
            regime_instruction = """
【重要大盤情境性格引導 (BEAR_RISK_OFF)】：
目前大盤處於熊市保守避險狀態（BEAR_RISK_OFF）。在評估標的時，市場避險情緒高漲，請以極度嚴苛的視角審視任何潛在財務與消息風險。高度關注股權稀釋、負債比率與現金流健康度，若有任何瑕疵或不確定性，請果斷調降評級（如 Hold 或 Sell），切忌盲目樂觀。
"""
        elif macro_regime == "VOLATILE_RANGEBOUND":
            regime_instruction = """
【重要大盤情境性格引導 (VOLATILE_RANGEBOUND)】：
目前大盤處於震盪防守狀態（VOLATILE_RANGEBOUND）。此時市場缺乏明確方向，請保持平衡與中立。著重評估標的的估值安全邊際（如 PEG、P/E 水平）與防禦屬性，避免推薦波動度過高或基本面空泛的投機標的。
"""
        
        # Determine region and currency based on ticker
        is_tw = ticker.endswith(".TW") or ticker.endswith(".TWO")
        currency = "TWD" if is_tw else "USD"

        # Build prompt formatting key metrics safely
        def safe_fmt(val, prefix="", suffix="", placeholder="N/A", is_currency=False):
            if val is None:
                return placeholder
            if isinstance(val, (int, float)):
                if suffix == "%":
                    return f"{prefix}{val*100:.2f}%"
                if is_currency:
                    # In Chinese financial contexts, "億" (100M) is standard and intuitive for both currencies.
                    if val >= 100_000_000:
                        return f"{prefix}{val/100_000_000:,.2f} 億 {currency}{suffix}"
                    if val >= 10_000:
                        return f"{prefix}{val/10_000:,.2f} 萬 {currency}{suffix}"
                    return f"{prefix}{val:,.2f} {currency}{suffix}"
                return f"{prefix}{val:,.2f}{suffix}"
            return f"{prefix}{val}{suffix}"

        is_etf = financials.get("is_etf_proxy", False)
        curr_price = financials.get("current_price", 0.0)
        atr_14 = financials.get("atr_14")
        beta = financials.get("beta", 1.0)
        
        # Calculate dynamic volatility stops based on Beta-adjusted ATR via risk manager
        from core.risk.risk_manager import calculate_risk_boundaries
        risk_res = calculate_risk_boundaries(curr_price, atr_14, beta, macro_regime=macro_regime)
        
        k1 = risk_res["k1"]
        k2 = risk_res["k2"]
        suggested_sl = risk_res["suggested_sl"]
        suggested_tp = risk_res["suggested_tp"]
        suggested_buy_lower = risk_res["suggested_buy_lower"]
        suggested_buy_upper = risk_res["suggested_buy_upper"]
        beta_adj = risk_res["beta_adj"]

        # Trigger anti-chasing mechanism when the price regime indicates mean reversion/rangebound
        if price_regime == "MEAN_REVERSION_RANGE":
            rsi_val = financials.get("rsi_14")
            sma_50 = financials.get("fifty_day_sma")
            bias_str = ""
            if rsi_val is not None or sma_50 is not None:
                bias_str = "\n【目前標的之短線超買指標偏離度】:\n"
                if rsi_val is not None:
                    bias_str += f"- RSI-14: {rsi_val:.1f}\n"
                if sma_50 is not None and curr_price:
                    bias = (curr_price - sma_50) / sma_50 * 100
                    bias_str += f"- 50日均線正偏離度 (Bias): {bias:+.2f}%\n"
            
            anti_chasing = f"""
【重要指令變更 - 均值回歸防追高硬性限制】:{bias_str}
⚠️ 目前市場處於【均值回歸/震盪市】氣候。在該氣候下，追逐高位突破股極易遭受動能崩潰 (Momentum Crash)。
請嚴格遵循防追高紀律：
1. 若此標的目前 RSI > 70 或 50日均線正偏離度 > 15%，代表股價短線已嚴重超買或乖離過大。除非有極端強烈之基本面實質支撐，否則你必須一律強制將評級調降至 Hold 或 Sell，以觸發預算閹割風控！
2. 即使基本面良好，亦必須在「估值與安全邊際評估」中特別強調高位追價的回撤風險，並調低建議持倉權重。
"""
            regime_instruction += anti_chasing



        if is_etf:
            prompt = f"""
【重要指令變更】：此標的為 ETF（指數股票型基金），而非單一個股。請你以「大類資產配置與技術動能分析師」的角色進行評估。
你不需要分析個股財務結構（如 ROE、FCF、PEG 等），請專注於此 ETF 的「技術面均線系統（SMA/RSI/MACD）」、「產業/板塊巨觀景氣與新聞催化劑」以及「資產規模與配息率」進行估值。
{regime_instruction}

請為標的【{company_name} ({ticker})】進行深度 ETF 技術估值與投資價值評估。

【標的基本資料與技術指標數據】：
* 標的代碼: {ticker}
* 標的全名: {company_name}
* 當前價格: {safe_fmt(financials.get('current_price'), is_currency=True)}
* 系統建議波動買入區間: {safe_fmt(suggested_buy_lower, is_currency=True)} - {safe_fmt(suggested_buy_upper, is_currency=True)} (以現價為基準，結合 Beta 與 ATR 波動度調整)
* 資產規模 (AUM): {safe_fmt(financials.get('total_assets'), is_currency=True)}
* 配息率/收益率: {safe_fmt(financials.get('dividend_yield'), suffix="%")}
* 折溢價/淨值價 (NAV): {safe_fmt(financials.get('nav_price'), is_currency=True)}
* 20天均線 (20-day SMA): {safe_fmt(financials.get('sma_20'), is_currency=True)}
* 50天均線 (50-day SMA): {safe_fmt(financials.get('fifty_day_sma'), is_currency=True)}
* 200天均線 (200-day SMA): {safe_fmt(financials.get('two_hundred_day_sma'), is_currency=True)}
* 14天強弱指標 (RSI-14): {safe_fmt(financials.get('rsi_14'))} (注意：低於 30 為超賣，高於 70 為超買)
* 分析師共識建議: {safe_fmt(financials.get('recommendation_consensus'))}

【該產業/板塊最新的新聞與重大消息面分析】：
{news_analysis}

【重要指令變更 - 波動度風控要求】：
本系統已全面導入 ATR 與 Beta 波動度風控限制。請你在撰寫最後的「具體投資操作指南」時：
1. 務必優先參考系統建議的波動買入區間（{safe_fmt(suggested_buy_lower, is_currency=True)} - {safe_fmt(suggested_buy_upper, is_currency=True)}）、波動停損價與停利價。
2. 若無極其強烈之基本面/消息面重大催化劑理由，請直接採用系統建議的波動買入區間、停損與停利價，或在其上下 1.5% 的極小範圍內微調。

【當前大市場總體經濟環境脈絡】：
{macro_context}

請綜合上述的所有技術量化指標與行業定性脈絡，撰寫出一份極致專業的「ETF 板塊技術估值報告」與「明確操作指引」。

【重要輸出紀律限制】：
在輸出報告時，請直接從標題開始輸出。**嚴禁**輸出任何前導招呼語、確認句或廢話（例如：『好的，收到您的指令。身為...，我將...為您剖析...』）。請直接以 Markdown 結構輸出內容，否則系統將無法解析。

輸出格式請嚴格依照以下 Markdown 結構：
### [{company_name} / {ticker}] 板塊技術估值與投資價值評估
* **投資評級與核心論點**：[強烈買入 Strong Buy / 買入 Buy / 持有 Hold / 賣出 Sell] (請附帶一句話最核心的板塊輪動與技術面核心投資亮點。注意：此行開頭必須嚴格使用「* **投資評級與核心論點**：」，且評級必須嚴格使用「強烈買入 Strong Buy」、「買入 Buy」、「持有 Hold」、「賣出 Sell」這四個標準詞彙之一，不得加上括號如「(Strong Buy)」，亦不得將行頭改寫為「投資建議評級」或任何其他變體，否則系統解析將出錯。)
* **基本面與技術面關鍵指標深度剖析**：
  * *行業景氣與資金流向*：[分析該產業/板塊在當前總經環境下的發展空間與資金流入熱度]
  * *技術指標與動能評估*：[分析目前價格相對於 20MA、50MA、200MA 的均線位階，以及 RSI 狀態，判斷是否處於多頭強勢或超跌區]
  * *ETF 規模與配息健康度*：[分析 AUM 與配息率，評估流動性與持倉穩定度]
* **結合總經與消息面的綜合評語**：[結合當前宏觀政策與產業重大消息，說明該板塊有何天時地利]
* **具體投資操作指南**：
  * **當前價格**：{safe_fmt(financials.get('current_price'), is_currency=True)}
  * **推薦買入區間**：[給出合理的買入區間，如 140 - 145 元]
  * **中線目標價**：[根據技術排列與上檔壓力算出的合理中線目標價]
  * **防禦停損點**：[根據均線支撐或前波低點設定的防禦停損位]
  * **建議持倉權重**：[例如：適中佔比 10%、加碼配置 15% 等]
"""
        else:
            prompt = f"""
請為標的【{company_name} ({ticker})】進行深度基本面財務估值與投資價值評估。
{regime_instruction}

【標的財務基本面與波動風控數據】：
* 股票代碼: {ticker}
* 企業全名: {company_name}
* 當前股價: {safe_fmt(financials.get('current_price'), is_currency=True)}
* 系統建議波動買入區間: {safe_fmt(suggested_buy_lower, is_currency=True)} - {safe_fmt(suggested_buy_upper, is_currency=True)} (以現價為基準，結合 Beta 與 ATR 波動度調整)
* 市值: {safe_fmt(financials.get('market_cap'), is_currency=True)}
* 過去本益比 (PE): {safe_fmt(financials.get('pe_ratio'))}
* 未來本益比 (Forward PE): {safe_fmt(financials.get('forward_pe'))}
* 本益成長比 (PEG): {safe_fmt(financials.get('peg_ratio'))}
* 股價淨值比 (PB): {safe_fmt(financials.get('price_to_book'))}
* 淨利潤率: {safe_fmt(financials.get('profit_margin'), suffix="%")}
* 營業利益率: {safe_fmt(financials.get('operating_margin'), suffix="%")}
* 股東權益報酬率 (ROE): {safe_fmt(financials.get('roe'), suffix="%")}
* 負債權益比 (Debt/Equity): {safe_fmt(financials.get('debt_to_equity') / 100.0 if financials.get('debt_to_equity') is not None else None, suffix="%")}
* 營收年增率 (Revenue Growth): {safe_fmt(financials.get('revenue_growth'), suffix="%")}
* EPS年增率 (EPS Growth): {safe_fmt(financials.get('eps_growth'), suffix="%")}
* 自由現金流: {safe_fmt(financials.get('free_cash_flow'), is_currency=True)}
* 50天均線 (50-day SMA): {safe_fmt(financials.get('fifty_day_sma'), is_currency=True)}
* 200天均線 (200-day SMA): {safe_fmt(financials.get('two_hundred_day_sma'), is_currency=True)}
* 14天真實波動均值 (ATR-14): {safe_fmt(atr_14, is_currency=True)}
* 大盤敏感度 (Beta): {safe_fmt(beta)}
* 系統建議波動停損價: {safe_fmt(suggested_sl, is_currency=True)} (買入價 - {k1:.2f} * ATR，已結合 Beta 微調)
* 系統建議波動停利價: {safe_fmt(suggested_tp, is_currency=True)} (買入價 + {k2:.2f} * ATR，已結合 Beta 微調)
* 華爾街投行與分析師評估（數據參考）：
  - 分析師共識建議評級: {safe_fmt(financials.get('recommendation_consensus'))} (共識評分: {safe_fmt(financials.get('analyst_mean_score'))}，共 {safe_fmt(financials.get('analyst_count'))} 位分析師參與評估。評分定義：1.0=強烈買入 Strong Buy，3.0=持有 Hold，5.0=賣出 Sell)
  - 分析師目標價估值區間: {safe_fmt(financials.get('analyst_target_low'), is_currency=True)} - {safe_fmt(financials.get('analyst_target_high'), is_currency=True)} (共識平均目標價: {safe_fmt(financials.get('analyst_target_mean'), is_currency=True)})


【重要指令變更 - 波動度風控與投行估值要求】：
本系統已全面導入 ATR 與 Beta 波動度風控限制，以及投行量化估值模型報告。請你在撰寫最後的「具體投資操作指南」與「估值與安全邊際評估」時：
1. 務必優先參考系統建議的波動買入區間（{safe_fmt(suggested_buy_lower, is_currency=True)} - {safe_fmt(suggested_buy_upper, is_currency=True)}）、波動停損價與停利價。
2. 若無極其強烈之基本面/消息面重大催化劑理由，請直接採用系統建議的波動買入區間、停損價與停利價，或在其上下 1.5% 的極小範圍內微調。
3. 務必在你的操作指南中，明確點出你是採用了幾倍的 ATR（例如：目標價採 +{k2:.2f} 倍 ATR，停損點採 -{k1:.2f} 倍 ATR，買入區間採 -{1.0:.2f} 倍至 +{0.25:.2f} 倍 ATR）作為設定依據。
4. 務必詳細研讀與評估輸入內容中的【投行級別量化估值模型報告 (Equity Valuation Engine)】（包含 DCF 與同業比較法），並在「估值與安全邊際評估」部分詳細評論其算出的綜合內在合理價（Fair Price）與目前股價之偏離幅度（被低估/合理/被高估），說明目前價格相較於合理估值的安全邊際。

【該標的最新的新聞與重大消息面分析】：
{news_analysis}

【當前大市場總體經濟環境脈絡】：
{macro_context}

請綜合上述的所有量化數據與定性脈絡，撰寫出一份極致專業的「基本面財務估值報告」與「明確操作指引」。

【重要輸出紀律限制】：
在輸出報告時，請直接從第一個規定的 Markdown 標題開始輸出。**嚴禁**輸出任何前導招呼語、確認句或廢話（例如：『好的，收到您的指令。身為...，我將...為您剖析...』）。請直接以 Markdown 結構輸出內容，否則系統將無法解析。
"""
        return self.run(prompt)
