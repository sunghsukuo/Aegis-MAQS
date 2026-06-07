from pathlib import Path

def load_prompt_file(filename: str, fallback: str) -> str:
    try:
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[!] Failed to load external prompt {filename}: {e}")
    return fallback

FALLBACK_INSTRUCTION = "你是一位資深的「總體經濟分析師 (Macroeconomic Analyst)」。你的職責是深入分析特定國家/區域當前所處的宏觀經濟週期與金融政策環境。"
SYSTEM_INSTRUCTION = load_prompt_file("macro_agent_baseline.txt", FALLBACK_INSTRUCTION)


class MacroAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="MacroAgent",
            role="Macroeconomic Analyst",
            system_instruction=SYSTEM_INSTRUCTION
        )

    def analyze(self, region_name: str, benchmark_data: dict, news_data: list) -> str:
        """Executes the macro analysis for a given region."""
        # Format the input prompt with tools data
        formatted_news = ""
        for i, art in enumerate(news_data):
            formatted_news += f"新聞 {i+1}: {art['title']}\n   發布時間: {art['pub_date']}\n"
            if art.get('summary') and art['summary'].strip():
                formatted_news += f"   摘要: {art['summary']}\n"
            formatted_news += "\n"
            
        prompt = f"""
請針對【{region_name}】進行總體經濟環境深度分析。

【數據資料】：
* 大盤基準 Ticker: {benchmark_data.get('ticker')}
* 大盤名稱: {benchmark_data.get('name')}
* 當前價格/指數點數: {benchmark_data.get('current_price'):,.2f}
* 週報酬率: {benchmark_data.get('weekly_return', 0)*100:.2f}%
* 月報酬率: {benchmark_data.get('monthly_return', 0)*100:.2f}%

【當週最新相關總經新聞摘要】：
{formatted_news if formatted_news else "（暫無相關最新總經新聞）"}

請依據你的專業知識與上述客觀數據，產出專屬的總經分析報告。
"""
        return self.run(prompt)
