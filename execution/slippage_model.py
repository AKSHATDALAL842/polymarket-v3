# execution/slippage_model.py
"""
Slippage estimator.

Formula (linear market-impact model):
    slippage = (order_size / book_depth) * spread

Clamps output to [0.0, 0.20] (never estimate > 20% slippage).
Returns 0.0 if book depth is unknown.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


def estimate(order_size: float, book_depth_usd: float, spread: float) -> float:
    """
    Estimate one-way slippage as a fraction of the order price.

    Args:
        order_size:    Size in USD.
        book_depth_usd: USD available on the relevant side of the book.
        spread:        Bid-ask spread as fraction of mid (e.g. 0.03 for 3%).

    Returns:
        Estimated slippage as a fraction [0.0, 0.20].
    """
    if book_depth_usd <= 0:
        return 0.0

    impact = (order_size / book_depth_usd) * spread
    result = max(0.0, min(0.20, impact))
    log.debug(
        f"[slippage] size=${order_size:.2f} depth=${book_depth_usd:.0f} "
        f"spread={spread:.3f} → slippage={result:.4f}"
    )
    return result
