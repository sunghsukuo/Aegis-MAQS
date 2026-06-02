# Aegis-MAQS (Aegis Multi-Agent Quantmental System)

這是一個基於 AI 多代理人（Multi-Agent）與量化定性融合（Quantmental）架構的自動化投資研究與風控系統。系統能每週自動掃描市場、分析總體經濟、抓取即時新聞催化劑、評估企業基本面，並進行自動化決策回測與自我修正，最終產出精美的每週投資研究建議報告，並支援動態 ATR 止損/止利與夏普值/最大回撤實時監控看板。

## 專案目錄結構 (Directory Structure)

```
Aegis-MAQS/
├── .github/
│   └── workflows/              # GitHub Actions 雲端自動化流程
├── backend/                    # 後端系統
│   ├── api/                    # Web API (FastAPI)
│   ├── core/                   # 核心邏輯
│   │   ├── agents/             # AI 代理人群 (Gemini SDK)
│   │   └── tools/              # 數據與搜尋工具 (yfinance, web scraping)
│   ├── aegis_cli.py            # 本地端測試與執行工具 (週報生成與量化選股管線)
│   ├── Pipfile                 # 套件依賴管理 (Pipenv)
│   └── Dockerfile              # 後端容器打包定義
├── frontend/                   # 前端看板 (Vite + React + TypeScript)
└── README.md
```

## 快速開始 (Quick Start)

### 1. 後端環境設定
進入後端目錄並使用 `pipenv` 安裝依賴：
```bash
cd backend
pipenv install
```

### 2. 設定環境變數
在 `backend/` 目錄下建立 `.env` 檔案並填入您的 Gemini API Key：
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. 本地端執行測試 (CLI)
```bash
pipenv run python aegis_cli.py --regions US Taiwan
```
