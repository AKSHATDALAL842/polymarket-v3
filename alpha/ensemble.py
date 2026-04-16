# alpha/ensemble.py
"""
Ensemble signal combiner.
Combines multiple AlphaSignal objects for the same market into one
AggregatedSignal using weighted voting and conflict detection.

Strategy weights:
  news:     0.6 (LLM-backed, longer-horizon reliability)
  momentum: 0.4 (price-driven, short-horizon signal)

Size multipliers:
  1.0 → multiple strategies agree
  0.6 → single strategy only
  0.4 → strategies conflict (trade smaller)
"""
from __future__ import annotations
import logging
from alpha.signal import AlphaSignal, AggregatedSignal

log = logging.getLogger(__name__)

STRATEGY_WEIGHTS: dict[str, float] = {
    "news":     0.6,
    "momentum": 0.4,
}


def combine(signals: list[AlphaSignal]) -> AggregatedSignal:
    """
    Combine a list of AlphaSignals (from different strategies, same market)
    into a single AggregatedSignal.

    Args:
        signals: non-empty list of AlphaSignal objects for the SAME market.

    Returns:
        AggregatedSignal with weighted direction, confidence, edge, and multiplier.

    Raises:
        ValueError: if signals is empty.
    """
    if not signals:
        raise ValueError("combine() requires at least one signal")

    # Validate all signals are for the same market
    market_ids = {s.market_id for s in signals}
    if len(market_ids) > 1:
        log.warning(f"[ensemble] Signals for multiple markets: {market_ids} — using first")

    market_id  = signals[0].market_id
    market_q   = signals[0].market_question
    market_obj = next((s.market for s in signals if s.market is not None), None)

    # Deduplicate: keep the highest-confidence signal per strategy
    by_strategy: dict[str, AlphaSignal] = {}
    for sig in signals:
        existing = by_strategy.get(sig.strategy)
        if existing is None or sig.confidence > existing.confidence:
            by_strategy[sig.strategy] = sig

    deduped = list(by_strategy.values())
    strategies = [s.strategy for s in deduped]

    # Weighted vote on direction
    yes_score = 0.0
    no_score  = 0.0
    total_weight = 0.0

    for sig in deduped:
        w = STRATEGY_WEIGHTS.get(sig.strategy, 0.5)
        if sig.direction == "YES":
            yes_score += w * sig.confidence
        else:
            no_score += w * sig.confidence
        total_weight += w

    direction = "YES" if yes_score >= no_score else "NO"

    # Weighted aggregate confidence and edge (from winning-direction signals only)
    winning_sigs = [s for s in deduped if s.direction == direction]
    w_conf  = _weighted_avg(winning_sigs, "confidence")
    w_edge  = _weighted_avg(winning_sigs, "expected_edge")

    # Size multiplier based on agreement
    if len(deduped) == 1:
        multiplier = 0.6    # single strategy
    elif len(set(s.direction for s in deduped)) > 1:
        multiplier = 0.4    # conflict
    else:
        multiplier = 1.0    # all agree

    log.debug(
        f"[ensemble] {market_id[:12]} → {direction} "
        f"conf={w_conf:.2f} edge={w_edge:.3f} mult={multiplier} "
        f"strategies={strategies}"
    )

    return AggregatedSignal(
        market_id=market_id,
        market_question=market_q,
        direction=direction,
        confidence=w_conf,
        expected_edge=w_edge,
        size_multiplier=multiplier,
        strategies=strategies,
        signals=deduped,
        market=market_obj,
    )


def _weighted_avg(signals: list[AlphaSignal], attr: str) -> float:
    """Compute strategy-weighted average of a float attribute across signals."""
    if not signals:
        return 0.0
    total_w = sum(STRATEGY_WEIGHTS.get(s.strategy, 0.5) for s in signals)
    if total_w == 0:
        return 0.0
    return sum(
        STRATEGY_WEIGHTS.get(s.strategy, 0.5) * getattr(s, attr)
        for s in signals
    ) / total_w
