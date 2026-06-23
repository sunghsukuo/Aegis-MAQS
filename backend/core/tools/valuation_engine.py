import sys
import math
from pathlib import Path
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Import database and config
from core.db_manager import db_session, execute_sql
from core.tools.utils import get_cached_data, retry_on_exception
from core.config import CACHE_DIR, GEMINI_API_KEY, DEEPSEEK_API_KEY
from core.agents.base_agent import BaseAgent

def get_df_row(df, keys):
    """Safely extracts a row from a pandas DataFrame by checking multiple potential index keys."""
    if df is None or df.empty:
        return None
    for k in keys:
        if k in df.index:
            return df.loc[k]
    return None

def fetch_risk_free_rate() -> float:
    """Fetches the 10-year US Treasury yield (^TNX) dynamically, falling back to 4.25% on failure."""
    try:
        tnx = yf.Ticker("^TNX")
        rf_history = tnx.history(period="5d").dropna(subset=["Close"])
        if not rf_history.empty:
            # ^TNX Close is returned in percentage format (e.g. 4.35 for 4.35%)
            return float(rf_history["Close"].iloc[-1]) / 100.0
    except Exception:
        pass
    return 0.0425  # Fallback to 4.25%

class ValuationEngine:
    @staticmethod
    def calculate_wacc_and_dcf(ticker: str, financials: dict, currency: str, override_beta: float = None) -> dict:
        """
        Runs a 5-year Discounted Cash Flow (DCF) model and calculates WACC dynamically.
        """
        is_tw = currency == "TWD"
        curr_price = financials.get("current_price", 0.0)
        beta = override_beta if override_beta is not None else financials.get("beta", 1.0)
        if beta is None or beta <= 0:
            beta = 1.0
        
        # 1. Fetch Ticker statements
        t = yf.Ticker(ticker)
        try:
            cf = t.cashflow
            bs = t.balance_sheet
            income = t.financials
        except Exception as e:
            return {"status": "error", "message": f"無法載入財務報表: {e}"}
            
        # 2. Extract Shares Outstanding
        shares_outstanding = t.info.get("sharesOutstanding")
        if not shares_outstanding:
            # Fallback calculate from market cap
            mc = financials.get("market_cap")
            if mc and curr_price:
                shares_outstanding = mc / curr_price
            else:
                return {"status": "error", "message": "無法取得發行股數，DCF 中斷。"}

        # 3. Retrieve Cash & Debt from Balance Sheet
        cash_row = get_df_row(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"])
        cash = float(cash_row.iloc[0]) if (cash_row is not None and len(cash_row) > 0) else 0.0
        
        debt_row = get_df_row(bs, ["Total Debt"])
        total_debt = 0.0
        if debt_row is not None and len(debt_row) > 0:
            total_debt = float(debt_row.iloc[0])
        else:
            # Fallback: Long Term Debt + Current Debt
            lt_debt = get_df_row(bs, ["Long Term Debt"])
            curr_debt = get_df_row(bs, ["Current Debt", "Current Debt And Capital Lease Obligation"])
            if lt_debt is not None and len(lt_debt) > 0:
                total_debt += float(lt_debt.iloc[0])
            if curr_debt is not None and len(curr_debt) > 0:
                total_debt += float(curr_debt.iloc[0])
                
        # 4. Extract Free Cash Flow
        fcf_row = get_df_row(cf, ["Free Cash Flow"])
        fcf_0 = None
        if fcf_row is not None and len(fcf_row) > 0:
            # Get the most recent FCF (first column)
            fcf_0 = float(fcf_row.iloc[0])
        else:
            # Fallback Operating Cash Flow + Capital Expenditure
            ocf_row = get_df_row(cf, ["Operating Cash Flow"])
            capex_row = get_df_row(cf, ["Capital Expenditure", "Purchase Of PPE"])
            if ocf_row is not None and len(ocf_row) > 0:
                ocf = float(ocf_row.iloc[0])
                capex = float(capex_row.iloc[0]) if (capex_row is not None and len(capex_row) > 0) else 0.0
                fcf_0 = ocf + capex  # capex is typically negative

        if fcf_0 is None or fcf_0 <= 0:
            return {
                "status": "inapplicable",
                "message": "歷史自由現金流為負值或無法獲取，不適用標的 DCF 估值模型。"
            }

        # 5. Calculate WACC
        # Re = Rf + Beta * ERP
        rf_rate = fetch_risk_free_rate()
        erp = 0.055  # Equity Risk Premium assumed at 5.5%
        cost_of_equity = rf_rate + (beta * erp)
        
        # Effective Tax Rate
        tax_prov_row = get_df_row(income, ["Tax Provision"])
        pretax_row = get_df_row(income, ["Pretax Income"])
        if tax_prov_row is not None and pretax_row is not None and len(tax_prov_row) > 0 and len(pretax_row) > 0:
            tax_prov = float(tax_prov_row.iloc[0])
            pretax = float(pretax_row.iloc[0])
            tax_rate = tax_prov / pretax if pretax > 0 else (0.20 if is_tw else 0.21)
        else:
            tax_rate = 0.20 if is_tw else 0.21
        tax_rate = max(0.0, min(0.4, tax_rate))
        
        # Cost of Debt (Rd)
        interest_row = get_df_row(income, ["Interest Expense"])
        interest_expense = abs(float(interest_row.iloc[0])) if (interest_row is not None and len(interest_row) > 0) else 0.0
        
        if total_debt > 0 and interest_expense > 0:
            cost_of_debt = interest_expense / total_debt
            if cost_of_debt < 0.02 or cost_of_debt > 0.15:
                cost_of_debt = rf_rate + 0.02
        else:
            cost_of_debt = rf_rate + 0.02  # Fallback to Risk Free + Spread
            
        # Capital structure weights
        market_cap = financials.get("market_cap") or (curr_price * shares_outstanding)
        total_cap = market_cap + total_debt
        w_equity = market_cap / total_cap if total_cap > 0 else 1.0
        w_debt = total_debt / total_cap if total_cap > 0 else 0.0
        
        wacc = (w_equity * cost_of_equity) + (w_debt * cost_of_debt * (1 - tax_rate))
        wacc = max(0.05, min(0.20, wacc))  # Clamp between 5% and 20%
        
        # 6. Projections (5 Years)
        # Dynamic growth rate based on revenue growth
        rev_growth = financials.get("revenue_growth")
        if rev_growth is None:
            rev_growth = 0.06 if is_tw else 0.05
        growth_rate = max(0.02, min(0.20, rev_growth))  # Clamp growth rate between 2% and 20%
        
        # Perpetual terminal growth rate
        g_terminal = 0.015 if is_tw else 0.02  # 1.5% for TW, 2.0% for US
        
        projected_fcf = []
        discounted_fcf = []
        for year in range(1, 6):
            fcf_t = fcf_0 * ((1 + growth_rate) ** year)
            pv_t = fcf_t / ((1 + wacc) ** year)
            projected_fcf.append(fcf_t)
            discounted_fcf.append(pv_t)
            
        # Terminal Value
        terminal_value = (projected_fcf[-1] * (1 + g_terminal)) / (wacc - g_terminal)
        pv_terminal_value = terminal_value / ((1 + wacc) ** 5)
        
        # Enterprise Value
        enterprise_value = sum(discounted_fcf) + pv_terminal_value
        
        # Equity Value
        equity_value = enterprise_value + cash - total_debt
        intrinsic_value = equity_value / shares_outstanding
        
        return {
            "status": "success",
            "wacc": wacc,
            "cost_of_equity": cost_of_equity,
            "cost_of_debt": cost_of_debt,
            "tax_rate": tax_rate,
            "w_equity": w_equity,
            "w_debt": w_debt,
            "fcf_0": fcf_0,
            "growth_rate": growth_rate,
            "terminal_growth": g_terminal,
            "projected_fcf": projected_fcf,
            "discounted_fcf": discounted_fcf,
            "terminal_value": terminal_value,
            "pv_terminal": pv_terminal_value,
            "enterprise_value": enterprise_value,
            "cash": cash,
            "debt": total_debt,
            "equity_value": equity_value,
            "shares": shares_outstanding,
            "intrinsic_value": intrinsic_value
        }

    @staticmethod
    def calculate_comps(ticker: str, financials: dict, region: str) -> dict:
        """
        Runs a Comparables Analysis (同業乘數法) by loading peer stocks in the same sector.
        """
        from google import genai
        from google.genai import types
        import core.tools.yahoo_finance as yf_tool
        
        peers = []
        db_peers = []
        
        # 1. Query local database sector peers first as robust backup
        try:
            with db_session() as conn:
                cursor = conn.cursor()
                # Query the most specific sector (the one with the minimum constituent count).
                # Exclude broad market index ETFs and high dividend yield ETFs.
                query_sqlite = """
                    SELECT sc.sector_id, COUNT(sc2.ticker) as cnt
                    FROM sector_constituents sc
                    JOIN sector_registry sr ON sc.sector_id = sr.id
                    JOIN sector_constituents sc2 ON sc.sector_id = sc2.sector_id
                    WHERE sc.ticker = ? 
                      AND sr.sector_code NOT IN ('0050.TW', '0051.TW', '0056.TW', '006208.TW', '00878.TW', '00919.TW', '00929.TW', '00940.TW')
                    GROUP BY sc.sector_id
                    ORDER BY cnt ASC
                    LIMIT 1
                """
                query_mysql = """
                    SELECT sc.sector_id, COUNT(sc2.ticker) as cnt
                    FROM sector_constituents sc
                    JOIN sector_registry sr ON sc.sector_id = sr.id
                    JOIN sector_constituents sc2 ON sc.sector_id = sc2.sector_id
                    WHERE sc.ticker = %s 
                      AND sr.sector_code NOT IN ('0050.TW', '0051.TW', '0056.TW', '006208.TW', '00878.TW', '00919.TW', '00929.TW', '00940.TW')
                    GROUP BY sc.sector_id
                    ORDER BY cnt ASC
                    LIMIT 1
                """
                execute_sql(cursor, query_sqlite, query_mysql, (ticker,))
                row = cursor.fetchone()
                if row:
                    sector_id = row[0] if isinstance(row, (tuple, list)) else (row.get("sector_id") if isinstance(row, dict) else row["sector_id"])
                    execute_sql(
                        cursor,
                        "SELECT ticker, company_name FROM sector_constituents WHERE sector_id = ? AND ticker != ? LIMIT 4",
                        "SELECT ticker, company_name FROM sector_constituents WHERE sector_id = %s AND ticker != %s LIMIT 4",
                        (sector_id, ticker)
                    )
                    for peer_row in cursor.fetchall():
                        p_ticker = peer_row[0] if isinstance(peer_row, (tuple, list)) else (peer_row.get("ticker") if isinstance(peer_row, dict) else peer_row["ticker"])
                        p_name = peer_row[1] if isinstance(peer_row, (tuple, list)) else (peer_row.get("company_name") if isinstance(peer_row, dict) else peer_row["company_name"])
                        
                        # Populate Chinese stock names dynamically for Taiwan stocks
                        if not p_name:
                            if p_ticker.endswith((".TW", ".TWO")) or p_ticker.isdigit():
                                try:
                                    from core.tools.taiwan_stock_names import get_taiwan_stock_name
                                    p_name = get_taiwan_stock_name(p_ticker)
                                except Exception:
                                    pass
                            if not p_name:
                                p_name = p_ticker
                                
                        db_peers.append({"ticker": p_ticker, "name": p_name})
        except Exception as e:
            print(f"[!] 查詢本地資料庫同業時發生錯誤: {e}")
            
        # 2. Leverage Large Language Model to query global/regional competitors (Dynamic & Smart)
        if GEMINI_API_KEY or DEEPSEEK_API_KEY:
            try:
                company_name = financials.get("company_name", ticker)
                sector = financials.get("sector")
                industry = financials.get("industry")
                summary = financials.get("long_business_summary")
                
                company_context = f"產業板塊: {sector or '未提供'}\n行業類別: {industry or '未提供'}"
                if summary:
                    company_context += f"\n業務簡介: {summary[:600]}..."
                
                db_peers_context = ""
                if db_peers:
                    db_peers_context = "本地資料庫參考同業候選名單：\n" + "\n".join([f"- {p['ticker']} ({p['name']})" for p in db_peers])
                
                agent = BaseAgent(
                    name="ValuationHelper",
                    role="Financial Competitor Identifier",
                    system_instruction="你是一個專業的財經分析助手，專門識別上市公司的競爭對手。請只回覆合法的 JSON 資料。",
                    register_db=False
                )
                prompt = f"""
請為股票代號 {ticker} (公司名稱: {company_name}) 識別並篩選出 4 檔業務最相似、最具可比性的全球或區域競爭對手（同業）。

【目標公司資訊】
股票代號: {ticker}
公司名稱: {company_name}
{company_context}

{db_peers_context}

【篩選與回傳規範】
1. **必須為「正常上市交易中」的股票**：絕對不要推薦已下市、已合併、或更名的歷史股票代號！
   - 例如：台灣日月光請推薦 `3711.TW` (日月光投控)，絕對不能推薦已下市的 `2311.TW`。
2. **商業模式與價值鏈對齊 (最重要)**：
   - 同業必須與目標公司具有**相同或極度相似的商業模式與產業定位**（如：代工廠 vs 代工廠；IC設計 vs IC設計；晶圓代工 vs 晶圓代工；品牌廠 vs 品牌廠）。
   - **絕對不要混淆產業鏈上下游或客戶**。例如：
     - 若目標公司是代工廠（如鴻海 2317.TW），同業**必須**是其他電子代工/組裝廠（如廣達、和碩、緯創），**絕對不可**將其重要客戶（如 Apple）或上游晶片商（如 Qualcomm）列為同業，因為其利潤率、商業模式與估值倍數完全不同。
     - 若目標公司是晶圓代工廠（如台積電 2330.TW），同業應為聯電、Intel、Samsung，**絕對不可**將其客戶（如 Nvidia, Apple）或設備供應商（如 ASML）列為同業。
3. **正確同業範例參考 (Few-Shot)**：
   - 鴻海 (2317.TW) 的正確同業應為：廣達 (2382.TW)、和碩 (4938.TW)、緯創 (3231.TW)、英業達 (2356.TW)。
   - 台積電 (2330.TW) 的正確同業應為：聯電 (2303.TW)、Intel (INTC)、Samsung (005930.KS)。
4. **優先參考本地候選名單**：你可以參考「本地資料庫參考同業候選名單」，但如果該名單內的公司不符合上述「商業模式對齊」原則（例如本地分類過於廣泛），請**果斷排除並尋找更精準的全球/區域同業**。
5. **回傳格式**：請只回傳一個標準 JSON 陣列，不包含 ```json 或 ``` 等 Markdown 標記，格式如下：
[
  {{"ticker": "同業代號", "name": "同業名稱"}}
]

同業代號格式說明 (必須與 Yahoo Finance Ticker 一致)：
- 美股：直接使用 Ticker (例如 INTC, NVDA, AMD, QCOM)
- 台股：上市代號加上 .TW (例如 2303.TW)，上櫃代號加上 .TWO (例如 5274.TWO)
- 韓股：代號加上 .KS (例如 005930.KS)
- 其他市場比照 Yahoo Finance 標準代碼格式。
- ⚠️特別警告：在 "ticker" 欄位中必須填寫標準的 Yahoo Finance 股票代號（Ticker），絕對不可填寫公司完整名稱（例如：不准填寫 'Samsung Electronics Co., Ltd.', 'SK Hynix Inc.', 'Western Digital Corporation'，而必須填寫 '005930.KS', '000660.KS', 'WDC'）。
"""
                response_text = agent.run(prompt)
                if response_text:
                    import json
                    import re
                    clean_text = response_text.strip()
                    # Defensive parsing to strip markdown backticks if any
                    if clean_text.startswith("```"):
                        lines = clean_text.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        clean_text = "\n".join(lines).strip()
                    
                    llm_peers = json.loads(clean_text)
                    if isinstance(llm_peers, list):
                        valid_llm_peers = []
                        for p in llm_peers:
                            if isinstance(p, dict) and "ticker" in p and "name" in p:
                                p_ticker = p["ticker"].strip().upper()
                                # Validation defense: Must not be empty, must be <= 12 chars, no spaces, only allowed characters
                                if p_ticker and p_ticker != ticker.upper() and " " not in p_ticker and len(p_ticker) <= 12:
                                    if re.match(r"^[A-Z0-9.\-^:]+$", p_ticker):
                                        valid_llm_peers.append({
                                            "ticker": p_ticker,
                                            "name": p["name"]
                                        })
                        peers = valid_llm_peers
                        print(f"[✓] 成功利用大模型檢索到 {ticker} 的全球同業: {[p['ticker'] for p in peers]}")
            except Exception as e:
                print(f"[!] 利用大模型檢索同業時發生錯誤 (將回退至資料庫查詢): {e}")

        # If LLM failed or not available, use DB peers
        if not peers:
            peers = db_peers

        # Fallback to hardcoded list if both are empty
        if not peers:
            if region == "US":
                peers = [
                    {"ticker": "MSFT", "name": "Microsoft"},
                    {"ticker": "AAPL", "name": "Apple"},
                    {"ticker": "NVDA", "name": "NVIDIA"},
                    {"ticker": "GOOGL", "name": "Alphabet"}
                ]
            else:
                peers = [
                    {"ticker": "2330.TW", "name": "台積電"},
                    {"ticker": "2454.TW", "name": "聯發科"},
                    {"ticker": "2303.TW", "name": "聯電"},
                    {"ticker": "3711.TW", "name": "日月光投控"}
                ]
            peers = [p for p in peers if p["ticker"].upper() != ticker.upper()]

        # 3. Fetch peer metrics from Cache or API
        peer_valuations = []
        for p in peers:
            p_ticker = p["ticker"]
            cache_key = f"financials_{p_ticker.upper()}"
            p_data = get_cached_data(CACHE_DIR, cache_key, ttl_hours=12)
            if not p_data:
                try:
                    p_data = yf_tool.get_stock_financials(p_ticker)
                except Exception:
                    p_data = None
                    
            if p_data:
                pe = p_data.get("pe_ratio")
                pb = p_data.get("price_to_book")
                if pe or pb:
                    peer_valuations.append({
                        "ticker": p_ticker,
                        "name": p["name"],
                        "pe": pe,
                        "pb": pb
                    })

        # 4. Fallback check: If LLM peers fetched less than 2 valid valuation metrics, fallback to local DB peers
        if len(peer_valuations) < 2 and peers != db_peers and db_peers:
            print(f"[*] 大模型推薦的同業有效估值數據不足 ({len(peer_valuations)} 檔)，將 Fallback 至本地資料庫同業...")
            peers = db_peers
            peer_valuations = []
            for p in peers:
                p_ticker = p["ticker"]
                cache_key = f"financials_{p_ticker.upper()}"
                p_data = get_cached_data(CACHE_DIR, cache_key, ttl_hours=12)
                if not p_data:
                    try:
                        p_data = yf_tool.get_stock_financials(p_ticker)
                    except Exception:
                        p_data = None
                        
                if p_data:
                    pe = p_data.get("pe_ratio")
                    pb = p_data.get("price_to_book")
                    if pe or pb:
                        peer_valuations.append({
                            "ticker": p_ticker,
                            "name": p["name"],
                            "pe": pe,
                            "pb": pb
                        })
                    


        if not peer_valuations:
            return {"status": "error", "message": "無法載入同業的估值乘數，同業比較模型中斷。"}

        # 3. Calculate Peer averages
        valid_pes = [p["pe"] for p in peer_valuations if p["pe"] is not None and p["pe"] > 0]
        valid_pbs = [p["pb"] for p in peer_valuations if p["pb"] is not None and p["pb"] > 0]
        
        avg_pe = sum(valid_pes) / len(valid_pes) if valid_pes else None
        avg_pb = sum(valid_pbs) / len(valid_pbs) if valid_pbs else None
        
        # 4. Determine Stock Type & Dynamic Weighting (成長股 vs 金融股 vs 一般股)
        pe_weight = 0.5
        pb_weight = 0.5
        
        is_financial = False
        comp_name = financials.get("company_name", "")
        # 檢查公司名稱中是否含有金融相關關鍵字
        if any(k in comp_name for k in ["金控", "銀行", "證券", "保險", "金融", "Financial"]):
            is_financial = True
            
        is_growth = False
        rev_growth = financials.get("revenue_growth")
        eps_growth = financials.get("eps_growth")
        # 如果營收增長率或EPS增長率大於 15% (0.15)
        if (rev_growth and rev_growth > 0.15) or (eps_growth and eps_growth > 0.15):
            is_growth = True
            
        if is_financial:
            pe_weight = 0.1
            pb_weight = 0.9
            stock_type = "金融股 (資產負債驅動)"
        elif is_growth:
            pe_weight = 0.9
            pb_weight = 0.1
            stock_type = "成長股 (盈餘成長驅動)"
        else:
            pe_weight = 0.5
            pb_weight = 0.5
            stock_type = "一般/價值股 (平衡配置)"
            
        # 5. Calculate target implied prices
        target_pe = financials.get("pe_ratio")
        target_pb = financials.get("price_to_book")
        curr_price = financials.get("current_price", 0.0)
        
        target_eps = curr_price / target_pe if (target_pe and target_pe > 0) else None
        target_bvps = curr_price / target_pb if (target_pb and target_pb > 0) else None
        
        implied_pe_price = target_eps * avg_pe if (target_eps and avg_pe) else None
        implied_pb_price = target_bvps * avg_pb if (target_bvps and avg_pb) else None
        
        # Calculate dynamic weighted intrinsic value
        if implied_pe_price is not None and implied_pb_price is not None:
            intrinsic_value = (implied_pe_price * pe_weight) + (implied_pb_price * pb_weight)
        elif implied_pe_price is not None:
            intrinsic_value = implied_pe_price
        elif implied_pb_price is not None:
            intrinsic_value = implied_pb_price
        else:
            intrinsic_value = curr_price
            
        return {
            "status": "success",
            "peer_valuations": peer_valuations,
            "avg_pe": avg_pe,
            "avg_pb": avg_pb,
            "implied_pe_price": implied_pe_price,
            "implied_pb_price": implied_pb_price,
            "intrinsic_value": intrinsic_value,
            "stock_type": stock_type,
            "pe_weight": pe_weight,
            "pb_weight": pb_weight
        }

    @classmethod
    def run_valuation(cls, ticker: str, financials: dict) -> str:
        """
        Runs both DCF and Comparables valuations, and formats a clean Markdown report.
        """
        is_tw = ticker.endswith(".TW") or ticker.endswith(".TWO")
        currency = "TWD" if is_tw else "USD"
        region = "Taiwan" if is_tw else "US"
        curr_price = financials.get("current_price", 0.0)

        # 1. Run DCF Model
        dcf_res = cls.calculate_wacc_and_dcf(ticker, financials, currency)
        
        # 2. Run Comps Model
        comps_res = cls.calculate_comps(ticker, financials, region)
        
        # 3. Check for Extreme Deviation & Auto-Calibration
        is_calibrated = False
        raw_beta = financials.get("beta", 1.0)
        if raw_beta is None or raw_beta <= 0:
            raw_beta = 1.0
        calibrated_beta = raw_beta
        deviation_pct = 0.0
        
        if dcf_res["status"] == "success" and comps_res["status"] == "success":
            dcf_val = dcf_res["intrinsic_value"]
            comps_val = comps_res["intrinsic_value"]
            min_val = min(dcf_val, comps_val)
            if min_val > 0:
                deviation_pct = (abs(dcf_val - comps_val) / min_val) * 100.0
                if deviation_pct > 50.0:
                    # Apply Blume's Beta Adjustment: beta_adj = 0.5 * raw_beta + 0.5 * 1.0
                    calibrated_beta = 0.5 * raw_beta + 0.5 * 1.0
                    is_calibrated = True
                    # Re-run DCF with calibrated Beta
                    dcf_res = cls.calculate_wacc_and_dcf(ticker, financials, currency, override_beta=calibrated_beta)
        
        # 4. Format Report
        report = []
        report.append(f"## 投資銀行級別量化估值模型報告 ({ticker})")
        
        # Helper to format large numbers
        def fmt_money(val):
            if val is None:
                return "N/A"
            if val >= 100_000_000:
                return f"{val/100_000_000:,.2f} 億 {currency}"
            return f"{val:,.2f} {currency}"

        # DCF Output
        report.append("### I. 5年期現金流量折現模型 (Discounted Cash Flow Model) - 僅供參考")
        if dcf_res["status"] == "success":
            report.append(f"*   **WACC（加權平均資金成本）**: `{dcf_res['wacc']*100:.2f}%` ")
            report.append(f"    *   *股權權重/成本*: `{dcf_res['w_equity']*100:.1f}%` / `{dcf_res['cost_of_equity']*100:.2f}%` (CAPM 模型)")
            report.append(f"    *   *債權權重/稅後成本*: `{dcf_res['w_debt']*100:.1f}%` / `{dcf_res['cost_of_debt']*(1-dcf_res['tax_rate'])*100:.2f}%` (稅率: `{dcf_res['tax_rate']*100:.1f}%`) ")
            report.append(f"*   **折現模型假設**: ")
            report.append(f"    *   *基準自由現金流 (FCF_0)*: `{fmt_money(dcf_res['fcf_0'])}` ")
            report.append(f"    *   *過渡期成長率 (1-5年)*: `{dcf_res['growth_rate']*100:.1f}%`，*永續成長率*: `{dcf_res['terminal_growth']*100:.2f}%` ")
            report.append(f"*   **企業價值 (Enterprise Value)**: `{fmt_money(dcf_res['enterprise_value'])}` ")
            report.append(f"    *   加上現金或等價物: `{fmt_money(dcf_res['cash'])}`，扣除總債務: `{fmt_money(dcf_res['debt'])}` ")
            report.append(f"*   **股權價值 (Equity Value)**: `{fmt_money(dcf_res['equity_value'])}` ")
            report.append(f"*   **DCF 估值之內在合理股價**: **`{dcf_res['intrinsic_value']:.2f} {currency}` (僅供參考)** ")
            report.append(f"    *   較目前價格偏離幅度: **`{((dcf_res['intrinsic_value'] - curr_price)/curr_price)*100:+.2f}%`**")
        else:
            report.append(f"*   **DCF模型狀態**: `不適用` ")
            report.append(f"    *   *原因說明*: {dcf_res['message']} ")
            
        # Comps Output
        report.append("\n### II. 同業乘數比較模型 (Comparables Analysis)")
        if comps_res["status"] == "success":
            t_pe = financials.get("pe_ratio")
            t_pe_str = f"{t_pe:.2f} 倍" if t_pe is not None else "N/A"
            t_pb = financials.get("price_to_book")
            t_pb_str = f"{t_pb:.2f} 倍" if t_pb is not None else "N/A"
            
            report.append(f"*   **同行業競爭對手平均估值倍數**: ")
            if comps_res['avg_pe']:
                report.append(f"    *   *同業平均 P/E (本益比)*: `{comps_res['avg_pe']:.2f} 倍` (目標 PE: `{t_pe_str}`) ")
            if comps_res['avg_pb']:
                report.append(f"    *   *同業平均 P/B (股價淨值比)*: `{comps_res['avg_pb']:.2f} 倍` (目標 PB: `{t_pb_str}`) ")
            report.append(f"*   **同業估值乘數詳情**: ")
            for p in comps_res["peer_valuations"]:
                pe_str = f"{p['pe']:.2f}x" if p["pe"] else "N/A"
                pb_str = f"{p['pb']:.2f}x" if p["pb"] else "N/A"
                report.append(f"    *   `{p['ticker']}` ({p['name']}): P/E = `{pe_str}`, P/B = `{pb_str}`")
            report.append(f"*   **同業比較法之內在合理股價**: **`{comps_res['intrinsic_value']:.2f} {currency}`** ")
            report.append(f"    *   *估值屬性與權重*: `{comps_res.get('stock_type', '一般股')}` (PE 權重: `{comps_res.get('pe_weight', 0.5)*100:.0f}%` / PB 權重: `{comps_res.get('pb_weight', 0.5)*100:.0f}%`) ")
            if comps_res['implied_pe_price']:
                report.append(f"    *   *本益比 (PE) 乘數推估價 (權重 {comps_res.get('pe_weight', 0.5)*100:.0f}%)*: `{comps_res['implied_pe_price']:.2f} {currency}` ")
            if comps_res['implied_pb_price']:
                report.append(f"    *   *淨值比 (PB) 乘數推估價 (權重 {comps_res.get('pb_weight', 0.5)*100:.0f}%)*: `{comps_res['implied_pb_price']:.2f} {currency}` ")
            report.append(f"    *   較目前價格偏離幅度: **`{((comps_res['intrinsic_value'] - curr_price)/curr_price)*100:+.2f}%`**")
        else:
            report.append(f"*   **同業比較模型狀態**: `不適用` ")
            report.append(f"    *   *原因說明*: {comps_res['message']} ")
            
        # Calibration Output
        if is_calibrated:
            report.append("\n### III. 估值模型極端偏離與自適應校準 (Valuation Calibration)")
            report.append(f"*   **偏離警告**: 絕對估值 (DCF) 與相對估值 (Comps) 偏離度達 `{deviation_pct:.2f}%`（已超過 50% 警戒閾值）。")
            report.append(f"*   **自適應調整**: 為防止個股 Beta 異常導致折現率失真，系統已將個股 Beta 值由 `{raw_beta:.2f}` 平滑校準為 `{calibrated_beta:.2f}`，並重新計算 DCF 估值，以合理化估值結果。")

        # Overall Summary
        report.append("\n### IV. 投行量化估值總結 (Valuation Summary)")
        # Under user instruction, the final integrated Fair Price is based ONLY on the Comparable multiples model (Comps).
        # The DCF model is listed for reference only.
        if comps_res["status"] == "success":
            final_fair_price = comps_res["intrinsic_value"]
            diff = ((final_fair_price - curr_price) / curr_price) * 100
            diff_str = f"{diff:+.2f}%"
            bias_str = "「被低估」" if diff > 5 else ("「被高估」" if diff < -5 else "「估值合理」")
            
            report.append(f"*   **投行綜合內在合理價 (Fair Price)**: **`{final_fair_price:.2f} {currency}`** ")
            report.append(f"*   **目前價格與合理價之偏離幅度**: **`{diff_str}`** (目前價格處於 **{bias_str}** 區間) ")
            report.append(f"    *(備註: 此合理價以同業比較乘數估值為準，絕對估值 DCF 模型僅列出供參考。)* ")
        elif dcf_res["status"] == "success":
            # If comps is not available, fallback to DCF but mark as reference-only
            final_fair_price = dcf_res["intrinsic_value"]
            diff = ((final_fair_price - curr_price) / curr_price) * 100
            diff_str = f"{diff:+.2f}%"
            bias_str = "「被低估」" if diff > 5 else ("「被高估」" if diff < -5 else "「估值合理」")
            
            report.append(f"*   **投行綜合內在合理價 (Fair Price)**: **`{final_fair_price:.2f} {currency}` (僅供參考)** ")
            report.append(f"*   **目前價格與合理價之偏離幅度**: **`{diff_str}`** (目前價格處於 **{bias_str}** 區間) ")
            report.append(f"    *(備註: 同業比較不可用，此處合理價使用 DCF 模型推估，僅供參考。)* ")
        else:
            report.append("*   **無法計算綜合合理價**: 所有量化模型皆不適用。")

        return "\n".join(report)
