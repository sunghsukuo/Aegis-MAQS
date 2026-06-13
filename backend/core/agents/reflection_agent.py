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

FALLBACK_SYSTEM_INSTRUCTION = "你是一位擁有魔鬼視角且極具客觀性的「回測與自我反思分析師 (Backtest & Reflection Analyst)」。你的唯一使命是：無情地檢視本系統「歷史推薦標的」的真實表現，找出決策中的漏洞與盲點，並產出修正下一期投資決策的核心反饋。"
SYSTEM_INSTRUCTION = load_prompt_file("reflection_agent_baseline.txt", FALLBACK_SYSTEM_INSTRUCTION)

def extract_case_summary(response_text: str) -> str:
    """從 FundamentalAgent 輸出的 Markdown 報告中提煉評級、核心論點與操作指南"""
    if not response_text:
        return "N/A"
    lines = response_text.splitlines()
    summary_lines = []
    
    for line in lines:
        stripped = line.strip()
        if any(kw in stripped for kw in ["投資評級", "當前價格", "推薦買入區間", "中線目標價", "防禦停損點", "建議持倉權重"]):
            summary_lines.append(stripped)
            
    if summary_lines:
        return "\n".join(summary_lines)
    return response_text[:300] + "..."



class ReflectionAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="ReflectionAgent",
            role="Backtest & Reflection Analyst",
            system_instruction=SYSTEM_INSTRUCTION
        )

    def analyze(self, historical_recs: list, benchmark_perf: dict) -> str:
        """Executes the backtest analysis and generates the self-reflection prompt for other agents."""
        
        # Build prompt formatting past recommendations
        formatted_recs = ""
        if not historical_recs:
            formatted_recs = "（目前資料庫中尚無歷史推薦記錄。本期為第一期運行，暫無回測對象。請為未來的回測做奠基準備。）"
        else:
            for i, rec in enumerate(historical_recs):
                status_str = "追蹤中 (Active)" if rec.get('is_active') == 1 else "已結案 (Closed)"
                roi_val = rec.get('performance')
                if roi_val is None:
                    roi_val = 0.0
                roi_str = f"+{roi_val*100:.2f}%" if roi_val >= 0 else f"{roi_val*100:.2f}%"
                
                formatted_recs += f"{i+1}. Ticker: {rec['ticker']} ({rec['company_name']})\n"
                formatted_recs += f"   推薦日期: {rec['report_date']} | 推薦價: {rec['recommend_price']:.2f} | 停損位: {rec.get('stop_loss', 0):.2f} | 目標價: {rec.get('target_price', 0):.2f}\n"
                formatted_recs += f"   目前價格: {rec.get('current_price', 0):.2f} | 即時回報率: {roi_str} | 狀態: {status_str}\n\n"
                
        prompt = f"""
請針對本系統歷史的投資推薦列表進行深度回測與決策反思。

【大盤基準對比數據】：
* 大盤 Ticker: {benchmark_perf.get('ticker', 'N/A')}
* 大盤當前價格: {benchmark_perf.get('current_price', 0):,.2f}
* 大盤週報酬率: {benchmark_perf.get('weekly_return', 0)*100:.2f}%
* 大盤月報酬率: {benchmark_perf.get('monthly_return', 0)*100:.2f}%

【歷史推薦標的當前表現數據】：
{formatted_recs}

請依據上述的歷史真實損益數據，進行冷酷客觀的回測與反思，並產出給本週分析師的「自我修正調整令」。
"""
        return self.run(prompt)

    @classmethod
    def evolve_prompts(cls):
        """
        自適應 Prompt 演化引擎 (Self-Reflective Prompt Optimization Engine)
        分析最近的已平倉交易紀錄與其實際投資績效 (ROI)，
        針對表現欠佳或估值失真的 FundamentalAgent 進行 Prompt 自我演化與版本升級。
        """
        cls.evolve_prompts_core(dry_run=False)

    @classmethod
    def evolve_prompts_core(cls, report_date: str = None, limit: int = 10, mock_if_empty: bool = False, dry_run: bool = False, model_name: str = "gemini-2.5-pro") -> dict:
        """
        核心自適應 Prompt 演化邏輯，支援指定日期週查詢與 Dry-Run (唯讀) 測試模式。
        """
        import json
        import core.db_manager as db
        from core.agents.base_agent import BaseAgent
        
        print("[*] [自適應 Prompt 演化] 正在啟動自適應 Prompt 演化核心...")
        try:
            # 1. 獲取 FundamentalAgent 的交易推論日誌與 ROI
            agent_name = "FundamentalAgent"
            if report_date:
                query_sqlite = """
                    SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version, r.macro_regime, r.price_regime
                    FROM agent_inference_logs l
                    JOIN recommendations r ON l.rec_id = r.id
                    WHERE r.report_date = ? AND l.agent_name = ?
                """
                query_mysql = """
                    SELECT l.ticker, r.performance as roi, l.input_prompt, l.output_response, l.prompt_version, r.macro_regime, r.price_regime
                    FROM agent_inference_logs l
                    INNER JOIN recommendations r ON l.rec_id = r.id
                    WHERE r.report_date = %s AND l.agent_name = %s
                """
                logs = []
                with db.db_session() as conn:
                    cursor = conn.cursor()
                    db.execute_sql(cursor, query_sqlite, query_mysql, (report_date, agent_name))
                    rows = cursor.fetchall()
                    for r in rows:
                        if isinstance(r, dict):
                            logs.append({
                                "ticker": r["ticker"],
                                "roi": r["roi"],
                                "input_prompt": r["input_prompt"],
                                "output_response": r["output_response"],
                                "prompt_version": r["prompt_version"],
                                "macro_regime": r.get("macro_regime", "N/A"),
                                "price_regime": r.get("price_regime", "N/A")
                            })
                        else:
                            logs.append({
                                "ticker": r[0],
                                "roi": r[1],
                                "input_prompt": r[2],
                                "output_response": r[3],
                                "prompt_version": r[4],
                                "macro_regime": r[5],
                                "price_regime": r[6]
                            })
                            
                # 如果為空且開啟了 mock
                if not logs and mock_if_empty:
                    print(f"[*] 指定日期 {report_date} 沒有找到已結算 ROI 的推論日誌，正在模擬 Mock 資料進行測試...")
                    rec_query_sqlite = "SELECT id, ticker, company_name FROM recommendations WHERE report_date = ?"
                    rec_query_mysql = "SELECT id, ticker, company_name FROM recommendations WHERE report_date = %s"
                    recs = []
                    with db.db_session() as conn:
                        cursor = conn.cursor()
                        db.execute_sql(cursor, rec_query_sqlite, rec_query_mysql, (report_date,))
                        rows = cursor.fetchall()
                        for r in rows:
                            if isinstance(r, dict):
                                recs.append(r)
                            else:
                                recs.append({"id": r[0], "ticker": r[1], "company_name": r[2]})
                                
                    import random
                    for rec in recs:
                        mock_roi = random.uniform(-0.15, 0.15)
                        logs.append({
                            "ticker": rec["ticker"],
                            "roi": mock_roi,
                            "input_prompt": f"Mock input for {rec['company_name']}",
                            "output_response": f"Mock recommendation for {rec['ticker']}: Buy with mock ROI {mock_roi*100:.2f}%",
                            "prompt_version": "v1.0.0"
                        })
            else:
                logs = db.get_extreme_inference_logs_with_roi(agent_name, limit_success=5, limit_failure=5)
                
            # 2. 進行 cold start 防禦檢查 (Cold-Start Defense Check)
            if len(logs) < 2:
                print(f"[*] [自適應 Prompt 演化] 目前交易記錄為 {len(logs)} 筆，少於演化閾值 2 筆，跳過本次 Prompt 演化。")
                return None
                
            print(f"[*] [自適應 Prompt 演化] 偵測到 {len(logs)} 筆交易紀錄，開始進行多維度效能分析...")
            
            # 3. 獲取前一週使用的系統提示詞
            if report_date and logs:
                curr_version = logs[0]["prompt_version"]
                query_sqlite = "SELECT system_prompt FROM prompt_registry WHERE agent_name = ? AND version = ?"
                query_mysql = "SELECT system_prompt FROM prompt_registry WHERE agent_name = %s AND version = %s"
                with db.db_session() as conn:
                    cursor = conn.cursor()
                    db.execute_sql(cursor, query_sqlite, query_mysql, (agent_name, curr_version))
                    row = cursor.fetchone()
                    if row:
                        curr_prompt = row[0] if isinstance(row, (tuple, list)) else row.get("system_prompt")
                    else:
                        baseline_path = Path(__file__).resolve().parent.parent / "prompts" / "fundamental_agent_baseline.txt"
                        if baseline_path.exists():
                            curr_prompt = baseline_path.read_text(encoding="utf-8").strip()
                        else:
                            curr_prompt = "你是一位頂尖的「標的篩選與基本面分析師」。"
            else:
                active_prompt_data = db.get_active_prompt(agent_name)
                if not active_prompt_data:
                    print("[!] [自適應 Prompt 演化] 無法自資料庫獲取當前活躍的 Prompt，跳過演化。")
                    return None
                curr_prompt = active_prompt_data["system_prompt"]
                curr_version = active_prompt_data["version"]
                
            # 4. 區分成功與失敗案例以進行對比學習
            success_cases = []
            failure_cases = []
            for log in logs:
                roi_val = log.get("roi")
                if roi_val is None:
                    roi_val = 0.0
                case_desc = {
                    "ticker": log["ticker"],
                    "roi": f"{roi_val * 100:.2f}%",
                    "macro_regime": log.get("macro_regime", "N/A"),
                    "price_regime": log.get("price_regime", "N/A"),
                    "recommendation_summary": extract_case_summary(log["output_response"])
                }
                roi = roi_val
                if roi > 0:
                    success_cases.append(case_desc)
                else:
                    failure_cases.append(case_desc)
                    
            print(f"[*] [自適應 Prompt 演化] 成功交易案例：{len(success_cases)} 筆 | 失敗交易案例：{len(failure_cases)} 筆")
            
            # 5. 調度 Meta-Agent 作為 Prompt 優化工程師
            print("[*] [自適應 Prompt 演化] 正在初始化 MetaPromptOptimizer 代理人進行對比反思...")
            
            fallback_meta = "你是一位頂尖的金融大模型 Prompt 工程師與量化投資策略專家。你的任務是分析 FundamentalAgent 過去的分析案例，優化其 system_prompt。請只輸出新的、優化後的完整 system_prompt。"
            meta_instruction = load_prompt_file("meta_prompt_optimizer_baseline.txt", fallback_meta)
            meta_version = "v1.0.1"
            
            # 6. 自動同步防禦：比對資料庫與代碼版本，若資料庫版本落後則主動升級
            try:
                active_meta = db.get_active_prompt("MetaPromptOptimizer")
                db_version_tuple = [int(i) for i in active_meta["version"].replace("v", "").split(".")] if active_meta else [0, 0, 0]
                code_version_tuple = [int(i) for i in meta_version.replace("v", "").split(".")]
                
                if not active_meta or db_version_tuple < code_version_tuple:
                    print(f"[*] [自適應 Prompt 演化] 偵測到資料庫中 MetaPromptOptimizer 版本落後，自動升級為最新代碼版本：{meta_version}")
                    if not dry_run:
                        db.save_prompt_registry("MetaPromptOptimizer", meta_instruction, meta_version, is_active=1)
                    else:
                        print("[*] [自適應 Prompt 演化] Dry-run 模式下，跳過資料庫 MetaPromptOptimizer 升級寫入。")
            except Exception as sync_err:
                print(f"[!] [自適應 Prompt 演化] 自動同步 MetaPromptOptimizer 時出錯: {sync_err}")

            meta_optimizer = BaseAgent(
                name="MetaPromptOptimizer",
                role="Meta-Prompt Optimizer",
                system_instruction=meta_instruction,
                model_name=model_name
            )
            
            # 組裝對比學習的推論上下文
            success_text = json.dumps(success_cases, ensure_ascii=False, indent=2)
            failure_text = json.dumps(failure_cases, ensure_ascii=False, indent=2)
            
            evolution_prompt = f"""
請根據以下提供的資訊，演化並優化 FundamentalAgent 的系統提示詞 (System Prompt)。

【當前活躍之 System Prompt】：
{curr_prompt}

【近期成功的分析案例 (ROI > 0)】：
{success_text}

【近期失敗的分析案例 (ROI <= 0)】：
{failure_text}

請透過對比成功與失敗案例的差異，進行多維度的盲點優化。請在優化後的提示詞中特別強調：
1. 避開那些容易造成高回撤或追高的估值偏好。
2. 進一步嚴格化 those 導致失敗案例的財務健康度指標。

優化後，請直接回覆優化後的「完整 system_prompt 內容」，絕對不要包含任何包裹用的 ``` 或 markdown 標籤，也不要有前言或解釋。
"""
            new_prompt = meta_optimizer.run(evolution_prompt)
            if not new_prompt:
                print("[!] [自適應 Prompt 演化] 大模型輸出的新 Prompt 為空。放棄本次演化。")
                return None
                
            # 嚴格校驗新 Prompt 的完整度與長度比例，防禦局部修改或截斷 Bug
            curr_len = len(curr_prompt.strip())
            new_len = len(new_prompt.strip())
            
            # 1. 長度縮水比例檢查 (不得低於原長度的 55%)
            min_allowed_len = int(curr_len * 0.55)
            if new_len < min_allowed_len:
                print(f"[!] [自適應 Prompt 演化] 新 Prompt 長度為 {new_len} 字元，低於當前版本 55% 閾值 ({min_allowed_len} 字元)。疑似截斷，放棄本次演化。")
                return None
                
            # 2. 核心結構關鍵字完整性檢查
            required_keywords = [
                "投資評級與核心論點",
                "推薦買入區間",
                "中線目標價",
                "防禦停損點",
                "建議持倉權重"
            ]
            missing_keywords = [kw for kw in required_keywords if kw not in new_prompt]
            if missing_keywords:
                print(f"[!] [自適應 Prompt 演化] 新 Prompt 缺少核心結構關鍵字: {missing_keywords}。判定為殘缺，放棄本次演化。")
                return
                
            # 解析版本號
            try:
                major, minor, patch = map(int, curr_version.replace("v", "").split("."))
                patch += 1
                new_version = f"v{major}.{minor}.{patch}"
            except Exception:
                new_version = "v1.0.1"
                
            if not dry_run:
                # 寫入 Prompt 註冊表
                db.save_prompt_registry(agent_name, new_prompt.strip(), new_version)
                print(f"[✓] [自適應 Prompt 演化] 恭喜！系統 Prompt 已自動由 {curr_version} 成功演化升級至 {new_version}！")
                
                # 儲存 Prompt 進化推論日誌
                db.save_agent_inference_log(
                    rec_id=None,
                    agent_name="MetaPromptOptimizer",
                    ticker=None,
                    input_prompt=meta_optimizer.last_prompt,
                    output_response=new_prompt,
                    prompt_version=curr_version
                )
            else:
                print(f"[✓] [自適應 Prompt 演化] [Dry-run 模式] 成功模擬演化新版 System Prompt，預計升級版本 {curr_version} -> {new_version}。")

            return {
                "old_prompt": curr_prompt,
                "new_prompt": new_prompt.strip(),
                "old_version": curr_version,
                "new_version": new_version,
                "success_cases": success_cases,
                "failure_cases": failure_cases,
                "logs_count": len(logs)
            }
            
        except Exception as e:
            print(f"[!] [自適應 Prompt 演化] Prompt 演化中途出錯: {e}")
            raise e

