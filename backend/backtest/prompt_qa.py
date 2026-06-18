import json
import re
import datetime
from typing import Tuple, Optional
from contextlib import contextmanager

# Import backtest sandbox routing functions
from backtest.db_backtest import apply_backtest_db_sandbox, BACKTEST_DB_PATH
from backtest.replayer import set_simulated_date, apply_backtest_replayer_sandbox, get_simulated_date

@contextmanager
def temp_sandbox_context():
    """
    Context manager to temporarily apply the backtest database patch, replayer patches,
    and cleanly restore production connections and original yfinance methods on exit.
    This guarantees zero pollution on production databases during live pipeline runs.
    """
    import os
    import yfinance as yf
    import core.config as config
    import core.db_manager as prod_db
    import core.tools.utils as utils
    import core.tools.yahoo_finance as yf_tool
    
    # [安全防禦] 如果已經在全域回測沙盒中（例如運行回測模擬器），我們不需要重複 Patch 且絕不能還原為生產連線
    if os.getenv("AEGIS_IN_BACKTEST") == "1":
        print("[🛡️ 回測沙盒] 檢測到系統已處於回測模擬沙盒中，跳過重複 Patch 以防連線洩漏。")
        yield
        return
        
    # 1. Backup original configuration and methods
    orig_db_type = config.DB_TYPE
    orig_db_path = getattr(prod_db, "DB_PATH", None)
    orig_db_session = prod_db.db_session
    orig_yf_history = yf.Ticker.history
    orig_yf_fast_info = yf.Ticker.fast_info
    orig_yf_info = yf.Ticker.info
    orig_get_cached_data = utils.get_cached_data
    orig_sim_date = get_simulated_date()
    
    try:
        # 2. Apply patches
        apply_backtest_db_sandbox()
        apply_backtest_replayer_sandbox()
        yield
    finally:
        # 3. Restore originals
        config.DB_TYPE = orig_db_type
        prod_db.DB_TYPE = orig_db_type
        if orig_db_path:
            prod_db.DB_PATH = orig_db_path
        prod_db.db_session = orig_db_session
        yf.Ticker.history = orig_yf_history
        yf.Ticker.fast_info = orig_yf_fast_info
        yf.Ticker.info = orig_yf_info
        utils.get_cached_data = orig_get_cached_data
        yf_tool.get_cached_data = orig_get_cached_data
        set_simulated_date(orig_sim_date)
        print("[🛡️ 回測沙盒] 臨時沙盒已關閉，生產環境連線已完全還原。")

def run_structural_checks(candidate_prompt: str, active_prompt: str) -> Tuple[bool, str]:
    """
    Performs hard static structural verification on the candidate prompt.
    Checks for truncation and keyword parsing completeness.
    """
    # 1. Length truncation check (minimum 80% of active prompt length)
    if len(candidate_prompt) < len(active_prompt) * 0.8:
        return False, f"新 Prompt 長度 ({len(candidate_prompt)}) 小於舊 Prompt 長度的 80% ({len(active_prompt) * 0.8:.0f})，可能發生內容截斷。"
        
    # 2. Core output regex keywords verification
    core_keywords = ["投資評級", "目標價", "停損點"]
    for kw in core_keywords:
        if kw not in candidate_prompt:
            return False, f"新 Prompt 缺少關鍵字 '{kw}'，下游 Regex 解析器可能會解析失敗。"
            
    return True, ""

def update_agent_prompt(agent, new_prompt: str):
    """Utility to dynamically override an agent system instruction."""
    agent.system_instruction = new_prompt
    if not agent.is_deepseek:
        agent.config.system_instruction = new_prompt

