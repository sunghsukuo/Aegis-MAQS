from pathlib import Path

def load_prompt_file(filename: str, fallback: str) -> str:
    try:
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[!] Failed to load external prompt {filename}: {e}")
    return fallback

FALLBACK_INSTRUCTION = "你是一位精銳的「重大消息與新聞催化劑分析師 (News & Catalyst Analyst)」。你的職責是解讀個股或產業板塊最新的重大新聞、財務公告、法說會紀要及產業傳言，從中挑選並評估具有「催化劑（Catalysts）」效果的事件。"
SYSTEM_INSTRUCTION = load_prompt_file("news_agent_baseline.txt", FALLBACK_INSTRUCTION)


class NewsAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="NewsAgent",
            role="News & Catalyst Analyst",
            system_instruction=SYSTEM_INSTRUCTION
        )

    def analyze(self, ticker: str, company_name: str, news_data: list) -> str:
        """Executes the news and catalyst analysis for a specific stock/ETF."""
        formatted_news = ""
        for i, art in enumerate(news_data):
            formatted_news += f"新聞 {i+1}: {art['title']}\n   發布時間: {art['pub_date']}\n"
            if art.get('summary') and art['summary'].strip():
                formatted_news += f"   摘要: {art['summary']}\n"
            formatted_news += "\n"
            
        prompt = f"""
請針對標的【{company_name} ({ticker})】最新的重大消息與新聞進行深度催化劑分析。

【當週最新新聞數據】：
{formatted_news if formatted_news else "（暫無最新相關重大消息）"}

請依據上述客觀消息，篩選出最核心的 2 個催化事件，進行深度評估，並給出消息面綜合評級。
"""
        return self.run(prompt)
