# portfolio/exposure_tracker.py
"""
Tracks current open exposure per category and per market.
Thin read-layer over RiskManager._category_exposure and ._open_positions.
Provides clean query interface without modifying risk.py.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


class ExposureTracker:
    """
    Query-only view of exposure state held in RiskManager.
    Does not mutate RiskManager state — RiskManager.on_trade_opened() still does that.
    """

    def get_category_exposure(self, category: str) -> float:
        """Return current USD exposure in the given category."""
        from risk import RiskManager
        rm = RiskManager.instance()
        return rm._category_exposure.get(category, 0.0)

    def get_total_exposure(self) -> float:
        """Return total USD across all open positions."""
        from risk import RiskManager
        rm = RiskManager.instance()
        return sum(rm._open_positions.values())

    def get_open_position_count(self) -> int:
        """Return count of currently open positions."""
        from risk import RiskManager
        rm = RiskManager.instance()
        return len(rm._open_positions)

    def get_category_utilization(self, category: str, cap_usd: float) -> float:
        """Return category exposure as a fraction of the cap [0.0, 1.0+]."""
        exp = self.get_category_exposure(category)
        return exp / cap_usd if cap_usd > 0 else 0.0
