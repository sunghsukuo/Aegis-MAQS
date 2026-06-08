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

def calculate_risk_adjusted_metrics(currency: str) -> dict:
    """
    Calculates Sharpe Ratio, Sortino Ratio, and Maximum Drawdown (MDD)
    using the historical daily NAV records in portfolio_nav_history.
    Assuming Risk-Free Rate = 0.0 for simplicity, annualized by sqrt(252).
    Requires zero external dependencies.
    """
    import math
    
    # 1. Fetch NAV history
    nav_history = db.get_portfolio_nav_history(currency)
    if not nav_history or len(nav_history) < 2:
        return {"sharpe": 0.0, "sortino": 0.0, "mdd": 0.0, "data_points": len(nav_history)}
        
    # Extract NAV values in chronological order
    navs = [r["total_nav"] for r in nav_history]
    
    # 2. Calculate daily returns
    returns = []
    for i in range(1, len(navs)):
        prev = navs[i-1]
        if prev > 0:
            returns.append((navs[i] - prev) / prev)
        else:
            returns.append(0.0)
            
    if not returns:
        return {"sharpe": 0.0, "sortino": 0.0, "mdd": 0.0, "data_points": len(nav_history)}
        
    # 3. Calculate Sharpe Ratio
    # Mean return
    mean_return = sum(returns) / len(returns)
    # Standard deviation of returns
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_return = math.sqrt(variance)
    
    sharpe = 0.0
    if std_return > 0:
        # Annualized Sharpe (assuming 252 trading days per year)
        sharpe = (mean_return / std_return) * math.sqrt(252)
        
    # 4. Calculate Sortino Ratio
    # Downside deviation only considers negative returns
    downside_returns = [r for r in returns if r < 0.0]
    sortino = 0.0
    if downside_returns:
        downside_mean = sum(downside_returns) / len(downside_returns)
        downside_variance = sum((r - downside_mean) ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_variance)
        if downside_std > 0:
            sortino = (mean_return / downside_std) * math.sqrt(252)
    elif mean_return > 0:
        # If there are no negative returns and mean return is positive, Sortino is infinite or extremely high
        sortino = 99.9
        
    # 5. Calculate Maximum Drawdown (MDD)
    peak = navs[0]
    max_dd = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        if peak > 0:
            dd = (peak - nav) / peak
            if dd > max_dd:
                max_dd = dd
                
    return {
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "mdd": float(max_dd),
        "data_points": len(nav_history)
    }

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
        from core.tools.line_notifier import LineNotifier
        notifier = LineNotifier()
        
        # 1. Fetch active recommendations from Database
        active_recs = []
        if regions:
            for r in regions:
                active_recs.extend(db.get_active_recommendations(region=r))
        else:
            active_recs = db.get_active_recommendations()
            
        # Filter out recommendations that have no actual holdings (shares == 0)
        active_recs = [r for r in active_recs if r.get("shares", 0.0) > 0.0]
            
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
                
                # Send LINE Notifier alert
                msg = (
                    f"🎯 【投資研究代理人·獲利平倉警報】\n\n"
                    f"標的：{ticker} ({company_name})\n"
                    f"狀態：已觸發目標價獲利平倉 🟢\n"
                    f"推薦價：{recommend_price:.2f} {currency}\n"
                    f"平倉價：{current_price:.2f} {currency} (目標價: {target_price:.2f} {currency})\n"
                    f"累計投報率：{performance*100:+.2f}%\n\n"
                    f"系統已自動結案並釋放資金至現金帳戶。📈"
                )
                notifier.send_message(msg)
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
                
                # Send LINE Notifier alert
                msg = (
                    f"⚠️ 【投資研究代理人·避險停損警報】\n\n"
                    f"標的：{ticker} ({company_name})\n"
                    f"狀態：跌破防禦停損點避險平倉 🔴\n"
                    f"推薦價：{recommend_price:.2f} {currency}\n"
                    f"平倉價：{current_price:.2f} {currency} (停損價: {stop_loss:.2f} {currency})\n"
                    f"累計投報率：{performance*100:+.2f}%\n\n"
                    f"系統已自動執行避險賣出，保護資金水位。🛡️"
                )
                notifier.send_message(msg)
            else:
                # Still active, check and apply trailing stop (breakeven) protection!
                tech_metrics = yf_tool.calculate_technical_metrics(ticker)
                atr_14 = tech_metrics.get("atr_14")
                if atr_14:
                    from core.risk.trailing_stop import check_and_apply_breakeven_stop
                    updated = check_and_apply_breakeven_stop(rec, current_price, atr_14)
                    if updated:
                        rec["stop_loss"] = recommend_price
                        stop_loss = recommend_price
                        
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
        
        # 2. Daily Portfolio NAV Logging & Risk Metrics Calculation (Phase 4)
        print_info("📊 正在執行每日組合淨值 (NAV) 結算與風險指標 (Sharpe/Sortino/MDD) 計算...")
        
        from core.agents.budget_agent import BudgetAgent
        budget_agent = BudgetAgent()
        
        # We determine which currencies to check based on requested regions
        target_currencies = []
        if regions:
            for r in regions:
                target_currencies.append(budget_agent.get_currency_by_region(r))
            target_currencies = list(set(target_currencies))
        else:
            target_currencies = ["USD", "TWD"]
            
        for curr in target_currencies:
            # A. Get ledger balance
            state = budget_agent.get_capital_state(curr)
            available = state.get("available_capital", 0.0)
            reserved = state.get("reserved_cash", 0.0)
            
            # B. Get active holdings value for this currency
            active_value = 0.0
            region_filter = "US" if curr == "USD" else "Taiwan"
            region_recs = db.get_active_recommendations(region=region_filter)
            
            for rec in region_recs:
                shares = rec.get("shares", 0.0)
                ticker = rec.get("ticker")
                curr_price = yf_tool.get_stock_price(ticker)
                if curr_price > 0.0:
                    active_value += shares * curr_price
                    
            total_nav = available + reserved + active_value
            
            # C. Save daily NAV to database
            db.save_portfolio_nav(report_date, curr, total_nav, available, active_value)
            print_success(f"[{curr}] 每日組合淨值結算完成：總資產 (NAV): {total_nav:,.2f} | 可用資金: {available:,.2f} | 在庫持股價值: {active_value:,.2f}")
            
            # D. Calculate Sharpe, Sortino, MDD
            metrics = calculate_risk_adjusted_metrics(curr)
            if metrics["data_points"] >= 2:
                print_success(
                    f"📈 [{curr}] 量化風控回報歸因績效：\n"
                    f"   - 觀測交易日天數: {metrics['data_points']} 天\n"
                    f"   - 年化夏普比率 (Sharpe Ratio): {metrics['sharpe']:>+6.2f}\n"
                    f"   - 年化索提諾比率 (Sortino Ratio): {metrics['sortino']:>+6.2f}\n"
                    f"   - 組合最大回撤 (Max Drawdown): {metrics['mdd']*100:>6.2f}%"
                )
            else:
                print_info(f"ℹ️ [{curr}] 目前累積交易日天數為 {metrics['data_points']} 天，需至少 2 天的歷史 NAV 紀錄以計算 Sharpe/Sortino 指標。")

            # E. Risk Watchdog & Circuit Breaker (3.0% Dynamic Monitor)
            try:
                # Fetch historical NAVs to evaluate current asset drop
                nav_history = db.get_portfolio_nav_history(curr)
                nav_values = [r["total_nav"] for r in nav_history]
                peak_nav = max(nav_values + [total_nav]) if nav_values else total_nav
                current_drop = (peak_nav - total_nav) / peak_nav if peak_nav > 0.0 else 0.0
                current_mdd = metrics.get("mdd", 0.0)
                
                # Fetch dynamic limit based on regime
                from core.regime.registry import get_macro_regime
                from core.risk.risk_manager import get_dynamic_mdd_limit
                
                regime_info = get_macro_regime(region_filter)
                regime_name = regime_info.get("regime", "VOLATILE_RANGEBOUND")
                mdd_limit = get_dynamic_mdd_limit(regime_name, curr)

                
                triggered = (current_mdd > mdd_limit) or (current_drop > mdd_limit)
                
                # Sync circuit breaker state in database
                db.update_risk_circuit_breaker(curr, 1 if triggered else 0)
                
                if triggered:
                    print_error(
                        f"🚨 [風控熔斷] {curr} 帳戶已觸發警戒線！\n"
                        f"   - 當前 MDD: {current_mdd*100:.2f}% | 自峰值回落: {current_drop*100:.2f}% (動態警戒: {mdd_limit*100:.1f}%)\n"
                        f"   - 執行動作: 啟動熔斷，凍結新買單預算。"
                    )
                    # Send LINE Warning message
                    msg = (
                        f"🚨 【風控警報·沙盒資產淨值與回撤警告】\n"
                        f"================================\n"
                        f"發送時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"⚠️ 系統已偵測到風控指標突破動態警戒線！\n"
                        f"• {region_filter} 歷史最大回撤 (MDD) 達 {current_mdd*100:.2f}% (動態警戒: {mdd_limit*100:.1f}%)\n"
                        f"• {region_filter} 資產自峰值回降 達 {current_drop*100:.2f}% (動態警戒: {mdd_limit*100:.1f}%)\n\n"
                        f"💰 當前資產淨值: {total_nav:,.2f} {curr}\n"
                        f"🛑 【緊急處置與風控對策】\n"
                        f"沙盒實戰期回撤已突破風險警戒！為保護本金安全，系統已自動執行熔斷機制，全面凍結新標的買入分配。🛡️"
                    )
                    notifier.send_message(msg)
            except Exception as cb_ex:
                print_error(f"[!] 無法在對帳中進行風控熔斷檢查: {cb_ex}")
        print_success("==================================================")
        
    except Exception as e:
        print_error(f"執行持股監測時發生例外錯誤: {e}")
        # Send LINE Alert defensively
        try:
            from core.tools.line_notifier import LineNotifier
            notifier = LineNotifier()
            err_msg = (
                f"🚨 【投資研究代理人·持股對帳系統崩潰】\n\n"
                f"當前系統時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"錯誤類別：{type(e).__name__}\n"
                f"錯誤描述：{str(e)}\n\n"
                f"⚠️ 警告：每日實時對帳任務執行失敗，請儘速檢查後台日誌或網路狀態！"
            )
            notifier.send_message(err_msg)
        except Exception as line_ex:
            print(f"[!] 發送 LINE 崩潰警報失敗: {line_ex}")
            
        # When called as module in pipeline, raise exception; when run as script, exit with error
        if __name__ == "__main__":
            sys.exit(1)
        else:
            raise e

