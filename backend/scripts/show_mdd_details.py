import sys
import json
from pathlib import Path

# Add backend directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.config import (
    DEFAULT_TWD_MDD_LIMIT,
    DEFAULT_USD_MDD_LIMIT,
    DEFAULT_MDD_LIMIT,
    BULL_MDD_MULTIPLIER,
    BEAR_MDD_MULTIPLIER,
    RANGEBOUND_MDD_MULTIPLIER,
    BACKEND_ROOT
)
import core.db_manager as db
from core.regime.registry import get_market_regime
from core.regime.multi_factor import detect_meso_regime
from core.risk.risk_manager import calculate_portfolio_beta, get_dynamic_mdd_limit
import core.tools.yahoo_finance as yf_tool

def get_portfolio_holdings_details(currency: str = 'TWD'):
    region_filter = "US" if currency.upper() == "USD" else "Taiwan"
    try:
        active_recs = db.get_active_recommendations(region=region_filter)
        active_recs = [r for r in active_recs if r.get('shares', 0.0) > 0.0]
    except Exception:
        return [], 0.0
        
    holdings = []
    total_val = 0.0
    
    for r in active_recs:
        shares = r.get("shares", 0.0)
        ticker = r.get("ticker")
        name = r.get("company_name", ticker)
        curr_price = yf_tool.get_stock_price(ticker)
        if curr_price <= 0.0:
            curr_price = r.get("recommend_price", 0.0)
            
        pos_val = shares * curr_price
        if pos_val > 0.0:
            total_val += pos_val
            stock_beta = 1.0
            cache_file = BACKEND_ROOT / "core" / "data" / "cache" / f"financials_{ticker}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache_data = json.load(f)
                        stock_beta = cache_data.get("beta", 1.0) or 1.0
                except Exception:
                    pass
            holdings.append({
                "ticker": ticker,
                "name": name,
                "shares": shares,
                "price": curr_price,
                "value": pos_val,
                "beta": stock_beta
            })
            
    # Calculate weights
    for h in holdings:
        h["weight"] = h["value"] / total_val if total_val > 0.0 else 0.0
        
    return holdings, total_val

