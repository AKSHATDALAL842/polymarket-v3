from __future__ import annotations
import logging
from alpha.signal import AlphaSignal, AggregatedSignal

log = logging.getLogger(__name__)

# news=0.6 (LLM-backed), momentum=0.4 (price-driven, shorter horizon)
STRATEGY_WEIGHTS: dict[str, float] = {
    "news":     0.6,
    "momentum": 0.4,
}


def combine(signals: list[AlphaSignal]) -> AggregatedSignal:
    """
    Combine AlphaSignals from different strategies for the same market.
    Raises ValueError if signals is empty.
    """
    if not signals:
        raise ValueError("combine() requires at least one signal")

    market_ids = {s.market_id for s in signals}
    if len(market_ids) > 1:
        log.warning(f"[ensemble] Signals for multiple markets: {market_ids} — using first")

    market_id  = signals[0].market_id
    market_q   = signals[0].market_question
    market_obj = next((s.market for s in signals if s.market is not None), None)

    by_strategy: dict[str, AlphaSignal] = {}
    for sig in signals:
        existing = by_strategy.get(sig.strategy)
        if existing is None or sig.confidence > existing.confidence:
            by_strategy[sig.strategy] = sig

    deduped = list(by_strategy.values())
    strategies = [s.strategy for s in deduped]

    yes_score = 0.0
    no_score  = 0.0
    for sig in deduped:
        w = STRATEGY_WEIGHTS.get(sig.strategy, 0.5)
        if sig.direction == "YES":
            yes_score += w * sig.confidence
        else:
            no_score += w * sig.confidence

    if yes_score > no_score:
        direction = "YES"
    elif no_score > yes_score:
        direction = "NO"
    else:
        direction = max(deduped, key=lambda s: s.confidence).direction

    winning_sigs = [s for s in deduped if s.direction == direction] or deduped
    w_conf = _weighted_avg(winning_sigs, "confidence")
    w_edge = _weighted_avg(winning_sigs, "expected_edge")

    if len(deduped) == 1:
        multiplier = 0.6
    elif len(set(s.direction for s in deduped)) > 1:
        multiplier = 0.4
    else:
        multiplier = 1.0

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
    if not signals:
        return 0.0
    total_w = sum(STRATEGY_WEIGHTS.get(s.strategy, 0.5) for s in signals)
    if total_w == 0:
        return 0.0
    return sum(
        STRATEGY_WEIGHTS.get(s.strategy, 0.5) * getattr(s, attr)
        for s in signals
    ) / total_w
