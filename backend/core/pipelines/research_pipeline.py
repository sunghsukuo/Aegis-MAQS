import time
import re
import os
import sys
import json
import markdown
from datetime import datetime
from pathlib import Path

# Import DB and config values
from core.config import (
    REGIONS, REPORTS_DIR, DEFAULT_REPORTS_DIR, 
    MAX_SECTORS_PER_REGION, MAX_STOCKS_PER_REGION, 
    DB_TYPE, REPORT_LANGUAGE
)
import core.db_manager as db
import core.tools.yahoo_finance as yf_tool
import core.tools.web_search as search_tool
from check_portfolio import run_portfolio_check

# Import AI Agents & tools
from core.agents.base_agent import BaseAgent
from core.agents.macro_agent import MacroAgent
from core.agents.market_agent import MarketAgent
from core.agents.news_agent import NewsAgent
from core.agents.fundamental_agent import FundamentalAgent
from core.agents.reflection_agent import ReflectionAgent
from core.agents.writer_agent import WriterAgent
from core.tools.valuation_engine import ValuationEngine
from core.utils.parsers import extract_price_from_line, extract_range_from_line
from core.tools.utils import get_cached_data

def print_info(msg): print(f"\033[96m[*] {msg}\033[0m")
def print_warning(msg): print(f"\033[93m[!] {msg}\033[0m")
def print_success(msg): print(f"\033[93m[✓] {msg}\033[0m")
def print_error(msg): print(f"\033[91m[✗] {msg}\033[0m")


def research_and_track_asset(
    ticker: str,
    company_name: str,
    region_code: str,
    macro_regime: str,
    macro_report: str,
    reflection_directives: str,
    report_date: str,
    save_to_db: bool = True,
    is_weekly_pipeline: bool = True,
    custom_recommend_reason: str = None,
    price_regime: str = None,
    source_track: str = None
) -> dict:
    """
    統一「單一標的深度分析與模擬下單/追蹤管線」。
    負責個股消息抓取、NewsAgent 輿情分析、財務爬蟲、ValuationEngine 估值、
    FundamentalAgent 分析、Regex 目標價/停損價/評級解析、BudgetAgent 預算配置、
    以及資料庫寫入 (recommendations 與 inference_logs)。
    """
    print_info(f"   - 正在檢索 {ticker} 的個股消息與社群輿情...")
    stock_news = search_tool.get_stock_news(ticker, max_items=5)
    
    print_info("   - 消息面分析中...")
    news_agent = NewsAgent()
    news_analysis = news_agent.analyze(ticker, company_name, stock_news)
    time.sleep(2)
    
    print_info(f"   - 正在抓取 {ticker} 的量化財務指標與波動率參數...")
    financials = yf_tool.get_stock_financials(ticker)
    if not financials:
        print_warning(f"   - 無法取得 {ticker} 的財務指標，跳過分析。")
        return None
        
    curr_price = financials.get("current_price", 0.0)
    if curr_price == 0.0:
        print_warning(f"   - 無法獲取 {ticker} 的即時交易市價，跳過分析。")
        return None
        
    print_info("   - 啟動投行量化估值模型 (Equity Valuation Engine)...")
    try:
        valuation_report = ValuationEngine.run_valuation(ticker, financials)
    except Exception as val_err:
        valuation_report = f"量化估值模型執行出錯: {val_err}"

    print_info("   - 基本面估值與決策修正分析中...")
    fundamental_agent = FundamentalAgent()
    combined_context = f"""
【當前巨觀經濟環境】：
{macro_report}

【前期歷史回測之自我修正指令】：
{reflection_directives}

【投行級別量化估值模型報告 (Equity Valuation Engine)】:
{valuation_report}
"""
    stock_report = fundamental_agent.analyze(
        ticker, company_name, financials, news_analysis, combined_context,
        macro_regime=macro_regime, price_regime=price_regime
    )
    time.sleep(2)
    
    # 預先計算系統建議波動停損利價作為解析時的對比參考點，避免四捨五入誤差將買入價誤判為目標價
    from core.risk.risk_manager import calculate_risk_boundaries
    atr_14 = financials.get("atr_14")
    beta = financials.get("beta", 1.0)
    risk_res = calculate_risk_boundaries(curr_price, atr_14, beta, macro_regime=macro_regime)
    suggested_tp = risk_res["suggested_tp"]
    suggested_sl = risk_res["suggested_sl"]

    # 解析輸出參數
    target_p = suggested_tp
    stop_l = suggested_sl
    rating = "Hold"
    suggested_weight = None
    
    lines = stock_report.split("\n")
    for line in lines:
        if "目標價" in line or "中線目標價" in line:
            parsed_val = extract_price_from_line(line, curr_price, is_target=True, reference_price=suggested_tp)
            if parsed_val > 0.0: target_p = parsed_val
        elif "停損點" in line or "防禦停損點" in line:
            parsed_val = extract_price_from_line(line, curr_price, is_target=False, reference_price=suggested_sl)
            if parsed_val > 0.0: stop_l = parsed_val
        elif "投資評級" in line:
            line_upper = line.upper()
            if "STRONG BUY" in line_upper or "強烈買入" in line_upper:
                rating = "Strong Buy"
            elif "SELL" in line_upper or "賣出" in line_upper or "避開" in line_upper or "避免" in line_upper or "不建議買入" in line_upper:
                rating = "Sell"
            elif "HOLD" in line_upper or "持有" in line_upper or "NEUTRAL" in line_upper or "觀望" in line_upper:
                rating = "Hold"
            elif "BUY" in line_upper or "買入" in line_upper:
                rating = "Buy"

        elif "建議持倉權重" in line or "持倉權重" in line or "建議權重" in line:
            weight_match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
            if weight_match:
                try:
                    suggested_weight = float(weight_match.group(1)) / 100.0
                except ValueError:
                    pass
                    
    # 🕵️‍♂️ 決策防線聯動：降級防守，禁止封殺
    # 若標的來源於「板塊動能/防禦 Beta (趨勢/回歸)」或「前瞻主題」選股軌道（即資金與趨勢驅動型），
    # 且大模型評級為 Sell/Avoid（避開），則強制將其評級提升至 "Hold"，分配 5% 的極輕倉位以防「定性恐高」封殺強勢股行情。
    is_trend_or_theme = False
    if source_track:
        s_track_upper = source_track.upper()
        if "動能" in source_track or "防禦" in source_track or "主題" in source_track or "BETA" in s_track_upper or "THEMATIC" in s_track_upper:
            is_trend_or_theme = True
            
    if rating == "Sell" and is_trend_or_theme:
        rating = "Hold"
        override_msg = " [⚠️ 決策防線聯動：因該標的屬資金流動能/前瞻主題驅動，為避免大模型基本面定性恐高而完全封殺強勢股，啟動「降級防守」模式，將評級修正為 Hold 並配以 5% 的防守性輕倉，同時收緊移動止損。]"
        custom_recommend_reason = (custom_recommend_reason or f"Aegis-MAQS 自動分析。當前大盤狀態: {macro_regime}。") + override_msg
        print(f"\033[93m[🛡️ 決策防線聯動] 偵測到 {ticker} 屬動能/主題型標的且被評為 Sell，啟動「降級防守」提升評級為 Hold，配以 5% 部位。\033[0m")

    # Option A: Quant decides, LLM adjusts weight (Hold is allocated a starter 5% weight instead of being blocked)
    if rating == "Hold":
        if suggested_weight is not None:
            suggested_weight = min(suggested_weight, 0.05)
        else:
            suggested_weight = 0.05
    elif rating == "Strong Buy":
        if suggested_weight is None: suggested_weight = 0.25
    elif rating == "Buy":
        if suggested_weight is None: suggested_weight = 0.15
    else: # Sell or Avoid (Only Track 2 or purely fundamental stocks can be fully vetoed here)
        suggested_weight = 0.0

    invested_amount = 0.0
    shares = 0.0
    rec_id = None
    
    # 判斷是否需要進行寫入資料庫
    should_save = False
    if save_to_db:
        if is_weekly_pipeline:
            should_save = True
        elif rating in ["Buy", "Strong Buy", "Hold"]:
            should_save = True
            
    if should_save:
        if rating in ["Buy", "Strong Buy", "Hold"]:
            from core.agents.budget_agent import BudgetAgent
            budget_agent = BudgetAgent()
            invested_amount, shares = budget_agent.allocate_budget(ticker, region_code, curr_price, custom_weight=suggested_weight, report_date=report_date)
        
        reason = custom_recommend_reason or f"Aegis-MAQS 自動分析。當前大盤狀態: {macro_regime}。"
        try:
            rec_id = db.save_recommendation(
                report_date=report_date,
                region=region_code,
                ticker=ticker,
                company_name=company_name,
                recommend_price=curr_price,
                recommend_reason=reason,
                target_price=target_p,
                stop_loss=stop_l,
                rating=rating,
                invested_amount=invested_amount,
                shares=shares,
                macro_regime=macro_regime,
                price_regime=price_regime,
                source_track=source_track
            )
            
            if invested_amount > 0.0:
                budget_agent.record_purchase(rec_id, ticker, region_code, curr_price, invested_amount, shares)
                
            # 儲存推論日誌
            try:
                db.save_agent_inference_log(
                    rec_id=rec_id,
                    agent_name="FundamentalAgent",
                    ticker=ticker,
                    input_prompt=fundamental_agent.last_prompt,
                    output_response=stock_report,
                    prompt_version=fundamental_agent.prompt_version,
                    report_date=report_date
                )
                db.save_agent_inference_log(
                    rec_id=rec_id,
                    agent_name="NewsAgent",
                    ticker=ticker,
                    input_prompt=news_agent.last_prompt,
                    output_response=news_analysis,
                    prompt_version=news_agent.prompt_version,
                    report_date=report_date
                )
            except Exception as log_ex:
                print(f"[!] Warning: 記錄 Fundamental/News 推論日誌失敗: {log_ex}")
        except Exception as db_ex:
            print_warning(f"寫入推薦數據庫時發生輕微解析異常: {db_ex}")
            
    return {
        "stock_report": stock_report,
        "financials": financials,
        "valuation_report": valuation_report,
        "news_analysis": news_analysis,
        "rating": rating,
        "target_price": target_p,
        "stop_loss": stop_l,
        "suggested_weight": suggested_weight,
        "invested_amount": invested_amount,
        "shares": shares,
        "rec_id": rec_id
    }