def main():
    print("==================================================")
    print("🔍 Aegis-MAQS 動態最大回撤 (MDD) 警戒線計算詳情與因子排查")
    print("==================================================")
    
    # 1. Fetch Global parameters
    try:
        meso = detect_meso_regime()
        vix_scale = meso.get('vix_scale', 1.0)
    except Exception:
        vix_scale = 1.0
        
    print(f"⚙️ 系統全域基準與乘數配置：")
    print(f"  • 台股基礎警戒額度 (DEFAULT_TWD_MDD_LIMIT): {DEFAULT_TWD_MDD_LIMIT*100:.2f}%")
    print(f"  • 美股基礎警戒額度 (DEFAULT_USD_MDD_LIMIT): {DEFAULT_USD_MDD_LIMIT*100:.2f}%")
    print(f"  • 牛市警戒乘數 (BULL_MDD_MULTIPLIER): {BULL_MDD_MULTIPLIER}")
    print(f"  • 熊市警戒乘數 (BEAR_MDD_MULTIPLIER): {BEAR_MDD_MULTIPLIER}")
    print(f"  • 震盪警戒乘數 (RANGEBOUND_MDD_MULTIPLIER): {RANGEBOUND_MDD_MULTIPLIER}")
    print(f"  • 當前 VIX 波動調整係數 (vix_scale): {vix_scale:.4f}")
    
    # 2. TWD Pocket Details
    twd_r = get_market_regime('Taiwan').get('regime', 'VOLATILE_RANGEBOUND')
    twd_beta = calculate_portfolio_beta('TWD')
    twd_holdings, twd_total_value = get_portfolio_holdings_details('TWD')
    
    twd_regime_multiplier = BULL_MDD_MULTIPLIER if "BULL" in twd_r or "RISK_ON" in twd_r else (
        BEAR_MDD_MULTIPLIER if "BEAR" in twd_r or "RISK_OFF" in twd_r else RANGEBOUND_MDD_MULTIPLIER
    )
    
    print("\n🇹🇼 1. 台股資產賬戶 (TWD Pocket) 計算過程")
    print("-" * 50)
    print(f"  • 1. 基礎回撤限額: {DEFAULT_TWD_MDD_LIMIT*100:.2f}%")
    print(f"  • 2. 持股加權 Beta: {twd_beta:.4f} -> Beta 調整因子: {max(0.5, min(twd_beta, 2.0)):.4f}")
    print(f"  • 3. Beta 敏感度調整: {DEFAULT_TWD_MDD_LIMIT * max(0.5, min(twd_beta, 2.0)) * 100:.4f}%")
    print(f"  • 4. 市場狀態與乘數: {twd_r} ➡️ 乘數 {twd_regime_multiplier}")
    print(f"  • 5. 乘數調整後限額: {DEFAULT_TWD_MDD_LIMIT * max(0.5, min(twd_beta, 2.0)) * twd_regime_multiplier * 100:.4f}%")
    print(f"  • 6. VIX 波動調整 (乘以 vix_scale): {DEFAULT_TWD_MDD_LIMIT * max(0.5, min(twd_beta, 2.0)) * twd_regime_multiplier * vix_scale * 100:.4f}%")
    twd_final = get_dynamic_mdd_limit(twd_r, 'TWD')
    print(f"  • 7. 邊界保護限制 [0.5% - 20%]: {twd_final*100:.2f}%")
    
    print(f"\n  📊 台股持倉明細 (總市值: {twd_total_value:,.2f} TWD)：")
    if not twd_holdings:
        print("    (目前無 active 持倉，加權 Beta 預設為 1.00)")
    else:
        for h in twd_holdings:
            print(f"    - {h['ticker']} ({h['name']}) | 市值: {h['value']:,.2f} TWD | 權重: {h['weight']*100:.1f}% | Beta: {h['beta']:.2f}")

    # 3. USD Pocket Details
    usd_r = get_market_regime('US').get('regime', 'VOLATILE_RANGEBOUND')
    usd_beta = calculate_portfolio_beta('USD')
    usd_holdings, usd_total_value = get_portfolio_holdings_details('USD')
    
    usd_regime_multiplier = BULL_MDD_MULTIPLIER if "BULL" in usd_r or "RISK_ON" in usd_r else (
        BEAR_MDD_MULTIPLIER if "BEAR" in usd_r or "RISK_OFF" in usd_r else RANGEBOUND_MDD_MULTIPLIER
    )
    
    print("\n🇺🇸 2. 美股資產賬戶 (USD Pocket) 計算過程")
    print("-" * 50)
    print(f"  • 1. 基礎回撤限額: {DEFAULT_USD_MDD_LIMIT*100:.2f}%")
    print(f"  • 2. 持股加權 Beta: {usd_beta:.4f} -> Beta 調整因子: {max(0.5, min(usd_beta, 2.0)):.4f}")
    print(f"  • 3. Beta 敏感度調整: {DEFAULT_USD_MDD_LIMIT * max(0.5, min(usd_beta, 2.0)) * 100:.4f}%")
    print(f"  • 4. 市場狀態與乘數: {usd_r} ➡️ 乘數 {usd_regime_multiplier}")
    print(f"  • 5. 乘數調整後限額: {DEFAULT_USD_MDD_LIMIT * max(0.5, min(usd_beta, 2.0)) * usd_regime_multiplier * 100:.4f}%")
    print(f"  • 6. VIX 波動調整 (乘以 vix_scale): {DEFAULT_USD_MDD_LIMIT * max(0.5, min(usd_beta, 2.0)) * usd_regime_multiplier * vix_scale * 100:.4f}%")
    usd_final = get_dynamic_mdd_limit(usd_r, 'USD')
    print(f"  • 7. 邊界保護限制 [0.5% - 20%]: {usd_final*100:.2f}%")
    
    print(f"\n  📊 美股持倉明細 (總市值: {usd_total_value:,.2f} USD)：")
    if not usd_holdings:
        print("    (目前無 active 持倉，加權 Beta 預設為 1.00)")
    else:
        for h in usd_holdings:
            print(f"    - {h['ticker']} ({h['name']}) | 市值: {h['value']:,.2f} USD | 權重: {h['weight']*100:.1f}% | Beta: {h['beta']:.2f}")

    print("==================================================")

if __name__ == "__main__":
    main()
