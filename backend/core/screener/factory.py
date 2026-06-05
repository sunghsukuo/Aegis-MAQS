from core.screener.momentum_strategy import MomentumScreener
from core.screener.reversion_strategy import ReversionScreener

class ScreenerFactory:
    _instances = {}

    @classmethod
    def get_screener(cls, market_regime: str = None):
        """
        Factory method to return the appropriate screener strategy based on market regime.
        """
        # Clean regime string
        regime = (market_regime or "MOMENTUM_TREND").upper()
        
        if "REVERSION" in regime or "RANGEBOUND" in regime or regime == "MEAN_REVERSION_RANGE":
            strategy_name = "reversion"
            screener_cls = ReversionScreener
        else:
            strategy_name = "momentum"
            screener_cls = MomentumScreener
            
        if strategy_name not in cls._instances:
            cls._instances[strategy_name] = screener_cls()
            
        return cls._instances[strategy_name]