def run_regional_reflection(region_code: str, report_date: str, state: dict = None) -> str:
    """
    Gathers active and closed recommendations specific to a region,
    measures them against regional benchmark index, and triggers ReflectionAgent
    to produce region-specific corrective directives.
    """
    print_info(f"[{region_code}] 正在啟動區域專屬歷史回測與決策反思...")
    
    # Extract price_regime and macro_regime from state with fallbacks
    price_regime = None
    macro_regime = None
    if state and "analysis" in state and region_code in state["analysis"]:
        price_regime = state["analysis"][region_code].get("price_regime")
        macro_regime = state["analysis"][region_code].get("macro_regime")
        
    if not price_regime:
        try:
            from core.regime.price_regime import detect_region as detect_price_regime
            price_info = detect_price_regime(region_code)
            price_regime = price_info.get("regime", "MOMENTUM_TREND")
        except Exception:
            price_regime = "MOMENTUM_TREND"
            
    if not macro_regime:
        try:
            from core.regime.registry import get_macro_regime
            macro_regime_info = get_macro_regime(region_code)
            macro_regime = macro_regime_info.get("regime", "BULL_RISK_ON") if isinstance(macro_regime_info, dict) else macro_regime_info
        except Exception:
            macro_regime = "BULL_RISK_ON"
            
    # 1. Get region-specific benchmark performance
    benchmark = yf_tool.get_benchmark_performance(region_code)
    
    # 2. Get region-specific active recommendations
    active_recs = db.get_active_recommendations(region=region_code)
    active_recs_patched = []
    for r in active_recs:
        r_dict = dict(r)
        r_dict["current_price"] = yf_tool.get_stock_price(r_dict["ticker"])
        active_recs_patched.append(r_dict)
        
    # 3. Get region-specific closed recommendations
    historical_stats = db.get_historical_performance()
    closed_recs = historical_stats.get("closed", [])
    closed_recs_filtered = [r for r in closed_recs if r.get("region") == region_code]
    
    closed_recs_patched = []
    for r in closed_recs_filtered:
        r_dict = dict(r)
        r_dict["current_price"] = r_dict.get("close_price", 0.0)
        closed_recs_patched.append(r_dict)
        
    # Merge active and closed (up to last 10)
    recent_recs = active_recs_patched + closed_recs_patched[:10]
    
    if not recent_recs:
        print_info(f"[{region_code}] 目前尚無歷史持股紀錄，跳過本週自我反思。")
        return "（本區域目前尚無歷史交易紀錄，暫無自我反思修正指令。請採用標準安全邊際進行基本面估值。）"
        
    # 4. Run Reflection Agent
    reflection_agent = ReflectionAgent()
    reflection_report = reflection_agent.analyze(
        recent_recs,
        benchmark,
        price_regime=price_regime,
        macro_regime=macro_regime
    )
    
    # [Prompt Evolution Integration] Log ReflectionAgent's inference
    try:
        db.save_agent_inference_log(
            rec_id=None,
            agent_name="ReflectionAgent",
            ticker=None,
            input_prompt=reflection_agent.last_prompt,
            output_response=reflection_report,
            prompt_version=reflection_agent.prompt_version,
            report_date=report_date
        )
    except Exception as log_ex:
        print(f"[!] Warning: 記錄 ReflectionAgent 推論日誌失敗: {log_ex}")
        
    print_success(f"[{region_code}] 區域專屬決策反思分析完成！")
    return reflection_report

def analyze_macro_regime(region_code: str, price_info: dict = None, dry_run: bool = False, report_date: str = None) -> tuple:
    """
    Executes Macroeconomic Analysis via MacroAgent, logs the inference (unless dry_run),
    and returns (macro_report, macro_regime).
    """
    region_name = REGIONS[region_code]["name"]
    # 1. Get Benchmark Performance & Multi-dimensional Macro Indicators
    macro_indicators = yf_tool.get_macro_indicators(region_code)
    benchmark_data = macro_indicators.get("benchmark", {})
    
    # 2. Get Macroeconomic News
    macro_news = search_tool.get_macro_news(region_code, max_items=5)
    
    # 3. Run Macro Agent
    print_info(f"[{region_name}] 正在執行總體經濟分析...")
    macro_agent = MacroAgent()
    raw_macro_report = macro_agent.analyze(region_name, benchmark_data, macro_news, price_info=price_info, macro_indicators=macro_indicators)
    
    # [Prompt Evolution Integration] Log MacroAgent's inference
    if not dry_run:
        try:
            db.save_agent_inference_log(
                rec_id=None,
                agent_name="MacroAgent",
                ticker=None,
                input_prompt=macro_agent.last_prompt,
                output_response=raw_macro_report,
                prompt_version=macro_agent.prompt_version,
                report_date=report_date
            )
        except Exception as log_ex:
            print(f"[!] Warning: 記錄 MacroAgent 推論日誌失敗: {log_ex}")
        
    time.sleep(3)  # Respect free tier rate limits (15 RPM)
    
    # Parse market regime from macro report
    regime_match = re.search(r"\[MACRO_REGIME:\s*(BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]", raw_macro_report)
    macro_regime = regime_match.group(1) if regime_match else "BULL_RISK_ON"
    print_success(f"[{region_name}] 偵測到宏觀市場狀態標籤：{macro_regime}")
    
    # Clean the raw tag from macro_report so it doesn't show in the final human-readable report
    macro_report = re.sub(r"\[MACRO_REGIME:\s*(BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]\s*", "", raw_macro_report)
    
    return macro_report, macro_regime


def run_liquidity_analysis(region_code: str, report_date: str, dry_run: bool = False) -> tuple:
    """
    Executes Macro Liquidity and Capital Flow Analysis via LiquidityScoutAgent,
    logs the inference in the database, and returns (liquidity_report, liquidity_regime).
    Supports time-travel backtesting by automatically checking simulated date.
    """
    region_name = REGIONS[region_code]["name"]
    
    # 1. Determine if we are in backtest mode to prevent lookahead bias
    is_backtest_mode = False
    query_date = report_date
    try:
        from backtest.replayer import get_simulated_date
        sim_date = get_simulated_date()
        if sim_date:
            is_backtest_mode = True
            query_date = sim_date
    except Exception:
        pass
        
    # 2. Load quantitative liquidity state
    from core.tools.liquidity_loader import get_liquidity_state
    liquidity_state = get_liquidity_state(query_date, is_backtest=is_backtest_mode)
    
    # 3. Run Liquidity Scout Agent
    print_info(f"[{region_name}] 正在執行全球與區域流動性偵察分析...")
    from core.agents.liquidity_agent import LiquidityScoutAgent
    agent = LiquidityScoutAgent()
    raw_report = agent.analyze(region_name, liquidity_state)
    
    # 4. Log the inference to database
    if not dry_run:
        try:
            db.save_agent_inference_log(
                rec_id=None,
                agent_name="LiquidityScoutAgent",
                ticker=None,
                input_prompt=agent.last_prompt,
                output_response=raw_report,
                prompt_version=agent.prompt_version,
                report_date=report_date
            )
        except Exception as log_ex:
            print(f"[!] Warning: 記錄 LiquidityScoutAgent 推論日誌失敗: {log_ex}")
            
    time.sleep(3)  # Respect API rate limits
    
    # 5. Parse liquidity regime from report
    import re
    regime_match = re.search(r"\[LIQUIDITY_REGIME:\s*(EXPANSION|NEUTRAL|CONTRACTION)\]", raw_report)
    liquidity_regime = regime_match.group(1) if regime_match else "NEUTRAL"
    print_success(f"[{region_name}] 偵測到流動性狀態標籤：{liquidity_regime}")
    
    # Clean the raw tag from report so it doesn't show in the final human-readable report
    liquidity_report = re.sub(r"\[LIQUIDITY_REGIME:\s*(EXPANSION|NEUTRAL|CONTRACTION)\]\s*", "", raw_report)
    
    return liquidity_report, liquidity_regime

def run_report_pipeline(args, report_date, regions_list, timestamp_suffix, daily_reports_dir):
    print_success("==================================================")
    print_success("🚀 歡迎使用：投資研究代理人自動化研報系統 (CLI)")
    print_success(f"執行日期：{report_date} | 目標市場：{', '.join(regions_list)}")
    phase = getattr(args, "phase", None)
    if phase:
        print_success(f"執行單一階段：{phase}")
    print_success("==================================================")
    
    existing_report = db.get_report_by_date(report_date)
    existing_recs_count = 0
    with db.db_session() as conn:
        cursor = conn.cursor()
        db.execute_sql(
            cursor,
            "SELECT COUNT(*) FROM recommendations WHERE report_date = ?",
            "SELECT COUNT(*) FROM recommendations WHERE report_date = %s",
            (report_date,)
        )
        row = cursor.fetchone()
        if row:
            existing_recs_count = row["COUNT(*)"] if isinstance(row, dict) else row[0]
            
    # Safety warnings and database rollbacks only apply to full runs or the stock analysis phase
    is_writing_phase = (not phase) or (phase == "analyze_stocks")
    
    if is_writing_phase and (existing_report or existing_recs_count > 0) and not args.force:
        print_warning(f"偵測到資料庫中已存在【{report_date}】的投資報告或推薦記錄。")
        print_warning("使用 --force 參數可強制重新運行，系統將自動清理舊資料以確保資料庫一致性。")
        sys.exit(0)
        
    if is_writing_phase and (args.force or existing_recs_count > 0 or existing_report):
        print_info(f"正在自動清理與還原【{report_date}】的舊有報告與交易記錄，確保資料庫一致性...")
        db.rollback_reports_and_recommendations(report_date)
        
        # Only delete state file if running the entire pipeline (not a single phase)
        if not phase:
            from core.config import CACHE_DIR
            state_file = CACHE_DIR / f"pipeline_state_{report_date}.json"
            if state_file.exists():
                try:
                    state_file.unlink()
                    print_info(f"已清理舊有的快取狀態檔案: {state_file}")
                except Exception as e:
                    print_warning(f"清理快取狀態檔案失敗: {e}")

    state = load_pipeline_state(report_date)
    init_pipeline_state_dates(state)

    phases_to_run = [
        "portfolio_check",
        "analyze_macro",
        "analyze_sectors",
        "portfolio_reflect",
        "screen_targets",
        "analyze_stocks",
        "weekly_report",
        "screener_report",
        "notify",
        "prompt_evolve"
    ]
    
    if phase:
        if phase not in phases_to_run:
            print_error(f"無效的階段名稱：{phase}")
            sys.exit(1)
        active_phases = [phase]
    else:
        active_phases = phases_to_run

    for p in active_phases:
        if p == "portfolio_check":
            run_portfolio_check_phase(report_date, regions_list)
            
        elif p == "portfolio_reflect":
            run_reflection_phase(regions_list, report_date, state)
            save_pipeline_state(report_date, state)
            
        elif p == "analyze_macro":
            run_analyze_macro_phase(regions_list, report_date, state)
            save_pipeline_state(report_date, state)
            
        elif p == "analyze_sectors":
            run_analyze_sectors_phase(regions_list, report_date, state)
            save_pipeline_state(report_date, state)
            
        elif p == "screen_targets":
            run_screen_targets_phase(regions_list, report_date, state)
            save_pipeline_state(report_date, state)
            
        elif p == "analyze_stocks":
            run_analyze_stocks_phase(regions_list, report_date, state)
            save_pipeline_state(report_date, state)
            
        elif p == "weekly_report":
            run_weekly_report_phase(regions_list, report_date, timestamp_suffix, daily_reports_dir, state)
            save_pipeline_state(report_date, state)
            
        elif p == "screener_report":
            run_screener_report_phase(regions_list, report_date, timestamp_suffix, daily_reports_dir, state)
            save_pipeline_state(report_date, state)
            
        elif p == "notify":
            run_notify_phase(regions_list, report_date, state)
            
        elif p == "prompt_evolve":
            run_prompt_evolve_phase()

def evolve_active_prompts():
    """
    自適應 Prompt 演化引擎 (Self-Reflective Prompt Optimization Engine)
    分析最近的已平倉交易紀錄與其實際投資績效 (ROI)，
    針對表現欠佳或估值失真的 FundamentalAgent 進行 Prompt 自我演化與版本升級。
    """
    print_info("[自適應 Prompt 演化] 正在啟動自適應 Prompt 演化引擎...")
    try:
        ReflectionAgent.evolve_prompts()
    except Exception as ex:
        print_warning(f"[自適應 Prompt 演化] 執行過程中發生異常，跳過本次 Prompt 演化: {ex}")

def resolve_ticker_and_region(query_str: str) -> tuple:
    """
    Resolves ticker, region and company names by checking the local Taiwan stock database first,
    then falling back to LLM.
    """
    try:
        from core.tools.taiwan_stock_names import resolve_taiwan_ticker_locally
        local_result = resolve_taiwan_ticker_locally(query_str)
        if local_result:
            return (
                local_result["ticker"],
                local_result["region"],
                local_result["company_name"],
                local_result["company_name_zh"]
            )
    except Exception as ex:
        print(f"[!] Local Taiwan ticker resolution error: {ex}")
        
    return resolve_ticker_and_region_via_llm(query_str)

