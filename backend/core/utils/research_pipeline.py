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

def print_info(msg): print(f"\033[94m[*] {msg}\033[0m")
def print_warning(msg): print(f"\033[93m[!] {msg}\033[0m")
def print_success(msg): print(f"\033[92m[✓] {msg}\033[0m")
def print_error(msg): print(f"\033[91m[✗] {msg}\033[0m")


def research_and_track_asset(
    ticker: str,
    company_name: str,
    region_code: str,
    market_regime: str,
    macro_report: str,
    reflection_directives: str,
    report_date: str,
    save_to_db: bool = True,
    is_weekly_pipeline: bool = True,
    custom_recommend_reason: str = None
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
    stock_report = fundamental_agent.analyze(ticker, company_name, financials, news_analysis, combined_context, market_regime=market_regime)
    time.sleep(2)
    
    # 解析輸出參數
    target_p = curr_price * 1.15
    stop_l = curr_price * 0.92
    rating = "Hold"
    suggested_weight = None
    
    lines = stock_report.split("\n")
    for line in lines:
        if "目標價" in line or "中線目標價" in line:
            parsed_val = extract_price_from_line(line, curr_price, is_target=True)
            if parsed_val > 0.0: target_p = parsed_val
        elif "停損點" in line or "防禦停損點" in line:
            parsed_val = extract_price_from_line(line, curr_price, is_target=False)
            if parsed_val > 0.0: stop_l = parsed_val
        elif "投資評級" in line:
            line_upper = line.upper()
            if "STRONG BUY" in line_upper or "強烈買入" in line_upper:
                rating = "Strong Buy"
            elif "BUY" in line_upper or "買入" in line_upper:
                rating = "Buy"
            elif "HOLD" in line_upper or "持有" in line_upper or "NEUTRAL" in line_upper or "觀望" in line_upper:
                rating = "Hold"
            elif "SELL" in line_upper or "賣出" in line_upper or "避開" in line_upper:
                rating = "Sell"
        elif "建議持倉權重" in line or "持倉權重" in line or "建議權重" in line:
            weight_match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
            if weight_match:
                try:
                    suggested_weight = float(weight_match.group(1)) / 100.0
                except ValueError:
                    pass
                    
    if suggested_weight is None or suggested_weight <= 0.0:
        if rating == "Strong Buy": suggested_weight = 0.25
        elif rating == "Buy": suggested_weight = 0.15
        elif rating == "Hold": suggested_weight = 0.05
        elif rating == "Sell": suggested_weight = 0.0
        else: suggested_weight = 0.0
        
    invested_amount = 0.0
    shares = 0.0
    rec_id = None
    
    # 判斷是否需要進行寫入資料庫
    should_save = False
    if save_to_db:
        if is_weekly_pipeline:
            should_save = True
        elif rating in ["Buy", "Strong Buy"]:
            should_save = True
            
    if should_save:
        if rating in ["Buy", "Strong Buy"]:
            from core.agents.budget_agent import BudgetAgent
            budget_agent = BudgetAgent()
            invested_amount, shares = budget_agent.allocate_budget(ticker, region_code, curr_price, custom_weight=suggested_weight)
        
        reason = custom_recommend_reason or f"Aegis-MAQS 自動分析。當前大盤狀態: {market_regime}。"
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
                shares=shares
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
                    prompt_version=fundamental_agent.prompt_version
                )
                db.save_agent_inference_log(
                    rec_id=rec_id,
                    agent_name="NewsAgent",
                    ticker=ticker,
                    input_prompt=news_agent.last_prompt,
                    output_response=news_analysis,
                    prompt_version=news_agent.prompt_version
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

def run_regional_reflection(region_code: str, report_date: str) -> str:
    """
    Gathers active and closed recommendations specific to a region,
    measures them against regional benchmark index, and triggers ReflectionAgent
    to produce region-specific corrective directives.
    """
    print_info(f"[{region_code}] 正在啟動區域專屬歷史回測與決策反思...")
    
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
    reflection_report = reflection_agent.analyze(recent_recs, benchmark)
    
    # [Prompt Evolution Integration] Log ReflectionAgent's inference
    try:
        db.save_agent_inference_log(
            rec_id=None,
            agent_name="ReflectionAgent",
            ticker=None,
            input_prompt=reflection_agent.last_prompt,
            output_response=reflection_report,
            prompt_version=reflection_agent.prompt_version
        )
    except Exception as log_ex:
        print(f"[!] Warning: 記錄 ReflectionAgent 推論日誌失敗: {log_ex}")
        
    print_success(f"[{region_code}] 區域專屬決策反思分析完成！")
    return reflection_report

def run_regional_analysis(region_code: str, report_date: str, reflection_directives: str) -> tuple:
    """
    Executes the analytical pipeline for a specific country/region:
    Macro Analysis -> Sector Rankings -> News Scans -> Fundamental Valuation & Stock Recommendation.
    """
    region_name = REGIONS[region_code]["name"]
    print_info(f"==================================================")
    print_info(f"開始分析區域市場：{region_name} ({region_code})...")
    
    # 1. Get Benchmark Performance
    benchmark_data = yf_tool.get_benchmark_performance(region_code)
    
    # 2. Get Macroeconomic News
    macro_news = search_tool.get_macro_news(region_code, max_items=5)
    
    # 3. Run Macro Agent
    print_info(f"[{region_name}] 正在執行總體經濟分析...")
    macro_agent = MacroAgent()
    raw_macro_report = macro_agent.analyze(region_name, benchmark_data, macro_news)
    
    # [Prompt Evolution Integration] Log MacroAgent's inference
    try:
        db.save_agent_inference_log(
            rec_id=None,
            agent_name="MacroAgent",
            ticker=None,
            input_prompt=macro_agent.last_prompt,
            output_response=raw_macro_report,
            prompt_version=macro_agent.prompt_version
        )
    except Exception as log_ex:
        print(f"[!] Warning: 記錄 MacroAgent 推論日誌失敗: {log_ex}")
        
    time.sleep(3)  # Respect free tier rate limits (15 RPM)
    
    # Parse market regime from macro report
    regime_match = re.search(r"\[MARKET_REGIME:\s*(BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]", raw_macro_report)
    market_regime = regime_match.group(1) if regime_match else "BULL_RISK_ON"
    print_success(f"[{region_name}] 偵測到宏觀市場狀態標籤：{market_regime}")
    
    # Clean the raw tag from macro_report so it doesn't show in the final human-readable report
    macro_report = re.sub(r"\[MARKET_REGIME:\s*(BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]\s*", "", raw_macro_report)
    
    # 4. Get Sector Rankings
    sector_rankings = yf_tool.get_sector_rankings(region_code)
    
    # 5. Run Market Agent with dynamic sector news integration
    print_info(f"[{region_name}] 正在獲取最強勢板塊之產業趨勢新聞...")
    sector_news = []
    try:
        # Find top 2 sectors (excluding broad market if possible to focus on specific industries)
        c_sectors = [sec for sec in sector_rankings if "Broad Market" not in sec["label"]]
        if not c_sectors:
            c_sectors = sector_rankings
            
        top_2_sectors = c_sectors[:2]
        for sec in top_2_sectors:
            label = sec["label"]
            # Extract characters before parenthesis, e.g. "科技" from "科技 (Technology)"
            match = re.match(r"^([^\(]+)", label)
            sector_name = match.group(1).strip() if match else label
            
            if region_code == "US":
                query = f"US {sector_name} industry news when:7d"
                lang, reg = "en-US", "US"
            else:
                query = f"台灣 {sector_name} 產業 新聞 when:7d"
                lang, reg = "zh-TW", "TW"
                
            print_info(f"   - 正在檢索板塊【{label}】產業動向: '{query}'")
            news_items = search_tool.search_news(query, max_items=2, language=lang, region=reg)
            sector_news.extend(news_items)
            time.sleep(2)  # Respect free tier rate limits
    except Exception as sector_news_ex:
        print_error(f"[{region_name}] 獲取板塊相關產業新聞時失敗: {sector_news_ex}")
        
    print_info(f"[{region_name}] 正在進行板塊強度排序與資金流向分析...")
    market_agent = MarketAgent()
    market_report = market_agent.analyze(region_name, sector_rankings, sector_news)
    
    # [Prompt Evolution Integration] Log MarketAgent's inference
    try:
        db.save_agent_inference_log(
            rec_id=None,
            agent_name="MarketAgent",
            ticker=None,
            input_prompt=market_agent.last_prompt,
            output_response=market_report,
            prompt_version=market_agent.prompt_version
        )
    except Exception as log_ex:
        print(f"[!] Warning: 記錄 MarketAgent 推論日誌失敗: {log_ex}")
        
    time.sleep(3)  # Respect free tier rate limits (15 RPM)
    
    # 6. Parse Top Recommended Sectors/Themes from Market Agent's report using LLM guidance
    max_scan_sectors = max(MAX_SECTORS_PER_REGION, MAX_STOCKS_PER_REGION)
    top_etfs = [sec["ticker"] for sec in sector_rankings[:max_scan_sectors]]
    print_info(f"[{region_name}] 本週焦點強勢板塊 ETF (自適應擴大)：{', '.join(top_etfs)}")
    
    # 7. Dynamic Target Discovery & Fundamental Valuation
    stock_analysis_reports = []
    stocks_analyzed = 0
    
    # Scrape news & evaluate representative stock assets for the top performing sector ETFs
    for etf_ticker in top_etfs:
        if stocks_analyzed >= MAX_STOCKS_PER_REGION:
            break
            
        # Get sector configuration (prioritize database-driven configuration)
        sector_config = db.get_active_sectors(region_code).get(etf_ticker, {})
        target_type = sector_config.get("target_type", "constituents")
        
        if target_type == "proxy":
            # If target_type is proxy, we target the ETF itself directly
            target_stocks = [{
                "ticker": etf_ticker,
                "name": f"{sector_config.get('name', etf_ticker)}"
            }]
            print_info(f"[{region_name}] 板塊 {etf_ticker} 配置為直接投資 ETF 標的 (target_type: proxy)。")
        else:
            # Otherwise, target constituent stocks
            representative_stocks = yf_tool.get_etf_holdings(etf_ticker, region=region_code, market_regime=market_regime)
            # Determine how many stocks to pull from this sector to respect our region limit
            stocks_to_analyze = max(1, MAX_STOCKS_PER_REGION - stocks_analyzed)
            # Grab at most 2 per sector for diversity if total limit allows, otherwise grab remaining
            stocks_to_analyze = min(stocks_to_analyze, 2)
            target_stocks = representative_stocks[:stocks_to_analyze]
            print_info(f"[{region_name}] 板塊 {etf_ticker} 配置為投資旗下成分股 (target_type: constituents)。")
        
        for stock in target_stocks:
            ticker = stock["ticker"]
            name = stock["name"]
            print_info(f"[{region_name}] 🔍 正在對目標標的進行深度研究：{name} ({ticker})...")
            
            custom_reason = f"直接買入強勢板塊 ETF {etf_ticker}，獲取行業平均 Beta 收益。" if target_type == "proxy" else f"板塊 {etf_ticker} 強勢動能領頭，精選旗下龍頭成分股。"
            
            res = research_and_track_asset(
                ticker=ticker,
                company_name=name,
                region_code=region_code,
                market_regime=market_regime,
                macro_report=macro_report,
                reflection_directives=reflection_directives,
                report_date=report_date,
                save_to_db=True,
                custom_recommend_reason=custom_reason
            )
            
            if not res:
                continue
                
            # If target_type is proxy, record in the screener report now with enriched financials and weekly return!
            if target_type == "proxy":
                try:
                    etf_rank = next((sec for sec in sector_rankings if sec["ticker"] == etf_ticker), {})
                    weekly_mom = etf_rank.get("weekly_return", 0.0)
                    screener_instance = yf_tool.get_screener_instance()
                    screener_instance.record_proxy_etf(etf_ticker, region_code, financials=res["financials"], weekly_return=weekly_mom)
                except Exception as ex:
                    print_warning(f"記錄篩選報告 proxy ETF 失敗: {ex}")
                    
            stock_analysis_reports.append(res["stock_report"])
            print_success(f"標的 {ticker} 推薦參數與預算已成功寫入回測帳本！(現價: {res['financials'].get('current_price', 0.0):.2f} | 分配預算: {res['invested_amount']:.2f} | 股數: {res['shares']:.2f})")
            stocks_analyzed += 1
                
    return macro_report, market_report, "\n\n---\n\n".join(stock_analysis_reports), market_regime

def run_report_pipeline(args, report_date, regions_list, timestamp_suffix, daily_reports_dir):
    print_success("==================================================")
    print_success("🚀 歡迎使用：投資研究代理人自動化研報系統 (CLI)")
    print_success(f"執行日期：{report_date} | 目標市場：{', '.join(regions_list)}")
    print_success("==================================================")
    
    # Check if a report for today already exists to prevent duplicate LLM calls
    existing_report = db.get_report_by_date(report_date)
    if existing_report and not args.force:
        print_warning(f"偵測到資料庫中已存在【{report_date}】的投資報告。")
        print_warning("使用 --force 參數可強制重新運行並覆蓋。")
        sys.exit(0)
        
    # Step 1: Defensive pre-reflection price check & closing using our 0-token check_portfolio logic
    try:
        run_portfolio_check(report_date)
        time.sleep(2)  # Cooldown
    except Exception as e:
        print_warning(f"全域持股前置對帳時發生輕微異常（將繼續使用現有資料庫資料進行反思）: {e}")
        
    # Retrieve the exact trading date range for this week's data to ensure algorithmic transparency
    start_date_str = ""
    end_date_str = ""
    try:
        us_bench = yf_tool.get_benchmark_performance("US")
        start_date_str = us_bench.get("start_date", "")
        end_date_str = us_bench.get("end_date", "")
    except Exception as e:
        print_warning(f"取得大盤本週計算區間失敗: {e}")

    # Step 2: Execute macro, sector, news, and fundamental analysis FOR EACH region, and compile split reports
    analyzed_successfully = 0
    regional_regimes = {}
    
    for r_code in regions_list:
        if r_code not in REGIONS:
            print_error(f"不支援的國家區域：{r_code}，跳過。")
            continue
            
        region_name = REGIONS[r_code]["name"]
        print_info(f"\n==================================================")
        print_info(f"📍 啟動國家/區域獨立分析：{region_name} ({r_code})")
        print_info(f"==================================================")
        
        try:
            # A. Run region-specific portfolio reflection and backtesting
            try:
                reflection_directives = run_regional_reflection(r_code, report_date)
                time.sleep(3)  # Cooldown
            except Exception as ex:
                print_error(f"[{r_code}] 執行區域專屬自我反思時失敗: {ex}")
                reflection_directives = "（本區域目前尚無歷史交易紀錄，暫無自我反思修正指令。請採用標準安全邊際進行基本面估值。）"
                
            # Run the analytical pipeline for this specific region
            mac_rep, mkt_rep, stk_rep, regime = run_regional_analysis(r_code, report_date, reflection_directives)
            regional_regimes[region_name] = regime
            
            # Step 3: Run Writer Agent (Chief Editor) to synthesize THIS region's report independently!
            print_info(f"✍ 正在調度總編輯代理人 (WriterAgent) 進行【{region_name}】專用策略週報撰寫...")
            writer_agent = WriterAgent()
            time.sleep(3)  # Rate limit cool-down
            
            date_range_label = f"{report_date} (本週數據涵蓋區間: {start_date_str} 至 {end_date_str})" if start_date_str else report_date
            
            final_markdown = writer_agent.synthesize(
                date_str=date_range_label,
                macro_reports=[mac_rep],
                market_reports=[mkt_rep],
                stock_reports=[stk_rep],
                reflection_report=reflection_directives
            )
            print_info(f"[{region_name}] 總編輯生成的原始週報長度: {len(final_markdown)} 字元。")
            
            # [Prompt Evolution Integration] Log WriterAgent's inference
            try:
                db.save_agent_inference_log(
                    rec_id=None,
                    agent_name="WriterAgent",
                    ticker=None,
                    input_prompt=writer_agent.last_prompt,
                    output_response=final_markdown,
                    prompt_version=writer_agent.prompt_version
                )
            except Exception as log_ex:
                print(f"[!] Warning: 記錄 WriterAgent 推論日誌失敗: {log_ex}")
            
            # Physically override the title to customize it per-region and force calculations date range
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
                    region_title = f"# 🌍 Weekly {r_lbl} Investment Strategy & Multi-Agent Advisory Report {report_date}"
                    final_markdown = final_markdown.replace(f"# 🌍 Weekly Global Investment Strategy & Multi-Agent Advisory Report {report_date}", region_title)
                    # Safe fallback override
                    if not final_markdown.startswith("#"):
                        final_markdown = f"{region_title}\n{date_range_text}\n" + final_markdown
                    else:
                        lines = final_markdown.splitlines()
                        final_markdown = f"{region_title}\n{date_range_text}\n" + "\n".join(lines[1:])
                else:
                    r_lbl = "美股" if r_code == "US" else "台股"
                    region_title = f"# 🌍 每週{r_lbl}投資策略與多維度決策週報 {report_date}"
                    final_markdown = final_markdown.replace(f"# 🌍 每週全球投資策略與多維度決策週報 {report_date}", region_title)
                    # Safe fallback override
                    if not final_markdown.startswith("#"):
                        final_markdown = f"{region_title}\n{date_range_text}\n" + final_markdown
                    else:
                        lines = final_markdown.splitlines()
                        final_markdown = f"{region_title}\n{date_range_text}\n" + "\n".join(lines[1:])
            
            # Convert synthesized Markdown to HTML
            final_html = markdown.markdown(final_markdown, extensions=['fenced_code', 'tables'])
            
            # Archive and Save the regional report (Physical files + DB)
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
            analyzed_successfully += 1
            
        except Exception as e:
            print_error(f"分析編撰區域 {r_code} 時發生嚴重錯誤: {e}")

    if analyzed_successfully == 0:
        print_error("所有區域的分析及編撰均失敗。")
        sys.exit(1)
        
    # Step 4: Generate a unified Stock Selection Screener Report!
    print_info("\n==================================================")
    print_info("📊 正在產出「量化動態選股掃描決策報告」...")
    print_info("==================================================")
    try:
        screener = yf_tool.get_screener_instance()
        screener_md, screener_html = screener.generate_report(report_date)
        if screener_md:
            screener_filename = f"{report_date}_{timestamp_suffix}_screener_report_{REPORT_LANGUAGE}"
            db.save_report(screener_filename, regions_list, screener_md, screener_html)
            
            s_md_path = daily_reports_dir / f"{screener_filename}.md"
            s_html_path = daily_reports_dir / f"{screener_filename}.html"
            
            with open(s_md_path, "w", encoding="utf-8") as f:
                f.write(screener_md)
            with open(s_html_path, "w", encoding="utf-8") as f:
                f.write(screener_html)
                
            print_success(f"🎉 恭喜！量化選股掃描報告已成功產出並存檔！")
            print_success(f"💾 Markdown 存檔路徑：{s_md_path}")
            print_success(f"💾 HTML 存檔路徑：{s_html_path}")
            print_success(f"💾 報告已成功同步寫入 {DB_TYPE.upper()} 數據庫。")
        else:
            print_warning("本次執行未觸發 any 板塊篩選，跳過選股報告生成。")
    except Exception as e:
        print_error(f"產出量化選股報告時發生錯誤: {e}")
        
    # LINE Notifier週報生成推送 (Phase 5)
    try:
        print_info("🔔 正在透過 LINE Messaging API 發送每週研報生成通知...")
        from core.tools.line_notifier import LineNotifier
        notifier = LineNotifier()
        
        # 1. 取得今日新增的推薦個股
        all_active = db.get_active_recommendations()
        today_recs = [rec for rec in all_active if rec.get("report_date") == report_date]
        
        # 2. 格式化 Regime 資訊
        regime_msg = ""
        for reg_name, reg_val in regional_regimes.items():
            emoji = "🟢" if "BULL" in reg_val else ("🔴" if "BEAR" in reg_val else "🟡")
            regime_msg += f"- {reg_name}專區：{reg_val} {emoji}\n"
        if not regime_msg:
            regime_msg = "- 暫無區域情境數據\n"
            
        # 3. 格式化新增推薦名單
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
            
        # 4. 組裝訊息
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
    except Exception as line_ex:
        print_error(f"LINE 週報推送失敗（跳過以防止程式崩潰）: {line_ex}")
        
    # 執行自適應 Prompt 演化引擎 (Phase 9)
    try:
        evolve_active_prompts()
    except Exception as evolve_ex:
        print_warning(f"自適應 Prompt 演化引擎執行失敗（安全跳過以避免阻斷週報主程式）: {evolve_ex}")
        
    print_success("\n==================================================")
    print_success("🏁 投資策略研報與選股掃描 Pipeline 全數執行完畢！")
    print_success("==================================================")

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
    resolver = BaseAgent(
        name="TickerResolver",
        role="Financial Ticker Translator",
        system_instruction=(
            "You are a financial database utility. Your job is to translate a user's input (stock name, Chinese name, or ticker) "
            "into standard format: standard Yahoo Finance ticker, region code ('US' or 'Taiwan'), English official company name, and Chinese official company name. "
            "Format your response strictly as a JSON object: {\"ticker\": \"...\", \"region\": \"...\", \"company_name\": \"...\", \"company_name_zh\": \"...\"}. "
            "Specifically for Taiwan stocks, note that Yahoo Finance uses '.TW' for TWSE (Main board) listed companies and '.TWO' for TPEx (OTC/GreTai board) listed companies (e.g., TSMC is '2330.TW', but TPEx companies like IGS 鈊象 must be '3293.TWO', 8070 晉泰 must be '8070.TWO', etc.). Make sure to resolve the correct board suffix (.TW vs .TWO) based on your financial database knowledge. "
            "No markdown formatting, no code block backticks, no explanations. Just raw JSON."
        )
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
        regime_match = re.search(r"\[MARKET_REGIME:\s*(BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]", macro_report)
        market_regime = regime_match.group(1) if regime_match else "BULL_RISK_ON"
        macro_report_cleaned = re.sub(r"\[MARKET_REGIME:\s*(BULL_REGIME|BULL_RISK_ON|BEAR_RISK_OFF|VOLATILE_RANGEBOUND)\]\s*", "", macro_report)
        
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
        
        return macro_report_cleaned, market_regime, reflection_directives

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
    macro_report, market_regime, reflection_directives = get_latest_regime_and_reflection(region_code)
    print_success(f"當前大盤市場情境標籤：{market_regime}")
    
    res = research_and_track_asset(
        ticker=ticker,
        company_name=display_name,
        region_code=region_code,
        market_regime=market_regime,
        macro_report=macro_report,
        reflection_directives=reflection_directives,
        report_date=report_date,
        save_to_db=track_option,
        is_weekly_pipeline=False,
        custom_recommend_reason=f"Aegis-MAQS 即時查詢注入追蹤。當前市場情境: {market_regime}。"
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
        
    print("\n" + "\033[92m" + "="*60 + "\033[0m")
    print("  🎯 第一章：智慧投資決策與交易指令概要 (Decision Card)")
    print("\033[92m" + "="*60 + "\033[0m")
    
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
        
    print("\033[92m" + "="*60 + "\033[0m")
    
    print("\n" + "\033[94m" + "="*60 + "\033[0m")
    print("  🏦 第二章：投行量化估值模型報告 (Equity Valuation Engine Report)")
    print("\033[94m" + "="*60 + "\033[0m")
    print(valuation_report)
    print("\033[94m" + "="*60 + "\033[0m")
    
    print("\n" + "\033[93m" + "="*60 + "\033[0m")
    print("  💡 第三章：大模型深度基本面分析與決策修正 (LLM Report)")
    print("\033[93m" + "="*60 + "\033[0m")
    print(stock_report)
    print("\033[93m" + "="*60 + "\033[0m")
 
    try:
        query_dir = Path(DEFAULT_REPORTS_DIR).parent / "query"
        query_dir.mkdir(parents=True, exist_ok=True)
        
        query_md_content = f"""# 🎯 Aegis-MAQS 智慧投資決策報告 - {ticker} ({display_name})
*   **分析日期**: {report_date}
*   **國家區域**: {region_display}

## 🎯 第一章：智慧投資決策與交易指令概要

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

{valuation_report}

---

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
                prompt_version=active_prompt["version"] if active_prompt else "v1.0.0"
            )
            
            db.save_agent_inference_log(
                rec_id=failure_rec_id,
                agent_name="FundamentalAgent",
                ticker="INTC",
                input_prompt="當前總經：BEAR_RISK_OFF\n基本面：EPS 成長 -20%，本益比 40 倍，負債比 65%",
                output_response="基本面分析：Intel 面臨重重挑戰，雖本益比高企且成長衰退，但基於晶片法案補貼，給予買入評級。操作指引：目標價 34.5 元，停損點 27.6 元，建議持倉 10%。",
                prompt_version=active_prompt["version"] if active_prompt else "v1.0.0"
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
