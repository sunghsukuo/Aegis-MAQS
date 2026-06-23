import math

def calculate_risk_boundaries(curr_price: float, atr_14: float, beta: float, macro_regime: str = None) -> dict:
    """
    Calculates dynamic stop-loss, take-profit, and buy range boundaries
    based on Beta-adjusted ATR, adapting parameters based on the market regime.
    """
    beta_bounded = max(0.3, min(beta or 1.0, 3.0))
    beta_adj = math.sqrt(beta_bounded)
    
    regime = (macro_regime or "VOLATILE_RANGEBOUND").upper()
    
    # Adapt multipliers based on regime
    if "BEAR" in regime or "RISK_OFF" in regime:
        # Bear Market / Risk Off: tightest defensive parameters (盈虧比 1.50x)
        k1 = 1.5 * beta_adj
        k2 = 2.25 * beta_adj
        buy_lower_multiplier = 0.5 * beta_adj
        buy_upper_multiplier = 0.1 * beta_adj
    elif "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
        # Mean Reversion / Rangebound: standard range trading (盈虧比 1.50x)
        k1 = 2.0 * beta_adj
        k2 = 3.0 * beta_adj
        buy_lower_multiplier = 0.8 * beta_adj
        buy_upper_multiplier = 0.2 * beta_adj
    else:
        # Momentum / Trend: standard alpha seeking (盈虧比 2.00x)
        k1 = 2.5 * beta_adj
        k2 = 5.0 * beta_adj
        buy_lower_multiplier = 1.0 * beta_adj
        buy_upper_multiplier = 0.25 * beta_adj
        
    if atr_14 and curr_price:
        suggested_sl = curr_price - (k1 * atr_14)
        suggested_tp = curr_price + (k2 * atr_14)
        
        # Enforce a minimum stop-loss floor percentage to prevent whip-saws on minor market noise
        min_sl_pct = 0.05 if ("BEAR" in regime or "RISK_OFF" in regime or "REVERSION" in regime or "RANGEBOUND" in regime) else 0.07
        min_sl_dist = curr_price * min_sl_pct
        if (curr_price - suggested_sl) < min_sl_dist:
            suggested_sl = curr_price - min_sl_dist
            
        suggested_buy_lower = curr_price - (buy_lower_multiplier * atr_14)
        suggested_buy_upper = curr_price + (buy_upper_multiplier * atr_14)
    else:
        # Fallbacks if metrics are missing
        if "BEAR" in regime or "RISK_OFF" in regime:
            suggested_sl = curr_price * 0.95  # 5% stop-loss
            suggested_tp = curr_price * 1.08  # 8% target price
            suggested_buy_lower = curr_price * 0.99
            suggested_buy_upper = curr_price * 1.005
        elif "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
            suggested_sl = curr_price * 0.93  # 7% stop-loss
            suggested_tp = curr_price * 1.12  # 12% target price
            suggested_buy_lower = curr_price * 0.98
            suggested_buy_upper = curr_price * 1.01
        else:
            suggested_sl = curr_price * 0.90  # 10% stop-loss
            suggested_tp = curr_price * 1.20  # 20% target price
            suggested_buy_lower = curr_price * 0.97
            suggested_buy_upper = curr_price * 1.02
            
    return {
        "k1": k1,
        "k2": k2,
        "suggested_sl": suggested_sl,
        "suggested_tp": suggested_tp,
        "suggested_buy_lower": suggested_buy_lower,
        "suggested_buy_upper": suggested_buy_upper,
        "beta_adj": beta_adj
    }


