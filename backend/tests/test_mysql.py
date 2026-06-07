#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Investment Analyst Agent - MySQL Standalone Connection & Access Test
This script is designed for safe local testing of MySQL database connection,
table creation, and basic CRUD operations before integration.
"""

import os
import sys
import json
from pathlib import Path
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

# Set paths
BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")

# Color formatting for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_banner():
    print("=" * 60)
    print(f"🚀 {BLUE}投資研究代理人系統 - MySQL 本地端獨立存取測試{RESET}")
    print("=" * 60)

def check_env_variables():
    """Validates the MySQL configurations inside backend/.env."""
    print(f"[*] 正在檢查 .env 資料庫設定變數...")
    
    db_type = os.getenv("DB_TYPE", "sqlite")
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "your_mysql_password_here")
    db_name = os.getenv("MYSQL_DB", "investment_db")
    
    print(f"    - 目前 DB_TYPE      : {GREEN if db_type == 'mysql' else YELLOW}{db_type}{RESET}")
    print(f"    - MySQL 主機 (Host) : {host}")
    print(f"    - MySQL 埠號 (Port) : {port}")
    print(f"    - MySQL 使用者      : {user}")
    print(f"    - MySQL 密碼 (Pswd) : {'**** (已設定)' if password != 'your_mysql_password_here' else YELLOW + '未修改預設密碼 (your_mysql_password_here)' + RESET}")
    print(f"    - 目標資料庫 (DB)   : {db_name}")
    
    if password == "your_mysql_password_here":
        print(f"\n{YELLOW}[!] 警告：偵測到您尚未在 .env 中修改您的 MySQL 密碼！{RESET}")
        print(f"    請打開 {BLUE}backend/.env{RESET} 並將 {GREEN}MYSQL_PASSWORD{RESET} 修改為您本地的 MySQL 密碼。")
        print(f"    本測試將以現有設定嘗試連線...")
        
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password if password != "your_mysql_password_here" else "",
        "db": db_name
    }

def get_base_connection(config):
    """Establishes connection to MySQL server without specifying a database."""
    return pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

def get_db_connection(config):
    """Establishes connection to the target database."""
    return pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["db"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

def test_pipeline():
    print_banner()
    config = check_env_variables()
    
    # 1. Test Server Connectivity & Dynamic DB Creation
    print(f"\n[*] 1. {BLUE}測試 MySQL 伺服器連線與自動建庫...{RESET}")
    try:
        conn = get_base_connection(config)
        with conn.cursor() as cursor:
            # Check server version
            cursor.execute("SELECT VERSION() as version;")
            version = cursor.fetchone()
            print(f"    [✓] 連線成功！MySQL 版本為：{GREEN}{version['version']}{RESET}")
            
            # Create Database if not exists
            print(f"    [*] 正在確認資料庫 `{config['db']}` 是否存在...")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{config['db']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            print(f"    [✓] 資料庫 `{config['db']}` 確認/建立成功！")
        conn.close()
    except Exception as e:
        print(f"    {RED}[✗] 連線失敗！請確認您的 MySQL Server 已啟動、帳號密碼正確，且防火牆/通訊埠 (Port) 未受阻擋。{RESET}")
        print(f"    錯誤訊息：{e}")
        sys.exit(1)

    # 2. Test Table Creation (DDL)
    print(f"\n[*] 2. {BLUE}測試資料表結構建立 (DDL)...{RESET}")
    try:
        conn = get_db_connection(config)
        with conn.cursor() as cursor:
            # Create reports table
            print("    [*] 正在建立 `reports` 資料表...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    date VARCHAR(50) UNIQUE NOT NULL,
                    regions TEXT NOT NULL,          -- JSON string of analyzed regions
                    markdown_content LONGTEXT NOT NULL,
                    html_content LONGTEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            print("    [✓] `reports` 資料表建立完成！")
            
            # Create recommendations table
            print("    [*] 正在建立 `recommendations` 資料表...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    report_date VARCHAR(50) NOT NULL,      -- Link to report date
                    region VARCHAR(50) NOT NULL,           -- e.g., 'US', 'Taiwan'
                    ticker VARCHAR(50) NOT NULL,           -- e.g., 'AAPL', '2330.TW'
                    company_name VARCHAR(255) NOT NULL,
                    recommend_price DOUBLE NOT NULL,       -- Stock price at recommendation time
                    recommend_reason TEXT,                 -- Bullet points of key thesis
                    target_price DOUBLE,                   -- Bull target price
                    stop_loss DOUBLE,                      -- Stop loss protection
                    rating VARCHAR(50),                    -- e.g., 'Buy', 'Strong Buy'
                    is_active INT DEFAULT 1,               -- 1 = Active, 0 = Completed
                    close_price DOUBLE,                    -- Price when closed
                    close_date VARCHAR(50),                -- Date when closed
                    performance DOUBLE,                    -- ROI (e.g. 0.05 for +5%)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_report_date (report_date),
                    INDEX idx_ticker (ticker)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            print("    [✓] `recommendations` 資料表建立完成！")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"    {RED}[✗] 建立資料表失敗！{RESET}")
        print(f"    錯誤訊息：{e}")
        sys.exit(1)

    # 3. CRUD: Write Mock Data (Insert)
    print(f"\n[*] 3. {BLUE}測試模擬資料寫入 (DML - Insert)...{RESET}")
    test_date = "2026-05-28"
    try:
        conn = get_db_connection(config)
        with conn.cursor() as cursor:
            # Clean old test data to keep database neat
            cursor.execute("DELETE FROM recommendations WHERE ticker = 'TEST_TSLA'")
            cursor.execute("DELETE FROM reports WHERE date = %s", (test_date,))
            
            # Insert Report
            print("    [*] 寫入模擬週報...")
            report_sql = """
                INSERT INTO reports (date, regions, markdown_content, html_content)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    regions = VALUES(regions),
                    markdown_content = VALUES(markdown_content),
                    html_content = VALUES(html_content)
            """
            mock_regions = ["US", "Taiwan"]
            mock_md = "# 本週投資週報\n- 科技板塊持續強勢。\n- 台積電法說會優於預期。"
            mock_html = "<h1>本週投資週報</h1><ul><li>科技板塊持續強勢。</li><li>台積電法說會優於預期。</li></ul>"
            
            cursor.execute(report_sql, (test_date, json.dumps(mock_regions), mock_md, mock_html))
            print("    [✓] 模擬週報寫入成功！")
            
            # Insert Recommendation
            print("    [*] 寫入模擬個股推薦 (TSLA)...")
            rec_sql = """
                INSERT INTO recommendations (
                    report_date, region, ticker, company_name, recommend_price,
                    recommend_reason, target_price, stop_loss, rating, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """
            cursor.execute(rec_sql, (
                test_date, "US", "TEST_TSLA", "Tesla Inc (Mock)", 180.50,
                "- 自動駕駛 Beta 釋出\n- 交付量觸底反彈", 220.00, 160.00, "Buy"
            ))
            print("    [✓] 模擬個股推薦寫入成功！")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"    {RED}[✗] 資料寫入失敗！{RESET}")
        print(f"    錯誤訊息：{e}")
        sys.exit(1)

    # 4. CRUD: Query Mock Data (Read)
    print(f"\n[*] 4. {BLUE}測試資料查詢讀取 (DML - Read)...{RESET}")
    try:
        conn = get_db_connection(config)
        with conn.cursor() as cursor:
            # Query latest report
            print("    [*] 查詢最新週報...")
            cursor.execute("SELECT * FROM reports ORDER BY date DESC LIMIT 1")
            report = cursor.fetchone()
            if report:
                print(f"    [✓] 成功取得週報！日期：{GREEN}{report['date']}{RESET}")
                print(f"        - 分析區域: {report['regions']}")
                print(f"        - Markdown 長度: {len(report['markdown_content'])} 字元")
            else:
                print(f"    {RED}[✗] 未找到週報！{RESET}")
                
            # Query active recommendations
            print("    [*] 查詢活躍個股推薦...")
            cursor.execute("SELECT * FROM recommendations WHERE is_active = 1 AND ticker = 'TEST_TSLA'")
            recs = cursor.fetchall()
            for r in recs:
                print(f"    [✓] 成功取得推薦股！代號：{GREEN}{r['ticker']}{RESET} | 推薦價：{r['recommend_price']} | 評等：{r['rating']}")
                print(f"        - 推薦原因簡述: {r['recommend_reason']}")
        conn.close()
    except Exception as e:
        print(f"    {RED}[✗] 資料讀取失敗！{RESET}")
        print(f"    錯誤訊息：{e}")
        sys.exit(1)

    # 5. CRUD: Update Performance (Update)
    print(f"\n[*] 5. {BLUE}測試資料更新與關閉推薦 (DML - Update)...{RESET}")
    try:
        conn = get_db_connection(config)
        with conn.cursor() as cursor:
            # Get the recommendation ID we just inserted
            cursor.execute("SELECT id FROM recommendations WHERE ticker = 'TEST_TSLA' AND is_active = 1 LIMIT 1")
            row = cursor.fetchone()
            if row:
                rec_id = row['id']
                print(f"    [*] 正在關閉個股推薦 ID = {rec_id} (TSLA)...")
                
                # Close the recommendation
                close_sql = """
                    UPDATE recommendations
                    SET is_active = 0,
                        close_price = %s,
                        close_date = %s,
                        performance = %s
                    WHERE id = %s
                """
                # Close price = 210.00 (ROI = (210-180.5)/180.5 = 16.34%)
                perf = (210.00 - 180.50) / 180.50
                cursor.execute(close_sql, (210.00, "2026-06-05", perf, rec_id))
                print(f"    [✓] 推薦個股已成功關閉！模擬獲利 ROI: {GREEN}{perf * 100:.2f}%{RESET}")
                
                # Verify update
                cursor.execute("SELECT is_active, close_price, performance FROM recommendations WHERE id = %s", (rec_id,))
                updated = cursor.fetchone()
                print(f"    [✓] 驗證資料更新：狀態 (is_active)={updated['is_active']} | 關閉價={updated['close_price']} | ROI={updated['performance']:.4f}")
            else:
                print(f"    {RED}[✗] 未找到活躍的 TSLA 測試推薦，無法進行更新測試。{RESET}")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"    {RED}[✗] 資料更新失敗！{RESET}")
        print(f"    錯誤訊息：{e}")
        sys.exit(1)

    # 6. Conclusion
    print("\n" + "=" * 60)
    print(f"🎉 {GREEN}MySQL 連線與 CRUD 本地端存取測試成功！{RESET}")
    print("=" * 60)
    print(f"👉 {YELLOW}現在，您可以打開 MySQL Workbench 進行資料確認：{RESET}")
    print(f"   1. 連線至您的 MySQL Instance。")
    print(f"   2. 執行查詢：{BLUE}SELECT * FROM `{config['db']}`.reports;{RESET}")
    print(f"   3. 執行查詢：{BLUE}SELECT * FROM `{config['db']}`.recommendations;{RESET}")
    print("   確認測試資料 `TEST_TSLA` 是否都在裡面且欄位無誤。")
    print("=" * 60)
    print(f"如果您在 Workbench 中確認沒問題，請在此回覆：{GREEN}「Workbench 確認OK，可以導入專案」{RESET}。")
    print("我將隨即為您把 `db_manager.py` 升級為支援 MySQL 的正式版本。")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    test_pipeline()
