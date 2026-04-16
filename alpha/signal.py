# alpha/signal.py
"""
Unified Alpha Signal schema for the multi-strategy trading engine.
All signal sources (news, momentum) produce AlphaSignal objects.
The ensemble layer combines them into AggregatedSignal for portfolio decisions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time

_VALID_DIRECTIONS = ("YES", "NO")
_VALID_HORIZONS   = ("5m", "1h", "1d")
_VALID_STRATEGIES = ("news", "momentum")


@dataclass
class AlphaSignal:
    """A single directional signal from one alpha strategy."""
    market_id: str
    market_question: str
    direction: str          # "YES" | "NO"
    confidence: float       # [0.0, 1.0]
    expected_edge: float    # estimated EV (e.g. 0.05 = 5 cents per dollar)
    horizon: str            # "5m" | "1h" | "1d"
    strategy: str           # "news" | "momentum"
    timestamp: float = field(default_factory=time.time)
    market: object = field(default=None, repr=False)     # markets.Market reference
    raw_signal: object = field(default=None, repr=False) # edge_model.Signal reference

    def __post_init__(self):
        assert self.direction in _VALID_DIRECTIONS, \
            f"direction must be YES or NO, got {self.direction!r}"
        assert 0.0 <= self.confidence <= 1.0, \
            f"confidence must be in [0,1], got {self.confidence}"
        assert self.horizon in _VALID_HORIZONS, \
            f"horizon must be 5m|1h|1d, got {self.horizon!r}"
        assert self.strategy in _VALID_STRATEGIES, \
            f"strategy must be news|momentum, got {self.strategy!r}"


@dataclass
class AggregatedSignal:
    """
    Combined signal from multiple alpha strategies targeting the same market.
    Produced by ensemble.combine(). This is what PortfolioManager receives.
    """
    market_id: str
    market_question: str
    direction: str          # "YES" | "NO" — majority weighted vote result
    confidence: float       # weighted aggregate confidence
    expected_edge: float    # weighted aggregate edge
    size_multiplier: float  # 1.0=agreement, 0.6=single-strategy, 0.4=conflict
    strategies: list        # list[str] of strategy names that contributed
    signals: list           # list[AlphaSignal] that were combined
    timestamp: float = field(default_factory=time.time)
    market: object = field(default=None, repr=False)  # markets.Market reference

    @property
    def is_strong(self) -> bool:
        """True if multiple strategies agree (not a conflict, more than one strategy)."""
        return self.size_multiplier == 1.0 and len(self.strategies) > 1

    @property
    def has_conflict(self) -> bool:
        """True if strategies disagree on direction."""
        return self.size_multiplier == 0.4
