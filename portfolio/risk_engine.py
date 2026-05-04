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
        if rm.in_cooldown():
            return RiskDecision(False, "rejected_cooldown")

        condition_id = getattr(signal, "market_id", "unknown")
        category = getattr(signal.market, "category", "unknown") if signal.market else "unknown"

        # Atomically check position count + category exposure and reserve the slot.
        # Must not call on_trade_opened() separately after this succeeds.
        rejection = rm.try_open_position(condition_id, category, size_usd)
        if rejection:
            return RiskDecision(False, rejection)

        return RiskDecision(True, "ok")
