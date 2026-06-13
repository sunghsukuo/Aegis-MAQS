from core.screener.factory import ScreenerFactory

class QuantScreener:
    """
    Facade class that wraps the new strategy-based screener system
    to maintain backwards compatibility with existing imports and workflows.
    """
    def __init__(self):
        # Clear the shared session history on initialization to start fresh
        ScreenerFactory.get_screener().clear_history()

    def clear_history(self):
        ScreenerFactory.get_screener().clear_history()

    @property
    def session_history(self):
        return ScreenerFactory.get_screener().session_history

    def fetch_etf_constituents(self, etf_ticker: str) -> list:
        return ScreenerFactory.get_screener().fetch_etf_constituents(etf_ticker)

    def screen_stocks(self, etf_ticker: str, region: str, limit: int = 5, price_regime: str = None, macro_regime: str = None) -> list:
        # Use price_regime (quantitative ADX/Hurst) to route the correct screener strategy
        screener = ScreenerFactory.get_screener(price_regime)
        # Pass macro_regime (qualitative LLM) into the strategy for risk weight adjustments
        return screener.screen_stocks(etf_ticker, region=region, limit=limit, macro_regime=macro_regime)

    def record_proxy_etf(self, etf_ticker: str, region: str, financials: dict = None, weekly_return: float = 0.0):
        # We can record using any screener strategy since session_history is shared
        ScreenerFactory.get_screener().record_proxy_etf(
            etf_ticker, region=region, financials=financials, weekly_return=weekly_return
        )

    def generate_report(self, report_date: str) -> tuple:
        return ScreenerFactory.get_screener().generate_report(report_date)
