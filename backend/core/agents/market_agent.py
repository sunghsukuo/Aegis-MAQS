from pathlib import Path

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
