from __future__ import annotations
import logging

log = logging.getLogger(__name__)


def estimate(order_size: float, book_depth_usd: float, spread: float) -> float:
    """
    Linear market-impact slippage estimate: (order_size / book_depth) * spread.
    Returns 0.0 if depth is unknown. Clamped to [0.0, 0.20].
    """
    if book_depth_usd <= 0:
        return 0.0
    result = max(0.0, min(0.20, (order_size / book_depth_usd) * spread))
    log.debug(
        f"[slippage] size=${order_size:.2f} depth=${book_depth_usd:.0f} "
        f"spread={spread:.3f} → slippage={result:.4f}"
    )
    return result
