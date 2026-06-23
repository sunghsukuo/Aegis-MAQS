import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add backend directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent))

from core.config import REPORTS_DIR

# Import core workflows and printing helpers
from core.pipelines.research_pipeline import (
    run_report_pipeline, 
    run_realtime_query, 
    run_prompt_evolution_test,
    print_error
)

def main():
    parser = argparse.ArgumentParser(description="Aegis-MAQS 投資研究代理人群系統 - 本地端執行與個股即時查詢工具 (CLI)")
    parser.add_argument("--regions", nargs="+", default=["US", "Taiwan"], help="指定要分析的國家區域，例如 US Taiwan")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="指定週報產出日期 (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="強制重新執行並覆蓋當日已有的報告")
    parser.add_argument("--phase", type=str, choices=[
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
    ], help="指定要執行的單一管線步驟 (按順序為: portfolio_check -> analyze_macro -> analyze_sectors -> portfolio_reflect -> screen_targets -> analyze_stocks -> weekly_report -> screener_report -> notify -> prompt_evolve)")
    parser.add_argument("--test-prompt-evolution", action="store_true", help="測試自適應 Prompt 演化引擎（注入模擬交易數據進行演化測試）")
    parser.add_argument("--query", type=str, help="即時個股分析與操作建議查詢 (支援個股代號或中文名稱，如 '2330.TW'、'鴻海')")
    parser.add_argument("--track", action="store_true", help="與 --query 搭配使用，若推薦評級為 Buy/Strong Buy，自動將該標的納入實戰持股追蹤與每日風控哨兵對帳")
    
    args = parser.parse_args()
    report_date = args.date
    regions_list = args.regions
    
    if args.query:
        run_realtime_query(args.query, args.track, report_date)
        sys.exit(0)
        
    if args.test_prompt_evolution:
        run_prompt_evolution_test()
        sys.exit(0)
    
    # Auto-rotate logs defensively on startup to prevent disk space exhaustion
    try:
        from core.config import LOGS_DIR
        from core.tools.utils import rotate_log_file
        rotate_log_file(LOGS_DIR / "generate_report.log", max_bytes=10*1024*1024)
        
        # Automatically clear error_details.log on startup to prevent pollution from previous runs
        error_log = LOGS_DIR / "error_details.log"
        if error_log.exists():
            error_log.unlink()
    except Exception as le:
        print(f"[!] Log Initialization Failure: {le}")
        
    # Clean expired cache files defensively on startup to prevent disk space exhaustion
    try:
        from core.config import CACHE_DIR
        from core.tools.utils import clean_expired_cache
        clean_expired_cache(CACHE_DIR, max_age_days=7)
    except Exception as ce:
        print(f"[!] Cache Cleanup Failure on Startup: {ce}")
    
    # Generate timestamp suffix to synchronize all output filenames and DB records
    timestamp_suffix = datetime.now().strftime("%H%M%S")
    
    # Construct daily output directory to keep the reports folder clean and organized
    daily_reports_dir = REPORTS_DIR / report_date
    daily_reports_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        run_report_pipeline(args, report_date, regions_list, timestamp_suffix, daily_reports_dir)
    except Exception as e:
        print_error(f"週報生成管線執行中途發生嚴重崩潰: {e}")
        # Send LINE weekly pipeline crash alert defensively
        try:
            from core.tools.line_notifier import LineNotifier
            notifier = LineNotifier()
            err_msg = (
                f"🚨 【投資研究代理人·週報生成管線崩潰】\n\n"
                f"當前系統時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"錯誤類別：{type(e).__name__}\n"
                f"錯誤描述：{str(e)}\n\n"
                f"⚠️ 警告：本週週報產出與量化選股管線執行中途崩潰失敗，請儘速登入伺服器檢查！"
            )
            notifier.send_message(err_msg)
        except Exception as line_ex:
            print(f"[!] 發送 LINE 崩潰警報失敗: {line_ex}")
        sys.exit(1)

if __name__ == "__main__":
    main()
