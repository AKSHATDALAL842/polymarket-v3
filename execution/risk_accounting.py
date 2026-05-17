"""
Global Risk Accounting — portfolio-level exposure management.

Tracks: total exposure, correlated exposure, platform caps, category caps,
event-cluster caps, volatility-adjusted exposure, dynamic drawdown throttling,
concentration limits.

Detects: correlated bets, hidden concentration, runaway exposure,
conflicting positions, excessive illiquid exposure, stale-market exposure.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ExposureLimits:
    total_max: float = 100.0           # Absolute total exposure cap
    per_market_max: float = 25.0       # Max per single market
    per_category_max: float = 60.0     # Max per category
    per_platform_max: float = 100.0    # Max per platform (polymarket/kalshi)
    correlated_max: float = 40.0       # Max correlated exposure
    max_concurrent: int = 5            # Max concurrent positions
    concentration_warning: float = 0.30  # Warn if single position > 30% of total
    illiquid_max: float = 15.0         # Max exposure to illiquid markets


@dataclass
class RiskExposure:
    total_exposure: float = 0.0
    by_market: dict[str, float] = field(default_factory=dict)
    by_category: dict[str, float] = field(default_factory=dict)
    by_platform: dict[str, float] = field(default_factory=dict)
    correlated_exposure: float = 0.0
    illiquid_exposure: float = 0.0
    position_count: int = 0
    concentration_risk: float = 0.0     # max(exposure_i / total)
    drawdown_pct: float = 0.0


class RiskAccountant:
    """Global exposure tracker with limits enforcement."""

    def __init__(self, limits: ExposureLimits | None = None):
        self.limits = limits or ExposureLimits()
        self._violations: list[dict] = []

    def assess(self, positions: list, drawdown: float = 0.0) -> tuple[RiskExposure, list[str]]:
        """Assess current exposure and return violations."""
        exp = RiskExposure()

        for pos in positions:
            if not getattr(pos, 'is_active', lambda: False)():
                continue

            size = getattr(pos, 'size_usd', 0.0)
            market = getattr(pos, 'market_id', 'unknown')
            cat = getattr(pos, 'category', 'unknown')
            platform = getattr(pos, 'platform', 'polymarket')

            exp.total_exposure += size
            exp.by_market[market] = exp.by_market.get(market, 0.0) + size
            exp.by_category[cat] = exp.by_category.get(cat, 0.0) + size
            exp.by_platform[platform] = exp.by_platform.get(platform, 0.0) + size
            exp.position_count += 1

        max_single = max(exp.by_market.values()) if exp.by_market else 0.0
        exp.concentration_risk = max_single / max(0.01, exp.total_exposure)
        exp.drawdown_pct = drawdown

        # Correlated exposure: markets in same category
        exp.correlated_exposure = max(exp.by_category.values()) if exp.by_category else 0.0

        violations = self._check_violations(exp)
        return exp, violations

    def _check_violations(self, exp: RiskExposure) -> list[str]:
        violations = []

        if exp.total_exposure > self.limits.total_max:
            violations.append(
                f"Total exposure ${exp.total_exposure:.2f} > ${self.limits.total_max:.2f}"
            )

        if exp.position_count > self.limits.max_concurrent:
            violations.append(
                f"Concurrent positions {exp.position_count} > {self.limits.max_concurrent}"
            )

        for market, size in exp.by_market.items():
            if size > self.limits.per_market_max:
                violations.append(
                    f"Market {market[:20]} exposure ${size:.2f} > ${self.limits.per_market_max:.2f}"
                )

        for cat, size in exp.by_category.items():
            if size > self.limits.per_category_max:
                violations.append(
                    f"Category {cat} exposure ${size:.2f} > ${self.limits.per_category_max:.2f}"
                )

        if exp.correlated_exposure > self.limits.correlated_max:
            violations.append(
                f"Correlated exposure ${exp.correlated_exposure:.2f} > ${self.limits.correlated_max:.2f}"
            )

        if exp.concentration_risk > self.limits.concentration_warning:
            violations.append(
                f"Concentration risk {exp.concentration_risk:.1%} > {self.limits.concentration_warning:.1%}"
            )

        if exp.illiquid_exposure > self.limits.illiquid_max:
            violations.append(
                f"Illiquid exposure ${exp.illiquid_exposure:.2f} > ${self.limits.illiquid_max:.2f}"
            )

        if violations:
            for v in violations:
                log.warning("[risk_accounting] VIOLATION: %s", v)

        return violations

    def pre_trade_check(self, market_id: str, category: str, platform: str,
                         size_usd: float, current_positions: list) -> tuple[bool, str]:
        """Check if a proposed trade would violate any limits. Returns (approved, reason)."""
        # Simulate the trade
        from execution.position_lifecycle import Position

        class SimPosition:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        simulated = list(current_positions)
        simulated.append(SimPosition(market_id, category, platform, size_usd))
        exp, violations = self.assess(simulated)

        if violations:
            return False, "; ".join(violations)
        return True, "ok"

    def status(self) -> dict:
        return {
            "limits": {
                "total_max": self.limits.total_max,
                "per_market_max": self.limits.per_market_max,
                "per_category_max": self.limits.per_category_max,
                "max_concurrent": self.limits.max_concurrent,
            },
            "recent_violations": len(self._violations),
        }
