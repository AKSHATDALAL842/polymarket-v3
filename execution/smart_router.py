from __future__ import annotations
import logging

log = logging.getLogger(__name__)

# Routing thresholds: spread < 2% → aggressive, > 8% → reject, |momentum| > 3% → aggressive
SPREAD_AGGRESSIVE_THRESHOLD = 0.02
SPREAD_REJECT_THRESHOLD     = 0.08
MOMENTUM_AGGRESSIVE_TRIGGER = 0.03


def get_routing_strategy(spread: float, momentum: float = 0.0) -> str:
    """Returns "aggressive" | "passive" | "reject"."""
    if spread > SPREAD_REJECT_THRESHOLD:
        log.debug(f"[smart_router] reject: spread={spread:.3f}")
        return "reject"
    if abs(momentum) > MOMENTUM_AGGRESSIVE_TRIGGER or spread < SPREAD_AGGRESSIVE_THRESHOLD:
        log.debug(f"[smart_router] aggressive: spread={spread:.3f} momentum={momentum:+.3f}")
        return "aggressive"
    log.debug(f"[smart_router] passive: spread={spread:.3f}")
    return "passive"
