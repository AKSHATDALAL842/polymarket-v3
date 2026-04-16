# execution/smart_router.py
"""
Smart order router — chooses execution aggressiveness based on microstructure.

Routing rules:
  spread < 2%  → aggressive (marketable limit)
  spread 2-8%  → passive (post at bid/ask)
  spread > 8%  → reject (too wide)
  |momentum| > 3%  → aggressive regardless of spread
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

SPREAD_AGGRESSIVE_THRESHOLD = 0.02   # < 2% spread → aggressive
SPREAD_REJECT_THRESHOLD     = 0.08   # > 8% spread → reject
MOMENTUM_AGGRESSIVE_TRIGGER = 0.03   # |momentum| > 3% → aggressive


def get_routing_strategy(spread: float, momentum: float = 0.0) -> str:
    """
    Determine order routing strategy.

    Returns:
        "aggressive" | "passive" | "reject"
    """
    if spread > SPREAD_REJECT_THRESHOLD:
        log.debug(f"[smart_router] reject: spread={spread:.3f} > {SPREAD_REJECT_THRESHOLD}")
        return "reject"

    if abs(momentum) > MOMENTUM_AGGRESSIVE_TRIGGER:
        log.debug(f"[smart_router] aggressive: momentum={momentum:+.3f}")
        return "aggressive"

    if spread < SPREAD_AGGRESSIVE_THRESHOLD:
        log.debug(f"[smart_router] aggressive: spread={spread:.3f} < {SPREAD_AGGRESSIVE_THRESHOLD}")
        return "aggressive"

    log.debug(f"[smart_router] passive: spread={spread:.3f}")
    return "passive"