def resolve_ticker_and_region_via_llm(query_str: str) -> tuple:
    """
    Uses a quick LLM call to resolve name or ticker to (standard_ticker, region_code, company_name, company_name_zh).
    Returns (None, None, None, None) if unresolved.
    """
    from pathlib import Path
    
    fallback_instruction = (
        "You are a financial database utility. Your job is to translate a user's input (stock name, Chinese name, or ticker) "
        "into standard format: standard Yahoo Finance ticker, region code ('US' or 'Taiwan'), English official company name, and Chinese official company name. "
        "Format your response strictly as a JSON object: {\"ticker\": \"...\", \"region\": \"...\", \"company_name\": \"...\", \"company_name_zh\": \"...\"}."
    )
    
    system_instruction = fallback_instruction
    try:
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "ticker_resolver_baseline.txt"
        if prompt_path.exists():
            system_instruction = prompt_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[!] Failed to load external prompt ticker_resolver_baseline.txt: {e}")

    resolver = BaseAgent(
        name="TickerResolver",
        role="Financial Ticker Translator",
        system_instruction=system_instruction
    )
    try:
        resp = resolver.run(f"Translate this input: {query_str}")
        clean_resp = resp.strip()
        if clean_resp.startswith("```"):
            lines = clean_resp.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_resp = "\n".join(lines).strip()
        data = json.loads(clean_resp)
        ticker = data.get("ticker")
        region = data.get("region")
        company_name = data.get("company_name")
        company_name_zh = data.get("company_name_zh")
        
        if ticker and (ticker.endswith(".TW") or ticker.endswith(".TWO")):
            ticker_num = ticker.split(".")[0]
            from core.tools.taiwan_stock_names import get_taiwan_stock_name
            db_name = get_taiwan_stock_name(ticker_num)
            if db_name:
                company_name_zh = db_name
                
        return ticker, region, company_name, company_name_zh
    except Exception as e:
        print(f"[!] Ticker resolution error: {e}")
        return None, None, None, None

def get_latest_regime_and_reflection(region: str) -> tuple:
    """
    Queries the MySQL/SQLite database to fetch the latest Macro Report, Market Regime, and Reflection Directives.
    """
    with db.db_session() as conn:
        cursor = conn.cursor()
        region_term = "台股" if region != "US" else "美股"
        
        # 1. Fetch latest MacroAgent log for this region
        db.execute_sql(cursor,
            "SELECT output_response FROM agent_inference_logs WHERE agent_name = 'MacroAgent' AND input_prompt LIKE ? ORDER BY id DESC LIMIT 1",
            "SELECT output_response FROM agent_inference_logs WHERE agent_name = 'MacroAgent' AND input_prompt LIKE %s ORDER BY id DESC LIMIT 1",
            (f"%{region_term}%",)
        )
        macro_row = cursor.fetchone()
        macro_report = ""
        if macro_row:
            if isinstance(macro_row, dict):
                macro_report = macro_row.get("output_response", "")
            else:
                macro_report = macro_row[0]
        else:
            macro_report = "（無可用宏觀經濟分析資料，預設為多頭情境）"
        
        # Extract regime
        regime_match = re.search(r"\[MACRO_REGIME:\s*(BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]", macro_report)
        macro_regime = regime_match.group(1) if regime_match else "BULL_RISK_ON"
        macro_report_cleaned = re.sub(r"\[MACRO_REGIME:\s*(BULL_REGIME|BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]\s*", "", macro_report)
        
        # 2. Fetch latest ReflectionAgent log for this region
        db.execute_sql(cursor,
            "SELECT output_response FROM agent_inference_logs WHERE agent_name = 'ReflectionAgent' AND input_prompt LIKE ? ORDER BY id DESC LIMIT 1",
            "SELECT output_response FROM agent_inference_logs WHERE agent_name = 'ReflectionAgent' AND input_prompt LIKE %s ORDER BY id DESC LIMIT 1",
            (f"%{region_term}%",)
        )
        ref_row = cursor.fetchone()
        reflection_directives = ""
        if ref_row:
            if isinstance(ref_row, dict):
                reflection_directives = ref_row.get("output_response", "")
            else:
                reflection_directives = ref_row[0]
        else:
            reflection_directives = "（本區域目前尚無歷史交易紀錄，暫無自我反思修正指令。請採用標準安全邊際進行基本面估值。）"
        
        return macro_report_cleaned, macro_regime, reflection_directives

def run_realtime_query(query_str: str, track_option: bool, report_date: str):
    """
    Runs a real-time investment analysis query for a single ticker/name and optionally tracks it.
    """
    print_success("==================================================")
    print_success(f"🔍 Aegis-MAQS 即時個股分析與決策查詢啟動：'{query_str}'")
    print_success("==================================================")
    
    print_info("正在解析標的名稱與交易所代碼...")
    ticker, region_code, company_name, company_name_zh = resolve_ticker_and_region(query_str)
    if not ticker or not region_code:
        print_error(f"無法解析此標的：'{query_str}'，請確認輸入是否正確。")
        return
        
    if company_name_zh and company_name_zh != company_name:
        display_name = f"{company_name_zh} ({company_name})"
    else:
        display_name = company_name_zh if company_name_zh else company_name
    print_success(f"成功解析！標準代碼: {ticker} | 市場區域: {region_code} | 公司名稱: {display_name}")
    
    print_info("正在自資料庫加載最新宏觀經濟情境與歷史反思指令...")
    macro_report, macro_regime, reflection_directives = get_latest_regime_and_reflection(region_code)
    print_success(f"當前大盤市場情境標籤：{macro_regime}")
    
    # Detect price regime dynamically
    from core.regime.price_regime import detect_region as detect_price_regime
    try:
        price_info = detect_price_regime(region_code)
        price_regime = price_info.get("regime", "MOMENTUM_TREND")
    except Exception:
        price_regime = "MOMENTUM_TREND"
    print_success(f"當前大盤價格氣候標籤：{price_regime}")
    
    res = research_and_track_asset(
        ticker=ticker,
        company_name=display_name,
        region_code=region_code,
        macro_regime=macro_regime,
        macro_report=macro_report,
        reflection_directives=reflection_directives,
        report_date=report_date,
        save_to_db=track_option,
        is_weekly_pipeline=False,
        custom_recommend_reason=f"Aegis-MAQS 即時查詢注入追蹤。當前市場情境: {macro_regime}。",
        price_regime=price_regime
    )
    
    if not res:
        print_error(f"分析標的 {ticker} 失敗。")
        return
        
    rating = res["rating"]
    curr_price = res["financials"].get("current_price", 0.0)
    target_p = res["target_price"]
    stop_l = res["stop_loss"]
    suggested_weight = res["suggested_weight"]
    valuation_report = res["valuation_report"]
    stock_report = res["stock_report"]
    invested_amount = res["invested_amount"]
    shares = res["shares"]
    
    currency = "USD" if region_code == "US" else "TWD"
    region_display = "美股 (US)" if region_code == "US" else "台股 (Taiwan)"
    
    if rating in ["Hold", "Sell"]:
        buy_range_display = "不建議買入 (N/A)"
        target_p_display = "N/A"
        stop_l_display = "N/A"
    else:
        parsed_range = None
        for line in stock_report.split("\n"):
            if "推薦買入區間" in line or "買入區間" in line:
                parsed_range = extract_range_from_line(line, curr_price)
                break
        if parsed_range:
            buy_range_display = f"{parsed_range} {currency}"
        else:
            buy_range_display = f"{curr_price * 0.98:.2f} - {curr_price * 1.02:.2f} {currency}"
            
        target_p_display = f"{target_p:.2f} {currency}"
        stop_l_display = f"{stop_l:.2f} {currency}"
        
    print("\n" + "\033[93m" + "="*60 + "\033[0m")
    print("  🎯 第一章：智慧投資決策與交易指令概要 (Decision Card)")
    print("\033[93m" + "="*60 + "\033[0m")
    
    table_rows = [
        ("國家區域", region_display),
        ("標的代碼", ticker),
        ("企業名稱", display_name),
        ("推薦評級", rating),
        ("即時現價", f"{curr_price:.2f} {currency}"),
        ("推薦買入區間", buy_range_display),
        ("中線目標價", target_p_display),
        ("防禦停損點", stop_l_display),
        ("建議持倉權重", f"{suggested_weight * 100:.1f}%")
    ]
    
    for key, val in table_rows:
        print(f"  • {key.ljust(10, '　')}: {val}")
        
    print("\033[93m" + "="*60 + "\033[0m")
    
    print("\n" + "\033[96m" + "="*60 + "\033[0m")
    print("  🏦 第二章：投行量化估值模型報告 (Equity Valuation Engine Report)")
    print("\033[96m" + "="*60 + "\033[0m")
    print(valuation_report)
    print("\033[96m" + "="*60 + "\033[0m")
    
    print("\n" + "\033[93m" + "="*60 + "\033[0m")
    print("  💡 第三章：大模型深度基本面分析與決策修正 (LLM Report)")
    print("\033[93m" + "="*60 + "\033[0m")
    print(stock_report)
    print("\033[93m" + "="*60 + "\033[0m")
 
    try:
        query_dir = Path(DEFAULT_REPORTS_DIR).parent / "query"
        query_dir.mkdir(parents=True, exist_ok=True)
        
        query_md_content = f"""# Aegis-MAQS 智慧投資決策報告 - {ticker} ({display_name})
*   **分析日期**: {report_date}
*   **國家區域**: {region_display}

## 第一章：智慧投資決策與交易指令概要

| 項目 | 數值 |
| :--- | :--- |
| **國家區域** | {region_display} |
| **標的代碼** | {ticker} |
| **企業名稱** | {display_name} |
| **推薦評級** | {rating} |
| **即時現價** | {curr_price:.2f} {currency} |
| **推薦買入區間** | {buy_range_display} |
| **中線目標價** | {target_p_display} |
| **防禦停損點** | {stop_l_display} |
| **建議持倉權重** | {suggested_weight * 100:.1f}% |

---

## 第二章：投行量化估值模型報告 (Equity Valuation Engine Report)

{valuation_report}

---

## 第三章：大模型深度基本面分析與決策修正 (LLM Report)

{stock_report}
"""
        query_file_name = f"{ticker}_{report_date}.md"
        query_file_path = query_dir / query_file_name
        with open(query_file_path, "w", encoding="utf-8") as f:
            f.write(query_md_content)
            
        print_success(f"已將即時查詢報告儲存至: {query_file_path}")
    except Exception as save_err:
        print_warning(f"儲存即時查詢報告失敗: {save_err}")
        
    if track_option:
        if rating not in ["Buy", "Strong Buy"]:
            print_warning(f"\n[⚠️ 追蹤警告] 標的 {ticker} 推薦評級為 {rating}，未達 Buy/Strong Buy 買入標準，不予寫入持股追蹤帳本。")
        else:
            if res.get("rec_id"):
                print_success(f"🎉 標的 {ticker} 已成功寫入 MySQL 並開始追蹤！(分配預算: {invested_amount:.2f} | 股數: {shares:.2f})")
                print_success("💡 提示：本標的將在明天的 17:00 全自動納入每日持股對帳、風控停損與 HTML 看板中！")
            else:
                print_error("追蹤寫入失敗。")

