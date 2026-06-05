# 🛠️ Aegis-MAQS 技術維護與運行指引手冊
**Technical Operations & Database Schema Manual**

本文件為「投資研究與風控多代理人決策系統（Aegis-MAQS）」的技術維護與操作手冊。本手冊旨在為工程師、量化研究員及運維人員提供系統部署、資料庫 Schema 設計、動態板塊配置機制、每日排程腳本運行及故障排除的完整指南。

本文件為 [Aegis-MAQS_Introduction.md](file:///home/gordon/learning/program/python/Aegis-MAQS/docs/Aegis-MAQS_Introduction.md) 的技術對照手冊，雙軌共存以維護系統架構的一致性。

---

## 📂 一、 系統運行環境與目錄結構

Aegis-MAQS 系統核心模組位於 `backend/` 目錄中，並遵循以下結構設計：

```text
backend/
├── core/
│   ├── agents/             # 多代理人決策核心 (Base, Budget, Fundamental, Macro, Market, News, Reflection, Writer)
│   ├── tools/              # 物理輔助工具 (Screener, Yahoo Finance Scraper, Web Search, Line Notifier 等)
│   ├── data/
│   │   ├── cache/          # API 與網頁抓取之 12 小時 JSON 本地快取
│   │   ├── db/             # 本地 SQLite 資料庫備援儲存目錄
│   │   ├── reports/        # 投研週報本機備用儲存目錄
│   │   └── sectors_config.json # 本地板塊與成分股備援組態
│   ├── config.py           # 全域系統組態與路徑/環境變數載入器
│   └── db_manager.py       # 資料庫 Schema 初始化與 SQL 抽象介面 (支援 MySQL & SQLite 雙模)
├── logs/                   # 系統執行日誌與智慧對帳 HTML 看板 (dashboard.html)
├── scratch/                # 系統測試、提示詞演化回滾與臨時維護測試腳本
├── aegis_cli.py            # 系統主入口：個股/板塊投研分析與報告生成 (Query / Pipeline)
├── check_portfolio.py      # 持倉對帳與物理波動 ATR/Beta 停損平倉腳本 (0-Token 風控哨兵)
├── monitor_performance.py  # 30天沙盒實戰績效監控、LINE 日報推送與網頁看板渲染
├── sync_data.py            # 歷史淨值與對帳數據之外部同步與校正工具
└── sync_sectors_config.py  # 板塊與成分股組態之雙向資料庫同步工具 (JSON ➔ DB)
```

### ⚙️ 環境變數配置 (.env)
系統執行前必須配置 `backend/.env`。核心變數如下：
* `GEMINI_API_KEY`: Google Gemini 大模型之 API 金鑰。
* `LINE_CHANNEL_ACCESS_TOKEN` & `LINE_USER_ID`: 每日風控與報告推送警報通知。
* `DB_TYPE`: `mysql` 或 `sqlite`（控制雙模資料庫切換）。
* `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`: MySQL 資料庫連線配置。

---

## 🗄️ 二、 核心數據模型與關聯（Database Schema）

Aegis-MAQS 採用關聯式資料庫記錄從「總經情境」、「個股決策推論」到「實體交易對帳」與「反思學習」的完整閉環。以下為核心資料表設計：

### 1. 板塊管理模組 (Sectors & Constituents)
用以存儲動態市場分類與追蹤標的，支援動態變更而無需部署程式碼。

#### 🔹 板塊登記表 (`sector_registry`)
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 板塊唯一識別碼 |
| `region` | `VARCHAR(20)` / `TEXT` | NOT NULL | 市場區域 (如 `US`, `Taiwan`) |
| `sector_code` | `VARCHAR(50)` / `TEXT` | UNIQUE, NOT NULL | 板塊 Ticker / 代碼 (如 `XLF`, `0050.TW`) |
| `sector_name` | `VARCHAR(100)` / `TEXT` | NOT NULL | 繁體中文板塊名稱 |
| `target_type` | `VARCHAR(20)` / `TEXT` | NOT NULL | `constituents` (成分股模式) 或 `etf` (單一ETF模式) |
| `is_etf` | `TINYINT` / `INTEGER` | DEFAULT 1, NOT NULL | 是否為 ETF（0 代表股票Proxy，需爬取財報；1 代表真實ETF，繞過財報爬取） |
| `is_active` | `TINYINT` / `INTEGER` | DEFAULT 1, NOT NULL | 是否啟用 (1=啟用, 0=停用) |
| `created_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 建立時間 |

#### 🔹 板塊成分股對照表 (`sector_constituents`)
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 成分股關聯唯一識別碼 |
| `sector_id` | `INT` / `INTEGER` | FK (sector_registry.id), NOT NULL | 所屬板塊 ID (級聯刪除 ON DELETE CASCADE) |
| `ticker` | `VARCHAR(20)` / `TEXT` | NOT NULL | 股票代碼 (如 `AAPL`, `2330.TW`) |
| `company_name` | `VARCHAR(100)` / `TEXT` | DEFAULT '' | 企業名稱（選填） |
| `created_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 建立時間 |
* **唯一索引約束**：`UNIQUE KEY uq_sector_ticker (sector_id, ticker)` 防止重複登記。

---

### 2. 投研決策與交易對帳模組 (Inference & Ledger)
用以實現「決策留痕（Audit Trail）」與「0-Token 物理風控」。

#### 🔹 投資建議與持倉表 (`recommendations`)
記錄 `WriterAgent` 根據多代理人管線生成的個股評級與最終操作目標。
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 建議案唯一識別碼 |
| `report_date` | `VARCHAR(50)` / `TEXT` | NOT NULL | 所屬投研週報之生成日期 (YYYY-MM-DD) |
| `region` | `VARCHAR(50)` / `TEXT` | NOT NULL | 市場區域 (`US` 或 `Taiwan`) |
| `ticker` | `VARCHAR(50)` / `TEXT` | NOT NULL | 標的代碼 |
| `company_name` | `VARCHAR(255)` / `TEXT` | NOT NULL | 企業中文/英文名稱 |
| `recommend_price`| `DOUBLE` / `REAL` | NOT NULL | 推薦買入時之參考價格 |
| `recommend_reason`| `TEXT` / `TEXT` | | 大模型評估之核心基本面護城河理由 |
| `target_price` | `DOUBLE` / `REAL` | | 定量錨定、定性微調之停利參考價 |
| `stop_loss` | `DOUBLE` / `REAL` | | 定量錨定、定性微調之物理停損參考價 |
| `rating` | `VARCHAR(50)` / `TEXT` | | 大模型最終評級 (`Strong Buy`, `Buy`, `Hold`, `Sell`) |
| `is_active` | `INT` / `INTEGER` | DEFAULT 1 | 是否在持倉監控中 (1=在庫持股中, 0=已平倉出場) |
| `close_price` | `DOUBLE` / `REAL` | | 平倉出場之真實結算價格 |
| `close_date` | `VARCHAR(50)` / `TEXT` | | 平倉日期 (YYYY-MM-DD) |
| `performance` | `DOUBLE` / `REAL` | | 單筆平倉報酬率 ROI (例如 `0.15` 代表 +15%) |
| `invested_amount`| `DOUBLE` / `REAL` | DEFAULT 0.0 | 此交易案實際動用之預算金額 (本幣) |
| `shares` | `DOUBLE` / `REAL` | DEFAULT 0.0 | 買入之虛擬/實體總股數 |
| `pnl` | `DOUBLE` / `REAL` | DEFAULT 0.0 | 此交易案之實現損益金額 (本幣) |
| `created_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 建立時間 |

#### 🔹 虛擬資金帳本表 (`capital_ledger`)
維護帳戶的預算上限與風控安全金門檻。
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 帳本唯一碼 |
| `currency` | `VARCHAR(10)` / `TEXT` | UNIQUE, NOT NULL | 貨幣代碼 (`USD` 或 `TWD`) |
| `available_capital`| `DOUBLE` / `REAL` | NOT NULL | 可用投資預算金額 (當前購買力) |
| `reserved_cash` | `DOUBLE` / `REAL` | NOT NULL | **絕對安全準備金**（台股預設 20 萬，美股預設 2 萬，永不動用） |
| `updated_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 最後更新時間 |

#### 🔹 實體交易歷史表 (`transaction_history`)
記錄每一次的虛擬/實體下單明細，做為反思對帳的依據。
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 交易明細識別碼 |
| `rec_id` | `INT` / `INTEGER` | NOT NULL | 對應的推薦案 ID (`recommendations.id`) |
| `action` | `VARCHAR(50)` / `TEXT` | NOT NULL | 交易動作 (`BUY`, `SELL_PROFIT_TARGET`, `SELL_STOP_LOSS`) |
| `ticker` | `VARCHAR(50)` / `TEXT` | NOT NULL | 標的代碼 |
| `currency` | `VARCHAR(10)` / `TEXT` | NOT NULL | 交易結算貨幣 |
| `shares` | `DOUBLE` / `REAL` | NOT NULL | 成交股數 |
| `price` | `DOUBLE` / `REAL` | NOT NULL | 成交單價 |
| `amount` | `DOUBLE` / `REAL` | NOT NULL | 總交易金額 (`shares` * `price`) |
| `roi` | `DOUBLE` / `REAL` | DEFAULT 0.0 | 平倉報酬率 (限 SELL 時計算) |
| `pnl` | `DOUBLE` / `REAL` | DEFAULT 0.0 | 實現損益金額 (限 SELL 時計算) |
| `created_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 交易時間 |

---

### 3. LLM 運作與自主反思進化模組 (Inference Logs & Registry)
記錄大模型的決策軌跡與 Prompt 版本控制。

#### 🔹 大模型推理日誌表 (`agent_inference_logs`)
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 日誌識別碼 |
| `rec_id` | `INT` / `INTEGER` | FK (recommendations.id) | 關聯的交易建議 ID (平倉時對帳用) |
| `agent_name` | `VARCHAR(50)` / `TEXT` | NOT NULL | 決策代理人名稱 (如 `FundamentalAgent`, `NewsAgent`) |
| `ticker` | `VARCHAR(20)` / `TEXT` | | 分析之股票標的 (若為總經則為空) |
| `input_prompt` | `LONGTEXT` / `TEXT` | NOT NULL | 發送給大模型之完整 Prompt |
| `output_response`| `LONGTEXT` / `TEXT` | NOT NULL | 大模型輸出之 JSON/Markdown 原始回覆 |
| `prompt_version` | `VARCHAR(20)` / `TEXT` | NOT NULL | 當時使用之 Prompt 版本號 |
| `created_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 分析生成時間 |

#### 🔹 自適應 Prompt 註冊表 (`prompt_registry`)
記錄隨實戰反思不斷進化的 Prompts。
| 欄位名稱 | 數據類型 (MySQL / SQLite) | 屬性 | 說明 |
| :--- | :--- | :--- | :--- |
| `id` | `INT` / `INTEGER` | AUTO_INCREMENT, PK | 唯一碼 |
| `agent_name` | `VARCHAR(50)` / `TEXT` | NOT NULL | 代理人名稱 |
| `system_prompt` | `LONGTEXT` / `TEXT` | NOT NULL | 系統提示詞（包含自適應反思修正後之內容） |
| `version` | `VARCHAR(20)` / `TEXT` | NOT NULL | 版本號 (如 `v1.0.0`, `v1.0.1`) |
| `is_active` | `INT` / `INTEGER` | DEFAULT 1 | 是否啟用 (1=當前使用, 0=歷史存檔) |
| `performance_score`| `DOUBLE` / `REAL` | DEFAULT 0.0 | 大模型此版本之滾動績效評分 |
| `updated_at` | `TIMESTAMP` / `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 更新時間 |
* **唯一索引約束**：`UNIQUE KEY idx_agent_version (agent_name, version)` 確保版本序號不衝突。

---

## 🔌 三、 板塊與成分股之設定、使用與管理

系統採用「資料庫優先、本地 JSON 備援、Git 雙向同步」的動態管理架構，以確保運行期的高可用性與版本控制。

### 1. 設定 (Configuration)：本地 JSON 配置規範
本地備援配置檔案存放於 `core/data/sectors_config.json`，作為系統的靜態真理源。
* **格式範例**：
  ```json
  "Taiwan": {
      "0055.TW": {
          "name": "金融保險",
          "target_type": "constituents",
          "is_etf": true,
          "constituents": ["2881.TW", "2882.TW", "2891.TW"]
      }
  }
  ```
* **核心欄位技術定義**：
  * `target_type`：板塊追蹤模式。可設為 `constituents`（讀取下方 constituents 清單中的代表個股）或 `etf`（直接交易此 ETF 代號本身，如直接買入 0055.TW）。
  * `is_etf`：基金屬性標記。設為 `true` 代表該代號是 ETF，數據模組會繞過個股 P/E 與債務等財報爬蟲（防止爬蟲當機）；設為 `false` 則代表該代號是股票 Proxy，系統會對其進行完整的估值分析。
  * `constituents`：成分股清單。列出該板塊底下的股票代號數組。

### 2. 使用 (Usage)：資料庫優先與備援 Fallback 機制
在系統運行期（例如執行 `aegis_cli.py` 進行動態篩選，或運行 `check_portfolio.py` 進行盤後對帳），系統會呼叫 [get_active_sectors(region_code)](file:///home/gordon/learning/program/python/Aegis-MAQS/backend/core/db_manager.py#L434-L487) 函數來獲取該市場（TWD / USD）的板塊與成分股配置。其詳細運作機制如下：

#### 執行步驟解析：
1. **第一優先：資料庫動態讀取 (MySQL / SQLite)**
   * **資料庫查詢**：系統建立連線後，會優先對 `sector_registry` 進行 SQL 查詢，篩選出符合指定區域且 `is_active = 1` 的所有啟用板塊。
   * **成分股關聯**：針對篩選出的每個板塊，系統會使用其 `id` 作為外鍵，進一步查詢 `sector_constituents` 獲取該板塊下登記的所有成分股 Ticker。
   * **結構重組**：最後，系統將從資料庫獲取的表數據，在記憶體中重組成與本地 JSON 格式完全一致的嵌套字典（Dictionary），返回給呼叫端。

2. **第二備援：自動 Fallback 機制 (靜態 JSON)**
   * **異常捕獲**：若資料庫發生連線超時、資料庫鎖定、連線埠被阻擋或資料表為空（未 Seed），系統會捕獲該異常，並在後台發出警告日誌：
     `[!] Warning: Failed to load sectors from database. Falling back to config.py.`
   * **本地載入**：系統立即繞過資料庫，改為從 [core/config.py](file:///home/gordon/learning/program/python/Aegis-MAQS/backend/core/config.py) 中加載在啟動時已由本地 `sectors_config.json` 緩存的板塊組態。
   * **無痛返回**：將本地 JSON 配置字典返回給呼叫端，確保上層的選股分析與停損對帳流程 100% 正常執行。

#### 💡 本機制的技術價值與設計優勢：
* **零停機保障 (Zero Downtime)**：對帳與平倉是高剛性的任務，若資料庫臨時異常，Fallback 機制能防止整個風控對帳腳本崩潰，確保即便在 DB 損壞的極端情況下，波動停損平倉依然能安全執行。
* **本地開發便利性**：開發者在本地測試單一模組時，無需在本地機器啟動 MySQL 伺服器，系統會自適應地退回 JSON 檔案模式，極大降低了本機開發調試的複雜度。

#### 安全備援流程圖：
```mermaid
flowchart LR
    Start([呼叫 get_active_sectors]) --> QueryDB[查詢資料庫]
    QueryDB -->|連線成功| ReturnDB[返回 DB 配置]
    QueryDB -->|連線失敗 或 無數據| LogWarning["觸發 ⚠️ 警報"]
    LogWarning --> ReadJSON[讀取本地 JSON]
    ReadJSON --> ReturnJSON[返回備援配置]
    ReturnDB --> End([載入完成])
    ReturnJSON --> End
```

### 3. 管理 (Management)：雙向同步工具與 Git 橋樑
系統在運行期支持隨時在資料庫調整板塊，並透過 `sync_sectors_config.py` 工具進行雙向管理，確保變更可被 Git 版本控制追蹤：

* **導入 (Seeding / 本地到資料庫)**：
  當開發端在本地 `sectors_config.json` 新增或修改成分股後，執行以下指令將變更同步寫入資料庫：
  ```bash
  pipenv run python sync_sectors_config.py --import
  ```
* **導出 (Exporting / 資料庫到本地)**：
  當運維人員直接在資料庫手動修改、新增板塊後，執行以下指令將配置導出並覆蓋本地的 `sectors_config.json`，隨後即可進行 Git Commit 提交：
  ```bash
  pipenv run python sync_sectors_config.py --export
  ```

---

## ⏱️ 四、 沙盒模擬與自動化排程（Workflow Operations）

Aegis-MAQS 的 30 天實戰觀測期依賴兩個核心風控對帳腳本運行。這兩個腳本應該被設定在 Linux 系統的 `crontab` 中每日定時執行。

### 1. 持倉對帳與波動停損腳本 (`check_portfolio.py`)
* **職責**：0-Token 物理風控。每日收盤後執行。
* **主要工作流**：
  1. 讀取資料庫中 `is_active = 1` 的持股明細。
  2. 使用 `yahoo_finance` API 抓取現價。
  3. 比對現價是否**低於 `stop_loss`**（停損觸發）或**高於 `target_price`**（停利觸發）。
  4. 一旦觸發，立即將 available_capital 加回（現價 * 股數），在 `transaction_history` 寫入 SELL 紀錄，並將 recommendations 狀態設為 0 (平倉)。
  5. 結算並記錄當日的 Portfolio NAV（總淨值 = 可用資金 + 安全準備金 + 在庫持股價值）。
  6. 計算該貨幣組合的滾動統計指標：**夏普比率 (Sharpe Ratio)**、**索提諾比率 (Sortino Ratio)** 以及 **最大回撤 (MDD)**。
* **CLI 指令**：
  ```bash
  # 對全域 (US 與 Taiwan) 進行持股對帳與 NAV 結算
  pipenv run python check_portfolio.py
  ```

### 2. 每日績效指標結算與 Watchdog 日報 (`monitor_performance.py`)
* **職責**：統計沙盒表現，並執行閉環回撤防禦。
* **主要工作流**：
  1. 從資料庫提取 NAV 歷史線，更新並在終端機渲染精美的績效看板。
  2. 比對當前組合回撤：一旦發現 **最大回撤 (MDD) 大於 3.0%** 的警戒線，將透過 LINE Notifier 即時拉響警報。
* **CLI 指令**：
  ```bash
  # 靜默執行，不輸出終端機表格，僅運算
  pipenv run python monitor_performance.py --silent
  
  # 主動向管理員發送 LINE 監督日報 (包含 Sharpe, MDD 與在庫持倉明細)
  pipenv run python monitor_performance.py --send-line
  ```

---

### 📅 建議之 Linux Crontab 自動化排程範例

為確保沙盒系統的每日自動化運行與 0-Token 監控，建議在 Linux 伺服器上配置以下 Crontab 設定（台股與美股收盤後定時執行對帳與通知）：

```text
# 每天台股收盤後 (週一至週五 15:30)，執行台股對帳與平倉判定
30 15 * * 1-5 cd /home/gordon/learning/program/python/Aegis-MAQS/backend && pipenv run python check_portfolio.py --regions Taiwan >> logs/check_portfolio.log 2>&1

# 每天美股收盤後 (週二至週六 05:30)，執行美股對帳與平倉判定
30 5 * * 2-6 cd /home/gordon/learning/program/python/Aegis-MAQS/backend && pipenv run python check_portfolio.py --regions US >> logs/check_portfolio.log 2>&1

# 每天早上 08:30，自動生成當日沙盒監督日報並發送到 LINE
30 8 * * * cd /home/gordon/learning/program/python/Aegis-MAQS/backend && pipenv run python monitor_performance.py --send-line >> logs/monitor_performance.log 2>&1
```

---

## 📝 五、 文件維護與升級規範

1. **變更追蹤**：凡是修改資料庫 `CREATE TABLE` DDL、變更 `.env` 環境變數配置、或者新增 CLI 腳本參數，必須同步在本技術手冊中修訂對應的欄位表與指令範例。
2. **唯一真理源**：此技術指引手冊應常駐於專案的工作目錄（`Aegis-MAQS/docs/Aegis-MAQS_Technical_Guide.md`），做為每次開發與部署時進行技術對齊之唯一真理源（Single Source of Truth）。
