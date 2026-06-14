from pathlib import Path
from core.agents.base_agent import BaseAgent
from core.config import REPORT_LANGUAGE, WRITER_GEMINI_MODEL

def load_prompt_file(filename: str, fallback: str) -> str:
    try:
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[!] Failed to load external prompt {filename}: {e}")
    return fallback

FALLBACK_ZH = "你是一位頂尖的「總編輯與投資策略師 (Chief Editor & Investment Strategist)」。請融會貫通並重新撰寫成一份極致專業的「每週全球投資決策白皮書 (Weekly Investment Advisory Report)」，並使用繁體中文撰寫。"
SYSTEM_INSTRUCTION_ZH = load_prompt_file("writer_agent_baseline_zh.txt", FALLBACK_ZH)

FALLBACK_EN = "You are a world-class Chief Editor & Investment Strategist. Your responsibility is to synthesize independent research into a Weekly Global Investment Advisory Report in English."
SYSTEM_INSTRUCTION_EN = load_prompt_file("writer_agent_baseline_en.txt", FALLBACK_EN)


class WriterAgent(BaseAgent):
    def __init__(self):
        # Choose system instruction dynamically based on configuration language
        system_instruction = SYSTEM_INSTRUCTION_EN if REPORT_LANGUAGE == "EN" else SYSTEM_INSTRUCTION_ZH
        super().__init__(
            name="WriterAgent",
            role="Chief Editor & Investment Strategist",
            system_instruction=system_instruction,
            model_name=WRITER_GEMINI_MODEL
        )

    def synthesize(self, date_str: str, macro_reports: list, market_reports: list,
                   stock_reports: list, reflection_report: str, candidate_summary: str = None) -> str:
        """Synthesizes all analyst sub-reports into a single comprehensive Weekly Investment Report."""
        
        # Structure the giant context prompt for synthesis
        macro_context = "\n\n".join(macro_reports)
        market_context = "\n\n".join(market_reports)
        stock_context = "\n\n".join(stock_reports)
        
        lang_directive_en = "Please synthesize all input reports and write the final output in perfect Financial English."
        lang_directive_zh = "請將所有輸入報告進行綜合融會，並嚴格以繁體中文（台灣財經文風）撰寫最終週報。同時請注意個股深度理由的 150-200 字數精煉限制。"
        lang_directive = lang_directive_en if REPORT_LANGUAGE == "EN" else lang_directive_zh
        
        prompt = f"""
請將以下所有專業分析師的獨立子報告，融會貫通並重新整合編輯，撰寫出【{date_str}】當週的【全球投資策略與多維度決策週報】。

【語言與寫作指示】：
{lang_directive}

【總編輯特別任務 ── 決策評級透明度】：
本週所有被分析的候選標的與其初步評級如下：
{candidate_summary or "（無）"}

請遵循以下寫作紀律以求決策透明：
1. 僅將評級為 Buy 或 Strong Buy 的標的列入「### 📋 本週推薦配置總覽表」中。
2. 所有評級為 Hold（持有/觀望）或 Sell / Avoid（避免買入）的標的，**必須無一遺漏地**列入「### ⚠️ 本週排除/觀望標的與防禦警示」表格，並在下方寫出具體的不推薦原因（例如：估值高估、風險報酬比不合要求、或大盤熔斷凍結），每檔限 50-80 字，使投資人清晰掌握不推薦的理由，絕不允許隨意遺漏！

==================================================
【1. 各區域總體經濟分析師子報告】：
{macro_context}

==================================================
【2. 各區域板塊動能分析師子報告】：
{market_context}

==================================================
<3. 嚴選標的基本面估值與消息催化劑子報告>：
{stock_context}

==================================================
【4. 歷史回測與決策自我修正子報告】：
{reflection_report}
==================================================

請嚴格遵循總編輯角色規範，消除贅字，統一格式，產出一份令人驚豔的高水準報告！
"""
        return self.run(prompt)
