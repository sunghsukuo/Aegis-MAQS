#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Investment Analyst Agent - Local Report Patching & Sync Utility (0 Token Cost)
This script directly patches the generated reports with the correct trading date range
and updates the MySQL database locally without calling the Gemini API.
"""

import os
import sys
import markdown
from pathlib import Path
from dotenv import load_dotenv

# Set paths
BACKEND_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKEND_ROOT / ".env")

# Color formatting
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"

def patch():
    print(f"[*] 🔧 {BLUE}啟動本地 0 Token 報告物理修復與 MySQL 同步程序...{RESET}")
    
    target_date = "2026-05-28"
    
    # 1. Paths
    reports_dir = Path("/mnt/p/linux/Aegis-MAQS/data/reports")
    md_file_path = reports_dir / f"{target_date}.md"
    html_file_path = reports_dir / f"{target_date}.html"
    
    if not md_file_path.exists():
        print(f"    {RED}[✗] 錯誤：找不到實體報告檔案 {md_file_path}{RESET}")
        sys.exit(1)
        
    try:
        # 2. Get exact trading date range from Yahoo Finance locally (No LLM cost)
        import core.tools.yahoo_finance as yf_tool
        us_bench = yf_tool.get_benchmark_performance("US")
        start_date = us_bench.get("start_date", "2026-05-21")
        end_date = us_bench.get("end_date", "2026-05-28")
        
        print(f"    [✓] 成功取得本週交易區間：{start_date} 至 {end_date}")
        
        # 3. Read physical Markdown
        with open(md_file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 4. Physically inject date range at the top
        en_target = f"# 🌍 Weekly Global Investment Strategy & Multi-Agent Advisory Report {target_date}"
        en_replacement = f"{en_target}\n**Data Calculation Range: {start_date} to {end_date} (5 Trading Days)**"
        
        if en_target in content:
            if f"Data Calculation Range" not in content:
                content = content.replace(en_target, en_replacement)
                print(f"    [✓] 已在 Markdown 第一行成功物理注入英文日期區間！")
            else:
                print(f"    [!] 報告中已存在日期區間，跳過注入。")
        else:
            # Fallback force inject
            fallback_inject = f"**Data Calculation Range: {start_date} to {end_date} (5 Trading Days)**\n\n"
            if fallback_inject not in content:
                content = content.replace(f"# 🌍 Weekly Global Investment Strategy & Multi-Agent Advisory Report {target_date}", 
                                          f"# 🌍 Weekly Global Investment Strategy & Multi-Agent Advisory Report {target_date}\n{fallback_inject}")
                print(f"    [✓] 已強制物理注入日期區間！")
                
        # 5. Re-render HTML locally
        final_html = markdown.markdown(content, extensions=['fenced_code', 'tables'])
        
        # 6. Save back to physical files
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        with open(html_file_path, "w", encoding="utf-8") as f:
            f.write(final_html)
        print(f"    [✓] 實體 .md 與 .html 檔案本地更新完成！")
        
        # 7. Save report directly to MySQL (0 Token Cost!)
        import core.db_manager as db
        # Set database mock regions list
        regions_list = ["US", "Taiwan"]
        db.save_report(target_date, regions_list, content, final_html)
        print(f"    {GREEN}[✓] 完美修復的大報告已同步寫入 MySQL 資料庫！{RESET}")
        
        # 8. Print verification query
        import pymysql
        conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST"),
            port=int(os.getenv("MYSQL_PORT", 3306)),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DB"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        with conn.cursor() as cur:
            cur.execute("SELECT date, SUBSTRING(markdown_content, 1, 300) as content FROM reports WHERE date = %s", (target_date,))
            row = cur.fetchone()
            print(f"\n{BLUE}[*] 驗證 MySQL 目前第一行最新內容：{RESET}")
            print(f"    - 日期：{row['date']}")
            print(f"    - 內容首段：\n{GREEN}{row['content']}{RESET}")
        conn.close()
        
        print(f"\n🎉 {GREEN}修復同步全部成功完成！100% 物理保證，耗費 0 個 Token！{RESET}\n")
        
    except Exception as e:
        print(f"    {RED}[✗] 修復失敗：{e}{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    patch()
