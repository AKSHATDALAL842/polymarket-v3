from __future__ import annotations
import logging

log = logging.getLogger(__name__)


class ExposureTracker:
    """Query-only view of exposure state held in RiskManager. Does not mutate state."""

    def get_category_exposure(self, category: str) -> float:
        from portfolio.risk import RiskManager
        return RiskManager.instance()._category_exposure.get(category, 0.0)

    def get_total_exposure(self) -> float:
        from portfolio.risk import RiskManager
        return sum(RiskManager.instance()._open_positions.values())

    def get_open_position_count(self) -> int:
        from portfolio.risk import RiskManager
        return len(RiskManager.instance()._open_positions)

    def get_category_utilization(self, category: str, cap_usd: float) -> float:
        exp = self.get_category_exposure(category)
        return exp / cap_usd if cap_usd > 0 else 0.0
