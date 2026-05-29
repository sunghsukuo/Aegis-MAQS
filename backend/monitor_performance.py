import sys
import os
import json
import unicodedata
from datetime import datetime, date
from pathlib import Path

# Add parent directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent))

# Import Config, Tools & Database
from core.config import DB_TYPE, REPORT_LANGUAGE
import core.db_manager as db
import core.tools.yahoo_finance as yf_tool

# Console Colors
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"

def get_display_width(s):
    """Calculates terminal rendering width of a string containing CJK characters and emojis."""
    width = 0
    for c in s:
        val = unicodedata.east_asian_width(c)
        if val in ('W', 'F', 'A'):
            width += 2
        elif ord(c) >= 0x1F300:  # Emoji range
            width += 2
        else:
            width += 1
    return width

def pad_left(s, width):
    """Pads string with spaces on the left based on terminal display width."""
    disp_w = get_display_width(s)
    if disp_w >= width:
        return s
    return " " * (width - disp_w) + s

def pad_right(s, width):
    """Pads string with spaces on the right based on terminal display width."""
    disp_w = get_display_width(s)
    if disp_w >= width:
        return s
    return s + " " * (width - disp_w)

def pad_center(s, width):
    """Centers string inside a given width based on terminal display width."""
    disp_w = get_display_width(s)
    if disp_w >= width:
        return s
    pad_total = width - disp_w
    pad_left_cnt = pad_total // 2
    pad_right_cnt = pad_total - pad_left_cnt
    return " " * pad_left_cnt + s + " " * pad_right_cnt

def print_header(title):
    """Renders a beautifully aligned terminal box considering display width of emojis and CJK."""
    inside_width = 78
    padded_title = pad_center(title, inside_width)
    print(f"\n{BOLD}{BLUE}┌" + "─" * inside_width + "┐")
    print(f"│{padded_title}│")
    print(f"└" + "─" * inside_width + "┘" + RESET)

def format_roi_padded(roi, pnl, currency, width):
    """Pads and colors ROI percentages and PnL values considering display width before wrapping with ANSI codes."""
    if roi is None:
        return pad_left("N/A", width)
    percentage = roi * 100
    color = GREEN if percentage >= 0 else RED
    sign = "+" if percentage >= 0 else ""
    raw_str = f"{sign}{percentage:.1f}% ({pnl:+.0f} {currency})"
    padded_raw = pad_left(raw_str, width)
    return padded_raw.replace(raw_str, f"{color}{raw_str}{RESET}")

def get_progress_bar(start_date_str, total_days=30):
    """Calculates progress days and renders a beautiful progress bar."""
    try:
        start_date = datetime.strptime(start_date_str.split(" ")[0], "%Y-%m-%d").date()
    except Exception:
        start_date = date.today()
        
    today = date.today()
    elapsed = (today - start_date).days + 1
    elapsed = max(1, elapsed)  # Day 1 start
    
    percent = min(1.0, elapsed / total_days)
    filled_length = int(40 * percent)
    bar = "█" * filled_length + "░" * (40 - filled_length)
    
    return elapsed, percent * 100, bar

