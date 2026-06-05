# 🏛️ Aegis-MAQS 系統模組化重構與升級協同計畫書
**System Modularization Refactoring & Integration Blueprint**

> [!IMPORTANT]
> 隨著系統考量的市場維度增加（動能、均值回歸、總經避險等），原有之單體腳本（Monolithic Scripts）如 [aegis_cli.py](file:///home/gordon/learning/program/python/Aegis-MAQS/backend/aegis_cli.py)（近 1,400 行）與 [monitor_performance.py](file:///home/gordon/learning/program/python/Aegis-MAQS/backend/monitor_performance.py)（逾 1,200 行）已負擔過多職責。為了避免程式碼日益龐大、修改單一模組波及整個管線，本計畫書制定了**「模組化解耦重構」**方案，並與「均值回歸適應計畫」協同導入。

---

## 🔍 一、 現有架構痛點分析 (Current Architectural Pain Points)

1.  **職責過度耦合 (Tight Coupling)**：
    *   `aegis_cli.py` 同時負責：CLI 參數解析、對象/區域解析、網頁 Markdown 解析、大模型調用協調、區域反思邏輯以及最終的報告寫入。
    *   `monitor_performance.py` 同時負責：資料庫統計、即時市價撈取、LINE 訊息推送，甚至內嵌了高達 650 行的 HTML 模板字串。
2.  **升級維護難度高 (Fragility)**：
    *   在導入「均值回歸」的選股與風控時，必須在現有的篩選與分析大函數中寫入大量 `if-else` 分支，容易引進 Regression Bug，且降低了程式碼可讀性。
3.  **測試困難度高 (Untestability)**：
    *   由於運作邏輯（Business Logic）與介面呈現（CLI Display / HTML Generate）混雜，無法針對單一演算法（如 ATR 風控公式、乖離率篩選器）進行獨立的單元測試（Unit Test）。

---

## 🏗️ 二、 模組化重構目標架構 (Target Modular Architecture)

我們採用**「分層負責、策略模式（Strategy Pattern）」**的設計哲學，將系統重構為以下模組：

```text
Aegis-MAQS/backend/
├── aegis_cli.py                    # 🟢 CLI 入口點 (僅負責參數解析，調用 PipelineOrchestrator)
├── monitor_performance.py          # 🟢 監控入口點 (僅負責調用 StatCollector 與 Renderer)
└── core/
    ├── pipeline/                   # 🚀 流程編排層 (Orchestration Layer)
    │   ├── weekly_pipeline.py      # 週報分析主管線
    │   └── realtime_pipeline.py    # 即時查詢主管線
    │
    ├── regime/                     # 🌍 市場氣候感知層 (Regime Detection Layer)
    │   ├── detector.py             # ADX/Hurst 等技術指標氣候分析
    │   └── registry.py             # 氣候狀態快取與同步
    │
    ├── screener/                   # 📊 選股策略層 (Screener Strategy Layer)
    │   ├── base.py                 # 選股策略抽象基底類別 (Abstract Base Class)
    │   ├── momentum_strategy.py    # 策略 A：動能突破選股
    │   ├── reversion_strategy.py   # 策略 B：超賣拉回選股
    │   └── factory.py              # 策略工廠 (根據氣候決定實體化對象)
    │
    ├── risk/                       # 🛡️ 風險與部位管理層 (Risk & Portfolio Layer)
    │   ├── risk_manager.py         # 波動度風控乘數計算
    │   └── trailing_stop.py        # 移動止損與保本點管理器
    │
    ├── visualization/              # 🎨 呈現層 (Presentation Layer)
    │   ├── cli_renderer.py         # 終端機表格與文字渲染
    │   ├── dashboard_renderer.py   # HTML 看板生成器 (分離 HTML 模板至獨立檔案)
    │   └── templates/
    │       └── dashboard_tpl.html  # 純 HTML/CSS 看板模板
    │
    └── utils/                      # 🔧 工具公用層 (Utility Layer)
        ├── parsers.py              # 文字與價格萃取 (extract_price_from_line)
        └── formatters.py           # Markdown 轉 Terminal / 字串排版
```

---

## 🔄 三、 重構與功能升級的協同導入路徑 (Combined Integration Path)

為確保系統在升級與重構過程中維持「運作不中斷（Zero Downtime / Zero Regressions）」，我們將重構與上述四個演進階段深度結合，採用 **「漸進式替換（Strangler Fig Pattern）」** 推進：

### 🏁 階段一：提取公用層與氣候感知解耦
*   **重構動作**：
    1.  建立 `core/utils/parsers.py`，將 `extract_price_from_line`、`extract_range_from_line` 與 `format_markdown_for_terminal` 從 `aegis_cli.py` 中移出，並補上單元測試。
    2.  將 `monitor_performance.py` 中的 ASCII 表格對齊工具（`pad_left` 等）移至 `core/utils/formatters.py`。
*   **氣候升級整合**：
    *   在 `core/regime/detector.py` 中實作氣候判定演算法，並將其與 `MacroAgent` 的巨觀標籤在 `core/regime/registry.py` 中同步。

### 🏁 階段二：導入策略模式重構選股器
*   **重構動作**：
    *   建立 `core/screener/` 封裝，定義 `BaseScreener` 抽象介面。
    *   將原本 `screener.py` 中的動能選股邏輯搬移至 `core/screener/momentum_strategy.py`。
*   **氣候升級整合**：
    *   開發 `core/screener/reversion_strategy.py`（拉回買進策略）。
    *   開發 `core/screener/factory.py`，系統執行選股時，直接呼叫 `ScreenerFactory.get_screener(market_regime)`，實現零耦合選股切換。

### 🏁 階段三：大腦評估器與風控參數配置解耦
*   **重構動作**：
    *   建立 `core/risk/risk_manager.py`。將 `aegis_cli.py` 中計算動態 ATR 通道的代碼提取出來，集中管理。
*   **氣候升級整合**：
    *   在 `risk_manager.py` 中根據氣候（`market_regime`）決定 ATR 乘數（趨勢市 2.0/3.0，回歸市 1.2/1.5）。
    *   更新 `FundamentalAgent` 的 Prompt 動態加載邏輯，將防追高硬性條文作為獨立的提示詞模組（Prompt Snippet）在運行時動態加載，而不是寫死在主 Agent 提示詞中。

### 🏁 階段四：視覺呈現層分離與移動止損模組化
*   **重構動作**：
    1.  建立 `core/visualization/` 封裝。
    2.  建立 `core/visualization/templates/dashboard_tpl.html`，將 HTML 標記與 CSS 樣式徹底移出 Python 程式碼，Python 改以 **Jinja2** 或簡單的 `str.format()` 方式填充 JSON 數據。
*   **氣候升級整合**：
    *   在 `core/risk/trailing_stop.py` 中實作移動止損邏輯，使 `check_portfolio.py` 與 `monitor_performance.py` 均可呼叫此統一風控模組進行保本判定。

---

## 📈 四、 重構後的長期維護優勢 (Long-term Benefits)

1.  **測試獨立性 (Isolation of Testing)**：
    *   想要測試新的「選股因子」？只需在 `core/screener/` 下新增一個策略子檔案，完全不需更動 `aegis_cli.py`。
2.  **看板維護前端化 (Design Separation)**：
    *   想要美化監控看板網頁的設計？直接編輯 `dashboard_tpl.html`（享有 HTML/CSS 語法高亮與自動完成），不需在 Python 字串中痛苦地拼接 HTML 標籤。
3.  **零 Token 浪費的快速迭代 (Prompt Maintenance)**：
    *   防追高的 AI 紀律防線將會與主基本面估值提示詞解耦。一旦市場回歸常態趨勢市，只需關閉氣候感知，防追高 Prompt 自動卸載，不會持續佔用大模型的 Context Token。
