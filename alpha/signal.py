from __future__ import annotations
from dataclasses import dataclass, field
import time

_VALID_DIRECTIONS = ("YES", "NO")
_VALID_HORIZONS   = ("5m", "1h", "1d")
_VALID_STRATEGIES = ("news", "momentum")
_VALID_MULTIPLIERS = (0.4, 0.6, 1.0)  # conflict, single-strategy, agreement


@dataclass
class AlphaSignal:
    market_id: str
    market_question: str
    direction: str          # "YES" | "NO"
    confidence: float       # [0.0, 1.0]
    expected_edge: float    # estimated EV, e.g. 0.05 = 5 cents per dollar
    horizon: str            # "5m" | "1h" | "1d"
    strategy: str           # "news" | "momentum"
    timestamp: float = field(default_factory=time.time)
    market: object = field(default=None, repr=False)     # ingestion.markets.Market
    raw_signal: object = field(default=None, repr=False) # signal.edge_model.Signal

    def __post_init__(self):
        if self.direction not in _VALID_DIRECTIONS:
            raise ValueError(f"direction must be YES or NO, got {self.direction!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.horizon not in _VALID_HORIZONS:
            raise ValueError(f"horizon must be 5m|1h|1d, got {self.horizon!r}")
        if self.strategy not in _VALID_STRATEGIES:
            raise ValueError(f"strategy must be news|momentum, got {self.strategy!r}")
        if not self.market_id:
            raise ValueError("market_id must not be empty")


@dataclass
class AggregatedSignal:
    """
    Combined signal from multiple alpha strategies for the same market.
    Produced by ensemble.combine(). Received by PortfolioManager.

    size_multiplier: 1.0=strategies agree, 0.6=single strategy, 0.4=conflict.
    """
    market_id: str
    market_question: str
    direction: str          # "YES" | "NO"
    confidence: float
    expected_edge: float
    size_multiplier: float  # 1.0 | 0.6 | 0.4
    strategies: list
    signals: list
    timestamp: float = field(default_factory=time.time)
    market: object = field(default=None, repr=False)

    def __post_init__(self):
        if self.direction not in _VALID_DIRECTIONS:
            raise ValueError(f"direction must be YES or NO, got {self.direction!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.size_multiplier not in _VALID_MULTIPLIERS:
            raise ValueError(
                f"size_multiplier must be one of {_VALID_MULTIPLIERS}, got {self.size_multiplier}"
            )

    @property
    def is_strong(self) -> bool:
        return self.size_multiplier == 1.0 and len(self.strategies) > 1

    @property
    def has_conflict(self) -> bool:
        return self.size_multiplier == 0.4
