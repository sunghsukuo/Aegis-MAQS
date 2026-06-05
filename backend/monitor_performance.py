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
from core.tools.line_notifier import LineNotifier
import argparse

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
    from datetime import timedelta
    try:
        # Support formats like YYYY-MM-DD_HHMMSS or standard YYYY-MM-DD safely
        start_date = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
    except Exception:
        start_date = date.today()
        
    today = date.today()
    
    # Calculate business days (Monday to Friday) inclusive
    elapsed = 0
    if start_date <= today:
        curr = start_date
        while curr <= today:
            if curr.weekday() < 5:  # 0 is Monday, 4 is Friday
                elapsed += 1
            curr += timedelta(days=1)
            
    elapsed = max(1, elapsed)  # Day 1 start
    
    percent = min(1.0, elapsed / total_days)
    filled_length = int(total_days * percent)
    bar = "█" * filled_length + "░" * (total_days - filled_length)
    
    return elapsed, percent * 100, bar

def save_html_dashboard(
    elapsed_days, progress_percent, prog_bar,
    twd_state, usd_state,
    active_twd_invested, active_usd_invested,
    active_twd_pnl, active_usd_pnl,
    twd_nav, usd_nav,
    twd_metrics, usd_metrics,
    perf_data, closed_recs, active_recs,
    twd_nav_history, usd_nav_history
):
    import json
    from datetime import datetime
    
    # Calculate pocket-specific returns
    total_pnl_twd = sum(r["pnl"] for r in closed_recs if r["region"] != "US")
    total_pnl_usd = sum(r["pnl"] for r in closed_recs if r["region"] == "US")
    total_twd_pnl = total_pnl_twd + active_twd_pnl
    total_usd_pnl = total_pnl_usd + active_usd_pnl
    total_twd_roi = (total_twd_pnl / 1200000.0) * 100
    total_usd_roi = (total_usd_pnl / 120000.0) * 100

    # We resolve logs/dashboard.html dynamically
    dashboard_path = Path(__file__).resolve().parent / "logs" / "dashboard.html"
    
    # Serialize data
    active_recs_json = json.dumps(active_recs, default=str, ensure_ascii=False)
    closed_recs_json = json.dumps(closed_recs, default=str, ensure_ascii=False)
    twd_history_json = json.dumps(twd_nav_history, default=str, ensure_ascii=False)
    usd_history_json = json.dumps(usd_nav_history, default=str, ensure_ascii=False)
    
    # Determine the status badge class & label
    status_label = "沙盒觀測中"
    
    # Construct html content
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>30天實戰觀測·智慧對帳與風險監控看板</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #111827;
            --card-hover: #1f2937;
            --border-color: #374151;
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --glow-color: rgba(59, 130, 246, 0.08);
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: 'Outfit', 'Noto Sans TC', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            padding: 2rem;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }}
        
        /* Header */
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}
        .header-title h1 {{
            font-size: 2.2rem;
            font-weight: 700;
            background: linear-gradient(135deg, #60a5fa, #3b82f6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 0.8rem;
        }}
        .status-badge {{
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid var(--accent-green);
            color: var(--accent-green);
            padding: 0.3rem 0.8rem;
            border-radius: 50px;
            font-size: 0.85rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }}
        .status-badge::before {{
            content: '';
            display: inline-block;
            width: 8px;
            height: 8px;
            background-color: var(--accent-green);
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.9); opacity: 0.6; }}
            50% {{ transform: scale(1.2); opacity: 1; }}
            100% {{ transform: scale(0.9); opacity: 0.6; }}
        }}
        .last-update {{
            font-size: 0.9rem;
            color: var(--text-secondary);
            text-align: right;
        }}
        
        /* Progress Card */
        .progress-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        }}
        .progress-info {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.8rem;
            font-weight: 600;
        }}
        .progress-track {{
            height: 12px;
            background: #1f2937;
            border-radius: 6px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--accent-blue), #60a5fa);
            border-radius: 6px;
            width: {progress_percent:.1f}%;
        }}
        
        /* Grid Layout */
        .grid-2 {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(600px, 1fr));
            gap: 2rem;
        }}
        .grid-3 {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 2rem;
        }}
        
        /* Cards */
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.8rem;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        }}
        .card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5), 0 0 20px var(--glow-color);
        }}
        .card-header {{
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            border-bottom: 1px solid #1f2937;
            padding-bottom: 0.8rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        /* Metrics values */
        .metric-row {{
            display: flex;
            justify-content: space-between;
            padding: 0.8rem 0;
            border-bottom: 1px dashed #1f2937;
        }}
        .metric-row:last-child {{
            border-bottom: none;
        }}
        .metric-label {{
            color: var(--text-secondary);
        }}
        .metric-value {{
            font-weight: 600;
        }}
        .nav-value {{
            font-size: 1.8rem;
            color: var(--accent-blue);
            font-weight: 700;
        }}
        
        /* Risk Indicators */
        .risk-indicators {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            margin-top: 1.5rem;
            text-align: center;
        }}
        .risk-box {{
            background: #1f2937;
            border-radius: 8px;
            padding: 0.8rem;
        }}
        .risk-box-lbl {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
        }}
        .risk-box-val {{
            font-size: 1.2rem;
            font-weight: 700;
            margin-top: 0.3rem;
        }}
        
        /* Chart Card */
        .chart-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.8rem;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        }}
        .chart-container {{
            height: 380px;
            position: relative;
        }}
        
        /* Table styles */
        .table-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.8rem;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .table-wrapper {{
            overflow-x: auto;
            margin-top: 1rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th {{
            background: #1f2937;
            color: var(--text-secondary);
            font-weight: 600;
            padding: 1rem;
            font-size: 0.9rem;
            text-transform: uppercase;
        }}
        td {{
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
        }}
        tr:hover td {{
            background: rgba(31, 41, 55, 0.4);
        }}
        .badge {{
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
        }}
        .badge-tw {{
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }}
        .badge-us {{
            background: rgba(245, 158, 11, 0.15);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }}
        
        .value-green {{
            color: var(--accent-green);
        }}
        .value-red {{
            color: var(--accent-red);
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            body {{ padding: 1rem; }}
            .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
            header {{ flex-direction: column; align-items: flex-start; gap: 1rem; }}
            .last-update {{ text-align: left; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="header-title">
                <h1>📊 30天實戰觀測·智慧對帳與風險監控看板</h1>
                <div class="status-badge" style="margin-top:0.5rem; display:inline-flex;">{status_label}</div>
            </div>
            <div class="last-update">
                <p>資料同步時間</p>
                <p style="font-weight: 600; color: var(--text-primary); font-size:1.1rem; margin-top:0.3rem;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </header>

        <!-- Progress Card -->
        <div class="progress-card">
            <div class="progress-info">
                <span>觀測進度</span>
                <span>第 {elapsed_days} / 30 天 ({progress_percent:.1f}%)</span>
            </div>
            <div class="progress-track">
                <div class="progress-fill"></div>
            </div>
        </div>

        <!-- Ledger HUD -->
        <div class="grid-2">
            <!-- TWD Pocket -->
            <div class="card">
                <div class="card-header">
                    <span>💰 台股資金水位 (TWD Pocket)</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">總資產淨值 (NAV)</span>
                    <span class="metric-value nav-value">{twd_nav:,.2f} TWD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">可投資現金 / 安全金</span>
                    <span class="metric-value">{twd_state['available_capital']:,.2f} / {twd_state['reserved_cash']:,.2f} TWD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">在製品持股金額</span>
                    <span class="metric-value">{active_twd_invested:,.2f} TWD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">未實現損益</span>
                    <span class="metric-value {'value-green' if active_twd_pnl >= 0 else 'value-red'}">{active_twd_pnl:+,.2f} TWD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">已實現損益</span>
                    <span class="metric-value {'value-green' if total_pnl_twd >= 0 else 'value-red'}">{total_pnl_twd:+,.2f} TWD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">總損益與回報</span>
                    <span class="metric-value {'value-green' if total_twd_pnl >= 0 else 'value-red'}">{total_twd_pnl:+,.2f} TWD ({total_twd_roi:+.2f}%)</span>
                </div>
                
                <div class="risk-indicators">
                    <div class="risk-box">
                        <div class="risk-box-lbl">Sharpe Ratio</div>
                        <div class="risk-box-val {'value-green' if twd_metrics.get('sharpe', 0.0) >= 0 else 'value-red'}">
                            {twd_metrics.get('sharpe', 0.0):+.2f}
                        </div>
                    </div>
                    <div class="risk-box">
                        <div class="risk-box-lbl">Sortino Ratio</div>
                        <div class="risk-box-val {'value-green' if twd_metrics.get('sortino', 0.0) >= 0 else 'value-red'}">
                            {twd_metrics.get('sortino', 0.0):+.2f}
                        </div>
                    </div>
                    <div class="risk-box">
                        <div class="risk-box-lbl">Max Drawdown</div>
                        <div class="risk-box-val value-red">
                            {twd_metrics.get('mdd', 0.0)*100:.2f}%
                        </div>
                    </div>
                </div>
            </div>

            <!-- USD Pocket -->
            <div class="card">
                <div class="card-header">
                    <span>💵 美股資金水位 (USD Pocket)</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">總資產淨值 (NAV)</span>
                    <span class="metric-value nav-value">{usd_nav:,.2f} USD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">可投資現金 / 安全金</span>
                    <span class="metric-value">{usd_state['available_capital']:,.2f} / {usd_state['reserved_cash']:,.2f} USD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">在製品持股金額</span>
                    <span class="metric-value">{active_usd_invested:,.2f} USD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">未實現損益</span>
                    <span class="metric-value {'value-green' if active_usd_pnl >= 0 else 'value-red'}">{active_usd_pnl:+,.2f} USD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">已實現損益</span>
                    <span class="metric-value {'value-green' if total_pnl_usd >= 0 else 'value-red'}">{total_pnl_usd:+,.2f} USD</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">總損益與回報</span>
                    <span class="metric-value {'value-green' if total_usd_pnl >= 0 else 'value-red'}">{total_usd_pnl:+,.2f} USD ({total_usd_roi:+.2f}%)</span>
                </div>
                
                <div class="risk-indicators">
                    <div class="risk-box">
                        <div class="risk-box-lbl">Sharpe Ratio</div>
                        <div class="risk-box-val {'value-green' if usd_metrics.get('sharpe', 0.0) >= 0 else 'value-red'}">
                            {usd_metrics.get('sharpe', 0.0):+.2f}
                        </div>
                    </div>
                    <div class="risk-box">
                        <div class="risk-box-lbl">Sortino Ratio</div>
                        <div class="risk-box-val {'value-green' if usd_metrics.get('sortino', 0.0) >= 0 else 'value-red'}">
                            {usd_metrics.get('sortino', 0.0):+.2f}
                        </div>
                    </div>
                    <div class="risk-box">
                        <div class="risk-box-lbl">Max Drawdown</div>
                        <div class="risk-box-val value-red">
                            {usd_metrics.get('mdd', 0.0)*100:.2f}%
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Equity Curve Chart -->
        <div class="chart-card">
            <div class="card-header">📈 淨值成長曲線 (Equity Curve - Sandbox observation)</div>
            <div class="chart-container">
                <canvas id="navChart"></canvas>
            </div>
        </div>

        <!-- Active holdings -->
        <div class="table-card">
            <div class="card-header">📈 當前在庫追蹤標的 (Active Holdings)</div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>市場</th>
                            <th>代號</th>
                            <th>企業名稱</th>
                            <th>推薦買入價</th>
                            <th>當前價格</th>
                            <th>投入資金</th>
                            <th>分配股數</th>
                            <th>未實現損益 (ROI / PnL)</th>
                        </tr>
                    </thead>
                    <tbody id="active-table-body">
                        <!-- JS Render -->
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Closed trades ledger -->
        <div class="table-card">
            <div class="card-header">📜 歷史已平倉結案明細 (Closed Trades Ledger - Top 15)</div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>市場</th>
                            <th>代號</th>
                            <th>企業名稱</th>
                            <th>買入價格</th>
                            <th>平倉價格</th>
                            <th>結案日期</th>
                            <th>已實現損益 (ROI)</th>
                        </tr>
                    </thead>
                    <tbody id="closed-table-body">
                        <!-- JS Render -->
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        // Pre-injected JSON Data
        const activeRecs = {active_recs_json};
        const closedRecs = {closed_recs_json};
        const twdHistory = {twd_history_json};
        const usdHistory = {usd_history_json};

        // 1. Draw Equity Curve Chart
        const dates = Array.from(new Set([
            ...twdHistory.map(r => r.date),
            ...usdHistory.map(r => r.date)
        ])).sort();

        const ctx = document.getElementById('navChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: dates,
                datasets: [
                    {{
                        label: '台股帳戶淨值 (TWD)',
                        data: dates.map(d => {{
                            const match = twdHistory.find(r => r.date === d);
                            return match ? match.total_nav : null;
                        }}),
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.03)',
                        yAxisID: 'y-twd',
                        tension: 0.15,
                        borderWidth: 2,
                        pointBackgroundColor: '#3b82f6',
                        fill: true
                    }},
                    {{
                        label: '美股帳戶淨值 (USD)',
                        data: dates.map(d => {{
                            const match = usdHistory.find(r => r.date === d);
                            return match ? match.total_nav : null;
                        }}),
                        borderColor: '#fbbf24',
                        backgroundColor: 'rgba(251, 191, 36, 0.03)',
                        yAxisID: 'y-usd',
                        tension: 0.15,
                        borderWidth: 2,
                        pointBackgroundColor: '#fbbf24',
                        fill: true
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false,
                }},
                scales: {{
                    'y-twd': {{
                        type: 'linear',
                        position: 'left',
                        grid: {{ color: '#1f2937' }},
                        ticks: {{ color: '#9ca3af' }},
                        title: {{ display: true, text: 'TWD (台幣)', color: '#3b82f6' }}
                    }},
                    'y-usd': {{
                        type: 'linear',
                        position: 'right',
                        grid: {{ drawOnChartArea: false }},
                        ticks: {{ color: '#9ca3af' }},
                        title: {{ display: true, text: 'USD (美金)', color: '#fbbf24' }}
                    }},
                    x: {{
                        grid: {{ color: '#1f2937' }},
                        ticks: {{ color: '#9ca3af' }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        labels: {{ color: '#f3f4f6' }}
                    }}
                }}
            }}
        }});

        // 2. Render Active table
        const activeTable = document.getElementById('active-table-body');
        if (activeRecs.length === 0) {{
            activeTable.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text-secondary);">目前在庫無追蹤股票。週六早上系統會執行量化選股掃描並新增追蹤標的。</td></tr>`;
        }} else {{
            activeRecs.forEach(rec => {{
                const isUS = rec.region === 'US';
                const currency = isUS ? 'USD' : 'TWD';
                const pnl = rec.pnl || 0;
                const currentPrice = rec.current_price !== undefined ? rec.current_price : rec.recommend_price;
                const roi = rec.recommend_price ? (pnl / (rec.shares * rec.recommend_price)) : 0;
                const pnlClass = pnl >= 0 ? 'value-green' : 'value-red';
                const pnlSign = pnl >= 0 ? '+' : '';
                
                activeTable.innerHTML += `
                    <tr>
                        <td><span class="badge ${{isUS ? 'badge-us' : 'badge-tw'}}">${{isUS ? '美股' : '台股'}}</span></td>
                        <td style="font-weight:600;">${{rec.ticker}}</td>
                        <td>${{rec.company_name}}</td>
                        <td>${{Number(rec.recommend_price).toFixed(1)}} ${{currency}}</td>
                        <td>${{Number(currentPrice).toFixed(1)}} ${{currency}}</td>
                        <td>${{Number(rec.invested_amount).toLocaleString()}} ${{currency}}</td>
                        <td>${{Number(rec.shares).toLocaleString()}}</td>
                        <td class="${{pnlClass}}" style="font-weight:600;">
                            ${{pnlSign}}${{Number(pnl).toLocaleString(undefined, {{maximumFractionDigits: 0}})}} ${{currency}} (${{pnlSign}}${{(roi * 100).toFixed(1)}}%)
                        </td>
                    </tr>
                `;
            }});
        }}

        // 3. Render Closed table
        const closedTable = document.getElementById('closed-table-body');
        if (closedRecs.length === 0) {{
            closedTable.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-secondary);">目前尚無歷史平倉紀錄。當持股達到止盈目標價或跌破止損點時，系統會自動平倉並計算績效。</td></tr>`;
        }} else {{
            const sortedClosed = [...closedRecs].sort((a,b) => b.close_date.localeCompare(a.close_date)).slice(0, 15);
            sortedClosed.forEach(rec => {{
                const isUS = rec.region === 'US';
                const currency = isUS ? 'USD' : 'TWD';
                const pnl = rec.pnl || 0;
                const roi = rec.performance || 0;
                const pnlClass = pnl >= 0 ? 'value-green' : 'value-red';
                const pnlSign = pnl >= 0 ? '+' : '';
                
                closedTable.innerHTML += `
                    <tr>
                        <td><span class="badge ${{isUS ? 'badge-us' : 'badge-tw'}}">${{isUS ? '美股' : '台股'}}</span></td>
                        <td style="font-weight:600;">${{rec.ticker}}</td>
                        <td>${{rec.company_name}}</td>
                        <td>${{Number(rec.recommend_price).toFixed(1)}} ${{currency}}</td>
                        <td>${{Number(rec.close_price).toFixed(1)}} ${{currency}}</td>
                        <td>${{rec.close_date || ''}}</td>
                        <td class="${{pnlClass}}" style="font-weight:600;">
                            ${{pnlSign}}${{Number(pnl).toLocaleString(undefined, {{maximumFractionDigits: 0}})}} ${{currency}} (${{pnlSign}}${{(roi * 100).toFixed(1)}}%)
                        </td>
                    </tr>
                `;
            }});
        }}
    </script>
</body>
</html>"""
    
    try:
        with open(dashboard_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        sys.__stdout__.write(f"[✓] 自動網頁面板渲染成功，已儲存至：{dashboard_path}\n")
    except Exception as e:
        sys.stderr.write(f"[!] 自動網頁面板渲染失敗: {e}\n")

def main():
    parser = argparse.ArgumentParser(description="投資研究多代理人系統 - 30天實戰觀測期監控看板")
    parser.add_argument("--silent", action="store_true", help="靜默執行，不輸出終端機表格")
    parser.add_argument("--send-line", action="store_true", help="主動發送 LINE 監督日報")
    args = parser.parse_args()
    
    if args.silent:
        import builtins
        builtins.print = lambda *args, **kwargs: None
        
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
            
        # Store live calculated price and pnl back to rec dict
        rec["current_price"] = current_price
        rec["pnl"] = unrealized_pnl
            
    # Calculate NAV (Net Asset Value)
    twd_nav = twd_state["available_capital"] + twd_state["reserved_cash"] + active_twd_invested + active_twd_pnl
    usd_nav = usd_state["available_capital"] + usd_state["reserved_cash"] + active_usd_invested + active_usd_pnl

    # Calculate Pocket-specific realized and total returns
    total_pnl_twd = sum(r["pnl"] for r in closed_recs if r["region"] != "US")
    total_pnl_usd = sum(r["pnl"] for r in closed_recs if r["region"] == "US")
    total_twd_pnl = total_pnl_twd + active_twd_pnl
    total_usd_pnl = total_pnl_usd + active_usd_pnl
    total_twd_roi = (total_twd_pnl / 1200000.0) * 100
    total_usd_roi = (total_usd_pnl / 120000.0) * 100
    
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
        print(f"  [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] {BOLD}第 0 / 30 天{RESET} (等待明早 10:00 週報產出)")
        
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
    print(f"    - 已實現損益: {BOLD}{GREEN if total_pnl_twd >= 0 else RED}{total_pnl_twd:+11,.2f} TWD{RESET} | 總損益/回報: {BOLD}{GREEN if total_twd_pnl >= 0 else RED}{total_twd_pnl:+11,.2f} TWD{RESET} ({BOLD}{GREEN if total_twd_roi >= 0 else RED}{total_twd_roi:+.2f}%{RESET})")
    print(f"    - 總資產淨值 (NAV): {BOLD}{BLUE}{twd_nav:14,.2f} TWD{RESET}")
    
    print(f"\n  {BOLD}• 美股資金水位 (USD Pocket)：{RESET}")
    print(f"    - 可投資現金: {BOLD}{usd_state['available_capital']:11,.2f} USD{RESET} | 保留安全金: {BOLD}{usd_state['reserved_cash']:11,.2f} USD{RESET}")
    print(f"    - 在庫持股金: {BOLD}{active_usd_invested:11,.2f} USD{RESET} | 未實現損益: {BOLD}{GREEN if active_usd_pnl >= 0 else RED}{active_usd_pnl:+11,.2f} USD{RESET}")
    print(f"    - 已實現損益: {BOLD}{GREEN if total_pnl_usd >= 0 else RED}{total_pnl_usd:+11,.2f} USD{RESET} | 總損益/回報: {BOLD}{GREEN if total_usd_pnl >= 0 else RED}{total_usd_pnl:+11,.2f} USD{RESET} ({BOLD}{GREEN if total_usd_roi >= 0 else RED}{total_usd_roi:+.2f}%{RESET})")
    print(f"    - 總資產淨值 (NAV): {BOLD}{BLUE}{usd_nav:14,.2f} USD{RESET}")
    
    # 4. Render Historical Performance (Closed Positions)
    print_header("🏆 歷史交易績效 (Realized Performance - Closed Positions)")
    
    if closed_recs:
        win_rate = perf_data["win_rate"] * 100
        avg_roi = perf_data["avg_roi"] * 100
        
        # Find best and worst trades
        best_trade = max(closed_recs, key=lambda x: x["performance"])
        worst_trade = min(closed_recs, key=lambda x: x["performance"])
        
        best_currency = "USD" if best_trade["region"] == "US" else "TWD"
        worst_currency = "USD" if worst_trade["region"] == "US" else "TWD"
        
        best_roi_formatted = format_roi_padded(best_trade['performance'], best_trade.get('pnl', 0.0), best_currency, 0).strip()
        worst_roi_formatted = format_roi_padded(worst_trade['performance'], worst_trade.get('pnl', 0.0), worst_currency, 0).strip()
        
        wins = sum(1 for r in closed_recs if r['performance'] > 0)
        losses = len(closed_recs) - wins
        print(f"  • 交易勝率 (Win Rate)  : {BOLD}{GREEN if win_rate >= 50 else RED}{win_rate:.1f}%{RESET} ({wins} 勝 / {losses} 敗)")
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
                
            # Retrieve cached live price and pnl
            current_price = rec.get("current_price", recommend_price)
            unrealized_pnl = rec.get("pnl", 0.0)
            unrealized_roi = (current_price - recommend_price) / recommend_price if recommend_price != 0.0 else 0.0
            
            region_str = pad_right(region, 4)
            ticker_str = pad_right(ticker, 7)
            company_str = pad_right(company_name, 17)
            recommend_price_str = pad_left(f"{recommend_price:.1f}", 7)
            current_price_str = pad_left(f"{current_price:.1f}", 7)
            invested_str = pad_left(f"{invested_amount:.0f}", 8)
            unrealized_roi_str = format_roi_padded(unrealized_roi, unrealized_pnl, currency, 18)
            
            print(f"{region_str} | {ticker_str} | {company_str} | {recommend_price_str} | {current_price_str} | {invested_str} | {unrealized_roi_str}")
        
        print("─" * 80)
        print("  * 損益資料與即時價格每分鐘同步更新 *")
        print("  * 當大模型未能順利產出評級或權重時，會以較為保守的 10% 基線建立初始部位 *")
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

    # --- 💡 LINE Auto-Pilot Daily Report & Risk Watchdog Integration ---
    if args.send_line:
        try:
            # 1. Fetch risk metrics
            from check_portfolio import calculate_risk_adjusted_metrics
            twd_metrics = calculate_risk_adjusted_metrics("TWD")
            usd_metrics = calculate_risk_adjusted_metrics("USD")
        except Exception as e:
            sys.stderr.write(f"[!] 無法載入或計算量化風險指標: {e}\n")
            twd_metrics = {"sharpe": 0.0, "sortino": 0.0, "mdd": 0.0, "data_points": 0}
            usd_metrics = {"sharpe": 0.0, "sortino": 0.0, "mdd": 0.0, "data_points": 0}

        # 2. Fetch historical peak NAVs to evaluate current asset drop
        twd_navs = [r["total_nav"] for r in db.get_portfolio_nav_history("TWD")]
        usd_navs = [r["total_nav"] for r in db.get_portfolio_nav_history("USD")]

        twd_peak = max(twd_navs + [twd_nav]) if twd_navs else twd_nav
        usd_peak = max(usd_navs + [usd_nav]) if usd_navs else usd_nav

        twd_drop = (twd_peak - twd_nav) / twd_peak if twd_peak > 0.0 else 0.0
        usd_drop = (usd_peak - usd_nav) / usd_peak if usd_peak > 0.0 else 0.0

        twd_mdd = twd_metrics.get("mdd", 0.0)
        usd_mdd = usd_metrics.get("mdd", 0.0)

        # 3. Determine if watchdog alert is triggered (MDD > 3% or drop from peak > 3%)
        trigger_warning = (twd_mdd > 0.03) or (usd_mdd > 0.03) or (twd_drop > 0.03) or (usd_drop > 0.03)

        # 4. Construct beautiful message card
        if trigger_warning:
            # 🚨 Risk Watchdog Emergency Warning
            message = (
                f"🚨 【風控警報·沙盒資產淨值與回撤警告】\n"
                f"================================\n"
                f"觀測進度：第 {elapsed_days} / 30 天\n"
                f"發送時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"⚠️ 系統已偵測到風控指標突破預設警戒線 (3.0%)！\n"
            )
            triggers = []
            if twd_mdd > 0.03:
                triggers.append(f"• 台股歷史最大回撤 (MDD) 達 {twd_mdd*100:.2f}%")
            if twd_drop > 0.03:
                triggers.append(f"• 台股資產自峰值回降 達 {twd_drop*100:.2f}%")
            if usd_mdd > 0.03:
                triggers.append(f"• 美股歷史最大回撤 (MDD) 達 {usd_mdd*100:.2f}%")
            if usd_drop > 0.03:
                triggers.append(f"• 美股資產自峰值回降 達 {usd_drop*100:.2f}%")
            message += "\n".join(triggers) + "\n\n"

            message += (
                f"💰 【台股資金狀態 (TWD Pocket)】\n"
                f"  • 當前資產淨值: {twd_nav:,.2f} TWD\n"
                f"  • 帳戶歷史峰值: {twd_peak:,.2f} TWD (目前回撤: {twd_drop*100:.2f}%)\n"
                f"  • 歷史最大回撤 (MDD): {twd_mdd*100:.2f}%\n"
                f"  • 現金/安全金/持股: {twd_state['available_capital']:,.0f}/{twd_state['reserved_cash']:,.0f}/{active_twd_invested:,.0f} TWD\n\n"
                f"💵 【美股資金狀態 (USD Pocket)】\n"
                f"  • 當前資產淨值: {usd_nav:,.2f} USD\n"
                f"  • 帳戶歷史峰值: {usd_peak:,.2f} USD (目前回撤: {usd_drop*100:.2f}%)\n"
                f"  • 歷史最大回撤 (MDD): {usd_mdd*100:.2f}%\n"
                f"  • 現金/安全金/持股: {usd_state['available_capital']:,.0f}/{usd_state['reserved_cash']:,.0f}/{active_usd_invested:,.0f} USD\n\n"
                f"🛑 【緊急處置與風控對策】\n"
                f"沙盒實戰期回撤已突破 3.0% 風險警戒！為保護本金安全，請儘速登入後台伺服器檢視，必要時進行策略調校或手動停損干預。\n"
                f"如需強制執行日內持股重啟對帳，請在終端機輸入：\n"
                f"pipenv run python check_portfolio.py"
            )
        else:
            # 📊 30-Day Sandbox Auto-Pilot Daily Report
            total_pnl_twd = sum(r["pnl"] for r in closed_recs if r["region"] != "US")
            total_pnl_usd = sum(r["pnl"] for r in closed_recs if r["region"] == "US")
            total_twd_pnl = total_pnl_twd + active_twd_pnl
            total_usd_pnl = total_pnl_usd + active_usd_pnl
            total_twd_roi = (total_twd_pnl / 1200000.0) * 100
            total_usd_roi = (total_usd_pnl / 120000.0) * 100

            message = (
                f"📊 【30天沙盒實戰觀測·每日自動監督日報】\n"
                f"================================\n"
                f"觀測進度：第 {elapsed_days} / 30 天 ({progress_percent:.1f}%)\n"
                f"進度條：[{prog_bar.replace('█', '■').replace('░', '□')}]\n"
                f"發送時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"💰 【台股資金水位 (TWD Pocket)】\n"
                f"  • 總資產淨值 (NAV): {twd_nav:,.2f} TWD\n"
                f"  • 可投資現金: {twd_state['available_capital']:,.2f} TWD\n"
                f"  • 在庫持股金額: {active_twd_invested:,.2f} TWD\n"
                f"  • 未實現損益: {active_twd_pnl:+,.2f} TWD\n"
                f"  • 已實現損益: {total_pnl_twd:+,.2f} TWD\n"
                f"  • 總損益/回報: {total_twd_pnl:+,.2f} TWD ({total_twd_roi:+.2f}%)\n"
            )
            if twd_metrics["data_points"] >= 2:
                message += (
                    f"  • 年化夏普值 (Sharpe): {twd_metrics['sharpe']:+.2f}\n"
                    f"  • 年化索提諾 (Sortino): {twd_metrics['sortino']:+.2f}\n"
                    f"  • 最大回撤 (MDD): {twd_metrics['mdd']*100:.2f}%\n"
                )
            else:
                message += f"  • 風險指標：暫無歷史數據 (累積 {twd_metrics['data_points']} 天)\n"

            message += (
                f"\n💵 【美股資金水位 (USD Pocket)】\n"
                f"  • 總資產淨值 (NAV): {usd_nav:,.2f} USD\n"
                f"  • 可投資現金: {usd_state['available_capital']:,.2f} USD\n"
                f"  • 在庫持股金額: {active_usd_invested:,.2f} USD\n"
                f"  • 未實現損益: {active_usd_pnl:+,.2f} USD\n"
                f"  • 已實現損益: {total_pnl_usd:+,.2f} USD\n"
                f"  • 總損益/回報: {total_usd_pnl:+,.2f} USD ({total_usd_roi:+.2f}%)\n"
            )
            if usd_metrics["data_points"] >= 2:
                message += (
                    f"  • 年化夏普值 (Sharpe): {usd_metrics['sharpe']:+.2f}\n"
                    f"  • 年化索提諾 (Sortino): {usd_metrics['sortino']:+.2f}\n"
                    f"  • 最大回撤 (MDD): {usd_metrics['mdd']*100:.2f}%\n"
                )
            else:
                message += f"  • 風險指標：暫無歷史數據 (累積 {usd_metrics['data_points']} 天)\n"

            # Historical realized stats
            if closed_recs:
                win_rate = perf_data["win_rate"] * 100
                avg_roi = perf_data["avg_roi"] * 100
                total_pnl_twd = sum(r["pnl"] for r in closed_recs if r["region"] != "US")
                total_pnl_usd = sum(r["pnl"] for r in closed_recs if r["region"] == "US")
                wins = sum(1 for r in closed_recs if r['performance'] > 0)
                losses = len(closed_recs) - wins
                message += (
                    f"\n🏆 【歷史已實現績效 (Closed)】\n"
                    f"  • 交易勝率: {win_rate:.1f}% ({wins}勝/{losses}敗)\n"
                    f"  • 平均已實現 ROI: {avg_roi:+.2f}%\n"
                    f"  • 累計損益: TWD {total_pnl_twd:+,.0f} | USD {total_pnl_usd:+,.2f}\n"
                )
            else:
                message += f"\n🏆 【歷史已實現績效 (Closed)】\n  • 目前尚無歷史平倉紀錄。\n"

            # Top active holdings list
            if active_recs:
                message += f"\n📈 【當前在庫追蹤標的 (Active Top 5)】\n"
                for rec in active_recs[:5]:
                    ticker = rec["ticker"]
                    region_tag = "美股" if rec["region"] == "US" else "台股"
                    currency_tag = "USD" if rec["region"] == "US" else "TWD"
                    rec_price = rec["recommend_price"]
                    rec_shares = rec["shares"]
                    current_price = rec.get("current_price", rec_price)
                    rec_roi = (current_price - rec_price) / rec_price if rec_price != 0.0 else 0.0
                    rec_pnl = rec.get("pnl", 0.0)
                    message += f"  • {ticker} ({region_tag}): {rec_roi*100:+.1f}% ({rec_pnl:+,.0f} {currency_tag})\n"
                if len(active_recs) > 5:
                    message += f"  • ... 以及其餘 {len(active_recs) - 5} 檔在監控中的標的\n"
            else:
                message += f"\n📈 【當前在庫追蹤標的 (Active)】\n  • 目前無在庫持股。\n"

            message += (
                f"\n================================\n"
                f"💡 系統運行正常，各項風控指標均在安全閥值內。\n"
                f"※ 損益及即時價格皆與主資料庫完全同步。"
            )

        # 5. Dispatch via LineNotifier
        try:
            sys.__stdout__.write("[*] 正在發送自動監督日報至 LINE...\n")
            notifier = LineNotifier()
            notifier.send_message(message)
            sys.__stdout__.write("[✓] 自動監督日報成功發送至 LINE。\n")
        except Exception as e:
            sys.stderr.write(f"[!] LINE 監督日報發送失敗: {e}\n")

    # 6. Render dynamic HTML Dashboard in logs/dashboard.html
    try:
        # Resolve metrics and histories defensively to ensure no reference errors
        from check_portfolio import calculate_risk_adjusted_metrics
        twd_metrics_h = calculate_risk_adjusted_metrics("TWD")
        usd_metrics_h = calculate_risk_adjusted_metrics("USD")
        twd_nav_history_h = db.get_portfolio_nav_history("TWD")
        usd_nav_history_h = db.get_portfolio_nav_history("USD")
        
        save_html_dashboard(
            elapsed_days, progress_percent, prog_bar,
            twd_state, usd_state,
            active_twd_invested, active_usd_invested,
            active_twd_pnl, active_usd_pnl,
            twd_nav, usd_nav,
            twd_metrics_h, usd_metrics_h,
            perf_data, closed_recs, active_recs,
            twd_nav_history_h, usd_nav_history_h
        )
    except Exception as html_ex:
        sys.stderr.write(f"[!] 自動 HTML 網頁面板渲染遭遇異常: {html_ex}\n")

if __name__ == "__main__":
    main()
