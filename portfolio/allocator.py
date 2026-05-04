from __future__ import annotations
import logging
from alpha.signal import AggregatedSignal

log = logging.getLogger(__name__)


class Allocator:
    """
    Dynamic position sizer.

    Formula:
      base     = sizing_k * edge * confidence * bankroll
      sized    = base * size_multiplier          (ensemble agreement: 1.0 / 0.6 / 0.4)
      dd_scale = max(0, 1 - drawdown * 2)        (linear reduction; 0 size at 50% drawdown)
      final    = 0 if dd_scale==0, else clamp(sized * dd_scale, 1.0, max_bet)
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
        base = self.sizing_k * signal.expected_edge * signal.confidence * self.bankroll
        sized = base * signal.size_multiplier
        dd_scalar = max(0.0, 1.0 - drawdown * 2.0)
        if dd_scalar <= 0.0:
            return 0.0
        dd_scaled = sized * dd_scalar
        final = max(1.0, min(self.max_bet, dd_scaled))
        log.debug(
            f"[allocator] base={base:.2f} sized={sized:.2f} "
            f"dd_scalar={dd_scalar:.2f} final={final:.2f}"
        )
        return round(final, 2)

    def update_capital(self, new_capital: float):
        self.capital = new_capital
        self.bankroll = new_capital  # bankroll drives the sizing formula