def main():
    # 1. Gather stats from Database
    reports = db.list_all_reports()
    active_recs = db.get_active_recommendations()
    perf_data = db.get_historical_performance()
    closed_recs = perf_data.get("closed", [])
    
    # 2. Gather budget and capital states from BudgetAgent
    from core.agents.budget_agent import BudgetAgent
    budget_agent = BudgetAgent()
    twd_state = budget_agent.get_capital_state("TWD")
    usd_state = budget_agent.get_capital_state("USD")
    
    # Calculate current active capital values
    active_twd_invested = sum(r["invested_amount"] for r in active_recs if r["region"] != "US")
    active_usd_invested = sum(r["invested_amount"] for r in active_recs if r["region"] == "US")
    
    # Dynamically update prices for active recommendations to compute exact current P&L
    active_twd_pnl = 0.0
    active_usd_pnl = 0.0
    
    # Cache live prices to avoid redundant queries during this rendering block
    for rec in active_recs:
        ticker = rec["ticker"]
        rec_price = rec["recommend_price"]
        shares = rec["shares"]
        region = rec["region"]
        
        current_price = yf_tool.get_stock_price(ticker)
        if current_price == 0.0:
            current_price = rec_price
            
        unrealized_pnl = shares * (current_price - rec_price)
        if region == "US":
            active_usd_pnl += unrealized_pnl
        else:
            active_twd_pnl += unrealized_pnl
            
    # Calculate NAV (Net Asset Value)
    twd_nav = twd_state["available_capital"] + twd_state["reserved_cash"] + active_twd_invested + active_twd_pnl
    usd_nav = usd_state["available_capital"] + usd_state["reserved_cash"] + active_usd_invested + active_usd_pnl
    
    # Define start date of 30-day sandbox
    if reports:
        sorted_reports = sorted(reports, key=lambda x: x["date"])
        start_date_str = sorted_reports[0]["date"]
        status_label = f"已啟動 (自 {start_date_str} 起)"
    else:
        start_date_str = datetime.now().strftime("%Y-%m-%d")
        status_label = "尚未正式啟動 (等待首航週報產出)"

    # Calculate 30-day progress
    elapsed_days, progress_percent, prog_bar = get_progress_bar(start_date_str)
    
    # 2. Render System Header & Status
    print_header("📊 投資研究多代理人系統 - 30天實戰觀測期監控看板 📊")
    
    print(f"  {BOLD}實戰觀測期進度：{RESET}")
    if reports:
        print(f"  [{prog_bar}] {BOLD}第 {elapsed_days} / 30 天{RESET} ({progress_percent:.1f}% 已完成)")
    else:
        print(f"  [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] {BOLD}第 0 / 30 天{RESET} (等待明早 10:00 週報產出)")
        
    print(f"\n  • 系統狀態　　: {BOLD}{status_label}{RESET}")
    print(f"  • 週報產出總數: {BOLD}{len(reports)} 份{RESET}")
    print(f"  • 在庫追蹤標的: {BOLD}{len(active_recs)} 檔{RESET}")
    print(f"  • 已平倉結案數: {BOLD}{len(closed_recs)} 檔{RESET}")
    print(f"  • 資料庫配置　: {BOLD}{DB_TYPE.upper()}{RESET}")
    
    # 3. Render Capital Ledger HUD
    print_header("💰 預算與資金水位監控 (Capital Ledger HUD)")
    
    print(f"  {BOLD}• 台股資金水位 (TWD Pocket)：{RESET}")
    print(f"    - 可投資現金: {BOLD}{twd_state['available_capital']:11,.2f} TWD{RESET} | 保留安全金: {BOLD}{twd_state['reserved_cash']:11,.2f} TWD{RESET}")
    print(f"    - 在庫持股金: {BOLD}{active_twd_invested:11,.2f} TWD{RESET} | 未實現損益: {BOLD}{GREEN if active_twd_pnl >= 0 else RED}{active_twd_pnl:+11,.2f} TWD{RESET}")
    print(f"    - 總資產淨值 (NAV): {BOLD}{BLUE}{twd_nav:14,.2f} TWD{RESET}")
    
    print(f"\n  {BOLD}• 美股資金水位 (USD Pocket)：{RESET}")
    print(f"    - 可投資現金: {BOLD}{usd_state['available_capital']:11,.2f} USD{RESET} | 保留安全金: {BOLD}{usd_state['reserved_cash']:11,.2f} USD{RESET}")
    print(f"    - 在庫持股金: {BOLD}{active_usd_invested:11,.2f} USD{RESET} | 未實現損益: {BOLD}{GREEN if active_usd_pnl >= 0 else RED}{active_usd_pnl:+11,.2f} USD{RESET}")
    print(f"    - 總資產淨值 (NAV): {BOLD}{BLUE}{usd_nav:14,.2f} USD{RESET}")
    
    # 4. Render Historical Performance (Closed Positions)
    print_header("🏆 歷史交易績效 (Realized Performance - Closed Positions)")
    
    if closed_recs:
        win_rate = perf_data["win_rate"] * 100
        avg_roi = perf_data["avg_roi"] * 100
        total_pnl_twd = sum(r["pnl"] for r in closed_recs if r["region"] != "US")
        total_pnl_usd = sum(r["pnl"] for r in closed_recs if r["region"] == "US")
        
        # Find best and worst trades
        best_trade = max(closed_recs, key=lambda x: x["performance"])
        worst_trade = min(closed_recs, key=lambda x: x["performance"])
        
        best_currency = "USD" if best_trade["region"] == "US" else "TWD"
        worst_currency = "USD" if worst_trade["region"] == "US" else "TWD"
        
        best_roi_formatted = format_roi_padded(best_trade['performance'], best_trade.get('pnl', 0.0), best_currency, 0).strip()
        worst_roi_formatted = format_roi_padded(worst_trade['performance'], worst_trade.get('pnl', 0.0), worst_currency, 0).strip()
        
        print(f"  • 交易勝率 (Win Rate)  : {BOLD}{GREEN if win_rate >= 50 else RED}{win_rate:.1f}%{RESET} ({sum(1 for r in closed_recs if r['performance'] > 0)} 勝 / {len(closed_recs)} 敗)")
        print(f"  • 已實現累計損益 (PnL) : {BOLD}台股: {GREEN if total_pnl_twd >= 0 else RED}{total_pnl_twd:+.2f} TWD{RESET} | {BOLD}美股: {GREEN if total_pnl_usd >= 0 else RED}{total_pnl_usd:+.2f} USD{RESET}")
        print(f"  • 每筆平均已實現回報 : {BOLD}{avg_roi:+.2f}%{RESET}")
        print(f"  • 最佳平倉黑馬標的   : {BOLD}{best_trade['ticker']} ({best_trade['company_name']}) {best_roi_formatted}{RESET}")
        print(f"  • 最差平倉風控標的   : {BOLD}{worst_trade['ticker']} ({worst_trade['company_name']}) {worst_roi_formatted}{RESET}")
    else:
        print(f"  {YELLOW}目前尚無歷史平倉紀錄。當持股達到止盈目標價或跌破止損點時，系統會自動平倉並計算績效。{RESET}")

    # 5. Render Active Portfolio Holdings (Unrealized Portfolio)
    print_header("📈 當前在庫追蹤標的 (Active Portfolio - Unrealized)")
    
    if active_recs:
        # Table Header aligned perfectly to exactly 80 cells
        header = (
            pad_right("市場", 4) + " | " +
            pad_right("代號", 7) + " | " +
            pad_right("企業名稱", 17) + " | " +
            pad_left("買入價", 7) + " | " +
            pad_left("當前價", 7) + " | " +
            pad_left("分配金額", 8) + " | " +
            pad_left("未實現損益 (ROI / PnL)", 18)
        )
        print(f"{BOLD}{UNDERLINE}{header}{RESET}")
        
        for rec in active_recs:
            ticker = rec["ticker"]
            region = "美股" if rec["region"] == "US" else "台股"
            currency = "USD" if rec["region"] == "US" else "TWD"
            recommend_price = rec["recommend_price"]
            company_name = rec["company_name"]
            invested_amount = rec["invested_amount"]
            shares = rec["shares"]
            
            # Shorten long company names safely to 17 cells
            comp_disp_w = get_display_width(company_name)
            if comp_disp_w > 17:
                truncated = ""
                current_w = 0
                for char in company_name:
                    char_w = 2 if unicodedata.east_asian_width(char) in ('W', 'F', 'A') or ord(char) >= 0x1F300 else 1
                    if current_w + char_w + 3 > 17:
                        truncated += "..."
                        break
                    truncated += char
                    current_w += char_w
                company_name = truncated
                
            # Fetch current live price
            current_price = yf_tool.get_stock_price(ticker)
            if current_price == 0.0:
                current_price = recommend_price  # Fallback to recommend price if market offline
                
            unrealized_roi = (current_price - recommend_price) / recommend_price
            unrealized_pnl = shares * (current_price - recommend_price)
            
            region_str = pad_right(region, 4)
            ticker_str = pad_right(ticker, 7)
            company_str = pad_right(company_name, 17)
            recommend_price_str = pad_left(f"{recommend_price:.1f}", 7)
            current_price_str = pad_left(f"{current_price:.1f}", 7)
            invested_str = pad_left(f"{invested_amount:.0f}", 8)
            unrealized_roi_str = format_roi_padded(unrealized_roi, unrealized_pnl, currency, 18)
            
            print(f"{region_str} | {ticker_str} | {company_str} | {recommend_price_str} | {current_price_str} | {invested_str} | {unrealized_roi_str}")
        
        print("─" * 80)
        print(f"  * 損益資料與即時價格每分鐘同步更新 (資金水位扣減 15% 預算)*")
    else:
        print(f"  {YELLOW}目前在庫無追蹤股票。週六早上系統會執行量化選股掃描並新增追蹤標的。{RESET}")

    # 6. Render Completed Transactions Ledger
    if closed_recs:
        print_header("📜 歷史已平倉結案明細 (Closed Trades Ledger)")
        header_closed = (
            pad_right("市場", 4) + " | " +
            pad_right("代號", 7) + " | " +
            pad_right("企業名稱", 17) + " | " +
            pad_left("買入", 7) + " | " +
            pad_left("平倉", 7) + " | " +
            pad_left("投入本金", 8) + " | " +
            pad_left("已實現損益 (ROI / PnL)", 18)
        )
        print(f"{BOLD}{UNDERLINE}{header_closed}{RESET}")
        
        # Sort closed by date descending
        for rec in sorted(closed_recs, key=lambda x: x.get("close_date", ""), reverse=True)[:10]:
            ticker = rec["ticker"]
            region = "美股" if rec["region"] == "US" else "台股"
            currency = "USD" if rec["region"] == "US" else "TWD"
            recommend_price = rec["recommend_price"]
            close_price = rec["close_price"] or 0.0
            company_name = rec["company_name"]
            invested_amount = rec["invested_amount"]
            pnl = rec.get("pnl", 0.0)
            
            comp_disp_w = get_display_width(company_name)
            if comp_disp_w > 17:
                truncated = ""
                current_w = 0
                for char in company_name:
                    char_w = 2 if unicodedata.east_asian_width(char) in ('W', 'F', 'A') or ord(char) >= 0x1F300 else 1
                    if current_w + char_w + 3 > 17:
                        truncated += "..."
                        break
                    truncated += char
                    current_w += char_w
                company_name = truncated
                
            performance = rec["performance"]
            
            region_str = pad_right(region, 4)
            ticker_str = pad_right(ticker, 7)
            company_str = pad_right(company_name, 17)
            recommend_price_str = pad_left(f"{recommend_price:.1f}", 7)
            close_price_str = pad_left(f"{close_price:.1f}", 7)
            invested_str = pad_left(f"{invested_amount:.0f}", 8)
            performance_str = format_roi_padded(performance, pnl, currency, 18)
            
            print(f"{region_str} | {ticker_str} | {company_str} | {recommend_price_str} | {close_price_str} | {invested_str} | {performance_str}")
            
        if len(closed_recs) > 10:
            print(f"  * 僅顯示最近 10 筆平倉紀錄（共計 {len(closed_recs)} 筆）*")
            
    print("\n" + "=" * 80)
    print(f"💡 {BOLD}提示：{RESET}本看板資料與您的 {DB_TYPE.upper()} 資料庫及預算帳本完全同步。")
    print("   如需手動強制觸發日內持股對帳，請隨時執行：")
    print(f"   {GREEN}pipenv run python check_portfolio.py{RESET}")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
