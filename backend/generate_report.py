import argparse
import sys
import os
import json
import markdown
from datetime import datetime
from pathlib import Path
import time

# Add backend directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent))

# Import Config, Tools & Database
from core.config import REGIONS, REPORTS_DIR, MAX_SECTORS_PER_REGION, MAX_STOCKS_PER_REGION, DB_TYPE, REPORT_LANGUAGE
import core.db_manager as db
import core.tools.yahoo_finance as yf_tool
import core.tools.web_search as search_tool
from check_portfolio import run_portfolio_check

# Import AI Agents
from core.agents.macro_agent import MacroAgent
from core.agents.market_agent import MarketAgent
from core.agents.news_agent import NewsAgent
from core.agents.fundamental_agent import FundamentalAgent
from core.agents.reflection_agent import ReflectionAgent
from core.agents.writer_agent import WriterAgent

# Color outputs
def print_success(msg): print(f"\033[92m[✓] {msg}\033[0m")
def print_info(msg): print(f"\033[94m[*] {msg}\033[0m")
def print_warning(msg): print(f"\033[93m[!] {msg}\033[0m")
def print_error(msg): print(f"\033[91m[✗] {msg}\033[0m")


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
    print_success(f"[{region_code}] 區域專屬決策反思分析完成！")
    return reflection_report

def extract_price_from_line(line: str, current_price: float) -> float:
    """
    Robustly extracts the target price or stop-loss price from a line of markdown text,
    filtering out small integers (like 10, 15, 200) representing days, weights, or SMA indicators,
    and returns the value that is closest to the current stock price.
    """
    import re
    # Regex to find all numbers, including decimals and handling commas
    numbers = re.findall(r"(?:\$|NT\$|元)?\s*([\d,]+\.?[\d]*)\s*(?:元|%)?", line)
    valid_prices = []
    
    for num_str in numbers:
        num_str_clean = num_str.replace(",", "")
        if not num_str_clean:
            continue
        try:
            val = float(num_str_clean)
            # Filter out standard non-price metrics (e.g. 50-day, 200-day, 10% weight) 
            # if they are far away from the actual price.
            if val in [5.0, 10.0, 15.0, 20.0, 50.0, 200.0]:
                if current_price and abs(val - current_price) / current_price > 0.5:
                    continue
            valid_prices.append(val)
        except ValueError:
            continue
            
    if valid_prices:
        if current_price:
            closest_price = min(valid_prices, key=lambda x: abs(x - current_price))
            if abs(closest_price - current_price) / current_price < 0.6:
                return closest_price
        return valid_prices[-1]  # Fallback to the last matched number
    return 0.0

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
    macro_report = macro_agent.analyze(region_name, benchmark_data, macro_news)
    time.sleep(3)  # Respect free tier rate limits (15 RPM)
    
    # 4. Get Sector Rankings
    sector_rankings = yf_tool.get_sector_rankings(region_code)
    
    # 5. Run Market Agent
    print_info(f"[{region_name}] 正在進行板塊強度排序與資金流向分析...")
    market_agent = MarketAgent()
    market_report = market_agent.analyze(region_name, sector_rankings)
    time.sleep(3)  # Respect free tier rate limits (15 RPM)
    
    # 6. Parse Top Recommended Sectors/Themes from Market Agent's report using LLM guidance
    top_etfs = [sec["ticker"] for sec in sector_rankings[:MAX_SECTORS_PER_REGION]]
    print_info(f"[{region_name}] 本週焦點強勢板塊 ETF：{', '.join(top_etfs)}")
    
    # 7. Dynamic Target Discovery & Fundamental Valuation
    stock_analysis_reports = []
    stocks_analyzed = 0
    
    # Scrape news & evaluate representative stock assets for the top performing sector ETFs
    for etf_ticker in top_etfs:
        if stocks_analyzed >= MAX_STOCKS_PER_REGION:
            break
            
        representative_stocks = yf_tool.get_etf_holdings(etf_ticker)
        # Determine how many stocks to pull from this sector to respect our region limit
        stocks_to_analyze = max(1, MAX_STOCKS_PER_REGION - stocks_analyzed)
        # Grab at most 2 per sector for diversity if total limit allows, otherwise grab remaining
        stocks_to_analyze = min(stocks_to_analyze, 2)
        target_stocks = representative_stocks[:stocks_to_analyze]
        
        for stock in target_stocks:
            ticker = stock["ticker"]
            name = stock["name"]
            print_info(f"[{region_name}] 🔍 正在對龍頭標的進行深度研究：{name} ({ticker})...")
            
            # A. Fetch stock-specific news headlines
            stock_news = search_tool.get_stock_news(ticker, max_items=5)
            
            # B. Run News Agent to find qualitative catalysts & sentiment
            print_info(f"   - 消息面分析中...")
            news_agent = NewsAgent()
            news_analysis = news_agent.analyze(ticker, name, stock_news)
            time.sleep(3)  # Respect free tier rate limits (15 RPM)
            
            # C. Fetch quantitative fundamental metrics
            financials = yf_tool.get_stock_financials(ticker)
            if not financials:
                print_warning(f"   - 無法取得 {ticker} 的財務指標，跳過估值。")
                continue
                
            # D. Run Fundamental Agent incorporating Macro Context & Self-Correction Reflection Directives!
            print_info(f"   - 基本面估值與決策修正中...")
            fundamental_agent = FundamentalAgent()
            
            # Combine macro context and reflection instructions to guide the fundamental agent
            combined_context = f"""
【當前巨觀經濟環境】：
{macro_report}

【前期歷史回測之自我修正指令】：
{reflection_directives}
"""
            stock_report = fundamental_agent.analyze(ticker, name, financials, news_analysis, combined_context)
            stock_analysis_reports.append(stock_report)
            time.sleep(3)  # Respect free tier rate limits (15 RPM)
            
            # E. Automatically save recommendation parameters to Database for future closed-loop backtesting!
            # We parse the output to save. For maximum robustness, we write a quick parser to extract
            # purchase range, target, and stop loss, or write a structured JSON output, or parse it using a quick LLM call.
            # Here, we will parse the key target & stop loss numbers from the stock report using regex or fallback to default values.
            # To ensure standard data logging, we can parse numbers cleanly.
            try:
                # Fallback default values
                curr_price = financials.get("current_price", 0.0)
                target_p = curr_price * 1.15 if curr_price else 0.0
                stop_l = curr_price * 0.92 if curr_price else 0.0
                rating = "Buy"
                
                # Robust regex extraction parsing logic from LLM Markdown output
                lines = stock_report.split("\n")
                for line in lines:
                    if "目標價" in line or "中線目標價" in line:
                        parsed_val = extract_price_from_line(line, curr_price)
                        if parsed_val > 0.0: 
                            target_p = parsed_val
                    elif "停損點" in line or "防禦停損點" in line:
                        parsed_val = extract_price_from_line(line, curr_price)
                        if parsed_val > 0.0: 
                            stop_l = parsed_val
                    elif "投資評級" in line:
                        if "Strong Buy" in line or "強烈買入" in line: rating = "Strong Buy"
                        elif "Hold" in line or "持有" in line: rating = "Hold"
                
                # Dynamically allocate capital via BudgetAgent
                from core.agents.budget_agent import BudgetAgent
                budget_agent = BudgetAgent()
                invested_amount, shares = budget_agent.allocate_budget(ticker, region_code, curr_price)
                
                rec_id = db.save_recommendation(
                    report_date=report_date,
                    region=region_code,
                    ticker=ticker,
                    company_name=name,
                    recommend_price=curr_price,
                    recommend_reason=f"板塊 {etf_ticker} 強勢動能領頭，基本面營收優異。",
                    target_price=target_p,
                    stop_loss=stop_l,
                    rating=rating,
                    invested_amount=invested_amount,
                    shares=shares
                )
                
                # Record purchase in budget agent transaction history
                if invested_amount > 0.0:
                    budget_agent.record_purchase(rec_id, ticker, region_code, curr_price, invested_amount, shares)
                
                print_success(f"標的 {ticker} 推薦參數與預算已成功寫入回測帳本！(現價: {curr_price:.2f} | 分配預算: {invested_amount:.2f} | 股數: {shares:.2f})")
            except Exception as ex:
                print_warning(f"寫入推薦數據庫時發生輕微解析異常: {ex}")
                
            stocks_analyzed += 1
                
    return macro_report, market_report, "\n\n---\n\n".join(stock_analysis_reports)