def run_prompt_evolution_test():
    print_info("⚡ 已啟動自適應 Prompt 演化引擎的測試模式...")
    try:
        # 檢查當前是否有足夠交易日誌
        logs = db.get_recent_inference_logs_with_roi("FundamentalAgent", limit=10)
        if len(logs) < 2:
            print_info("⚠️ 偵測到已平倉交易數據小於 2 筆，正在自動注入 2 筆模擬交易數據與推論日誌以進行測試...")
            
            # 初始化 FundamentalAgent 確保資料庫有 v1.0.0 首發 prompt
            FundamentalAgent()
            active_prompt = db.get_active_prompt("FundamentalAgent")
            
            # 注入模擬交易
            with db.db_session() as conn:
                cursor = conn.cursor()
                
                # 成功交易案例 (NVDA)
                db.execute_sql(cursor,
                    "INSERT INTO recommendations (report_date, region, ticker, company_name, recommend_price, is_active, performance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    "INSERT INTO recommendations (report_date, region, ticker, company_name, recommend_price, is_active, performance) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    ("2026-05-01", "US", "NVDA", "NVIDIA Corp", 100.0, 0, 0.15)
                )
                success_rec_id = cursor.lastrowid
                
                # 失敗交易案例 (INTC)
                db.execute_sql(cursor,
                    "INSERT INTO recommendations (report_date, region, ticker, company_name, recommend_price, is_active, performance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    "INSERT INTO recommendations (report_date, region, ticker, company_name, recommend_price, is_active, performance) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    ("2026-05-01", "US", "INTC", "Intel Corp", 30.0, 0, -0.12)
                )
                failure_rec_id = cursor.lastrowid
                
            # 儲存對應的推論日誌
            db.save_agent_inference_log(
                rec_id=success_rec_id,
                agent_name="FundamentalAgent",
                ticker="NVDA",
                input_prompt="當前總經：BULL_RISK_ON\n基本面：EPS 成長 50%，本益比 35 倍，負債比 20%",
                output_response="基本面分析：NVIDIA 獲利能力極強，毛利率高於 70%，受惠 AI 強勁需求。操作指引：目標價 115 元，停損點 92 元，建議持倉 20%。",
                prompt_version=active_prompt["version"] if active_prompt else "v1.0.0",
                report_date="2026-05-01"
            )
            
            db.save_agent_inference_log(
                rec_id=failure_rec_id,
                agent_name="FundamentalAgent",
                ticker="INTC",
                input_prompt="當前總經：BEAR_RISK_OFF\n基本面：EPS 成長 -20%，本益比 40 倍，負債比 65%",
                output_response="基本面分析：Intel 面臨重重挑戰，雖本益比高企且成長衰退，但基於晶片法案補貼，給予買入評級。操作指引：目標價 34.5 元，停損點 27.6 元，建議持倉 10%。",
                prompt_version=active_prompt["version"] if active_prompt else "v1.0.0",
                report_date="2026-05-01"
            )
            print_success("成功注入 2 筆測試用交易紀錄！現在啟動自適應 Prompt 演化引擎...")
        
        # 執行演化
        evolve_active_prompts()
        
        # 清理注入數據
        if len(logs) < 2:
            print_info("🧹 正在清理測試注入的模擬交易數據，回復資料庫至乾淨狀態...")
            with db.db_session() as conn:
                cursor = conn.cursor()
                db.execute_sql(cursor,
                    "DELETE FROM agent_inference_logs WHERE rec_id IN (?, ?)",
                    "DELETE FROM agent_inference_logs WHERE rec_id IN (%s, %s)",
                    (success_rec_id, failure_rec_id)
                )
                db.execute_sql(cursor,
                    "DELETE FROM recommendations WHERE id IN (?, ?)",
                    "DELETE FROM recommendations WHERE id IN (%s, %s)",
                    (success_rec_id, failure_rec_id)
                )
            print_success("[✓] 資料庫清理完成，已成功恢復原狀。")
            
    except Exception as e:
        print_error(f"自適應 Prompt 演化測試模式中途發生錯誤: {e}")


def load_pipeline_state(report_date: str) -> dict:
    from core.config import CACHE_DIR
    state_file = CACHE_DIR / f"pipeline_state_{report_date}.json"
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print_warning(f"載入快取狀態檔失敗: {e}")
    return {}

def save_pipeline_state(report_date: str, state: dict):
    from core.config import CACHE_DIR
    state_file = CACHE_DIR / f"pipeline_state_{report_date}.json"
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print_error(f"寫入快取狀態檔失敗: {e}")

def init_pipeline_state_dates(state: dict):
    if "start_date" not in state or "end_date" not in state or not state["start_date"]:
        try:
            us_bench = yf_tool.get_benchmark_performance("US")
            state["start_date"] = us_bench.get("start_date", "")
            state["end_date"] = us_bench.get("end_date", "")
        except Exception as e:
            print_warning(f"取得大盤本週計算區間失敗: {e}")
            state["start_date"] = ""
            state["end_date"] = ""

def run_portfolio_check_phase(report_date: str, regions_list: list = None):
    print_info("==================================================")
    print_info(f"[Phase 1/10] 持股對帳與風控 (portfolio_check)")
    print_info("==================================================")
    run_portfolio_check(report_date, regions=regions_list)
    print_success("[✓] 持股對帳與風控執行完成。")

def run_reflection_phase(regions_list: list, report_date: str, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 4/10] 歷史交易戰術反思 (portfolio_reflect)")
    print_info("==================================================")
    if "reflection" not in state:
        state["reflection"] = {}
        
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        print_info(f"[{region_name}] 正在啟動區域專屬歷史回測與決策反思...")
        try:
            directives = run_regional_reflection(r_code, report_date, state)
            state["reflection"][r_code] = directives
            time.sleep(3)
        except Exception as ex:
            print_error(f"[{r_code}] 執行區域專屬自我反思時失敗: {ex}")
            state["reflection"][r_code] = "（本區域目前尚無歷史交易紀錄，暫無自我反思修正指令。請採用標準安全邊際進行基本面估值。）"
    print_success("[✓] 歷史交易戰術反思執行完成。")

def run_analyze_macro_phase(regions_list: list, report_date: str, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 2/10] 總體經濟情境與市場流動性分析 (analyze_macro)")
    print_info("==================================================")
    if "analysis" not in state:
        state["analysis"] = {}
        
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        print_info(f"[{region_name}] 正在執行總體經濟與流動性分析...")
        if r_code not in state["analysis"]:
            state["analysis"][r_code] = {}
        
        # Detect price regime (quantitative ADX/Hurst) first to anchor macro analysis
        from core.regime.price_regime import detect_region as detect_price_regime
        price_info = detect_price_regime(r_code)
        price_regime = price_info.get("regime", "MOMENTUM_TREND")
        
        # Run macroeconomic analysis
        macro_report, macro_regime = analyze_macro_regime(r_code, price_info=price_info, report_date=report_date)
        
        # Run Liquidity Scout analysis
        liq_report, liq_regime = run_liquidity_analysis(r_code, report_date=report_date)
        
        try:
            from core.regime.registry import save_macro_regime
            save_macro_regime(r_code, {
                "regime": macro_regime,
                "adx": price_info.get("adx", 20.0),
                "hurst": price_info.get("hurst", 0.50),
                "ticker": "^GSPC" if r_code == "US" else "^TWII"
            })
            print_info(f"[{r_code}] 成功將總經市場情境標籤 {macro_regime} 寫入快取。")
        except Exception as reg_ex:
            print_error(f"[{r_code}] 無法將市場情境寫入快取: {reg_ex}")
            
        state["analysis"][r_code]["price_regime"] = price_regime
        state["analysis"][r_code]["macro_report"] = macro_report
        state["analysis"][r_code]["macro_regime"] = macro_regime
        state["analysis"][r_code]["liquidity_report"] = liq_report
        state["analysis"][r_code]["liquidity_regime"] = liq_regime
        time.sleep(3)
    print_success("[✓] 總體經濟情境與市場流動性分析執行完成。")

def run_analyze_sectors_phase(regions_list: list, report_date: str, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 3/10] 產業板塊資金流分析 (analyze_sectors)")
    print_info("==================================================")
    if "analysis" not in state:
        state["analysis"] = {}
        
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        if r_code not in state["analysis"]:
            state["analysis"][r_code] = {}
            
        if "macro_regime" not in state["analysis"][r_code]:
            try:
                from core.regime.registry import get_macro_regime
                macro_regime_info = get_macro_regime(r_code)
                macro_regime = macro_regime_info.get("regime", "VOLATILE_RANGEBOUND") if isinstance(macro_regime_info, dict) else macro_regime_info
            except Exception:
                macro_regime = "VOLATILE_RANGEBOUND"
            state["analysis"][r_code]["macro_regime"] = macro_regime
            print_warning(f"[{region_name}] 快取無總經情境，已自資料庫或預設載入：{macro_regime}")
            
        macro_regime = state["analysis"][r_code]["macro_regime"]
        
        from core.regime.price_regime import detect_region as detect_price_regime
        price_info = detect_price_regime(r_code)
        price_regime = price_info.get("regime", "MOMENTUM_TREND")
        print_info(f"[{region_name}] 偵測到價格氣候 (Price Regime): {price_regime} (ADX={price_info.get('adx', 'N/A'):.1f}, Hurst={price_info.get('hurst', 'N/A'):.2f})")
        
        print_info(f"[{region_name}] 正在獲取板塊績效排名...")
        sector_rankings = yf_tool.get_sector_rankings(r_code)
        
        print_info(f"[{region_name}] 正在獲取最強勢板塊之產業趨勢新聞...")
        sector_news = []
        try:
            c_sectors = [sec for sec in sector_rankings if "Broad Market" not in sec["label"]]
            if not c_sectors:
                c_sectors = sector_rankings
            top_2_sectors = c_sectors[:2]
            for sec in top_2_sectors:
                label = sec["label"]
                match = re.match(r"^([^\(]+)", label)
                sector_name = match.group(1).strip() if match else label
                
                if r_code == "US":
                    query = f"US {sector_name} industry news when:7d"
                    lang, reg = "en-US", "US"
                else:
                    query = f"台灣 {sector_name} 產業 新聞 when:7d"
                    lang, reg = "zh-TW", "TW"
                    
                print_info(f"   - 正在檢索板塊【{label}】產業動向: '{query}'")
                news_items = search_tool.search_news(query, max_items=2, language=lang, region=reg)
                sector_news.extend(news_items)
                time.sleep(2)
        except Exception as sector_news_ex:
            print_error(f"[{r_code}] 獲取板塊相關產業新聞時失敗: {sector_news_ex}")
            
        print_info(f"[{region_name}] 正在進行板塊強度排序與資金流向分析...")
        market_agent = MarketAgent()
        market_report = market_agent.analyze(region_name, sector_rankings, sector_news)
        
        try:
            db.save_agent_inference_log(
                rec_id=None,
                agent_name="MarketAgent",
                ticker=None,
                input_prompt=market_agent.last_prompt,
                output_response=market_report,
                prompt_version=market_agent.prompt_version,
                report_date=report_date
            )
        except Exception as log_ex:
            print(f"[!] Warning: 記錄 MarketAgent 推論日誌失敗: {log_ex}")
            
        # Extract themes via MarketAgent using general thematic news (decoupled from sector list)
        print_info(f"[{region_name}] 正在獲取全市場前瞻產業與投研主題新聞...")
        try:
            thematic_news = search_tool.get_thematic_industry_news(r_code, max_items=5)
            print_info(f"[{region_name}] 正在利用 MarketAgent 進行前瞻主題關鍵字萃取...")
            themes = market_agent.extract_themes_from_news(thematic_news)
            print_success(f"[{region_name}] 成功萃取前瞻產業主題：{', '.join(themes)}")
        except Exception as theme_ex:
            print_warning(f"[{region_name}] 萃取前瞻產業主題失敗: {theme_ex}")
            themes = ["AI硬體", "半導體"]
            
        state["analysis"][r_code]["price_regime"] = price_regime
        state["analysis"][r_code]["sector_rankings"] = sector_rankings
        state["analysis"][r_code]["market_report"] = market_report
        state["analysis"][r_code]["themes"] = themes
        time.sleep(3)
    print_success("[✓] 產業板塊資金流分析執行完成。")

