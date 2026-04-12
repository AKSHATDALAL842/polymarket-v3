"""Market provider package."""
from providers.base import MarketProvider
from providers.polymarket import PolymarketProvider
from providers.kalshi import KalshiProvider


def get_providers() -> list[MarketProvider]:
    """Return list of enabled providers."""
    import config
    providers: list[MarketProvider] = [PolymarketProvider()]
    if config.KALSHI_ENABLED:
        providers.append(KalshiProvider())
    return providers


__all__ = ["MarketProvider", "PolymarketProvider", "KalshiProvider", "get_providers"]