def main():
    parser = argparse.ArgumentParser(description="投資研究代理人系統 - 本地測試與執行工具 (CLI)")
    parser.add_argument("--regions", nargs="+", default=["US", "Taiwan"], help="指定要分析的國家區域，例如 US Taiwan")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="指定週報產出日期 (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="強制重新執行並覆蓋當日已有的報告")
    
    args = parser.parse_args()
    report_date = args.date
    regions_list = args.regions
    
    print_success("==================================================")
    print_success("🚀 歡迎使用：投資研究代理人自動化研報系統 (CLI)")
    print_success(f"執行日期：{report_date} | 目標市場：{', '.join(regions_list)}")
    print_success("==================================================")
    
    # Generate timestamp suffix to synchronize all output filenames and DB records
    timestamp_suffix = datetime.now().strftime("%H%M%S")
    
    # Construct daily output directory to keep the reports folder clean and organized
    daily_reports_dir = REPORTS_DIR / report_date
    daily_reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if a report for today already exists to prevent duplicate LLM calls
    existing_report = db.get_report_by_date(report_date)
    if existing_report and not args.force:
        print_warning(f"偵測到資料庫中已存在【{report_date}】的投資報告。")
        print_warning("使用 --force 參數可強制重新運行並覆蓋。")
        sys.exit(0)
    # Step 1: Defensive pre-reflection price check & closing using our 0-token check_portfolio logic
    # This guarantees the ledger is 100% current even if the daily check was not run!
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
            mac_rep, mkt_rep, stk_rep = run_regional_analysis(r_code, report_date, reflection_directives)
            
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
            
            # Physically override the title to customize it per-region and force calculations date range
            if start_date_str and end_date_str:
                date_range_text = f"**Data Calculation Range: {start_date_str} to {end_date_str} (5 Trading Days)**" if REPORT_LANGUAGE == "EN" else f"**本週數據涵蓋區間：{start_date_str} 至 {end_date_str}，共 5 個交易日**"
                
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
            print_warning("本次執行未觸發任何板塊篩選，跳過選股報告生成。")
    except Exception as e:
        print_error(f"產出量化選股報告時發生錯誤: {e}")
        
    print_success("\n==================================================")
    print_success("🏁 投資策略研報與選股掃描 Pipeline 全數執行完畢！")
    print_success("==================================================")

if __name__ == "__main__":
    main()