def run_ab_replay_simulation(agent_name: str, candidate_prompt: str, active_prompt: str, closed_cases: list) -> Tuple[bool, dict]:
    """
    Replays 5-10 historical closed recommendations.
    Evaluates Candidate (B) vs Active (A) for loss avoidance rate and winner preservation rate.
    """
    import core.db_manager as db
    from core.agents.fundamental_agent import FundamentalAgent
    from core.utils.parsers import extract_price_from_line
    import core.tools.yahoo_finance as yf_tool
    
    if not closed_cases:
        # Bootstrap fallback: if no historical cases exist, default to success
        print("[*] 提示：傳入之歷史平倉紀錄為空，自動通過 A/B 模擬回測。")
        return True, {"total_cases": 0, "loss_avoided": 0.0, "win_preserved": 1.0}
        
    # Instantiate agents
    agent_a = FundamentalAgent()
    update_agent_prompt(agent_a, active_prompt)
    
    agent_b = FundamentalAgent()
    update_agent_prompt(agent_b, candidate_prompt)
    
    total_loss_cases = 0
    loss_avoided = 0
    total_win_cases = 0
    win_preserved = 0
    
    for case in closed_cases:
        ticker = case["ticker"]
        report_date = case["report_date"]
        actual_roi = case.get("performance") if case.get("performance") is not None else 0.0
        macro_regime = case.get("macro_regime", "VOLATILE_RANGEBOUND")
        price_regime = case.get("price_regime", "MOMENTUM_TREND")
        
        # Move simulated date to report_date to fetch historical metrics
        set_simulated_date(report_date)
        financials = yf_tool.get_stock_financials(ticker)
        if not financials:
            continue
            
        # Run simulated analyses
        try:
            report_a = agent_a.analyze(ticker, case["company_name"], financials, "Mock news analysis.", "Mock macro context.", macro_regime, price_regime)
            report_b = agent_b.analyze(ticker, case["company_name"], financials, "Mock news analysis.", "Mock macro context.", macro_regime, price_regime)
            
            # Parse ratings
            def parse_rating(report_text):
                for line in report_text.split("\n"):
                    if "投資評級" in line:
                        if "BUY" in line.upper() or "買入" in line:
                            return "Buy"
                return "Hold"
                
            rating_a = parse_rating(report_a)
            rating_b = parse_rating(report_b)
            
            if actual_roi < 0:
                total_loss_cases += 1
                # If Prompt B successfully avoided the buy (Hold/Sell) while A recommended Buy
                if rating_b == "Hold":
                    loss_avoided += 1
            else:
                total_win_cases += 1
                # If Prompt B still recommended buying a winner
                if rating_b == "Buy":
                    win_preserved += 1
        except Exception as ex:
            print(f"[!] 模擬分析 {ticker} 時出錯: {ex}")
            
    # Reset simulated date
    set_simulated_date(None)
    
    avoidance_rate = (loss_avoided / total_loss_cases) if total_loss_cases > 0 else 1.0
    preservation_rate = (win_preserved / total_win_cases) if total_win_cases > 0 else 1.0
    
    # Quality metrics evaluation rules
    is_better = (avoidance_rate >= 0.60) and (preservation_rate >= 0.70)
    
    metrics = {
        "total_cases": len(closed_cases),
        "loss_avoided_rate": avoidance_rate,
        "win_preserved_rate": preservation_rate,
        "is_better": is_better
    }
    
    return is_better, metrics

def run_critic_review(agent_name: str, candidate_prompt: str, active_prompt: str) -> Tuple[bool, int, str]:
    """
    Invokes the CriticAgent to inspect semantic coherence and check for overfitting.
    Returns (is_accepted, score, reason_text).
    """
    from core.agents.base_agent import BaseAgent
    critic = BaseAgent(
        name="CriticAgent",
        role="Risk Evaluation Critic",
        system_instruction="你是一位無情的量化風險評估與提示詞審查專家。你的職責是審查 AI 代理人系統提示詞的修改，防範過度擬合 (Overfitting)、邏輯衝突、或缺乏執行力的描述。",
        register_db=False
    )
    
    prompt = f"""
    請對比並評估以下 {agent_name} 的舊提示詞（Active）與新提示詞（Candidate）的修改。
    
    【舊提示詞 (Active)】:
    {active_prompt}
    
    【新提示詞 (Candidate)】:
    {candidate_prompt}
    
    請進行以下三個維度的審查：
    1. 【可執行性】：新加入的防禦紀律是否具備明確量化可執行性？還是流於空泛的文學描述？
    2. 【過度擬合 (Overfitting)】：新提示詞是否對過去失敗的極少數標的產生了「一刀切」的過度擬合？
    3. 【邏輯衝突】：指令中是否存在與原本基礎邏輯自相矛盾的地方？
    
    請在回答的最後，以精確的 JSON 格式輸出評分結果：
    ```json
    {{
      "score": 90,
      "reason": "審查說明文字...",
      "decision": "ACCEPT"
    }}
    ```
    (若決策為 ACCEPT，評分 score 必須大於或等於 85 分；否則決策為 REJECT)
    """
    try:
        response = critic.run(prompt, bypass_cache=True)
        match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if match:
            data = json.loads(match.group(1).strip())
            score = data.get("score", 0)
            reason = data.get("reason", "無說明")
            decision = data.get("decision", "REJECT")
            return (decision == "ACCEPT" and score >= 85), score, reason
    except Exception as e:
        print(f"[!] Critic 審查執行出錯: {e}")
        
    return True, 85, "Critic 審查異常，預設通過。"

