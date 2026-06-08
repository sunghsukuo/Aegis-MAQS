import yfinance as yf
import pandas as pd
import numpy as np
from core.screener.base import BaseScreener

class ReversionScreener(BaseScreener):
    def screen_stocks(self, etf_ticker: str, region: str, limit: int = 5, macro_regime: str = None) -> list:
        """
        Implements Pullback / Mean Reversion Screening.
        Focuses on high-quality stocks that are short-term oversold (low RSI) but in a long-term uptrend (above 200MA),
        currently consolidating near support (50MA).
        """
        tickers = self.fetch_etf_constituents(etf_ticker)
        if not tickers:
            return []
            
        print(f"[*] [ReversionScreener] 開始對 {etf_ticker} 的成分股進行均值回歸拉回因子篩選...")
        screened_results = []
        
        min_mcap = 2 * 10**9 if region == "US" else 8 * 10**9
        min_vol = 200000 if region == "US" else 300000
        
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                # Pull 1 year history to get 200-day moving average and 14-day RSI
                hist = t.history(period="1y").dropna(subset=["Close"])
                if hist.empty or len(hist) < 200:
                    continue
                
                fast = t.fast_info
                market_cap = fast.get("marketCap", 0.0)
                if not market_cap:
                    market_cap = hist["Close"].iloc[-1] * fast.get("shares", 0.0)
                    
                # 1. Liquidity filter
                avg_volume = hist["Volume"].iloc[-20:].mean()
                if market_cap < min_mcap or avg_volume < min_vol:
                    continue
                    
                close_now = hist["Close"].iloc[-1]
                
                # 2. No Catching Falling Knives (Long-term uptrend check: Price must be above 200MA)
                ma200 = hist["Close"].iloc[-200:].mean()
                if close_now < ma200:
                    # Stock is in a long-term downtrend, skip
                    continue
                    
                # 3. Pullback check (Short-term support check: 50MA)
                ma50 = hist["Close"].iloc[-50:].mean()
                # We want the stock to be close to the 50MA support line (e.g. within -2% to +5% range)
                dist_to_ma50 = (close_now - ma50) / ma50
                if dist_to_ma50 < -0.05 or dist_to_ma50 > 0.08:
                    continue
                    
                # 4. Calculate RSI-14
                close_series = hist["Close"]
                delta = close_series.diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.rolling(window=14).mean()
                avg_loss = loss.rolling(window=14).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                rsi_14 = float(rsi.iloc[-1])
                
                # We want oversold/neutral-low conditions (RSI should ideally be < 50 for pullbacks)
                if rsi_14 > 55:
                    continue
                
                # 5. Pullback Depth (5-day return)
                close_5d_ago = hist["Close"].iloc[-6] if len(hist) >= 6 else hist["Close"].iloc[0]
                weekly_return = (close_now - close_5d_ago) / close_5d_ago
                
                # 6. Volume Spike Factor (consolidating or slight surge)
                volume_now = self._get_projected_volume(hist, region)
                volume_spike = volume_now / avg_volume if avg_volume > 0 else 1.0
                
                # Get the company name
                name = ticker
                try:
                    name = t.info.get("longName", ticker)
                except Exception:
                    pass
                
                if region == "Taiwan" or ticker.endswith(".TW") or ticker.endswith(".TWO"):
                    ticker_num = ticker.split(".")[0]
                    from core.tools.taiwan_stock_names import get_taiwan_stock_name
                    db_name = get_taiwan_stock_name(ticker_num)
                    if db_name:
                        name = f"{db_name} ({name})"
                
                # 7. Pullback & Mean Reversion Scoring
                # - Pullback depth score (lower weekly return is better)
                pullback_score = max(0, -weekly_return * 100)
                
                # - RSI score (lower RSI is better, e.g. RSI 30 gets higher score than RSI 50)
                rsi_score = max(0, (100 - rsi_14)) / 100.0 * 10.0
                
                # - Support proximity bonus (close to 50MA)
                if 0.0 <= dist_to_ma50 <= 0.04:
                    support_bonus = 5.0
                elif -0.03 <= dist_to_ma50 < 0.0:
                    support_bonus = 3.0
                else:
                    support_bonus = 0.0
                    
                # - Volume score (we like slight volume support or consolidation)
                volume_score = min(volume_spike, 2.0) / 2.0 * 3.0
                
                combined_score = pullback_score + rsi_score + support_bonus + volume_score
                
                screened_results.append({
                    "ticker": ticker,
                    "name": name,
                    "weekly_return": float(weekly_return),
                    "volume_spike": float(volume_spike),
                    "current_price": float(close_now),
                    "market_cap": float(market_cap),
                    "score": float(combined_score)
                })
            except Exception:
                continue
                
        screened_results.sort(key=lambda x: x["score"], reverse=True)
        final_picks = screened_results[:limit]
        
        print(f"[✓] [ReversionScreener] {etf_ticker} 均值回歸選股完成！挑選出前 {len(final_picks)} 拉回優質股：")
        for i, pick in enumerate(final_picks, 1):
            print(f"    {i}. {pick['name']} ({pick['ticker']}) - 5日幅: {pick['weekly_return']*100:.2f}%, 量能增幅: {pick['volume_spike']:.2f}x, 評分: {pick['score']:.2f}")
            
        # ETF own return calculation
        etf_weekly_return = 0.0
        try:
            etf_hist = yf.Ticker(etf_ticker).history(period="1mo").dropna(subset=["Close"])
            if not etf_hist.empty and len(etf_hist) >= 6:
                etf_close_now = etf_hist["Close"].iloc[-1]
                etf_close_5d_ago = etf_hist["Close"].iloc[-6]
                etf_weekly_return = float((etf_close_now - etf_close_5d_ago) / etf_close_5d_ago)
        except Exception as e:
            print(f"[!] 計算 ETF {etf_ticker} 自身週報酬率失敗: {e}")

        self.session_history.append({
            "etf": etf_ticker,
            "region": region,
            "picks": final_picks,
            "weekly_return": etf_weekly_return
        })
        return final_picks
