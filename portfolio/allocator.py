# portfolio/allocator.py
"""
Dynamic position allocator.

Replaces fixed Kelly with a multi-factor sizing formula:
  base_size    = SIZING_K * edge * confidence * bankroll
  sized        = base_size * size_multiplier    (ensemble agreement factor)
  dd_scaled    = sized * (1 - drawdown * 2)     (reduce when losing)
  final        = clamp(dd_scaled, 1.0, max_bet)

Drawdown scalar: linear reduction up to 50% size at 25% drawdown.
"""
from __future__ import annotations
import logging
from alpha.signal import AggregatedSignal

log = logging.getLogger(__name__)


class Allocator:
    """
    Compute position size in USD for a given AggregatedSignal.

    Args:
        capital:   Current portfolio cash balance (unused directly — kept for
                   future volatility scaling against portfolio fraction).
        max_bet:   Hard cap per trade in USD (from config.MAX_BET_USD).
        sizing_k:  Fractional Kelly multiplier (from config.SIZING_K = 0.25).
        bankroll:  Notional bankroll used in Kelly formula (config.BANKROLL_USD = 1000).
    """

    def __init__(
        self,
        capital: float = 1_000_000.0,
        max_bet: float = 25.0,
        sizing_k: float = 0.25,
        bankroll: float = 1000.0,
    ):
        self.capital   = capital
        self.max_bet   = max_bet
        self.sizing_k  = sizing_k
        self.bankroll  = bankroll

    def compute_size(self, signal: AggregatedSignal, drawdown: float = 0.0) -> float:
        """
        Compute trade size in USD.

        Args:
            signal:   AggregatedSignal from ensemble.combine()
            drawdown: Current max drawdown as a fraction, e.g. 0.10 for 10%.
                      Used to scale down size when the portfolio is losing.

        Returns:
            Float USD amount, clamped to [1.0, max_bet].
        """
        # Base Kelly-fractional size
        base = self.sizing_k * signal.expected_edge * signal.confidence * self.bankroll

        # Apply ensemble agreement multiplier (1.0, 0.6, or 0.4)
        sized = base * signal.size_multiplier

        # Drawdown scalar: linearly reduce up to 50% size at 25% drawdown
        # At drawdown=0.0 → scalar=1.0 (full size)
        # At drawdown=0.25 → scalar=0.5 (half size)
        # At drawdown>=0.5 → scalar=0.0, but $1 floor applies (minimum trade maintained)
        drawdown_scalar = max(0.0, 1.0 - drawdown * 2.0)
        dd_scaled = sized * drawdown_scalar

        final = max(1.0, min(self.max_bet, dd_scaled))

        log.debug(
            f"[allocator] base={base:.2f} sized={sized:.2f} "
            f"dd_scalar={drawdown_scalar:.2f} final={final:.2f}"
        )
        return round(final, 2)

    def update_capital(self, new_capital: float):
        """Update capital after portfolio state changes."""
        self.capital = new_capital
