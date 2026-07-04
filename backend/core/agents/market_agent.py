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

FALLBACK_INSTRUCTION = "你是一位頂尖的「區域市場與板塊分析師 (Regional Market & Sector Analyst)」。你的專長是通過追蹤各大「產業板塊 ETF」或「產業代表指數」的資金動向與相對強度，分析市場情緒與資金流向。"
SYSTEM_INSTRUCTION = load_prompt_file("market_agent_baseline.txt", FALLBACK_INSTRUCTION)


class MarketAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="MarketAgent",
            role="Market & Sector Analyst",
            system_instruction=SYSTEM_INSTRUCTION
        )

    def analyze(self, region_name: str, sector_rankings: list, sector_news: list = None) -> str:
        """Executes the sector ranking and money flow analysis."""
        formatted_sectors = ""
        date_range_info = ""
        
        if sector_rankings and "start_date" in sector_rankings[0]:
            start_d = sector_rankings[0]["start_date"]
            end_d = sector_rankings[0]["end_date"]
            date_range_info = f"【本週板塊週回報計算區間】：自 {start_d} 至 {end_d} (共 5 個交易日)\n"
            
        for i, sec in enumerate(sector_rankings):
            formatted_sectors += f"{i+1}. Ticker: {sec['ticker']} | 名稱: {sec['label']} | 週報酬率: {sec['weekly_return']*100:.2f}% | 收盤價: {sec['current_price']:.2f}\n"
            
        formatted_news = ""
        if sector_news:
            formatted_news += "\n【當週最強勢板塊相關產業新聞與動態】：\n"
            for i, art in enumerate(sector_news):
                formatted_news += f"新聞 {i+1}: {art['title']}\n   發布時間: {art['pub_date']}\n"
                if art.get('summary') and art['summary'].strip():
                    formatted_news += f"   摘要: {art['summary']}\n"
                formatted_news += "\n"
        
        prompt = f"""
請針對【{region_name}】的產業板塊數據進行深度分析，找出資金流向與黃金版塊。

{date_range_info}

【產業板塊週表現數據】：
{formatted_sectors if formatted_sectors else "（暫無相關板塊數據）"}
{formatted_news}

請依據上述真實市場數據與行業動態進行排行與邏輯解讀，並指引本週最看好的 2 大深挖產業主題。
"""
        return self.run(prompt)

    def match_thematic_stocks(self, all_tickers: list, themes: list) -> list:
        """Uses LLM to match the candidates from all_tickers to the extracted themes."""
        import json
        
        ticker_list_str = "\n".join([f"- {item['ticker']} ({item['name']})" for item in all_tickers])
        themes_str = ", ".join(themes)
        
        matcher_instruction = (
            "你是一個專業的投資組合經理。請從候選股票清單中，挑選出最符合當前熱門主題的 2 檔股票。"
            "請只回覆一個標準 JSON 陣列，其中每個元素包含 'ticker' 和 'reason'（推薦原因），絕對不要包含任何 markdown 標記（如 ```json）或多餘解釋。\n"
            "格式例如：[{\"ticker\": \"2330.TW\", \"reason\": \"契合...主題，是全球龍頭...\"}]"
        )
        
        agent = BaseAgent(
            name="ThematicMatcher",
            role="Thematic Stock Matcher",
            system_instruction=matcher_instruction,
            register_db=False
        )
        
        prompt = f"""
【熱門產業主題】: {themes_str}

【候選股票清單】:
{ticker_list_str}

請挑選出最契合這幾個熱門主題的 2 檔龍頭個股，並給出精煉的推薦理由（約 30-50 字）。
"""
        try:
            resp = agent.run(prompt)
            clean_resp = resp.strip()
            if clean_resp.startswith("```"):
                lines = clean_resp.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_resp = "\n".join(lines).strip()
            selected = json.loads(clean_resp)
            if isinstance(selected, list):
                matched = []
                for item in selected:
                    t_ticker = item.get("ticker", "").strip().upper()
                    t_reason = item.get("reason", "").strip()
                    matched_stock = next((s for s in all_tickers if s["ticker"].upper() == t_ticker), None)
                    if matched_stock:
                        matched.append({
                            "ticker": matched_stock["ticker"],
                            "name": matched_stock["name"],
                            "reason": t_reason
                        })
                return matched
        except Exception as e:
            print(f"[!] MarketAgent 篩選主題概念股失敗: {e}")
        return []

    def extract_themes_from_news(self, thematic_news: list) -> list:
        """Uses a quick LLM query to extract 2-3 hot industry thematic keywords from general thematic news."""
        import json
        
        formatted_news = ""
        for i, art in enumerate(thematic_news):
            formatted_news += f"新聞 {i+1}: {art['title']}\n"
            if art.get('summary') and art['summary'].strip():
                formatted_news += f"   摘要: {art['summary']}\n"
            formatted_news += "\n"
            
        extractor_instruction = (
            "你是一個頂尖的全球與區域主題投資基金經理。請將輸入的最新產業新聞作為「當前市場焦點的錨定與參考」。\n"
            "在此基礎上，請結合你對全球科技趨勢、政府政策方向及全球供應鏈的「深厚專業知識」，精確辨識並預測出 3 個未來 1-2 季最具需求爆發力與技術催化劑的「具體細分次產業」或「精準技術題材」關鍵字。\n"
            "⚠️ 【極重要 - 顆粒度與具體性要求】：\n"
            "1. 絕對不要回覆像『AI伺服器』、『晶片設計』、『AI資本支出』、『半導體』、『科技股』等過於寬泛、籠統或上位階的字眼！\n"
            "2. 你必須深入產業細節，萃取出具備高顆粒度的具體次產業或關鍵組件技術，其轉換邏輯如下：\n"
            "   - 寬泛主題 (❌) -> 高顆粒度具體技術 (✓)\n"
            "   - 半導體/AI晶片 (❌) -> 先進封裝與異質整合技術 (✓) 或 IP授權/特殊應用IC設計 (✓)\n"
            "   - 散熱技術 (❌) -> 浸沒式/液冷散熱模組與冷卻液 (✓)\n"
            "   - 光通訊/光電 (❌) -> 共同光學封裝與矽光子技術 (✓)\n"
            "   - 電力與電網 (❌) -> 高壓重電變壓器與電網韌性建設 (✓)\n"
            "3. ⚠️【反錨定與範例迴避規則 - 極度重要】：\n"
            "   - 為了保持萃取的真實性與動態性，你【絕對不能】直接複製或完全使用本指令中作為示範的字眼（如「先進封裝CoWoS」、「液冷散熱模組」、「矽光子與CPO」、「重電變壓器」等）。\n"
            "   - 你必須根據輸入新聞的實際內容，提煉出屬於該新聞脈絡下的「具體次產業」或「細分技術名稱」。\n"
            "4. 確保這 3 個主題具備【廣度與多元性】，盡量涵蓋不同的技術方向（例如：一個硬體半導體相關、一個組件/散熱/電力基礎建設相關、一個非AI高成長題材如摺疊螢幕/低軌衛星/生技等）。\n"
            "請只回覆一個符合標準 JSON 字串陣列格式的字串，例如：[\"細分主題1\", \"細分主題2\", \"細分主題3\"]，絕對不要包含任何 markdown 標記（如 ```json）或額外對話贅字。"
        )
        
        agent = BaseAgent(
            name="ThemeExtractor",
            role="Thematic Keyword Extractor",
            system_instruction=extractor_instruction,
            register_db=False
        )
        
        try:
            resp = agent.run(f"請從以下最新的產業趨勢與研究報告新聞中，萃取出最具前景之投資主題關鍵字：\n{formatted_news}")
            clean_resp = resp.strip()
            if clean_resp.startswith("```"):
                lines = clean_resp.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_resp = "\n".join(lines).strip()
            themes = json.loads(clean_resp)
            if isinstance(themes, list):
                return [str(t).strip() for t in themes if t]
        except Exception as e:
            print(f"[!] MarketAgent 萃取產業主題關鍵字失敗: {e}")
        # Fallback defaults
        return ["AI硬體", "半導體"]