def calculate_portfolio_beta(currency: str = 'TWD') -> float:
    """
    Calculates the weighted Beta of the active portfolio for a given currency/region.
    Falls back to 1.0 if there are no holdings or errors occur.
    """
    try:
        import json
        from pathlib import Path
        import core.db_manager as db
        from core.config import BACKEND_ROOT
        
        region_filter = "US" if currency.upper() == "USD" else "Taiwan"
        active_recs = db.get_active_recommendations(region=region_filter)
        active_recs = [r for r in active_recs if r.get('shares', 0.0) > 0.0]
        
        if not active_recs:
            return 1.0
            
        import core.tools.yahoo_finance as yf_tool

        
        total_val = 0.0
        weighted_beta_sum = 0.0
        
        for r in active_recs:
            shares = r.get("shares", 0.0)
            ticker = r.get("ticker")
            curr_price = yf_tool.get_stock_price(ticker)
            if curr_price <= 0.0:
                curr_price = r.get("recommend_price", 0.0)
                
            pos_val = shares * curr_price
            if pos_val > 0.0:
                total_val += pos_val
                
                # Load stock beta from cache
                stock_beta = 1.0
                cache_file = BACKEND_ROOT / "core" / "data" / "cache" / f"financials_{ticker}.json"
                if cache_file.exists():
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            cache_data = json.load(f)
                            stock_beta = cache_data.get("beta", 1.0) or 1.0
                    except Exception:
                        pass
                weighted_beta_sum += pos_val * stock_beta
                
        if total_val > 0.0:
            return weighted_beta_sum / total_val
    except Exception:
        pass
    return 1.0


def get_dynamic_mdd_limit(macro_regime: str = None, currency: str = 'TWD') -> float:
    """
    Returns the dynamic maximum drawdown (MDD) warning limit based on the macro regime and region.
    Applies multipliers from core.config to DEFAULT_TWD_MDD_LIMIT or DEFAULT_USD_MDD_LIMIT,
    scales it dynamically based on the weighted Portfolio Beta, and adjusts it by the VIX scale.
    """
    from core.config import (
        DEFAULT_TWD_MDD_LIMIT,
        DEFAULT_USD_MDD_LIMIT,
        DEFAULT_MDD_LIMIT,
        BULL_MDD_MULTIPLIER,
        BEAR_MDD_MULTIPLIER,
        RANGEBOUND_MDD_MULTIPLIER
    )
    from core.regime.multi_factor import detect_meso_regime
    
    curr = (currency or 'TWD').upper()
    if curr == 'USD':
        base_limit = DEFAULT_USD_MDD_LIMIT
    elif curr == 'TWD':
        base_limit = DEFAULT_TWD_MDD_LIMIT
    else:
        base_limit = DEFAULT_MDD_LIMIT
        
    # Calculate portfolio beta dynamically
    portfolio_beta = calculate_portfolio_beta(curr)
    
    # Scale base limit by portfolio beta (bounded between 0.5 and 2.0 to avoid extreme values)
    beta_adj = max(0.5, min(portfolio_beta, 2.0))
    adjusted_base = base_limit * beta_adj
    
    # Fetch VIX scale from multi-factor detector
    try:
        region_code = "US" if curr == "USD" else "Taiwan"
        meso_info = detect_meso_regime(region_code=region_code)
        vix_scale = meso_info.get("vix_scale", 1.0)
    except Exception:
        vix_scale = 1.0
        
    if not macro_regime:
        limit = adjusted_base * vix_scale
        return max(0.005, min(limit, 0.20))
        
    regime = macro_regime.upper()
    limit = adjusted_base
    
    if "BULL" in regime or "RISK_ON" in regime:
        limit = adjusted_base * BULL_MDD_MULTIPLIER
    elif "BEAR" in regime or "RISK_OFF" in regime:
        limit = adjusted_base * BEAR_MDD_MULTIPLIER
    elif "REVERSION" in regime or "RANGEBOUND" in regime or "VOLATILE" in regime:
        limit = adjusted_base * RANGEBOUND_MDD_MULTIPLIER
        
    # Scale the final limit by VIX scale
    limit = limit * vix_scale
    
    # Apply a sanity lower bound of 0.5% (0.005) and upper bound of 20% (0.20)
    return max(0.005, min(limit, 0.20))




