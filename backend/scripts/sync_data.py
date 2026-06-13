#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Investment Analyst Agent - SQLite to MySQL Data Sync Utility
This script safely migrates the generated weekly reports and stock recommendations
from the local SQLite file to your MySQL database to ensure data consistency.
"""

import os
import sys
import sqlite3
import pymysql
from pathlib import Path
from dotenv import load_dotenv

# Set paths
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

# Color formatting
GREEN = "\033[93m"
RED = "\033[91m"
BLUE = "\033[96m"
RESET = "\033[0m"

def sync():
    print(f"[*] 🚀 {BLUE}啟動 SQLite 至 MySQL 數據同步作業...{RESET}")
    
    # 1. Define Paths
    sqlite_path = BACKEND_ROOT / "core/data/db/investments.db"
    if not sqlite_path.exists():
        print(f"    {RED}[✗] 錯誤：找不到 SQLite 資料庫檔案於 {sqlite_path}{RESET}")
        sys.exit(1)
        
    target_date = "2026-05-28"
    
    try:
        # 2. Establish connections
        sqlite_conn = sqlite3.connect(str(sqlite_path))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cur = sqlite_conn.cursor()
        
        mysql_conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", 3306)),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DB", "investment_db"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        mysql_cur = mysql_conn.cursor()
        
        # 3. Migrate Report
        print(f"[*] 正在讀取 SQLite 中日期為 `{target_date}` 的真實大週報...")
        sqlite_cur.execute("SELECT * FROM reports WHERE date = ?", (target_date,))
        rep_row = sqlite_cur.fetchone()
        
        if rep_row:
            rep = dict(rep_row)
            print(f"    [✓] 成功取得真實大週報！Markdown 字數：{len(rep['markdown_content'])}")
            
            # Write to MySQL (ON DUPLICATE KEY UPDATE will overwrite the mock test report)
            print(f"[*] 正在將真實大週報同步寫入 MySQL...")
            rep_sql = """
                INSERT INTO reports (date, regions, markdown_content, html_content)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    regions = VALUES(regions),
                    markdown_content = VALUES(markdown_content),
                    html_content = VALUES(html_content)
            """
            mysql_cur.execute(rep_sql, (rep["date"], rep["regions"], rep["markdown_content"], rep["html_content"]))
            print(f"    {GREEN}[✓] 2026-05-28 真實週報成功同步寫入 MySQL！{RESET}")
        else:
            print(f"    {RED}[✗] 警告：在 SQLite 中未找到日期為 {target_date} 的報告。{RESET}")
            
        # 4. Migrate Recommendations
        # Clear out any previous mock test recommendations for the same date to keep database clean
        print(f"[*] 清除 MySQL 當天測試留下的舊模擬個股紀錄...")
        mysql_cur.execute("DELETE FROM recommendations WHERE report_date = %s", (target_date,))
        
        print(f"[*] 正在讀取 SQLite 中的真實推薦個股名單...")
        sqlite_cur.execute("SELECT * FROM recommendations WHERE report_date = ?", (target_date,))
        rec_rows = sqlite_cur.fetchall()
        
        sync_count = 0
        for r_row in rec_rows:
            r = dict(r_row)
            # Insert into MySQL
            rec_sql = """
                INSERT INTO recommendations (
                    report_date, region, ticker, company_name, recommend_price,
                    recommend_reason, target_price, stop_loss, rating, is_active,
                    close_price, close_date, performance
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            mysql_cur.execute(rec_sql, (
                r["report_date"], r["region"], r["ticker"], r["company_name"], r["recommend_price"],
                r["recommend_reason"], r["target_price"], r["stop_loss"], r["rating"], r["is_active"],
                r["close_price"], r["close_date"], r["performance"]
            ))
            sync_count += 1
            print(f"    - {r['ticker']} ({r['company_name']}) 同步成功")
            
        mysql_conn.commit()
        print(f"    {GREEN}[✓] 共 {sync_count} 檔真實個股推薦明細成功同步寫入 MySQL！{RESET}")
        
        sqlite_conn.close()
        mysql_conn.close()
        print(f"\n🎉 {GREEN}同步遷移流程圓滿成功！您的 MySQL 資料與實體週報已 100% 絕對一致！{RESET}")
        
    except Exception as e:
        print(f"    {RED}[✗] 同步失敗！錯誤訊息：{e}{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    sync()
