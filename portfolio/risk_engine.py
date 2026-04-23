from __future__ import annotations
import logging
from dataclasses import dataclass
import config

log = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    approved: bool
    reason: str  # "ok" if approved, rejection reason string otherwise


class RiskEngine:
    """Read-only interface over RiskManager. All state lives in portfolio.risk."""

    def validate(self, signal, size_usd: float) -> RiskDecision:
        from portfolio.risk import RiskManager
        rm = RiskManager.instance()

        if not rm.can_trade_daily():
            return RiskDecision(False, "rejected_daily_limit")
        if not rm.can_open_position():
            return RiskDecision(False, "rejected_max_positions")
        if rm.in_cooldown():
            return RiskDecision(False, "rejected_cooldown")

        category = getattr(signal.market, "category", "unknown") if signal.market else "unknown"
        if not rm.can_trade_category(category, size_usd):
            return RiskDecision(False, f"rejected_category_exposure_{category}")

        return RiskDecision(True, "ok")
