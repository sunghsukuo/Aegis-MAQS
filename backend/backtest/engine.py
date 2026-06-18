import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Force backtest mode before importing any core package
os.environ["AEGIS_IN_BACKTEST"] = "1"

# Add backend directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Import safety isolation from backtest module
from backtest.db_backtest import apply_backtest_db_sandbox, init_backtest_database
from backtest.replayer import apply_backtest_replayer_sandbox, set_simulated_date, get_simulated_date

# Import core modules
import core.config as config
# Force DB_TYPE to sqlite globally
config.DB_TYPE = "sqlite"

import core.db_manager as db
import core.tools.yahoo_finance as yf_tool
from core.agents.fundamental_agent import FundamentalAgent
from core.agents.reflection_agent import ReflectionAgent
from core.agents.budget_agent import BudgetAgent
from core.tools.valuation_engine import ValuationEngine
from core.utils.parsers import extract_price_from_line
from check_portfolio import run_portfolio_check

def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")

class BacktestEngine:
    def __init__(self, start_date: str, end_date: str, initial_usd: float = 100000.0, initial_twd: float = 3000000.0, regions: list = None, tickers: list = None, use_pipeline: bool = True):
        """
        Aegis-MAQS 歷史沙盒回測引擎。
        - 100% 數據與網絡隔離，零污染實戰資料庫。
        - 支援「指定個股歷史回播」與「完整生產管線流程回測」。
        - 時間旅行（Time-Travel）與 RSS 新聞重播，防範前瞻偏差（Lookahead Bias）。
        - 整合 ReflectionAgent 提示詞演化與 Prompt QA 沙盒防線。
        """
        self.start_date_str = start_date
        self.end_date_str = end_date
        self.regions = regions if regions else ["US", "Taiwan"]
        self.tickers = tickers
        self.initial_usd = initial_usd
        self.initial_twd = initial_twd
        
        # 決定是否執行完整的選股管線
        if tickers and len(tickers) > 0:
            self.use_pipeline = False
            print(f"[🛡️ 回測引擎] 偵測到指定個股池，回測將以【指定個股歷史回播】模式運行。")
        else:
            self.use_pipeline = use_pipeline
            print(f"[🛡️ 回測引擎] 未指定個股池，回測將以【完整生產管線流程回測】模式運行。")
        
        # 1. 先初始化回測資料庫與同步實戰配置（此時生產連線尚未被 Monkey-Patch）
        init_backtest_database(initial_usd=initial_usd, initial_twd=initial_twd)
        
        # 2. 然後啟動回測沙盒安全劫持 (Monkey-Patch)
        apply_backtest_db_sandbox()
        apply_backtest_replayer_sandbox()
        print(f"[🛡️ 回測引擎] 沙盒資料庫初始化、seeding 與 Monkey-Patch 隔離完成。")

    def run(self):
        """執行歷史區間的回測循環（以日為單位流逝進行風控，以週為單位進行選股與生成研報）"""
        print("\n" + "="*50)
        print(f"🎬 啟動 Aegis-MAQS 歷史區間回測模擬器 (日級風控、週級選股)")
        print(f"   - 歷史時間軸：{self.start_date_str} ~ {self.end_date_str}")
        print(f"   - 回測模式  ：{'完整生產管線流程回測' if self.use_pipeline else '指定個股歷史回播'}")
        if not self.use_pipeline:
            print(f"   - 追蹤個股池：{', '.join(self.tickers)}")
        print(f"   - 初始本金  ：USD ${self.initial_usd:,.2f} | TWD ${self.initial_twd:,.2f}")
        print("="*50 + "\n")

        start_dt = parse_date(self.start_date_str)
        end_dt = parse_date(self.end_date_str)
        
        current_dt = start_dt
        week_count = 0
        evolution_trigger_weeks = 4  # 每 4 週定期觸發一次 Prompt 自適應演化
        
        # 模擬時間每日流逝
        while current_dt <= end_dt:
            sim_date_str = current_dt.strftime("%Y-%m-%d")
            # 判斷是否為週五 (weekday 4 代表週五) 或是回測第一天
            is_friday = (current_dt.weekday() == 4)
            is_first_day = (current_dt == start_dt)
            is_weekly_trigger = is_friday or is_first_day
            
            if is_weekly_trigger:
                print(f"\n🔔 [週回測模擬] 當前歷史模擬日期：{sim_date_str} (第 {week_count + 1} 週)")
            else:
                print(f"\n📅 [日風控監測] 當前歷史模擬日期：{sim_date_str}")
            
            # 1. 更新 simulated date (重播 Yahoo Finance 歷史股價與 financials)
            set_simulated_date(sim_date_str)
            
            # 2. 【每日執行】持股對帳與風控檢測 (觸發停損/停利立即平倉)
            print("[*] 執行在庫持股對帳與防禦性風控檢測...")
            try:
                if self.use_pipeline:
                    from core.pipelines.research_pipeline import run_portfolio_check_phase
                    run_portfolio_check_phase(sim_date_str, regions_list=self.regions)
                else:
                    run_portfolio_check(sim_date_str, regions=self.regions)
            except Exception as e:
                print(f"[!] 警告：持股對帳檢測發生異常: {e}")
                
            # 3. 【每週五執行】選股與決策/報告生成
            if is_weekly_trigger:
                if self.use_pipeline:
                    # 執行整個生產研究管線流程，完全基於當前模擬歷史時間！
                    print(f"[*] 執行每週實戰研究管線流程（總經分析、板塊排序、Constituents 動態篩選、個股分析、評級與預算下單、寫入帳本與報告）...")
                    try:
                        # 模擬 argparse parameters 傳入 pipeline
                        class MockArgs:
                            def __init__(self, regions):
                                self.regions = regions
                                self.force = True
                                self.phase = None
                        
                        # 建立當期研報的臨時儲存目錄
                        daily_dir = Path(config.REPORTS_DIR) / f"backtest_{sim_date_str}"
                        daily_dir.mkdir(parents=True, exist_ok=True)
                        
                        from core.pipelines.research_pipeline import run_report_pipeline
                        run_report_pipeline(
                            args=MockArgs(self.regions),
                            report_date=sim_date_str,
                            regions_list=self.regions,
                            timestamp_suffix="000000",
                            daily_reports_dir=daily_dir
                        )
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        print(f"[!] 警告：每週生產研究管線執行中途發生異常: {e}")
                else:
                    # 執行指定個股分析與決策
                    print("[*] 執行每週指定個股分析與決策...")
                    self.execute_weekly_analysis(sim_date_str)
                
                # 4. 定期觸發自適應 Prompt 演化 (整合 Prompt QA 驗證)
                if week_count > 0 and week_count % evolution_trigger_weeks == 0:
                    print("\n[🛡️ 演化週期] 達到演化間隔，啟動 ReflectionAgent 自適應演化引擎...")
                    try:
                        # 執行演化，這會自動在 sqlite 內部調用 run_prompt_qa_verification
                        # 由於 AEGIS_IN_BACKTEST 已設置為 1，QA 內部的 temp_sandbox_context 會自動跳過 patch 且不污染實戰
                        result = ReflectionAgent.evolve_prompts_core(dry_run=False)
                        if result:
                            print(f"[✓] [自適應演化] 成功在模擬中將 Prompt 升級至版本：{result['new_version']}")
                        else:
                            print("[✗] [自適應演化] 新演化 Prompt 未通過 QA 沙盒驗證，演化被攔截，維持原 Prompt。")
                    except Exception as ev_ex:
                        print(f"[!] 警告：Prompt 演化中途發生異常: {ev_ex}")
                
                week_count += 1
            
            # 時間前進一日 (1天)
            current_dt += timedelta(days=1)
            
        # 5. 回測結束，產出最終績效報告
        self.generate_final_report()

    def execute_weekly_analysis(self, sim_date_str: str):
        """對追蹤個股池進行基本面分析，若評級為 Buy/Strong Buy 則買入"""
        fundamental_agent = FundamentalAgent()
        budget_agent = BudgetAgent()
        
        # 獲取當前的自我反思指令
        reflection_directives = "防守第一，重視資產回撤控制與本金安全。"
        try:
            active_reflect = db.get_active_prompt("ReflectionAgent")
            if active_reflect:
                reflection_directives = "嚴格執行停損停利，尋找低估值且財務健康度高的標的。"
        except Exception:
            pass

        for ticker in self.tickers:
            # A. 檢查是否已經持倉 (is_active = 1)
            is_holding = False
            try:
                active_recs = db.get_active_recommendations()
                if any(r["ticker"] == ticker and r.get("shares", 0.0) > 0.0 for r in active_recs):
                    is_holding = True
            except Exception:
                pass
                
            if is_holding:
                print(f"   - {ticker} 目前在庫持倉中，跳過重複分析與買入。")
                continue
                
            # B. 獲取當前模擬日期下的歷史 financials
            financials = yf_tool.get_stock_financials(ticker)
            if not financials:
                continue
                
            curr_price = financials.get("current_price", 0.0)
            if curr_price == 0.0:
                continue
                
            # C. 執行投行估值模型
            try:
                valuation_report = ValuationEngine.run_valuation(ticker, financials)
            except Exception:
                valuation_report = "估值計算異常。"
                
            # D. Mock 消息面與大盤以防前瞻偏差
            macro_report = f"市場環境穩定，當前大盤指數呈區間震盪整理。模擬歷史日期：{sim_date_str}。"
            news_analysis = "個股消息面平靜，無重大突發財務危機或法律訴訟。"
            combined_context = f"""
【當前巨觀經濟環境】：
{macro_report}

【前期歷史回測之自我修正指令】：
{reflection_directives}

【投行級別量化估值模型報告 (Equity Valuation Engine)】:
{valuation_report}
"""
            # E. 調用 FundamentalAgent 分析
            try:
                region_code = "US" if not ticker.endswith(".TW") else "Taiwan"
                company_name = financials.get("short_name", ticker)
                
                stock_report = fundamental_agent.analyze(
                    ticker, company_name, financials, news_analysis, combined_context,
                    macro_regime="VOLATILE_RANGEBOUND", price_regime="MOMENTUM_TREND"
                )
                
                # 解析目標價、停損價、評級
                target_p = curr_price * 1.15
                stop_l = curr_price * 0.92
                rating = "Hold"
                
                for line in stock_report.split("\n"):
                    if "目標價" in line or "中線目標價" in line:
                        val = extract_price_from_line(line, curr_price, is_target=True)
                        if val > 0.0: target_p = val
                    elif "停損點" in line or "防禦停損點" in line:
                        val = extract_price_from_line(line, curr_price, is_target=False)
                        if val > 0.0: stop_l = val
                    elif "投資評級" in line:
                        line_upper = line.upper()
                        if "STRONG BUY" in line_upper or "強烈買入" in line_upper:
                            rating = "Strong Buy"
                        elif "SELL" in line_upper or "賣出" in line_upper:
                            rating = "Sell"
                        elif "BUY" in line_upper or "買入" in line_upper:
                            rating = "Buy"
                            
                # G. 買入決策執行
                if rating in ["Buy", "Strong Buy"]:
                    suggested_weight = 0.25 if rating == "Strong Buy" else 0.15
                    
                    invested_amount, shares = budget_agent.allocate_budget(
                        ticker, region_code, curr_price, custom_weight=suggested_weight, report_date=sim_date_str
                    )
                    
                    if invested_amount > 0.0:
                        reason = f"【回測模擬買入】基本面評級為 {rating}。估值分析結果支持買入。"
                        rec_id = db.save_recommendation(
                            report_date=sim_date_str,
                            region=region_code,
                            ticker=ticker,
                            company_name=company_name,
                            recommend_price=curr_price,
                            recommend_reason=reason,
                            target_price=target_p,
                            stop_loss=stop_l,
                            rating=rating,
                            invested_amount=invested_amount,
                            shares=shares,
                            macro_regime="VOLATILE_RANGEBOUND",
                            price_regime="MOMENTUM_TREND"
                        )
                        budget_agent.record_purchase(rec_id, ticker, region_code, curr_price, invested_amount, shares)
                        
                        db.save_agent_inference_log(
                            rec_id=rec_id,
                            agent_name="FundamentalAgent",
                            ticker=ticker,
                            input_prompt=fundamental_agent.last_prompt,
                            output_response=stock_report,
                            prompt_version=fundamental_agent.prompt_version
                        )
                        print(f"   [✓] 買入下單：{ticker} (價格: {curr_price:.2f} | 股數: {shares:.2f} | 分配金額: {invested_amount:,.2f})")
                else:
                    print(f"   [-] 觀望持平：{ticker} (評級: {rating} | 價格: {curr_price:.2f})")
            except Exception as ex:
                print(f"   [!] 警告：分析 {ticker} 時發生錯誤: {ex}")

    def generate_final_report(self):
        """統計回測數據並輸出 Markdown 與終端報告"""
        print("\n" + "="*50)
        print("🏁 歷史回測結束！正在結算最終統計指標...")
        print("="*50)
        
        all_recs = []
        try:
            with db.db_session() as conn:
                conn.row_factory = None
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM recommendations ORDER BY id ASC")
                columns = [col[0] for col in cursor.description]
                all_recs = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[!] 無法從資料庫提取 recommendations: {e}")
            
        # Only recommendations that resulted in a purchase (shares > 0) are considered trades
        trades = [r for r in all_recs if (r.get("shares") or 0.0) > 0.0]
        total_trades = len(trades)
        closed_trades = [r for r in trades if r.get("is_active") == 0]
        active_trades = [r for r in trades if r.get("is_active") == 1]
        
        wins = [t for t in closed_trades if (t.get("performance") if t.get("performance") is not None else 0.0) > 0.0]
        losses = [t for t in closed_trades if (t.get("performance") if t.get("performance") is not None else 0.0) <= 0.0]
        win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0

        
        from core.agents.budget_agent import BudgetAgent
        budget_agent = BudgetAgent()
        
        currencies_report = {}
        for region in self.regions:
            curr = budget_agent.get_currency_by_region(region)
            
            nav_history = db.get_portfolio_nav_history(curr)
            start_nav = self.initial_usd if curr == "USD" else self.initial_twd
            end_nav = nav_history[-1]["total_nav"] if nav_history else start_nav
            total_return = (end_nav - start_nav) / start_nav
            
            from check_portfolio import calculate_risk_adjusted_metrics
            metrics = calculate_risk_adjusted_metrics(curr)
            
            currencies_report[curr] = {
                "start_nav": start_nav,
                "end_nav": end_nav,
                "total_return": total_return,
                "sharpe": metrics["sharpe"],
                "sortino": metrics["sortino"],
                "mdd": metrics["mdd"]
            }

        prompt_versions = []
        try:
            with db.db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT version, updated_at FROM prompt_registry WHERE agent_name = 'FundamentalAgent' ORDER BY id ASC")
                prompt_versions = [dict(zip(["version", "updated_at"], row)) for row in cursor.fetchall()]
        except Exception:
            pass

        print("\n📊 【回測績效總覽】")
        print("-" * 50)
        print(f"總交易筆數：{total_trades} 筆 (已平倉: {len(closed_trades)} | 持倉中: {len(active_trades)})")
        if closed_trades:
            print(f"平倉勝率  ：{win_rate*100:.2f}% (多頭獲利: {len(wins)} 筆 | 停損避險: {len(losses)} 筆)")
        
        for curr, rep in currencies_report.items():
            print(f"\n💵 貨幣組合帳本 [{curr}]：")
            print(f"   - 起始淨值 (NAV)：{rep['start_nav']:,.2f}")
            print(f"   - 最終淨值 (NAV)：{rep['end_nav']:,.2f}")
            print(f"   - 累計回報率    ：{rep['total_return']*100:+.2f}%")
            print(f"   - 年化夏普比率  ：{rep['sharpe']:+.2f}")
            print(f"   - 最大歷史回撤  ：{rep['mdd']*100:.2f}%")
            
        print(f"\n🤖 Prompt 演化次數：{len(prompt_versions) - 1} 次")
        for i, pv in enumerate(prompt_versions):
            print(f"   - 版本 {i+1}: {pv['version']} ({pv['updated_at']})")
        print("-" * 50 + "\n")

        # Markdown Report Generation
        report_md = f"""# 📊 Aegis-MAQS 歷史沙盒回測績效報告

## 1. 回測配置背景
*   **回測區間**：`{self.start_date_str}` 至 `{self.end_date_str}`
*   **回測模式**：`{'完整生產管線流程回測' if self.use_pipeline else '指定個股歷史回播'}`
"""
        if not self.use_pipeline:
            report_md += f"*   **追蹤個股池**：`{', '.join(self.tickers)}`\n"
        else:
            report_md += f"*   **追蹤市場區域**：`{', '.join(self.regions)}` (完全自適應板塊與成分股動態選股)\n"
            
        report_md += f"""*   **初始注資本金**：`USD ${self.initial_usd:,.2f}` 與 `TWD ${self.initial_twd:,.2f}`
*   **資料庫隔離狀態**：🟢 100% 獨立 SQLite 回測帳本，未污染實戰資料庫

## 2. 量化投資組合表現

| 貨幣種 | 起始資產 (NAV) | 最終資產 (NAV) | 累計報酬率 | 夏普值 (Sharpe) | 索提諾值 (Sortino) | 最大歷史回撤 (MDD) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""
        for curr, rep in currencies_report.items():
            report_md += f"| **{curr}** | {rep['start_nav']:,.2f} | {rep['end_nav']:,.2f} | {rep['total_return']*100:+.2f}% | {rep['sharpe']:+.2f} | {rep['sortino']:+.2f} | {rep['mdd']*100:.2f}% |\n"

        report_md += f"""
