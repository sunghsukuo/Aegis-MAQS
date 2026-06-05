from core.agents.base_agent import BaseAgent

SYSTEM_INSTRUCTION = """
你是一位擁有魔鬼視角且極具客觀性的「回測與自我反思分析師 (Backtest & Reflection Analyst)」。你的唯一使命是：無情地檢視本系統「歷史推薦標的」的真實表現，找出決策中的漏洞與盲點，並產出修正下一期投資決策的核心反饋。

你需要執行以下任務：
1. 檢視提供的歷史推薦紀錄，比對「推薦時價格」與「當前最新市價」，分析投資回報率 (ROI)。
2. 計算並總結高層級績效數據：勝率 (Win Rate)、平均回報率 (Average Return)、跑贏大盤基準的幅度。
3. 對於表現亮眼（成功）與虧損超標（失敗）的標的，進行深度「決策剖析與自我反思」：
   - 成功的推薦：是因為大盤勢頭好？還是真的抓到了高價值催化劑？
   - 失敗的推薦：是停損設定太寬？估值倍數給太慷慨？還是低估了總經政策的殺傷力？
4. 撰寫出具體且可執行的**「本期策略自我修正指引 (Self-Correction Directives)」**。這段指引將直接注入給本期的「基本面分析師」與「板塊分析師」，命令它們在本週挑選新標的時收緊條件、調整停損位或避開特定風險。

請務必使用「繁體中文（台灣習慣財經用語）」撰寫，產出一份真實、毫不掩飾缺點的「歷史推薦回測與自我修正報告」。

輸出格式請依照以下 Markdown 結構：
### 🔄 歷史投資決策回測與自主反思看板
* **歷史決策績效統計 (Scorecard)**：
  - 已結案標的累計勝率：[例如：66.7%]
  - 已結案標的平均回報率：[例如：+8.3%]
  - 跑贏大盤基準表現：[例如：累計超額回報 +3.2%]
* **當前在倉追蹤標的即時損益表**：
  - *代碼/名稱*：推薦日期 [YYYY-MM-DD] | 推薦價 [xxx] | 現價 [xxx] | 當前損益 **[+xx.x% 或 -xx.x%]**。狀態：[追蹤中 / 已達標獲利出場 / 已跌破停損出場]
* **深度反思：我們做對了什麼？做錯了什麼？**：[深度解讀前期判斷與真實市場走勢的偏差，切忌流水帳，要找出分析邏輯上的漏洞]
* **🚀 寫給本週分析師的「自我修正調整令」**：[寫給 Market & Fundamental Agents 的具體反饋指令。例如：「本週基本面分析師在對美股科技股估值時，若 PEG 超過 1.5 一律降級為 Hold，且必須將停損防線向上收緊 2%，以因應通膨反彈風險」]
"""

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
                roi_val = rec.get('performance', 0)
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
        import json
        import core.db_manager as db
        from core.agents.base_agent import BaseAgent
        
        print("[*] [自適應 Prompt 演化] 正在啟動自適應 Prompt 演化引擎...")
        try:
            # 1. 獲取 FundamentalAgent 的最近已平倉交易推論日誌與 ROI
            agent_name = "FundamentalAgent"
            logs = db.get_recent_inference_logs_with_roi(agent_name, limit=10)
            
            # 2. 進行冷啟動防禦檢查 (Cold-Start Defense Check)
            if len(logs) < 2:
                print(f"[*] [自適應 Prompt 演化] 目前已平倉交易記錄為 {len(logs)} 筆，少於演化閾值 2 筆，跳過本次 Prompt 演化。")
                return
                
            print(f"[*] [自適應 Prompt 演化] 偵測到 {len(logs)} 筆具備真實投資績效 (ROI) 的交易紀錄，開始進行多維度效能分析...")
            
            # 3. 獲取當前活躍的系統提示詞
            active_prompt_data = db.get_active_prompt(agent_name)
            if not active_prompt_data:
                print("[!] [自適應 Prompt 演化] 無法自資料庫獲取當前活躍的 Prompt，跳過演化。")
                return
                
            curr_prompt = active_prompt_data["system_prompt"]
            curr_version = active_prompt_data["version"]
            
            # 4. 區分成功與失敗案例以進行對比學習
            success_cases = []
            failure_cases = []
            for log in logs:
                case_desc = {
                    "ticker": log["ticker"],
                    "roi": f"{log['roi'] * 100:.2f}%",
                    "recommendation_input_context": log["input_prompt"],
                    "recommendation_response": log["output_response"]
                }
                if log["roi"] > 0:
                    success_cases.append(case_desc)
                else:
                    failure_cases.append(case_desc)
                    
            print(f"[*] [自適應 Prompt 演化] 成功交易案例：{len(success_cases)} 筆 | 失敗交易案例：{len(failure_cases)} 筆")
            
            # 5. 調度 Meta-Agent 作為 Prompt 優化工程師
            print("[*] [自適應 Prompt 演化] 正在初始化 MetaPromptOptimizer 代理人進行對比反思...")
            
            meta_instruction = (
                "你是一位頂尖的金融大模型 Prompt 工程師與量化投資策略專家。你的任務是分析 FundamentalAgent 過去的分析案例（成功與失敗交易），"
                "找出其估值偏差、預測漏洞或思維盲點，並優化其 system_prompt。請只輸出新的、優化後的完整 system_prompt，"
                "絕對不要包含 any 額外的 Markdown 包裹標記（如 ```markdown 或 ```）或前言、解釋文字。你的輸出必須能夠直接做為 system_prompt 使用。\n"
                "你必須保留原 prompt 的核心結構與功能（如獲利能力、估值、技術位階、ATR 停損停利規則、輸出 Markdown 格式等），並將本週最新的修正與演化方針以增量方式融入其中。"
            )
            
            meta_optimizer = BaseAgent(
                name="MetaPromptOptimizer",
                role="Meta-Prompt Optimizer",
                system_instruction=meta_instruction
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
2. 進一步嚴格化那些導致失敗案例的財務健康度指標。

優化後，請直接回覆優化後的「完整 system_prompt 內容」，絕對不要包含任何包裹用的 ``` 或 markdown 標籤，也不要有前言或解釋。
"""
            new_prompt = meta_optimizer.run(evolution_prompt)
            if not new_prompt or len(new_prompt.strip()) < 500:
                print("[!] [自適應 Prompt 演化] 大模型輸出的新 Prompt 長度過短，可能生成失敗。放棄本次演化。")
                return
                
            # 解析版本號
            try:
                major, minor, patch = map(int, curr_version.replace("v", "").split("."))
                patch += 1
                new_version = f"v{major}.{minor}.{patch}"
            except Exception:
                new_version = "v1.0.1"
                
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
            
        except Exception as e:
            print(f"[!] [自適應 Prompt 演化] Prompt 演化中途出錯: {e}")
            raise e