def run_screen_targets_phase(regions_list: list, report_date: str, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 5/10] 量化選股與目標篩選 (screen_targets)")
    print_info("==================================================")
    if "analysis" not in state:
        state["analysis"] = {}
        
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        if r_code not in state["analysis"]:
            state["analysis"][r_code] = {}
            
        # 1. Fallback for macro_regime
        if "macro_regime" not in state["analysis"][r_code]:
            try:
                from core.regime.registry import get_macro_regime
                macro_regime_info = get_macro_regime(r_code)
                macro_regime = macro_regime_info.get("regime", "VOLATILE_RANGEBOUND") if isinstance(macro_regime_info, dict) else macro_regime_info
            except Exception:
                macro_regime = "VOLATILE_RANGEBOUND"
            state["analysis"][r_code]["macro_regime"] = macro_regime
            print_warning(f"[{region_name}] 快取無總經情境，已自動載入：{macro_regime}")
            
        macro_regime = state["analysis"][r_code]["macro_regime"]
            
        # 2. Fallback for price_regime
        if "price_regime" not in state["analysis"][r_code]:
            try:
                from core.regime.price_regime import detect_region as detect_price_regime
                price_info = detect_price_regime(r_code)
                price_regime = price_info.get("regime", "MOMENTUM_TREND")
            except Exception:
                price_regime = "MOMENTUM_TREND"
            state["analysis"][r_code]["price_regime"] = price_regime
            print_warning(f"[{region_name}] 快取無價格氣候，已自動計算：{price_regime}")
            
        price_regime = state["analysis"][r_code]["price_regime"]
            
        # 3. Fallback for sector_rankings
        if "sector_rankings" not in state["analysis"][r_code]:
            try:
                sector_rankings = yf_tool.get_sector_rankings(r_code)
            except Exception as e:
                print_error(f"[{region_name}] 自動獲取板塊排行失敗: {e}")
                sector_rankings = []
            state["analysis"][r_code]["sector_rankings"] = sector_rankings
            print_warning(f"[{region_name}] 快取無板塊排行，已自動重新抓取。")
            
        sector_rankings = state["analysis"][r_code]["sector_rankings"]
        
        max_scan_sectors = max(MAX_SECTORS_PER_REGION, MAX_STOCKS_PER_REGION)
        top_etfs = [sec["ticker"] for sec in sector_rankings[:max_scan_sectors]]
        print_info(f"[{region_name}] 本週焦點強勢板塊 ETF (自適應擴大)：{', '.join(top_etfs)}")
        
        state["analysis"][r_code]["top_etfs"] = top_etfs
        state["analysis"][r_code]["target_stocks"] = []
        
        screener_instance = yf_tool.get_screener_instance()
        screener_instance.clear_history()
        
        # --- 雙向資料庫對照：載入全市場候選股池 ---
        all_tickers = []
        try:
            with db.db_session() as conn:
                cursor = conn.cursor()
                query_sqlite = """
                    SELECT DISTINCT sc.ticker, sc.company_name 
                    FROM sector_constituents sc 
                    JOIN sector_registry sr ON sc.sector_id = sr.id 
                    WHERE sr.region = ? AND sr.is_active = 1
                """
                query_mysql = """
                    SELECT DISTINCT sc.ticker, sc.company_name 
                    FROM sector_constituents sc 
                    JOIN sector_registry sr ON sc.sector_id = sr.id 
                    WHERE sr.region = %s AND sr.is_active = 1
                """
                db.execute_sql(cursor, query_sqlite, query_mysql, (r_code,))
                rows = cursor.fetchall()
                for row in rows:
                    if isinstance(row, dict):
                        all_tickers.append({"ticker": row["ticker"], "name": row["company_name"]})
                    else:
                        all_tickers.append({"ticker": row[0], "name": row[1]})
        except Exception as db_ex:
            print_warning(f"[{region_name}] 無法從資料庫獲取候選個股: {db_ex}")
            
        if not all_tickers:
            print_info(f"[{region_name}] 啟用靜態設定檔作為全市場候選股備用資料...")
            try:
                sectors = REGIONS.get(r_code, {}).get("sector_etfs", {})
                for etf, info in sectors.items():
                    constituents = info.get("constituents", [])
                    for t in constituents:
                        all_tickers.append({"ticker": t, "name": t})
            except Exception:
                pass
                
        for item in all_tickers:
            if not item.get("name"):
                item["name"] = item["ticker"]
                
        # --- 軌道一：板塊動能/防禦 Beta ---
        if "REVERSION" in price_regime or "RANGEBOUND" in price_regime or price_regime == "MEAN_REVERSION_RANGE":
            track1_label = "sector_reversion"
            track1_desc = "板塊防禦 Beta (均值回歸)"
        else:
            track1_label = "sector_momentum"
            track1_desc = "板塊動能 Beta (趨勢跟隨)"
            
        print_info(f"[{region_name}] 正在執行 軌道一：{track1_desc} 選股...")
        track1_stocks = []
        stocks_screened = 0
        for etf_ticker in top_etfs:
            if stocks_screened >= 2:
                break
                
            sector_config = db.get_active_sectors(r_code).get(etf_ticker, {})
            target_type = sector_config.get("target_type", "constituents")
            
            if target_type == "proxy":
                target_stocks = [{
                    "ticker": etf_ticker,
                    "name": f"{sector_config.get('name', etf_ticker)}",
                    "target_type": "proxy",
                    "etf_ticker": etf_ticker,
                    "source_track": track1_label,
                    "reason": f"隸屬焦點板塊 {etf_ticker} (動能領先)，以 proxy 模式直接配置板塊 ETF 獲取 Beta 收益。"
                }]
            else:
                representative_stocks = yf_tool.screen_sector_candidates(etf_ticker, region=r_code, macro_regime=macro_regime, price_regime=price_regime)
                if not representative_stocks:
                    target_stocks = [{
                        "ticker": etf_ticker,
                        "name": f"{sector_config.get('name', etf_ticker)}",
                        "target_type": "proxy",
                        "etf_ticker": etf_ticker,
                        "source_track": track1_label,
                        "reason": f"焦點板塊 {etf_ticker} 成分股皆未通過量化篩選，遞補直接配置板塊 ETF 本身。"
                    }]
                else:
                    stocks_to_analyze = min(len(representative_stocks), 2)
                    target_stocks = representative_stocks[:stocks_to_analyze]
                    for s in target_stocks:
                        s["target_type"] = "constituents"
                        s["etf_ticker"] = etf_ticker
                        s["source_track"] = track1_label
                        s["reason"] = f"隸屬焦點強勢板塊 {etf_ticker}，成分股量化篩選評分領先。"
            
            track1_stocks.extend(target_stocks)
            stocks_screened += len(target_stocks)
            
        # --- 軌道二：財務加速 Alpha ---
        print_info(f"[{region_name}] 正在執行 軌道二：財務加速 Alpha 選股...")
        track2_candidates = []
        from core.config import CACHE_DIR
        
        fetched_count = 0
        max_online_fetches = 300  # 當無快取時，提高至 300 檔以百分之百涵蓋所有分區候選股池 (美股 217 檔，台股 154 檔)
        
        for item in all_tickers:
            ticker = item["ticker"]
            cache_key = f"financials_{ticker.upper()}"
            f_data = get_cached_data(CACHE_DIR, cache_key, ttl_hours=24)
            if not f_data and fetched_count < max_online_fetches:
                try:
                    import time
                    # 引入 0.5 秒小延遲，避免密集請求 yfinance API 觸發 rate limit
                    time.sleep(0.5)
                    f_data = yf_tool.get_stock_financials(ticker)
                    fetched_count += 1
                except Exception:
                    pass
            if f_data:
                rev_growth = f_data.get("revenue_growth")
                eps_growth = f_data.get("eps_growth")
                if rev_growth is not None or eps_growth is not None:
                    rg = rev_growth if rev_growth is not None else 0.0
                    eg = eps_growth if eps_growth is not None else 0.0
                    if rg > 0.15 or eg > 0.15:
                        # 取得過濾因子
                        pe_ratio = f_data.get("pe_ratio")
                        peg_ratio = f_data.get("peg_ratio")
                        fifty_day_sma = f_data.get("fifty_day_sma")
                        current_price = f_data.get("current_price")
                        
                        # 1. 套用 PEG 篩選：放寬至 <= 1.5。
                        # 若為轉機股（盈餘剛從負轉正，導致 PE/PEG 為 None 或負數），則保留不予誤殺。
                        if peg_ratio is not None and peg_ratio > 1.5:
                            continue
                            
                        # 2. 套用技術面趨勢篩選：價格必須高於 50日均線（Price >= 50-day SMA）
                        if current_price is not None and fifty_day_sma is not None and current_price < fifty_day_sma:
                            continue
                            
                        avg_growth = (rg + eg) / 2.0 if (rev_growth is not None and eps_growth is not None) else (rg or eg)
                        
                        # 格式化顯示過濾因子
                        pe_str = f"{pe_ratio:.1f}" if pe_ratio is not None else "N/A"
                        peg_str = f"{peg_ratio:.2f}" if peg_ratio is not None else "N/A (轉機股)"
                        
                        track2_candidates.append({
                            "ticker": ticker,
                            "name": item["name"],
                            "target_type": "constituents",
                            "etf_ticker": "N/A",
                            "source_track": "bottom_up_acceleration",
                            "avg_growth": avg_growth,
                            "revenue_growth": rg,
                            "eps_growth": eg,
                            "pe_ratio": pe_ratio,
                            "peg_ratio": peg_ratio,
                            "fifty_day_sma": fifty_day_sma,
                            "current_price": current_price,
                            "reason": f"財務加速篩選：營收年增率 {rg*100:.1f}%, EPS年增率 {eg*100:.1f}% [過濾因子: PE={pe_str}, PEG={peg_str}, 已站上50日線]"
                        })
        track2_candidates.sort(key=lambda x: x["avg_growth"], reverse=True)
        track2_stocks = track2_candidates[:2]
        if track2_stocks:
            print_success(f"[{region_name}] 軌道二成功篩選出財務加速個股：{[s['ticker'] for s in track2_stocks]}")
        else:
            print_warning(f"[{region_name}] 軌道二未篩選出符合標準（年增率 > 15%）的財務加速個股。")
        
        # --- 軌道三：前瞻主題 ---
        print_info(f"[{region_name}] 正在執行 軌道三：前瞻主題選股...")
        themes = state["analysis"][r_code].get("themes", [])
        track3_stocks = []
        if themes:
            try:
                market_agent = MarketAgent()
                matched_thematic = market_agent.match_thematic_stocks(all_tickers, themes)
                for item in matched_thematic:
                    track3_stocks.append({
                        "ticker": item["ticker"],
                        "name": item["name"],
                        "target_type": "constituents",
                        "etf_ticker": "N/A",
                        "source_track": "thematic_scan",
                        "reason": f"前瞻主題篩選：{item['reason']}"
                    })
                print_success(f"[{region_name}] 軌道三成功篩選出主題概念股：{[s['ticker'] for s in track3_stocks]}")
                
                # --- 持久化儲存至資料庫 thematic 關聯表 ---
                try:
                    with db.db_session() as conn:
                        cursor = conn.cursor()
                        for t_name in themes:
                            t_name_stripped = t_name.strip()
                            # 1. 寫入或取得主題 ID
                            if db.DB_TYPE == "mysql":
                                cursor.execute("SELECT id FROM thematic_registry WHERE theme_name = %s", (t_name_stripped,))
                                row = cursor.fetchone()
                                if row:
                                    theme_id = row["id"]
                                else:
                                    cursor.execute("INSERT INTO thematic_registry (theme_name) VALUES (%s)", (t_name_stripped,))
                                    theme_id = cursor.lastrowid
                            else:
                                cursor.execute("SELECT id FROM thematic_registry WHERE theme_name = ?", (t_name_stripped,))
                                row = cursor.fetchone()
                                if row:
                                    theme_id = row[0]
                                else:
                                    cursor.execute("INSERT INTO thematic_registry (theme_name) VALUES (?)", (t_name_stripped,))
                                    theme_id = cursor.lastrowid
                            
                            # 2. 寫入或更新概念股對照關係
                            for item in matched_thematic:
                                t_ticker = item.get("ticker", "").strip().upper()
                                t_reason = item.get("reason", "").strip()
                                
                                if db.DB_TYPE == "mysql":
                                    cursor.execute("SELECT id FROM thematic_constituents WHERE theme_id = %s AND ticker = %s", (theme_id, t_ticker))
                                    c_row = cursor.fetchone()
                                    if c_row:
                                        cursor.execute("UPDATE thematic_constituents SET registered_reason = %s WHERE id = %s", (t_reason, c_row["id"]))
                                    else:
                                        cursor.execute("INSERT INTO thematic_constituents (theme_id, ticker, registered_reason) VALUES (%s, %s, %s)", (theme_id, t_ticker, t_reason))
                                else:
                                    cursor.execute("SELECT id FROM thematic_constituents WHERE theme_id = ? AND ticker = ?", (theme_id, t_ticker))
                                    c_row = cursor.fetchone()
                                    if c_row:
                                        cursor.execute("UPDATE thematic_constituents SET registered_reason = ? WHERE id = ?", (t_reason, c_row[0]))
                                    else:
                                        cursor.execute("INSERT INTO thematic_constituents (theme_id, ticker, registered_reason) VALUES (?, ?, ?)", (theme_id, t_ticker, t_reason))
                        conn.commit()
                    print_info(f"[{region_name}] 主題與概念股對照關係已持久化儲存至資料庫。")
                except Exception as db_save_ex:
                    print_warning(f"[{region_name}] 無法將主題與概念股存入資料庫: {db_save_ex}")
            except Exception as thematic_ex:
                print_warning(f"[{region_name}] 軌道三選股執行失敗: {thematic_ex}")
                
        # --- 輪流融合與去重 (Round-Robin) ---
        final_targets = []
        seen_tickers = set()
        
        tracks = [track3_stocks, track2_stocks, track1_stocks]
        max_len = max(len(t) for t in tracks) if tracks else 0
        
        for i in range(max_len):
            for t in tracks:
                if i < len(t):
                    stock = t[i]
                    ticker_upper = stock["ticker"].upper()
                    if ticker_upper not in seen_tickers:
                        seen_tickers.add(ticker_upper)
                        final_targets.append(stock)
                        if len(final_targets) >= MAX_STOCKS_PER_REGION:
                            break
            if len(final_targets) >= MAX_STOCKS_PER_REGION:
                break
                
        state["analysis"][r_code]["target_stocks"] = final_targets
        state["analysis"][r_code]["track2_candidates"] = track2_candidates
        state["analysis"][r_code]["screener_session_history"] = list(screener_instance.session_history)
        
        print_info(f"[{region_name}] 篩選完成！三軌融合最終待深度分析個股：")
        for idx, stock in enumerate(state["analysis"][r_code]["target_stocks"]):
            track_name = "板塊動能 Beta (趨勢)" if stock["source_track"] == "sector_momentum" else "板塊防禦 Beta (回歸)" if stock["source_track"] == "sector_reversion" else "財務加速 Alpha" if stock["source_track"] == "bottom_up_acceleration" else "前瞻主題"
            print_info(f"   {idx+1}. {stock['name']} ({stock['ticker']}) | 選股軌道: {track_name} | 篩選原因: {stock['reason']}")
            
    print_success("[✓] 量化選股與目標篩選執行完成。")