## 3. 交易統計摘要
*   **總交易筆數**：`{total_trades}` 筆
*   **已結案平倉**：`{len(closed_trades)}` 筆
*   **在庫持股追蹤**：`{len(active_trades)}` 筆
*   **平倉交易勝率**：`{win_rate*100:.2f}%` (`{len(wins)}` 勝 / `{len(losses)}` 負)

### 🧾 歷史平倉交易明細
| 編號 | 交易日期 | 個股 Ticker | 企業名稱 | 推薦價格 | 平倉價格 | 累計回報率 | 結算狀態 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""
        for i, t in enumerate(closed_trades):
            perf = t.get('performance') if t.get('performance') is not None else 0.0
            roi_str = f"{perf*100:+.2f}%"
            status_tag = "🟢 獲利平倉" if perf > 0.0 else "🔴 停損避險"
            report_md += f"| {i+1} | {t['report_date']} | {t['ticker']} | {t['company_name']} | {t['recommend_price']:.2f} | {t.get('close_price', 0.0):.2f} | **{roi_str}** | {status_tag} |\n"


        report_md += f"""
## 4. Prompt 提示詞演化軌跡
在回測模擬期間，當累積足夠失敗平倉紀錄後，系統自動調度 `ReflectionAgent` 與 `MetaPromptOptimizer` 對 `FundamentalAgent` 進行提示詞的自我校正升級。每次升級均通過了 QA 沙盒防線的嚴格校驗：

| 序號 | 演化版本 | 升級時間 | 狀態 |
| :---: | :---: | :---: | :---: |
"""
        for i, pv in enumerate(prompt_versions):
            status = "🚀 當前活躍" if i == len(prompt_versions)-1 else "已存檔"
            report_md += f"| {i+1} | **{pv['version']}** | {pv['updated_at']} | {status} |\n"

        report_md += "\n> [!NOTE]\n> 本回測結果完全在 SQLite 回測隔離沙盒中運行，所有股價均為歷史時間旅行重播數據，無任何前瞻偏差（Lookahead Bias），且完全未對實戰 MySQL/SQLite 資料庫產生污染。\n"

        # 儲存至報告目錄
        try:
            report_dir = config.REPORTS_DIR
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "backtest_report.md"
            report_path.write_text(report_md, encoding="utf-8")
            print(f"\n[✓] 績效報告已成功寫入報告目錄：{report_path}")
        except Exception as ex:
            print(f"[!] 寫入報告目錄失敗: {ex}")

