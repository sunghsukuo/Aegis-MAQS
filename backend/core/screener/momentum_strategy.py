import yfinance as yf
import pandas as pd
from core.screener.base import BaseScreener

class MomentumScreener(BaseScreener):
    def screen_stocks(self, etf_ticker: str, region: str, limit: int = 5, market_regime: str = None) -> list:
        """
        Implements Trend-Following / Momentum Screening.
        Calculates 5-day return momentum, volume surge, and applies dynamic regime weights/penalties.
        """
        tickers = self.fetch_etf_constituents(etf_ticker)
        if not tickers:
            return []
            
        print(f"[*] [MomentumScreener] 開始對 {etf_ticker} 的成分股進行動能因子計算與篩選...")
        screened_results = []
        
        min_mcap = 2 * 10**9 if region == "US" else 8 * 10**9
        min_vol = 200000 if region == "US" else 300000
        
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="1mo")
                if hist.empty or len(hist) < 20:
                    continue
                
                fast = t.fast_info
                market_cap = fast.get("marketCap", 0.0)
                if not market_cap:
                    market_cap = hist["Close"].iloc[-1] * fast.get("shares", 0.0)
                    
                # 1. Liquidity filter
                avg_volume = hist["Volume"].iloc[-20:].mean()
                if market_cap < min_mcap or avg_volume < min_vol:
                    continue
                    
                # 2. Trend filter (Price above 20-day MA)
                close_now = hist["Close"].iloc[-1]
                ma20 = hist["Close"].iloc[-20:].mean()
                if close_now < ma20:
                    continue
                    
                # 3. Momentum Factor (5-day return)
                close_5d_ago = hist["Close"].iloc[-6] if len(hist) >= 6 else hist["Close"].iloc[0]
                weekly_return = (close_now - close_5d_ago) / close_5d_ago
                
                # 4. Volume Spike Factor
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
                
                # 5. Combined Score
                return_score = weekly_return * 100
                volume_score = min(volume_spike, 3.0) / 3.0 * 10.0
                
                if market_regime == "BEAR_RISK_OFF":
                    daily_returns = hist["Close"].pct_change()
                    daily_vol = float(daily_returns.iloc[-20:].std() * 100)
                    if pd.isna(daily_vol): 
                        daily_vol = 0.0
                    vol_penalty = min(daily_vol * 1.5, 5.0)
                    combined_score = (return_score * 0.3) + (volume_score * 0.7) - vol_penalty
                elif market_regime == "VOLATILE_RANGEBOUND":
                    daily_returns = hist["Close"].pct_change()
                    daily_vol = float(daily_returns.iloc[-20:].std() * 100)
                    if pd.isna(daily_vol): 
                        daily_vol = 0.0
                    vol_penalty = min(daily_vol * 0.75, 2.5)
                    combined_score = (return_score * 0.5) + (volume_score * 0.5) - vol_penalty
                else:
                    combined_score = (return_score * 0.7) + (volume_score * 0.3)
                
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
        
        print(f"[✓] [MomentumScreener] {etf_ticker} 動態選股完成！挑選出前 {len(final_picks)} 強勢個股：")
        for i, pick in enumerate(final_picks, 1):
            print(f"    {i}. {pick['name']} ({pick['ticker']}) - 5日漲幅: {pick['weekly_return']*100:.2f}%, 量能增幅: {pick['volume_spike']:.2f}x, 評分: {pick['score']:.2f}")
            
        # ETF own return calculation
        etf_weekly_return = 0.0
        try:
            etf_hist = yf.Ticker(etf_ticker).history(period="1mo")
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
