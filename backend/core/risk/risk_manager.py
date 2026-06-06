import math

def calculate_risk_boundaries(curr_price: float, atr_14: float, beta: float, market_regime: str = None) -> dict:
    """
    Calculates dynamic stop-loss, take-profit, and buy range boundaries
    based on Beta-adjusted ATR, adapting parameters based on the market regime.
    """
    beta_bounded = max(0.3, min(beta or 1.0, 3.0))
    beta_adj = math.sqrt(beta_bounded)
    
    regime = (market_regime or "MOMENTUM_TREND").upper()
    
    # Adapt multipliers based on regime
    if "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
        # Mean Reversion / Rangebound: tighter profit targets & tight stop-loss
        k1 = 1.2 * beta_adj
        k2 = 1.5 * beta_adj
        buy_lower_multiplier = 0.8 * beta_adj
        buy_upper_multiplier = 0.2 * beta_adj
    else:
        # Momentum / Trend: standard alpha seeking
        k1 = 2.0 * beta_adj
        k2 = 3.0 * beta_adj
        buy_lower_multiplier = 1.0 * beta_adj
        buy_upper_multiplier = 0.25 * beta_adj
        
    if atr_14 and curr_price:
        suggested_sl = curr_price - (k1 * atr_14)
        suggested_tp = curr_price + (k2 * atr_14)
        suggested_buy_lower = curr_price - (buy_lower_multiplier * atr_14)
        suggested_buy_upper = curr_price + (buy_upper_multiplier * atr_14)
    else:
        # Fallbacks if metrics are missing
        if "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
            suggested_sl = curr_price * 0.95  # 5% stop-loss
            suggested_tp = curr_price * 1.08  # 8% target price
            suggested_buy_lower = curr_price * 0.98
            suggested_buy_upper = curr_price * 1.01
        else:
            suggested_sl = curr_price * 0.92  # 8% stop-loss
            suggested_tp = curr_price * 1.15  # 15% target price
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


def get_dynamic_mdd_limit(market_regime: str = None, currency: str = 'TWD') -> float:
    """
    Returns the dynamic maximum drawdown (MDD) warning limit based on the market regime and region.
    Applies multipliers from core.config to DEFAULT_TWD_MDD_LIMIT or DEFAULT_USD_MDD_LIMIT
    to adjust limits up/down dynamically.
    """
    from core.config import (
        DEFAULT_TWD_MDD_LIMIT,
        DEFAULT_USD_MDD_LIMIT,
        DEFAULT_MDD_LIMIT,
        BULL_MDD_MULTIPLIER,
        BEAR_MDD_MULTIPLIER,
        RANGEBOUND_MDD_MULTIPLIER
    )
    
    curr = (currency or 'TWD').upper()
    if curr == 'USD':
        base_limit = DEFAULT_USD_MDD_LIMIT
    elif curr == 'TWD':
        base_limit = DEFAULT_TWD_MDD_LIMIT
    else:
        base_limit = DEFAULT_MDD_LIMIT
        
    if not market_regime:
        return base_limit
        
    regime = market_regime.upper()
    limit = base_limit
    
    if "BULL" in regime or "RISK_ON" in regime:
        limit = base_limit * BULL_MDD_MULTIPLIER
    elif "BEAR" in regime or "RISK_OFF" in regime:
        limit = base_limit * BEAR_MDD_MULTIPLIER
    elif "REVERSION" in regime or "RANGEBOUND" in regime or "VOLATILE" in regime:
        limit = base_limit * RANGEBOUND_MDD_MULTIPLIER
        
    # Apply a sanity lower bound of 0.5% (0.005) and upper bound of 20% (0.20)
    return max(0.005, min(limit, 0.20))