def main():
    parser = argparse.ArgumentParser(description="Aegis-MAQS 歷史區間沙盒回測引擎 (100% 資料庫隔離)")
    parser.add_argument("--start", default="2022-01-07", help="回測起始日期 (YYYY-MM-DD，建議為週五)")
    parser.add_argument("--end", default="2022-02-28", help="回測結束日期 (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=None, help="初始注資本金 (若指定，將同時覆蓋台幣與美元帳戶本金以相容舊版)")
    parser.add_argument("--capital-twd", type=float, default=3000000.0, help="台幣帳戶的初始注資本金")
    parser.add_argument("--capital-usd", type=float, default=100000.0, help="美元帳戶的初始注資本金")
    parser.add_argument("--tickers", nargs="*", default=None, help="指定要分析的個股池。若不指定則執行完整生產管線流程回測")
    parser.add_argument("--no-pipeline", action="store_true", help="強制停用完整生產管線流程，採用指定個股歷史回播模式")
    
    args = parser.parse_args()
    
    # 解析本金配置，確保相容舊有的 --capital
    capital_twd = args.capital_twd
    capital_usd = args.capital_usd
    if args.capital is not None:
        capital_twd = args.capital
        capital_usd = args.capital
        
    # 執行回測
    engine = BacktestEngine(
        start_date=args.start,
        end_date=args.end,
        initial_usd=capital_usd,
        initial_twd=capital_twd,
        tickers=args.tickers,
        use_pipeline=not args.no_pipeline
    )
    engine.run()

if __name__ == "__main__":
    main()
