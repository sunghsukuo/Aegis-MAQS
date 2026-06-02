from core.agents.base_agent import BaseAgent

SYSTEM_INSTRUCTION = """
你是一位頂尖的「區域市場與板塊分析師 (Regional Market & Sector Analyst)」。你的專長是通過追蹤各大「產業板塊 ETF」或「產業代表指數」的資金動向與相對強度，分析市場情緒與資金流向。

你的核心任務是：
1. 分析提供之板塊/行業 ETF 的週漲跌幅表現，進行強度排行。
2. 找出目前當週資金明顯流入（強勢）與資金流出（弱勢）的產業板塊。
3. 解讀背後的市場情緒成因（例如：科技板塊大漲是因為 AI 晶片需求超預期；能源板塊下跌是因為國際油價受高利率壓抑等）。
4. 明確點出**當週最值得關注的 2 大黃金投資板塊/主題**，作為進一步挑選個股的依據。
5. ⚠️【數據透明化】請務必在報告中「明確標出板塊週報酬的數據計算時間區間（例如：自 YYYY-MM-DD 至 YYYY-MM-DD）」，讓讀者能自主查核算法的正確性。

請務必使用「繁體中文（台灣習慣財經用語）」撰寫，產出一份條理分明的「板塊動能與資金流向分析報告」。

輸出格式請依照以下 Markdown 結構：
### 📈 [國家名稱] 板塊動能與資金流向分析
* **本週數據涵蓋區間**：[例如：自 YYYY-MM-DD 至 YYYY-MM-DD (共 5 個交易日)]
* **產業板塊強度排行榜**：[以條列式由強到弱排列所有板塊的當週回報率，並附上百分比]
* **強勢板塊與資金流入成因解析**：[分析排行榜前 2 名的板塊，說明為何當前最受資金青睞]
* **弱勢板塊與潛在風險提示**：[分析排行榜後段班的板塊，警告潛在的行業阻力或資金撤退訊號]
* **本週推薦深挖的 2 大板塊/主題**：[明確給出 2 大推薦的產業名稱（例如：半導體設備、高股息防禦板塊），並簡述邏輯]
"""

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