def main():
    import argparse
    parser = argparse.ArgumentParser(description="投資持股實時對帳與風控監測系統 (0-Token Check)")
    parser.add_argument("--regions", nargs="+", default=[], help="指定對帳區域，例如 US Taiwan (不指定則預設全域對帳)")
    parser.add_argument("--daemon", action="store_true", help="以守護進程模式執行，定時在交易時段輪詢對帳")
    parser.add_argument("--interval", type=int, default=300, help="以守護進程執行時的輪詢間隔 (秒，預設 300 秒/5分鐘)")
    args = parser.parse_args()
    
    # Auto-rotate logs defensively on startup to prevent disk space exhaustion
    try:
        from core.config import LOGS_DIR
        from core.tools.utils import rotate_log_file
        rotate_log_file(LOGS_DIR / "check_portfolio.log", max_bytes=10*1024*1024)
    except Exception as le:
        print(f"[!] Log Rotator Failure: {le}")
        
    report_date = datetime.now().strftime("%Y-%m-%d")
    
    if args.daemon:
        import time
        print_success(f"[🛡️ 風控守護進程] 啟動背景監控 Daemon 模式。輪詢間隔為 {args.interval} 秒。")
        while True:
            try:
                curr_date = datetime.now().strftime("%Y-%m-%d")
                run_portfolio_check(curr_date, regions=args.regions)
            except Exception as loop_ex:
                print_error(f"[!] Daemon 循環內對帳出錯: {loop_ex}")
            
            time.sleep(args.interval)
    else:
        run_portfolio_check(report_date, regions=args.regions)


if __name__ == "__main__":
    main()
