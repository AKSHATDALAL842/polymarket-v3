"""
Edge Estimation Model — converts LLM signals into a calibrated price adjustment.

Design:
  p_true = p_market + adjustment(direction, materiality, novelty, confidence)

The adjustment is bounded and calibrated so that:
  - High materiality + high novelty + high confidence → large adjustment
  - Low novelty (already priced in) → adjustment shrinks toward zero
  - Adjustment is asymmetric near market boundaries (can't push price above 1 or below 0)

EV = p_true - p_market (for YES side)
   = p_market - p_true (for NO side)

Trade is rejected if:
  - |EV| < EDGE_THRESHOLD
  - novelty_score < MIN_NOVELTY
  - confidence < MIN_CONFIDENCE
  - liquidity_score < MIN_LIQUIDITY

Position sizing: size = min(MAX_BET, SIZING_K * |EV| * confidence * bankroll)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import config
from classifier import Classification
from markets import Market

log = logging.getLogger(__name__)


# ── Signal dataclass (replaces edge.Signal) ────────────────────────────────────

@dataclass
class Signal:
    market: Market
    side: str                   # "YES" or "NO"
    p_market: float             # current market price (YES probability)
    p_true: float               # estimated true probability
    ev: float                   # expected value = |p_true - p_market|
    bet_amount: float           # USD to wager
    reasoning: str
    classification: Classification
    # Microstructure data (filled in by market_watcher)
    spread: float = 0.0
    liquidity_score: float = 1.0
    estimated_slippage: float = 0.0
    # Latency tracking
    news_latency_ms: int = 0
    classification_latency_ms: int = 0
    total_latency_ms: int = 0
    # Source tracking
    news_source: str = ""
    headlines: str = ""


# ── Adjustment function ────────────────────────────────────────────────────────

def _adjustment(
    direction: str,
    materiality: float,
    novelty_score: float,
    confidence: float,
    p_market: float,
) -> float:
    """
    Compute the signed price adjustment.

    The raw adjustment magnitude is:
        adj_magnitude = alpha*materiality + beta*confidence + gamma*novelty
    weighted by config. It is then scaled by remaining room in the direction of the trade
    and clipped to prevent extreme probability values.

    Returns a signed float: positive → YES is more likely, negative → NO is more likely.
    """
    alpha = config.EDGE_ALPHA
    beta = config.EDGE_BETA
    gamma = config.EDGE_GAMMA

    # Weighted signal magnitude
    raw = alpha * materiality + beta * confidence + gamma * novelty_score

    # Scale by available room: asymmetric boundary correction
    # This prevents pushing price above 0.95 or below 0.05
    if direction == "YES":
        room = max(0.0, 0.95 - p_market)
        sign = +1.0
    elif direction == "NO":
        room = max(0.0, p_market - 0.05)
        sign = -1.0
    else:
        return 0.0

    # Sigmoid-like dampening so large raw values don't overshoot
    # Uses 1 - exp(-2*raw) which saturates at ~1 for large inputs
    scaled = room * (1.0 - math.exp(-2.0 * raw))

    # Hard cap: never move price more than EDGE_MAX_ADJUSTMENT from market
    # This prevents the LLM's overconfident scores from producing unrealistic EVs
    scaled = min(scaled, config.EDGE_MAX_ADJUSTMENT)

    return sign * scaled


# ── Main edge calculation ──────────────────────────────────────────────────────

def compute_edge(
    market: Market,
    classification: Classification,
    liquidity_score: float = 1.0,
    spread: float = 0.0,
    estimated_slippage: float = 0.0,
) -> Signal | None:
    """
    Compute edge from a classification result.
    Returns Signal if edge is sufficient, None if trade should be rejected.

    Rejection reasons:
      - direction is NEUTRAL
      - classification not actionable (low confidence/materiality/novelty/consistency)
      - |EV| below threshold
      - liquidity insufficient
    """
    if classification.direction == "NEUTRAL":
        log.debug("[edge] Rejected: direction=NEUTRAL")
        return None

    if not classification.is_actionable:
        log.debug(
            f"[edge] Rejected: not actionable "
            f"(conf={classification.confidence:.2f}, mat={classification.materiality:.2f}, "
            f"nov={classification.novelty_score:.2f}, consistency={classification.consistency:.2f})"
        )
        return None

    p_market = market.yes_price

    # Compute adjustment and true probability estimate
    adj = _adjustment(
        direction=classification.direction,
        materiality=classification.materiality,
        novelty_score=classification.novelty_score,
        confidence=classification.confidence,
        p_market=p_market,
    )
    p_true = max(0.02, min(0.98, p_market + adj))

    # Determine trade side and EV
    if classification.direction == "YES":
        side = "YES"
        ev = p_true - p_market        # positive: we think it's underpriced
    else:
        side = "NO"
        ev = p_market - p_true        # positive: we think YES is overpriced

    # Subtract estimated slippage cost from EV
    ev_net = ev - estimated_slippage

    if ev_net < config.EDGE_THRESHOLD:
        log.debug(f"[edge] Rejected: EV_net={ev_net:.3f} < threshold={config.EDGE_THRESHOLD}")
        return None

    # Microstructure gate: skip if market is too thin
    if liquidity_score < config.MIN_LIQUIDITY_SCORE:
        log.debug(f"[edge] Rejected: liquidity_score={liquidity_score:.2f} < {config.MIN_LIQUIDITY_SCORE}")
        return None

    # Spread guard: if spread is very wide, the true cost exceeds any edge
    if spread > config.MAX_SPREAD_FRACTION:
        log.debug(f"[edge] Rejected: spread={spread:.3f} > max={config.MAX_SPREAD_FRACTION}")
        return None

    # Position sizing: capped fractional
    bet_amount = _size_position(ev_net, classification.confidence)

    signal = Signal(
        market=market,
        side=side,
        p_market=p_market,
        p_true=p_true,
        ev=ev_net,
        bet_amount=bet_amount,
        reasoning=classification.reasoning,
        classification=classification,
        spread=spread,
        liquidity_score=liquidity_score,
        estimated_slippage=estimated_slippage,
    )

    log.info(
        f"[edge] SIGNAL {side} on '{market.question[:50]}...' "
        f"p_market={p_market:.3f} p_true={p_true:.3f} ev={ev_net:.3f} "
        f"bet=${bet_amount:.2f}"
    )
    return signal


def _size_position(ev: float, confidence: float) -> float:
    """
    Capped fractional position sizing.
      size = min(MAX_BET, SIZING_K * |EV| * confidence * bankroll)

    This is a conservative Kelly variant that avoids overbetting on uncertain signals.
    """
    raw_size = config.SIZING_K * ev * confidence * config.BANKROLL_USD
    return round(min(config.MAX_BET_USD, max(1.0, raw_size)), 2)


# ── Convenience wrapper for V2 compatibility ───────────────────────────────────

def detect_edge_v2(
    market: Market,
    classification,   # accepts both new Classification and old-style dicts
    news_event=None,
) -> Signal | None:
    """Backwards-compatible wrapper: accepts V2 Classification objects too."""
    # If old-style dataclass with "direction"/"materiality" but no confidence etc.
    from classifier import Classification as NewClassification
    if not isinstance(classification, NewClassification):
        # Shim: wrap old classification
        direction_map = {"bullish": "YES", "bearish": "NO", "neutral": "NEUTRAL"}
        direction = direction_map.get(getattr(classification, "direction", "neutral"), "NEUTRAL")
        cls_obj = NewClassification(
            direction=direction,
            confidence=0.65,
            materiality=getattr(classification, "materiality", 0.5),
            novelty_score=0.6,
            time_sensitivity="short-term",
            reasoning=getattr(classification, "reasoning", ""),
            consistency=1.0,
        )
        return compute_edge(market, cls_obj)

    return compute_edge(market, classification)
