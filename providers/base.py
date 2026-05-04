"""Abstract base class for market providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ingestion.markets import Market
    from signal.edge_model import Signal
    from execution.executor import ExecutionResult


class MarketProvider(ABC):
    name: str  # "polymarket" | "kalshi"

    @abstractmethod
    def fetch_markets(self, limit: int = 200) -> list:
        """Fetch active markets from this platform."""
        ...

    def get_price(self, market_id: str, watcher=None) -> float | None:
        """Look up live YES price from a shared MarketWatcher instance.

        watcher must be injected by the caller — a fresh MarketWatcher() has
        no snapshots and will always return None.
        """
        try:
            if watcher is None:
                return None
            snap = watcher.get_snapshot(market_id)
            return snap.yes_price if snap else None
        except Exception:
            return None

    def simulate_trade(self, signal) -> "ExecutionResult":
        """Delegate to portfolio.simulate_trade()."""
        from portfolio import get_portfolio
        return get_portfolio().simulate_trade(signal)

    def execute_trade(self, signal) -> "ExecutionResult":
        """Delegate to existing executor routing."""
        from execution.executor import execute_trade
        return execute_trade(signal)
