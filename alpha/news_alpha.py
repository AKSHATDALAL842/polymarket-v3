from __future__ import annotations
import logging
from alpha.base_alpha import BaseAlpha
from alpha.signal import AlphaSignal

log = logging.getLogger(__name__)

_HORIZON_MAP = {
    "immediate":   "5m",
    "short-term":  "1h",
    "long-term":   "1d",
}


class NewsAlpha(BaseAlpha):
    name = "news"

    def to_alpha_signal(self, signal) -> AlphaSignal | None:
        if signal is None:
            return None
        try:
            cls = signal.classification
            horizon = _HORIZON_MAP.get(getattr(cls, "time_sensitivity", "short-term"), "1h")
            return AlphaSignal(
                market_id=signal.market.condition_id,
                market_question=signal.market.question,
                direction=signal.side,
                confidence=cls.confidence,
                expected_edge=signal.ev,
                horizon=horizon,
                strategy="news",
                market=signal.market,
                raw_signal=signal,
            )
        except (ValueError, AttributeError) as e:
            log.warning(f"[news_alpha] Failed to convert signal: {e}")
            return None
