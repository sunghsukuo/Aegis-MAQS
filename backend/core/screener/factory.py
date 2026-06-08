from core.screener.momentum_strategy import MomentumScreener
from core.screener.reversion_strategy import ReversionScreener

class ScreenerFactory:
    _instances = {}

    @classmethod
    def get_screener(cls, price_regime: str = None):
        """
        Factory method to return the appropriate screener strategy based on price regime.
        Price regime is determined quantitatively (ADX/Hurst) and decides
        which screening strategy (Momentum vs Reversion) to use.
        """
        # Clean regime string
        regime = (price_regime or "MOMENTUM_TREND").upper()
        
        if "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
            strategy_name = "reversion"
            screener_cls = ReversionScreener
        else:
            strategy_name = "momentum"
            screener_cls = MomentumScreener
            
        if strategy_name not in cls._instances:
            cls._instances[strategy_name] = screener_cls()
            
        return cls._instances[strategy_name]