def run_analyze_stocks_phase(regions_list: list, report_date: str, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 6/10] 個股深度基本面估值 (analyze_stocks)")
    print_info("==================================================")
    if "analysis" not in state or not state["analysis"]:
        raise ValueError("請先執行 screen_targets 階段！")
        
    screener_instance = yf_tool.get_screener_instance()
    screener_instance.clear_history()
    for r_code in regions_list:
        if r_code in state["analysis"] and "screener_session_history" in state["analysis"][r_code]:
            screener_instance.session_history.extend(state["analysis"][r_code]["screener_session_history"])
            
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        if r_code not in state["analysis"] or "target_stocks" not in state["analysis"][r_code]:
            raise ValueError(f"區域 {r_code} 缺少候選股票清單，請重跑 screen_targets！")
            
        target_stocks = state["analysis"][r_code]["target_stocks"]
        macro_regime = state["analysis"][r_code]["macro_regime"]
        macro_report = state["analysis"][r_code]["macro_report"]
        price_regime = state["analysis"][r_code]["price_regime"]
        reflection_directives = state.get("reflection", {}).get(r_code, "（無自我反思修正指令）")
        
        stock_analysis_reports = []
        analyzed_summary = []
        for stock in target_stocks:
            ticker = stock["ticker"]
            name = stock["name"]
            if ".TW" in ticker.upper() or ".TWO" in ticker.upper():
                from core.tools.taiwan_stock_names import get_taiwan_stock_name
                tw_name = get_taiwan_stock_name(ticker)
                if tw_name and tw_name != ticker:
                    name = tw_name
            target_type = stock.get("target_type", "constituents")
            etf_ticker = stock.get("etf_ticker")
            
            s_track = stock.get("source_track")
            s_reason = stock.get("reason")
            
            if target_type == "proxy":
                custom_reason = f"直接買入強勢板塊 ETF {etf_ticker}，獲取行業平均 Beta 收益。"
            else:
                custom_reason = s_reason or f"板塊 {etf_ticker} 強勢動能領頭，精選旗下龍頭成分股。"
                
            res = research_and_track_asset(
                ticker=ticker,
                company_name=name,
                region_code=r_code,
                macro_regime=macro_regime,
                macro_report=macro_report,
                reflection_directives=reflection_directives,
                report_date=report_date,
                save_to_db=True,
                custom_recommend_reason=custom_reason,
                price_regime=price_regime,
                source_track=s_track
            )
            if not res:
                continue
                
            if target_type == "proxy":
                try:
                    sector_rankings = state["analysis"][r_code]["sector_rankings"]
                    etf_rank = next((sec for sec in sector_rankings if sec["ticker"] == etf_ticker), {})
                    weekly_mom = etf_rank.get("weekly_return", 0.0)
                    screener_instance.record_proxy_etf(etf_ticker, r_code, financials=res["financials"], weekly_return=weekly_mom)
                except Exception as ex:
                    print_warning(f"記錄篩選報告 proxy ETF 失敗: {ex}")
                    
            stock_analysis_reports.append(res["stock_report"])
            analyzed_summary.append({
                "ticker": ticker,
                "name": name,
                "rating": res["rating"],
                "etf_ticker": etf_ticker,
                "source_track": s_track,
                "reason": s_reason
            })
            print_success(f"標的 {ticker} 推薦參數與預算已成功寫入回測帳本！(現價: {res['financials'].get('current_price', 0.0):.2f} | 分配預算: {res['invested_amount']:.2f} | 股數: {res['shares']:.2f})")
            
        state["analysis"][r_code]["stock_reports_combined"] = "\n\n---\n\n".join(stock_analysis_reports)
        state["analysis"][r_code]["analyzed_stocks_summary"] = analyzed_summary
        
    state["screener_session_history"] = list(screener_instance.session_history)
    print_success("[✓] 個股深度基本面估值執行完成。")

