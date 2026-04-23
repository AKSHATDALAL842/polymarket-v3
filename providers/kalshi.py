"""Kalshi thin adapter."""
from __future__ import annotations

from providers.base import MarketProvider


class KalshiProvider(MarketProvider):
    name = "kalshi"

    def fetch_markets(self, limit: int = 200) -> list:
        from ingestion.kalshi_markets import fetch_kalshi_markets
        return fetch_kalshi_markets(limit=limit)
