from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class RejectionSeverity(Enum):
    INFO = 1
    SOFT_REJECT = 2
    HARD_REJECT = 3
    SYSTEM_FAILURE = 4


class RejectionReason(Enum):
    NLP_IMPACT_BELOW_THRESHOLD = ("nlp", "impact_score", "NLP_MIN_IMPACT", RejectionSeverity.HARD_REJECT)
    CATEGORY_NOT_SELECTED = ("category_filter", None, "SELECTED_CATEGORIES", RejectionSeverity.INFO)
    NO_MARKET_MATCHES = ("matcher", "similarity", "MATCHER_MIN_SIMILARITY", RejectionSeverity.HARD_REJECT)
    CLASSIFIER_NOT_ACTIONABLE = ("classifier", "confidence", "multi", RejectionSeverity.HARD_REJECT)
    EDGE_EV_BELOW_THRESHOLD = ("edge", "ev_net", "EDGE_THRESHOLD", RejectionSeverity.HARD_REJECT)
    LIQUIDITY_BELOW_MIN = ("edge", "liquidity_score", "MIN_LIQUIDITY_SCORE", RejectionSeverity.HARD_REJECT)
    SPREAD_EXCEEDS_MAX = ("edge", "spread", "MAX_SPREAD_FRACTION", RejectionSeverity.HARD_REJECT)
    DAILY_LOSS_CAP_HIT = ("risk", "daily_pnl", "DAILY_LOSS_LIMIT_USD", RejectionSeverity.SOFT_REJECT)
    MAX_POSITIONS_REACHED = ("risk", "open_positions", "MAX_CONCURRENT_POSITIONS", RejectionSeverity.SOFT_REJECT)
    CATEGORY_EXPOSURE_EXCEEDED = ("risk", "category_exposure", "MAX_EXPOSURE_PER_CATEGORY_USD", RejectionSeverity.SOFT_REJECT)
    COOLDOWN_ACTIVE = ("risk", "cooldown", "CONSECUTIVE_LOSS_COOLDOWN", RejectionSeverity.SOFT_REJECT)
    MARKET_COOLDOWN_ACTIVE = ("risk", "market_cooldown", "MARKET_SIGNAL_COOLDOWN_SECONDS", RejectionSeverity.SOFT_REJECT)
    SMART_ROUTER_REJECT = ("execution", "spread", "SPREAD_REJECT_THRESHOLD", RejectionSeverity.HARD_REJECT)
    SLIPPAGE_EXCEEDS_MAX = ("execution", "slippage", "MAX_SLIPPAGE_FRACTION", RejectionSeverity.HARD_REJECT)
    STALENESS_ABORT = ("pipeline", "price_move_pct", "STALENESS_THRESHOLD", RejectionSeverity.SOFT_REJECT)
    INSUFFICIENT_DEPTH = ("pipeline", "bid_depth_usd", "MIN_ORDERBOOK_DEPTH_USD", RejectionSeverity.SOFT_REJECT)
    CLASSIFIER_HOT_PATH_FILTERED = ("classifier", "confidence", "FAST_CLASSIFIER_MIN_CONFIDENCE", RejectionSeverity.HARD_REJECT)
    MOMENTUM_ALREADY_MOVING = ("pipeline", "momentum", "MOMENTUM_THRESHOLD", RejectionSeverity.SOFT_REJECT)
    PIPELINE_EXCEPTION = ("pipeline", None, None, RejectionSeverity.SYSTEM_FAILURE)

    @property
    def subsystem(self) -> str:
        return self.value[0]

    @property
    def threshold_field(self) -> str | None:
        return self.value[1]

    @property
    def config_key(self) -> str | None:
        return self.value[2]

    @property
    def severity(self) -> RejectionSeverity:
        return self.value[3]


@dataclass
class RejectionRecord:
    trace_id: str
    reason: RejectionReason
    severity: RejectionSeverity
    subsystem: str
    threshold_value: float | None
    actual_value: float | None
    threshold_snapshot: dict[str, object]
    detail: str | None
    timestamp: float