def run_weekly_report_phase(regions_list: list, report_date: str, timestamp_suffix: str, daily_reports_dir: Path, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 7/10] 每週策略週報合成 (weekly_report)")
    print_info("==================================================")
    
    start_date_str = state.get("start_date", "")
    end_date_str = state.get("end_date", "")
    
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        
        if "analysis" not in state or r_code not in state["analysis"]:
            raise ValueError(f"區域 {r_code} 缺少分析數據，請先執行前面的分析階段！")
            
        r_analysis = state["analysis"][r_code]
        mac_rep = r_analysis.get("macro_report")
        liq_rep = r_analysis.get("liquidity_report") or "暫無流動性分析數據。"
        mkt_rep = r_analysis.get("market_report")
        stk_rep = r_analysis.get("stock_reports_combined")
        reflection_directives = state.get("reflection", {}).get(r_code, "（無自我反思修正指令）")
        
        # Build candidate_summary text
        analyzed_summary_list = r_analysis.get("analyzed_stocks_summary", [])
        candidate_summary = ""
        if analyzed_summary_list:
            candidate_summary += "本週所有進行深度基本面分析之候選標的與評級如下：\n"
            for item in analyzed_summary_list:
                rating_label = "買入 Buy" if item['rating'] == "Buy" else "強烈買入 Strong Buy" if item['rating'] == "Strong Buy" else "持有 Hold" if item['rating'] == "Hold" else "避免買入 Avoid"
                etf_lbl = f"（隸屬板塊/ETF: {item['etf_ticker']}）" if item.get('etf_ticker') else ""
                s_track = item.get("source_track")
                track_name = "板塊動能 Beta" if s_track == "sector_momentum" else "板塊防禦 Beta" if s_track == "sector_reversion" else "財務加速 Alpha" if s_track == "bottom_up_acceleration" else "前瞻主題" if s_track == "thematic_scan" else "未指定"
                candidate_summary += f"- {item['name']} ({item['ticker']}) [選股軌道: {track_name}] {etf_lbl}: 最終分析評級為【{rating_label}】。\n"
        else:
            candidate_summary = "本週無待分析之個股。"
            
        if not mac_rep or not mkt_rep:
            raise ValueError(f"區域 {r_code} 缺少宏觀或板塊分析數據，請重跑 analyze_macro 與 analyze_sectors！")
            
        # Build transaction execution ledger details for the WriterAgent
        buys_summary = []
        blocked_buys_summary = []
        sells_summary = []
        try:
            with db.db_session() as conn:
                cursor = conn.cursor()
                db.execute_sql(cursor,
                    "SELECT * FROM recommendations WHERE (report_date = ? OR close_date = ?) AND region = ?",
                    "SELECT * FROM recommendations WHERE (report_date = %s OR close_date = %s) AND region = %s",
                    (report_date, report_date, r_code)
                )
                rows = cursor.fetchall()
                db_recs = [dict(r) for r in rows]
                
            for rec in db_recs:
                ticker = rec["ticker"]
                name = rec["company_name"]
                if ".TW" in ticker.upper() or ".TWO" in ticker.upper():
                    from core.tools.taiwan_stock_names import get_taiwan_stock_name
                    tw_name = get_taiwan_stock_name(ticker)
                    if tw_name and tw_name != ticker:
                        name = tw_name
                price_symbol = "$" if (".TW" not in ticker and ".TWO" not in ticker) else "NT$"
                
                # Check if it was bought (created on report_date)
                if rec["report_date"] == report_date:
                    rating = rec["rating"]
                    rec_price = rec["recommend_price"]
                    shares = rec["shares"]
                    amount = rec["invested_amount"]
                    
                    if rating in ["Buy", "Strong Buy", "Hold"]:
                        # If shares > 0, it means we actually had capital and executed a buy
                        if shares > 0:
                            weight_pct = 5.0 if rating == "Hold" else 15.0 if rating == "Buy" else 25.0 if rating == "Strong Buy" else 0.0
                            s_track = rec.get("source_track")
                            track_name = "板塊動能 Beta" if s_track == "sector_momentum" else "板塊防禦 Beta" if s_track == "sector_reversion" else "財務加速 Alpha" if s_track == "bottom_up_acceleration" else "前瞻主題" if s_track == "thematic_scan" else "未指定"
                            buys_summary.append(
                                f"- **買入建倉 {name} ({ticker})**:\n"
                                f"  - 評級: {rating}\n"
                                f"  - 選股軌道: {track_name}\n"
                                f"  - 交易單價: {price_symbol}{rec_price:.2f}\n"
                                f"  - 買入股數: {shares:.1f} 股\n"
                                f"  - 投入金額: {price_symbol}{amount:.2f}\n"
                                f"  - 當前持倉權重: {weight_pct:.1f}%\n"
                                f"  - 選股原因: {rec.get('recommend_reason')}"
                            )
                        else:
                            # Recommended but blocked / 0 shares bought
                            block_reason = "【配置限制】可用資金不足或未獲配發預算。"
                            try:
                                currency = "USD" if (".TW" not in ticker and ".TWO" not in ticker) else "TWD"
                                from core.risk.earnings_blocker import is_earnings_block_active
                                from core.agents.budget_agent import BudgetAgent
                                
                                is_blocked, next_earnings_date, biz_days = is_earnings_block_active(ticker, report_date)
                                if is_blocked:
                                    block_reason = f"【風控管制】即將於 {next_earnings_date} 公布財報（距離 {report_date} 僅 {biz_days} 個交易日），啟動財報前交易禁令，凍結買入預算。"
                                elif db.get_risk_circuit_breaker(currency):
                                    block_reason = f"【風控熔斷】偵測到 {currency} 帳戶已啟動風控熔斷，全面凍結買入預算配發。"
                                else:
                                    budget_agent = BudgetAgent()
                                    state = budget_agent.get_capital_state(currency)
                                    available = state["available_capital"]
                                    min_threshold = 100.0 if currency == "USD" else 3000.0
                                    if available < min_threshold:
                                        block_reason = f"【資金限制】{currency} 帳戶可用資金僅 {price_symbol}{available:.2f}（低於系統安全建倉門檻 {price_symbol}{min_threshold:.2f}），暫停配發預算。"
                                    elif available < rec_price:
                                        block_reason = f"【資金限制】{currency} 帳戶可用資金僅 {price_symbol}{available:.2f}（低於個股單價 {price_symbol}{rec_price:.2f}），不足購買 1 股。"
                            except Exception as block_ex:
                                print(f"[!] Warning: Failed to determine block reason for {ticker}: {block_ex}")
                                
                            s_track = rec.get("source_track")
                            track_name = "板塊動能 Beta" if s_track == "sector_momentum" else "板塊防禦 Beta" if s_track == "sector_reversion" else "財務加速 Alpha" if s_track == "bottom_up_acceleration" else "前瞻主題" if s_track == "thematic_scan" else "未指定"
                            blocked_buys_summary.append(
                                f"- **推薦但未交易 {name} ({ticker})**:\n"
                                f"  - 評級: {rating}\n"
                                f"  - 選股軌道: {track_name}\n"
                                f"  - 交易單價: {price_symbol}{rec_price:.2f}\n"
                                f"  - 執行股數: 0.0 股\n"
                                f"  - 投入金額: {price_symbol}0.00\n"
                                f"  - 未執行原因: {block_reason}\n"
                                f"  - 選股原因: {rec.get('recommend_reason')}"
                            )
                
                # Check if it was sold (closed on report_date)
                if rec["close_date"] == report_date:
                    rec_price = rec["recommend_price"]
                    close_price = rec["close_price"]
                    shares = rec["shares"]
                    amount = rec["invested_amount"]
                    pnl = rec["pnl"]
                    perf = rec["performance"] * 100
                    
                    action = "停損避險平倉 (Stop Loss)" if perf < 0 else "達到目標價獲利平倉 (Take Profit)"
                    sells_summary.append(
                        f"- **賣出平倉 {name} ({ticker})**:\n"
                        f"  - 執行類型: {action}\n"
                        f"  - 買入單價: {price_symbol}{rec_price:.2f}\n"
                        f"  - 平倉單價: {price_symbol}{close_price:.2f}\n"
                        f"  - 交易股數: {shares:.1f} 股\n"
                        f"  - 實現盈虧: {price_symbol}{pnl:+.2f} ({perf:+.2f}%)"
                    )
        except Exception as query_ex:
            print(f"[!] Warning: Failed to query recommendations for report: {query_ex}")

        portfolio_ledger_context = "【本週實戰帳戶交易與持倉調整明細】\n"
        if buys_summary or blocked_buys_summary or sells_summary:
            if buys_summary:
                portfolio_ledger_context += "本週買入交易紀錄：\n" + "\n".join(buys_summary) + "\n"
            if blocked_buys_summary:
                portfolio_ledger_context += "\n本週推薦但因風控/資金限制未執行交易紀錄：\n" + "\n".join(blocked_buys_summary) + "\n"
            if sells_summary:
                portfolio_ledger_context += "\n本週賣出平倉紀錄：\n" + "\n".join(sells_summary) + "\n"
        else:
            portfolio_ledger_context += "本週帳戶無進行任何買入或平倉交易，維持原有持倉。\n"

        print_info(f"✍ 正在調度總編輯代理人 (WriterAgent) 進行【{region_name}】專用策略週報撰寫...")
        writer_agent = WriterAgent()
        time.sleep(3)
        
        date_range_label = f"{report_date} (本週數據涵蓋區間: {start_date_str} 至 {end_date_str})" if start_date_str else report_date
        
        final_markdown = writer_agent.synthesize(
            date_str=date_range_label,
            macro_reports=[mac_rep],
            liquidity_reports=[liq_rep],
            market_reports=[mkt_rep],
            stock_reports=[stk_rep or "本週暫無推薦股票分析。"],
            reflection_report=reflection_directives,
            candidate_summary=candidate_summary,
            portfolio_ledger=portfolio_ledger_context
        )
        
        # 防禦性清理：移除非 Markdown 主要內容的對話性問候贅語（如「好的，總編輯...」）
        final_markdown = final_markdown.strip()
        if "#" in final_markdown:
            final_markdown = final_markdown[final_markdown.index("#"):]
            
        # 移除了所有大項及小項標題前面可能被 LLM 誤加的小圖示與 Emoji
        import re
        cleaned_lines = []
        for line in final_markdown.splitlines():
            if line.strip().startswith("#"):
                match = re.match(r'^(\s*#+)\s*(.*)$', line)
                if match:
                    hashes, title = match.groups()
                    # 匹配高 Unicode 區段的符號，包含各種小圖示、Emoji 等，並將其與其後的空白一併移除
                    cleaned_title = re.sub(r'^[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50\u2100-\u2bff\u2000-\u32ff]\s*', '', title)
                    cleaned_title = cleaned_title.strip()
                    cleaned_lines.append(f"{hashes} {cleaned_title}")
                else:
                    cleaned_lines.append(line)
            else:
                cleaned_lines.append(line)
        final_markdown = "\n".join(cleaned_lines)
            
        print_info(f"[{region_name}] 總編輯生成的原始週報長度: {len(final_markdown)} 字元（已清理標題圖示）。")
        
        try:
            db.save_agent_inference_log(
                rec_id=None,
                agent_name="WriterAgent",
                ticker=None,
                input_prompt=writer_agent.last_prompt,
                output_response=final_markdown,
                prompt_version=writer_agent.prompt_version,
                report_date=report_date
            )
        except Exception as log_ex:
            print(f"[!] Warning: 記錄 WriterAgent 推論日誌失敗: {log_ex}")
            
        r_start_date = start_date_str
        r_end_date = end_date_str
        try:
            r_bench = yf_tool.get_benchmark_performance(r_code)
            r_start_date = r_bench.get("start_date", r_start_date)
            r_end_date = r_bench.get("end_date", r_end_date)
        except Exception:
            pass
            
        if r_start_date and r_end_date:
            date_range_text = f"**Data Calculation Range: {r_start_date} to {r_end_date} (6 Trading Days, 5-Day Returns)**" if REPORT_LANGUAGE == "EN" else f"**本週數據涵蓋區間：{r_start_date} 至 {r_end_date}，共 6 個交易日 (計算 5 日累積收益)**"
            
            if REPORT_LANGUAGE == "EN":
                r_lbl = "US Market" if r_code == "US" else "Taiwan Market"
                region_title = f"# Weekly {r_lbl} Investment Strategy & Multi-Agent Advisory Report {report_date}"
                final_markdown = final_markdown.replace(f"# Weekly Global Investment Strategy & Multi-Agent Advisory Report {report_date}", region_title)
                final_markdown = final_markdown.replace(f"# 🌍 Weekly Global Investment Strategy & Multi-Agent Advisory Report {report_date}", region_title)
                if not final_markdown.startswith("#"):
                    final_markdown = f"{region_title}\n{date_range_text}\n" + final_markdown
                else:
                    lines = final_markdown.splitlines()
                    final_markdown = f"{region_title}\n{date_range_text}\n" + "\n".join(lines[1:])
            else:
                r_lbl = "美股" if r_code == "US" else "台股"
                region_title = f"# 每週{r_lbl}投資策略與多維度決策週報 {report_date}"
                final_markdown = final_markdown.replace(f"# 每週全球投資策略與多維度決策週報 {report_date}", region_title)
                final_markdown = final_markdown.replace(f"# 🌍 每週全球投資策略與多維度決策週報 {report_date}", region_title)
                if not final_markdown.startswith("#"):
                    final_markdown = f"{region_title}\n{date_range_text}\n" + final_markdown
                else:
                    lines = final_markdown.splitlines()
                    final_markdown = f"{region_title}\n{date_range_text}\n" + "\n".join(lines[1:])
                    
        final_html = markdown.markdown(final_markdown, extensions=['fenced_code', 'tables'])
        
        report_filename = f"{report_date}_{timestamp_suffix}_{r_code}_{REPORT_LANGUAGE}"
        db.save_report(report_filename, [r_code], final_markdown, final_html)
        
        md_file_path = daily_reports_dir / f"{report_filename}.md"
        html_file_path = daily_reports_dir / f"{report_filename}.html"
        
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(final_markdown)
        with open(html_file_path, "w", encoding="utf-8") as f:
            f.write(final_html)
            
        print_success(f"🎉 恭喜！【{region_name}】專區投資決策白皮書已成功產出並存檔！")
        print_success(f"💾 Markdown 存檔路徑：{md_file_path}")
        print_success(f"💾 HTML 存檔路徑：{html_file_path}")

