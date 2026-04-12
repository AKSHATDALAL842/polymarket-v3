"""Polymarket thin adapter."""
from __future__ import annotations

from providers.base import MarketProvider


class PolymarketProvider(MarketProvider):
    name = "polymarket"

    def fetch_markets(self, limit: int = 200) -> list:
        from markets import fetch_active_markets
        return fetch_active_markets(limit=limit)
