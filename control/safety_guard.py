# control/safety_guard.py
"""
Safety checks that must pass before enabling live trading.
All checks are read-only — they do not modify state.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

MAX_DRAWDOWN_FOR_LIVE = 0.20    # block live if drawdown > 20%


@dataclass
class SafetyCheckResult:
    safe: bool
    reason: str   # "ok" if safe, else human-readable reason


class SafetyGuard:
    """
    Checks that must pass before enabling LIVE trading.
    Currently enforces:
      1. Max drawdown <= 20%
      2. Not in risk cooldown
    """

    def check(self) -> SafetyCheckResult:
        """
        Run all safety checks.
        Returns SafetyCheckResult(safe=True, reason="ok") if all pass.
        """
        drawdown_result = self._check_drawdown()
        if not drawdown_result.safe:
            return drawdown_result

        cooldown_result = self._check_cooldown()
        if not cooldown_result.safe:
            return cooldown_result

        return SafetyCheckResult(safe=True, reason="ok")

    def _check_drawdown(self) -> SafetyCheckResult:
        try:
            from portfolio._paper import get_portfolio as get_paper_portfolio
            dd = get_paper_portfolio().get_max_drawdown()
            if dd > MAX_DRAWDOWN_FOR_LIVE:
                return SafetyCheckResult(
                    safe=False,
                    reason=f"drawdown too high: {dd*100:.2f}% (max allowed: {MAX_DRAWDOWN_FOR_LIVE*100:.0f}%)"
                )
        except Exception as e:
            log.warning(f"[safety_guard] Could not check drawdown: {e}")
        return SafetyCheckResult(safe=True, reason="ok")

    def _check_cooldown(self) -> SafetyCheckResult:
        try:
            from portfolio.risk import RiskManager
            rm = RiskManager.instance()
            if rm.in_cooldown():
                return SafetyCheckResult(
                    safe=False,
                    reason="risk manager in consecutive-loss cooldown"
                )
        except Exception as e:
            log.warning(f"[safety_guard] Could not check cooldown: {e}")
        return SafetyCheckResult(safe=True, reason="ok")