def run_screener_report_phase(regions_list: list, report_date: str, timestamp_suffix: str, daily_reports_dir: Path, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 8/10] 量化選股掃描報告產出 (screener_report)")
    print_info("==================================================")
    
    screener_instance = yf_tool.get_screener_instance()
    
    for r_code in regions_list:
        region_name = REGIONS[r_code]["name"]
        screener_instance.clear_history()
        
        history_loaded = False
        sector_rankings = []
        if "analysis" in state and r_code in state["analysis"]:
            r_analysis = state["analysis"][r_code]
            sector_rankings = r_analysis.get("sector_rankings", [])
            if "screener_session_history" in r_analysis:
                screener_instance.session_history.extend(r_analysis["screener_session_history"])
                history_loaded = True
                
        if "screener_session_history" in state:
            filtered_history = [item for item in state["screener_session_history"] if item.get("region") == r_code]
            if filtered_history:
                screener_instance.session_history.extend(filtered_history)
                history_loaded = True
                
        if not history_loaded:
            print_warning(f"[{region_name}] 快取狀態中未找到選股歷史紀錄，將跳過或生成空的選股報告。")
            
        try:
            screener_md, screener_html = screener_instance.generate_report(report_date, sector_rankings=sector_rankings)
            if screener_md:
                # --- 動態注入三軌融合選股總覽與專章明細至量化報告 ---
                try:
                    with db.db_session() as conn:
                        cursor = conn.cursor()
                        db.execute_sql(cursor,
                            "SELECT ticker, company_name, source_track, recommend_reason, recommend_price, rating FROM recommendations WHERE report_date = ? AND region = ?",
                            "SELECT ticker, company_name, source_track, recommend_reason, recommend_price, rating FROM recommendations WHERE report_date = %s AND region = %s",
                            (report_date, r_code)
                        )
                        rows = cursor.fetchall()
                        recs = [dict(r) for r in rows]
                    
                    # 1. 構造總覽表 (Synthesis Overview Table)
                    synthesis_section = ""
                    if recs:
                        synthesis_section = "\n## 三軌融合最終推薦標的總覽 (Three-Track Unified Recommendations)\n\n"
                        synthesis_section += "本週系統通過 **三軌融合選股模型**（軌道一：板塊動能/防禦 Beta、軌道二：財務加速 Alpha、軌道三：LLM 前瞻主題掃描）進行全方位篩選，最終選出的代表性推薦標的明細如下：\n\n"
                        synthesis_section += "| 股票代碼 | 企業名稱 | 推薦評級 | 建倉單價 | 選股軌道 (Source Track) | 核心篩選理由 (Thesis) |\n"
                        synthesis_section += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                        
                        for r in recs:
                            ticker = r["ticker"]
                            name = r["company_name"]
                            if ".TW" in ticker.upper() or ".TWO" in ticker.upper():
                                from core.tools.taiwan_stock_names import get_taiwan_stock_name
                                tw_name = get_taiwan_stock_name(ticker)
                                if tw_name and tw_name != ticker:
                                    name = tw_name
                            rating = r["rating"]
                            price = r["recommend_price"]
                            track = r["source_track"]
                            reason = r["recommend_reason"]
                            
                            price_symbol = "$" if (".TW" not in ticker and ".TWO" not in ticker) else "NT$"
                            track_name = "前瞻主題掃描" if track == "thematic_scan" else "財務加速 Alpha" if track == "bottom_up_acceleration" else "板塊防禦 Beta (均值回歸)" if track == "sector_reversion" else "板塊動能 Beta (趨勢跟隨)" if track == "sector_momentum" else "未指定"
                            
                            synthesis_section += f"| `{ticker}` | {name} | **{rating}** | {price_symbol}{price:.2f} | `{track_name}` | {reason} |\n"
                        
                        synthesis_section += "\n---\n"
                        
                    # 2. 構造軌道二專章 (Track 2 Chapter)
                    track2_candidates = r_analysis.get("track2_candidates", [])
                    track2_section = "\n## 軌道二：全市場財務加速篩選明細 (Financial Acceleration Alpha)\n\n"
                    track2_section += "本軌道採用 **自下而上 (Bottom-Up) 財務動能掃描**，深入全市場個股的財務基本面，尋找營收或盈餘呈現「拐點加速」的高增長黑馬股（篩選門檻：營收年增率 > 15% 或 EPS 年增率 > 15%）。\n\n"
                    track2_section += "> [!NOTE]\n"
                    track2_section += "> **指標定義說明**：表格中的「營收年增率」與「EPS 年增率」指該企業**「最新已公布之季度 (Most Recent Quarter, MRQ)」相較於「去年同期 (YoY)」的增長率**（數據源自 Yahoo Finance 季度數據）。因各企業財報發布時程不同，該指標反映最新已被收錄的單季財務同比增速。\n\n"
                    
                    if track2_candidates:
                        track2_section += "| 排名 | 股票代碼 | 企業名稱 | 營收年增率 | EPS 年增率 | PE 本益比 | PEG 估值 | 站上 50日線? | 綜合得分 |\n"
                        track2_section += "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n"
                        for idx, cand in enumerate(track2_candidates, 1):
                            ticker = cand["ticker"]
                            name = cand["name"]
                            if ".TW" in ticker.upper() or ".TWO" in ticker.upper():
                                from core.tools.taiwan_stock_names import get_taiwan_stock_name
                                tw_name = get_taiwan_stock_name(ticker)
                                if tw_name and tw_name != ticker:
                                    name = tw_name
                            
                            score = cand["avg_growth"] * 100
                            rg_val, eg_val = "N/A", "N/A"
                            pe_val = cand.get("pe_ratio")
                            peg_val = cand.get("peg_ratio")
                            price_val = cand.get("current_price")
                            sma_val = cand.get("fifty_day_sma")
                            
                            pe_str = f"{pe_val:.1f}" if pe_val is not None else "N/A"
                            peg_str = f"{peg_val:.2f}" if peg_val is not None else "N/A (轉機股)"
                            above_sma = "is_above" if (price_val is not None and sma_val is not None and price_val >= sma_val) else "is_below"
                            above_sma_text = "是" if above_sma == "is_above" else "否"
                            
                            try:
                                cache_key = f"financials_{ticker.upper()}"
                                from core.config import CACHE_DIR
                                f_data = get_cached_data(CACHE_DIR, cache_key, ttl_hours=24)
                                if f_data:
                                    rg = f_data.get("revenue_growth")
                                    eg = f_data.get("eps_growth")
                                    if rg is not None: rg_val = f"{rg*100:+.1f}%"
                                    if eg is not None: eg_val = f"{eg*100:+.1f}%"
                            except Exception:
                                pass
                            track2_section += f"| {idx} | `{ticker}` | {name} | {rg_val} | {eg_val} | {pe_str} | {peg_str} | {above_sma_text} | {score:+.1f} |\n"
                    else:
                        track2_section += "> [!WARNING]\n> **本週全市場無符合篩選標準（營收/EPS 年增率 > 15% 或符合 PEG/50日均線過濾）的財務加速個股。**\n"
                    track2_section += "\n---\n"
                    
                    # 3. 構造軌道三專章 (Track 3 Chapter)
                    track3_section = "\n## 軌道三：前瞻主題與概念股挖掘明細 (Forward-Looking Thematic Scan)\n\n"
                    track3_section += "本軌道採用 **前瞻性大模型主題掃描**，藉由分析最近 7 天全球與區域總經政策、券商投研報告及產業鏈動態，萃取出最具爆發力的前瞻產業主題，並與全市場股池進行即時語意比對，挑選出最具代表性的龍頭概念股。\n\n"
                    
                    themes = r_analysis.get("themes", [])
                    if themes:
                        track3_section += "#### 💡 本週提煉之三大前瞻投資主題：\n"
                        for idx, t in enumerate(themes, 1):
                            track3_section += f"{idx}. **{t}**\n"
                        track3_section += "\n"
                        
                    thematic_recs = [r for r in recs if r.get("source_track") == "thematic_scan"]
                    if thematic_recs:
                        track3_section += "#### 🎯 主題概念股語意匹配明細：\n"
                        track3_section += "| 股票代碼 | 企業名稱 | 推薦評級 | 契合主題與核心推薦邏輯 |\n"
                        track3_section += "| :--- | :--- | :--- | :--- |\n"
                        for r in thematic_recs:
                            ticker = r["ticker"]
                            name = r["company_name"]
                            if ".TW" in ticker.upper() or ".TWO" in ticker.upper():
                                from core.tools.taiwan_stock_names import get_taiwan_stock_name
                                tw_name = get_taiwan_stock_name(ticker)
                                if tw_name and tw_name != ticker:
                                    name = tw_name
                            rating = r["rating"]
                            reason = r["recommend_reason"]
                            track3_section += f"| `{ticker}` | {name} | **{rating}** | {reason} |\n"
                    else:
                        track3_section += "> [!WARNING]\n> **本週無符合前瞻產業主題匹配之概念股。**\n"
                    track3_section += "\n---\n"
                    
                    # 4. 進行整體報告重組與拼接
                    if "## 各板塊強勢個股動態篩選明細" in screener_md:
                        # 注入總覽，並重命名軌道一標題
                        screener_md = screener_md.replace(
                            "## 各板塊強勢個股動態篩選明細",
                            synthesis_section + "## 軌道一：焦點板塊動態篩選明細 (Sector Beta)"
                        )
                        # 拼接軌道二與軌道三專章
                        if "## 免責聲明 (Disclaimer)" in screener_md:
                            screener_md = screener_md.replace(
                                "## 免責聲明 (Disclaimer)",
                                track2_section + track3_section + "## 免責聲明 (Disclaimer)"
                            )
                        elif "## 免責聲明" in screener_md:
                            screener_md = screener_md.replace(
                                "## 免責聲明",
                                track2_section + track3_section + "## 免責聲明"
                            )
                        else:
                            screener_md = screener_md + "\n" + track2_section + track3_section
                            
                    elif "## Selected Sector Strong Stock Screening Details" in screener_md:
                        screener_md = screener_md.replace(
                            "## Selected Sector Strong Stock Screening Details",
                            synthesis_section + "## Track 1: Focus Sector Dynamic Screening Details (Sector Beta)"
                        )
                        if "## Disclaimer" in screener_md:
                            screener_md = screener_md.replace(
                                "## Disclaimer",
                                track2_section + track3_section + "## Disclaimer"
                            )
                        else:
                            screener_md = screener_md + "\n" + track2_section + track3_section
                            
                    # 重新渲染 HTML
                    import markdown as md_parser
                    screener_html = md_parser.markdown(screener_md, extensions=['fenced_code', 'tables'])
                    
                except Exception as inject_ex:
                    print(f"[!] Warning: 無法將三軌融合總覽與專章注入選股報告: {inject_ex}")
                    
                screener_filename = f"{report_date}_{timestamp_suffix}_screener_report_{r_code}_{REPORT_LANGUAGE}"
                db.save_report(screener_filename, [r_code], screener_md, screener_html)
                
                s_md_path = daily_reports_dir / f"{screener_filename}.md"
                s_html_path = daily_reports_dir / f"{screener_filename}.html"
                
                with open(s_md_path, "w", encoding="utf-8") as f:
                    f.write(screener_md)
                with open(s_html_path, "w", encoding="utf-8") as f:
                    f.write(screener_html)
                    
                print_success(f"🎉 恭喜！【{region_name}】量化選股掃描報告已成功產出並存檔！")
                print_success(f"💾 Markdown 存檔路徑：{s_md_path}")
                print_success(f"💾 HTML 存檔路徑：{s_html_path}")
                print_success(f"💾 報告已成功同步寫入 {DB_TYPE.upper()} 數據庫。")
            else:
                print_warning(f"[{region_name}] 本次執行未包含任何選股歷史紀錄，跳過選股報告生成。")
        except Exception as e:
            print_error(f"[{region_name}] 產出量化選股報告時發生錯誤: {e}")

def run_notify_phase(regions_list: list, report_date: str, state: dict):
    print_info("==================================================")
    print_info(f"[Phase 9/10] LINE 通知推送 (notify)")
    print_info("==================================================")
    try:
        from core.tools.line_notifier import LineNotifier
        notifier = LineNotifier()
        
        all_active = db.get_active_recommendations()
        today_recs = [rec for rec in all_active if rec.get("report_date") == report_date]
        
        regime_msg = ""
        for r_code in regions_list:
            region_name = REGIONS[r_code]["name"]
            reg_val = "UNKNOWN"
            if "analysis" in state and r_code in state["analysis"]:
                reg_val = state["analysis"][r_code].get("macro_regime", "UNKNOWN")
            emoji = "🟢" if "BULL" in reg_val else ("🔴" if "BEAR" in reg_val else "🟡")
            regime_msg += f"- {region_name}專區：{reg_val} {emoji}\n"
            
        recs_msg = ""
        if today_recs:
            for i, rec in enumerate(today_recs):
                recs_msg += (
                    f"{i+1}. 📌 {rec['ticker']} ({rec['company_name']})\n"
                    f"   - 評級: {rec.get('rating', 'BUY')} | 推薦價: {rec['recommend_price']:.2f}\n"
                    f"   - 區間: [{rec['stop_loss'] or 0:.1f} - {rec['target_price'] or 0:.1f}]\n"
                )
        else:
            recs_msg = "本週經多代理人評估，無新增推薦買入個股（在庫持股維持不變）。\n"
            
        line_msg = (
            f"📰 【投資研究代理人·每週策略週報完成】\n\n"
            f"報告日期：{report_date} 📅\n\n"
            f"🌐 **區域市場情境 (Regime)**：\n"
            f"{regime_msg}\n"
            f"📈 **本週最新量化決策強勢配置清單**：\n"
            f"{recs_msg}\n"
            f"💾 HTML 策略研報已生成並安全寫入 {DB_TYPE.upper()} 數據庫。\n"
            f"檔案已儲存至您本地的週報歸檔庫。📁\n\n"
            f"祝您本週交易順利，嚴格執行風控紀律！🚀"
        )
        notifier.send_message(line_msg)
        print_success("LINE 通知推送成功。")
    except Exception as line_ex:
        print_error(f"LINE 週報推送失敗: {line_ex}")

def run_prompt_evolve_phase():
    print_info("==================================================")
    print_info(f"[Phase 10/10] 底層指令系統升級 (prompt_evolve)")
    print_info("==================================================")
    evolve_active_prompts()
    print_success("[✓] 底層指令系統升級執行完成。")
