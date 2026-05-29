import sys
import os
from pathlib import Path
from datetime import datetime

# Add current directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent))

# Import Config, Tools & Database
from core.config import DB_TYPE
import core.db_manager as db
import core.tools.yahoo_finance as yf_tool

# Color outputs for CLI readability
def print_success(msg): print(f"\033[92m[✓] {msg}\033[0m")
def print_info(msg): print(f"\033[94m[*] {msg}\033[0m")
def print_warning(msg): print(f"\033[93m[!] {msg}\033[0m")
def print_error(msg): print(f"\033[91m[✗] {msg}\033[0m")

def run_portfolio_check(report_date: str, regions: list = None):
    """
    Performs the actual portfolio checking, price updating, and wind-down closings.
    Supports optional regional filtering.
    """
    print_success("==================================================")
    print_success("🛡️  啟動：投資持股實時對帳與風控監測系統 (0-Token Check)")
    region_label = ", ".join(regions) if regions else "ALL (全域)"
    print_success(f"監測日期：{report_date} | 目標區域：{region_label} | 資料庫類型：{DB_TYPE.upper()}")
    print_success("==================================================")
    
    try:
        # 1. Fetch active recommendations from Database
        active_recs = []
        if regions:
            for r in regions:
                active_recs.extend(db.get_active_recommendations(region=r))
        else:
            active_recs = db.get_active_recommendations()
            
        if not active_recs:
            print_info("目前指定區域無在庫追蹤個股 (Active Portfolio is empty)。")
            print_success("==================================================")
            return  # Changed from sys.exit(0) to prevent terminating parent report generator!
            
        print_info(f"偵測到目前在庫追蹤標的共 {len(active_recs)} 檔，開始進行實時對帳與風控檢測...")
        
        closed_count = 0
        active_count = 0
        
        for rec in active_recs:
            ticker = rec["ticker"]
            rec_id = rec["id"]
            region = rec["region"]
            recommend_price = rec["recommend_price"]
            target_price = rec["target_price"]
            stop_loss = rec["stop_loss"]
            company_name = rec["company_name"]
            
            # Fetch current live price from Yahoo Finance
            current_price = yf_tool.get_stock_price(ticker)
            if current_price == 0.0:
                print_warning(f"無法取得 {company_name} ({ticker}) 的最新報價，跳過本次更新。")
                continue
                
            # Calculate current ROI
            performance = (current_price - recommend_price) / recommend_price
            
            from core.agents.budget_agent import BudgetAgent
            budget_agent = BudgetAgent()
            currency = budget_agent.get_currency_by_region(region)
            
            # Check wind-down/close triggers: Profit Target or Stop Loss
            if target_price and current_price >= target_price:
                print_success(
                    f"🎯 標的 {ticker} 達到預設目標價！\n"
                    f"   - 企業名稱: {company_name}\n"
                    f"   - 推薦價格: {recommend_price:.2f} | 當前價格: {current_price:.2f} (目標: {target_price:.2f})\n"
                    f"   - 累計投報率: {performance*100:+.2f}%\n"
                    f"   - 執行動作: 獲利平倉 (CLOSE POSITIONS)"
                )
                budget_agent.record_sale(rec_id, ticker, region, current_price, report_date, performance)
                closed_count += 1
            elif stop_loss and current_price <= stop_loss:
                print_warning(
                    f"⚠️ 標的 {ticker} 跌破預設防禦停損點！\n"
                    f"   - 企業名稱: {company_name}\n"
                    f"   - 推薦價格: {recommend_price:.2f} | 當前價格: {current_price:.2f} (停損: {stop_loss:.2f})\n"
                    f"   - 累計投報率: {performance*100:+.2f}%\n"
                    f"   - 執行動作: 避險平倉 (STOP LOSS TRIGGERED)"
                )
                budget_agent.record_sale(rec_id, ticker, region, current_price, report_date, performance)
                closed_count += 1
            else:
                # Still active, calculate and update current unrealized ROI & PnL
                shares = rec.get("shares", 0.0)
                unrealized_pnl = shares * (current_price - recommend_price)
                db.update_recommendation_performance(rec_id, performance, unrealized_pnl)
                
                print_info(
                    f"📈 {ticker:<9} | 現價: {current_price:>8.2f} | "
                    f"買入: {recommend_price:>8.2f} | 區間: [{stop_loss or 0:.1f} - {target_price or 0:.1f}] | "
                    f"未實現損益: {performance*100:>+6.2f}% ({unrealized_pnl:>+8.2f} {currency})"
                )
                active_count += 1
                
        print_success("==================================================")
        print_success("🏁 實時持股監測對帳完畢！")
        print_success(f"📊 執行摘要：在庫維持監測 {active_count} 檔 | 本次觸發平倉 {closed_count} 檔")
        print_success("==================================================")
        
    except Exception as e:
        print_error(f"執行持股監測時發生例外錯誤: {e}")
        # When called as module in pipeline, raise exception; when run as script, exit with error
        if __name__ == "__main__":
            sys.exit(1)
        else:
            raise e

def main():
    import argparse
    parser = argparse.ArgumentParser(description="投資持股實時對帳與風控監測系統 (0-Token Check)")
    parser.add_argument("--regions", nargs="+", default=[], help="指定對帳區域，例如 US Taiwan (不指定則預設全域對帳)")
    args = parser.parse_args()
    
    report_date = datetime.now().strftime("%Y-%m-%d")
    run_portfolio_check(report_date, regions=args.regions)

if __name__ == "__main__":
    main()
