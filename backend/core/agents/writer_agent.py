from pathlib import Path
from core.agents.base_agent import BaseAgent
from core.config import REPORT_LANGUAGE, WRITER_MODEL

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
            model_name=WRITER_MODEL
        )

    def synthesize(self, date_str: str, macro_reports: list, market_reports: list,
                   stock_reports: list, reflection_report: str, candidate_summary: str = None,
                   portfolio_ledger: str = None) -> str:
        """Synthesizes all analyst sub-reports into a single comprehensive Weekly Investment Report."""
        
        # Structure the giant context prompt for synthesis
        macro_context = "\n\n".join(macro_reports)
        market_context = "\n\n".join(market_reports)
        stock_context = "\n\n".join(stock_reports)
        
        lang_directive_en = "Please synthesize all input reports and write the final output in perfect Financial English."
        lang_directive_zh = "請將所有輸入報告進行綜合融會，並嚴格以繁體中文（台灣財經文風）撰寫最終週報。同時請注意個股深度理由的 150-200 字數精煉限制。"
        lang_directive = lang_directive_en if REPORT_LANGUAGE == "EN" else lang_directive_zh
        
        prompt = f"""
請將以下所有專業分析師的獨立子報告，與本週實戰帳戶交易與持倉調整明細，融會貫通並重新整合編輯，撰寫出【{date_str}】當週的【全球投資策略與多維度決策週報】。

【語言與寫作指示】：
{lang_directive}

【總編輯特別任務 ── 決策評級透明度與交易/板塊呼應】：
本週所有被分析的候選標的（包含其隸屬的板塊/ETF）與其初步評級如下：
{candidate_summary or "（無）"}

請遵循以下寫作紀律以求決策透明與報告呼應：
1. 僅將評級為 Buy 或 Strong Buy 的標的列入「### 本週推薦配置總覽表」中。**請務必在推薦表內或下方的「深入投資理由說明」中，清晰標明每檔推薦個股所隸屬的產業板塊或對應的 ETF 代號（例如在個股名稱旁標註 (隸屬 XLP 板塊)），以便讀者對照選股掃描報告進行呼應查詢。**
2. 所有評級為 Hold（持有/觀望）或 Sell / Avoid（避免買入）的標的，**必須無一遺漏地**列入「### 本週調降/避險排除標的與防禦配置說明」表格，並在下方寫出具體的不推薦原因（例如：估值高估、風險報酬比不合要求、或大盤熔斷凍結，每檔限 50-80 字），並標註其隸屬的板塊/ETF，絕不允許隨意遺漏！
3. **本週所有實際帳戶交易成交紀錄已列於下方【5. 本週實戰帳戶交易與持倉調整明細】，請務必將其整理並填寫於最後的「### 本週實戰帳戶交易與持倉調整明細」表格中**，特別注意若有評級為 Hold 的個股被建倉/分配 5% 權重，必須在此表內明確列出，讓讀者清晰掌握帳戶資金與實際持股變化。

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
【5. 本週實戰帳戶交易與持倉調整明細】：
{portfolio_ledger or "（本週無新交易紀錄，維持原持倉）"}
==================================================

請嚴格遵循總編輯角色規範，消除贅字，統一格式，產出一份令人驚豔的高水準報告！
"""
        return self.run(prompt)
