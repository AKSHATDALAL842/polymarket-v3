from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import config
from signal.classifier import Classification
from ingestion.markets import Market

log = logging.getLogger(__name__)


@dataclass
class Signal:
    market: Market
    side: str
    p_market: float
    p_true: float
    ev: float
    bet_amount: float
    reasoning: str
    classification: Classification
    spread: float = 0.0
    liquidity_score: float = 1.0
    estimated_slippage: float = 0.0
    news_latency_ms: int = 0
    classification_latency_ms: int = 0
    total_latency_ms: int = 0
    news_source: str = ""
    headlines: str = ""


def _adjustment(
    direction: str,
    materiality: float,
    novelty_score: float,
    confidence: float,
    p_market: float,
) -> float:
    alpha = config.EDGE_ALPHA
    beta = config.EDGE_BETA
    gamma = config.EDGE_GAMMA

    raw = alpha * materiality + beta * confidence + gamma * novelty_score

    # Asymmetric boundary correction — prevents pushing price above 0.95 or below 0.05
    if direction == "YES":
        room = max(0.0, 0.95 - p_market)
        sign = +1.0
    elif direction == "NO":
        room = max(0.0, p_market - 0.05)
        sign = -1.0
    else:
        return 0.0

    # Sigmoid-like dampening: saturates at ~1 for large inputs
    scaled = room * (1.0 - math.exp(-2.0 * raw))

    # Hard cap prevents LLM overconfidence from producing unrealistic EVs
    scaled = min(scaled, config.EDGE_MAX_ADJUSTMENT)

    return sign * scaled


def compute_edge(
    market: Market,
    classification: Classification,
    liquidity_score: float = 1.0,
    spread: float = 0.0,
    estimated_slippage: float = 0.0,
) -> Signal | None:
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

    adj = _adjustment(
        direction=classification.direction,
        materiality=classification.materiality,
        novelty_score=classification.novelty_score,
        confidence=classification.confidence,
        p_market=p_market,
    )
    p_true = max(0.02, min(0.98, p_market + adj))

    if classification.direction == "YES":
        side = "YES"
        ev = p_true - p_market
    else:
        side = "NO"
        ev = p_market - p_true

    ev_net = ev - estimated_slippage

    if ev_net < config.EDGE_THRESHOLD:
        log.debug(f"[edge] Rejected: EV_net={ev_net:.3f} < threshold={config.EDGE_THRESHOLD}")
        return None

    if liquidity_score < config.MIN_LIQUIDITY_SCORE:
        log.debug(f"[edge] Rejected: liquidity_score={liquidity_score:.2f} < {config.MIN_LIQUIDITY_SCORE}")
        return None

    if spread > config.MAX_SPREAD_FRACTION:
        log.debug(f"[edge] Rejected: spread={spread:.3f} > max={config.MAX_SPREAD_FRACTION}")
        return None

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
    # Conservative Kelly variant: size = min(MAX_BET, K * |EV| * confidence * bankroll)
    raw_size = config.SIZING_K * ev * confidence * config.BANKROLL_USD
    return round(min(config.MAX_BET_USD, max(1.0, raw_size)), 2)


def detect_edge_v2(market: Market, classification, news_event=None) -> Signal | None:
    """Backward-compat shim used by dashboard.py. Delegates to compute_edge."""
    from signal.classifier import Classification
    if not isinstance(classification, Classification):
        cls = Classification(
            direction=str(getattr(classification, "direction", "NEUTRAL")),
            confidence=float(classification) if isinstance(classification, (int, float)) else 0.65,
            materiality=float(getattr(classification, "materiality", 0.5)),
            novelty_score=0.6,
            time_sensitivity="short-term",
            reasoning=str(getattr(classification, "reasoning", "")),
            consistency=1.0,
        )
        return compute_edge(market, cls)
    return compute_edge(market, classification)

