import json
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

def save_html_dashboard(
    elapsed_days, progress_percent, prog_bar,
    twd_state, usd_state,
    active_twd_invested, active_usd_invested,
    active_twd_pnl, active_usd_pnl,
    twd_nav, usd_nav,
    twd_metrics, usd_metrics,
    perf_data, closed_recs, active_recs,
    twd_nav_history, usd_nav_history,
    total_days=60
):
    """
    Renders the performance monitoring dashboard page using a Jinja2 HTML template.
    """
    try:
        from datetime import datetime
        
        # Calculate pocket-specific returns
        total_pnl_twd = sum(r["pnl"] for r in closed_recs if r["region"] != "US")
        total_pnl_usd = sum(r["pnl"] for r in closed_recs if r["region"] == "US")
        total_twd_pnl = total_pnl_twd + active_twd_pnl
        total_usd_pnl = total_pnl_usd + active_usd_pnl
        total_twd_roi = (total_twd_pnl / 1200000.0) * 100
        total_usd_roi = (total_usd_pnl / 120000.0) * 100

        # Define status label
        status_label = "沙盒觀測中"
        
        # Format helper
        def fmt(val, precision=2, signed=False, is_currency=False):
            if val is None:
                return "0.00"
            sign = "+" if (signed and val >= 0) else ""
            return f"{sign}{val:,.{precision}f}"
            
        twd_pnl_class = "value-green" if active_twd_pnl >= 0 else "value-red"
        usd_pnl_class = "value-green" if active_usd_pnl >= 0 else "value-red"
        
        total_twd_pnl_class = "value-green" if total_twd_pnl >= 0 else "value-red"
        total_usd_pnl_class = "value-green" if total_usd_pnl >= 0 else "value-red"
        
        total_pnl_twd_class = "value-green" if total_pnl_twd >= 0 else "value-red"
        total_pnl_usd_class = "value-green" if total_pnl_usd >= 0 else "value-red"
        
        twd_metrics_sharpe_class = "value-green" if twd_metrics.get("sharpe", 0.0) >= 0 else "value-red"
        twd_metrics_sortino_class = "value-green" if twd_metrics.get("sortino", 0.0) >= 0 else "value-red"
        
        usd_metrics_sharpe_class = "value-green" if usd_metrics.get("sharpe", 0.0) >= 0 else "value-red"
        usd_metrics_sortino_class = "value-green" if usd_metrics.get("sortino", 0.0) >= 0 else "value-red"

        # Load Jinja template
        template = env.get_template("dashboard_tpl.html")
        
        # Render HTML
        html_content = template.render(
            status_label=status_label,
            datetime_now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            elapsed_days=elapsed_days,
            total_days=total_days,
            progress_percent=f"{progress_percent:.1f}",
            
            twd_nav=fmt(twd_nav),
            twd_state_available_capital=fmt(twd_state["available_capital"]),
            twd_state_reserved_cash=fmt(twd_state["reserved_cash"]),
            active_twd_invested=fmt(active_twd_invested),
            active_twd_pnl=fmt(active_twd_pnl, signed=True),
            active_twd_pnl_class=twd_pnl_class,
            total_pnl_twd=fmt(total_pnl_twd, signed=True),
            total_pnl_twd_class=total_pnl_twd_class,
            total_twd_pnl=fmt(total_twd_pnl, signed=True),
            total_twd_pnl_class=total_twd_pnl_class,
            total_twd_roi=fmt(total_twd_roi, signed=True),
            
            twd_metrics_sharpe=fmt(twd_metrics.get("sharpe", 0.0), signed=True),
            twd_metrics_sharpe_class=twd_metrics_sharpe_class,
            twd_metrics_sortino=fmt(twd_metrics.get("sortino", 0.0), signed=True),
            twd_metrics_sortino_class=twd_metrics_sortino_class,
            twd_metrics_mdd=fmt(twd_metrics.get("mdd", 0.0)*100),
            
            usd_nav=fmt(usd_nav),
            usd_state_available_capital=fmt(usd_state["available_capital"]),
            usd_state_reserved_cash=fmt(usd_state["reserved_cash"]),
            active_usd_invested=fmt(active_usd_invested),
            active_usd_pnl=fmt(active_usd_pnl, signed=True),
            active_usd_pnl_class=usd_pnl_class,
            total_pnl_usd=fmt(total_pnl_usd, signed=True),
            total_pnl_usd_class=total_pnl_usd_class,
            total_usd_pnl=fmt(total_usd_pnl, signed=True),
            total_usd_pnl_class=total_usd_pnl_class,
            total_usd_roi=fmt(total_usd_roi, signed=True),
            
            usd_metrics_sharpe=fmt(usd_metrics.get("sharpe", 0.0), signed=True),
            usd_metrics_sharpe_class=usd_metrics_sharpe_class,
            usd_metrics_sortino=fmt(usd_metrics.get("sortino", 0.0), signed=True),
            usd_metrics_sortino_class=usd_metrics_sortino_class,
            usd_metrics_mdd=fmt(usd_metrics.get("mdd", 0.0)*100),
            
            active_recs_json=json.dumps(active_recs, default=str, ensure_ascii=False),
            closed_recs_json=json.dumps(closed_recs, default=str, ensure_ascii=False),
            twd_history_json=json.dumps(twd_nav_history, default=str, ensure_ascii=False),
            usd_history_json=json.dumps(usd_nav_history, default=str, ensure_ascii=False)
        )
        
        # Save output
        dashboard_path = Path(__file__).resolve().parent.parent.parent / "logs" / "dashboard.html"
        dashboard_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(dashboard_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        sys.__stdout__.write(f"[✓] 自動網頁面板渲染成功，已儲存至：{dashboard_path}\n")
    except Exception as e:
        sys.stderr.write(f"[!] 自動網頁面板渲染失敗: {e}\n")