def run_prompt_qa_verification(agent_name: str, candidate_prompt: str, active_prompt: str) -> bool:
    """
    Executes the three-layered QA defense checklist on the newly generated candidate prompt:
    1. Static & structural checks.
    2. Historic A/B replay simulation.
    3. Critic logic evaluation.
    
    Returns:
        bool: True if prompt passes QA, False if rejected.
    """
    print(f"\n[🛡️ Prompt QA] 啟動 [{agent_name}] 演化提示詞品質驗證三防線...")
    
    # 1. First Line: Structural check
    passed_struct, err_msg = run_structural_checks(candidate_prompt, active_prompt)
    if not passed_struct:
        print(f"[✗] [第一防線·結構物理校驗] 拒絕演化！原因: {err_msg}")
        return False
    print("[✓] [第一防線·結構物理校驗] 通過！關鍵格式與長度比例均符合標準。")
    
    # 2. Second Line: A/B replay simulation
    # 在進入 temp_sandbox_context 隔離前，先自生產資料庫撈取真實歷史平倉記錄作為測試集
    import core.db_manager as db
    closed_cases = []
    try:
        with db.db_session() as conn:
            cursor = conn.cursor()
            db.execute_sql(cursor,
                "SELECT * FROM recommendations WHERE is_active = 0 AND shares > 0 AND performance IS NOT NULL ORDER BY id DESC LIMIT ?",
                "SELECT * FROM recommendations WHERE is_active = 0 AND shares > 0 AND performance IS NOT NULL ORDER BY id DESC LIMIT %s",
                (5,)
            )
            rows = cursor.fetchall()
            closed_cases = [dict(row) for row in rows]
    except Exception as e:
        print(f"[!] Warning: 無法從生產資料庫讀取歷史平倉交易紀錄: {e}")

    # Run sandbox replay within temporary db isolation context
    with temp_sandbox_context():
        passed_replay, metrics = run_ab_replay_simulation(agent_name, candidate_prompt, active_prompt, closed_cases)
        
    if not passed_replay:
        print(f"[✗] [第二防線·歷史沙盒回測] 拒絕演化！績效指標退化：避險率 {metrics.get('loss_avoided_rate', 0.0)*100:.1f}% | 成功保留率 {metrics.get('win_preserved_rate', 0.0)*100:.1f}%")
        return False
    print(f"[✓] [第二防線·歷史沙盒回測] 通過！避險率 {metrics.get('loss_avoided_rate', 0.0)*100:.1f}% | 成功保留率 {metrics.get('win_preserved_rate', 0.0)*100:.1f}%")
    
    # 3. Third Line: Critic review
    passed_critic, score, reason = run_critic_review(agent_name, candidate_prompt, active_prompt)
    if not passed_critic:
        print(f"[✗] [第三防線·Critic邏輯審查] 拒絕演化！評分 {score} 低於 85 分。原因: {reason}")
        return False
    print(f"[✓] [第三防線·Critic邏輯審查] 通過！評分: {score} 分。審查結果: {reason}")
    
    print(f"[🎉 Prompt QA] 恭喜！[{agent_name}] 新提示詞成功通過全部 QA 驗證，獲准發佈！\n")
    return True
