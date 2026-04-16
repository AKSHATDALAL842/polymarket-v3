# portfolio/risk_engine.py
"""
Risk validation layer for the PortfolioManager.
Delegates all checks to the existing RiskManager singleton.
Returns a RiskDecision with reason for rejection or approval.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import config

log = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    approved: bool
    reason: str    # "ok" if approved, rejection reason string otherwise


class RiskEngine:
    """
    Validates an AggregatedSignal before the PortfolioManager executes it.
    All actual state is in risk.RiskManager — this is a clean interface layer.
    """

    def validate(self, signal, size_usd: float) -> RiskDecision:
        """
        Run all risk checks for a proposed trade.

        Args:
            signal:   AggregatedSignal
            size_usd: Proposed trade size in USD from Allocator

        Returns:
            RiskDecision(approved=True, reason="ok") or
            RiskDecision(approved=False, reason="<rejection_reason>")
        """
        from risk import RiskManager
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
