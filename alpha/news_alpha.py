# alpha/news_alpha.py
"""
News Alpha — wraps the existing edge_model.Signal into a unified AlphaSignal.
Called at the end of pipeline._process_market() instead of execute_trade_async().
"""
from __future__ import annotations
import logging
from alpha.base_alpha import BaseAlpha
from alpha.signal import AlphaSignal

log = logging.getLogger(__name__)

# Map time_sensitivity from Classification to horizon codes
_HORIZON_MAP = {
    "immediate":   "5m",
    "short-term":  "1h",
    "long-term":   "1d",
}


class NewsAlpha(BaseAlpha):
    name = "news"

    def to_alpha_signal(self, signal) -> AlphaSignal | None:
        """
        Convert an edge_model.Signal to AlphaSignal.

        Args:
            signal: edge_model.Signal — produced by compute_edge()

        Returns:
            AlphaSignal or None if signal is invalid.
        """
        if signal is None:
            return None

        cls = signal.classification
        horizon = _HORIZON_MAP.get(
            getattr(cls, "time_sensitivity", "short-term"), "1h"
        )

        try:
            return AlphaSignal(
                market_id=signal.market.condition_id,
                market_question=signal.market.question,
                direction=signal.side,          # already "YES" or "NO"
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
