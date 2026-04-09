"""
Event Intelligence Layer — multi-pass LLM classification with consistency scoring.

Replaces single-shot direction label with structured probabilistic output:
  direction, confidence, materiality, novelty_score, time_sensitivity, reasoning

Uses 3 independent LLM passes and aggregates to produce a stability-weighted result.
Rejects classification when pass agreement is below threshold.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field

import config
from markets import Market

log = logging.getLogger(__name__)

# Lazy client — instantiated on first use
_client = None

# Semaphore: limit concurrent Groq API calls to stay within free tier (30 RPM)
# 3 passes × max 3 concurrent events = 9 in-flight at once — well within limits
_groq_semaphore = asyncio.Semaphore(9)


def _get_client():
    global _client
    if _client is not None:
        return _client

    if config.USE_GROQ:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(
            api_key=config.GROQ_API_KEY,
            base_url=config.GROQ_BASE_URL,
        )
        log.info(f"[classifier] Using Groq ({config.CLASSIFICATION_MODEL})")
    else:
        import anthropic
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        log.info(f"[classifier] Using Anthropic ({config.CLASSIFICATION_MODEL})")

    return _client


# ── Prompt ─────────────────────────────────────────────────────────────────────

_PROMPT = """\
You are a quantitative news analyst for prediction markets. Your job is to determine how a news event should move a market price.

## Market Question
{question}

## Current Market Price
YES probability: {yes_price:.2%}   (implied odds: {yes_odds:.1f}x)

## Breaking News
{headline}
Source: {source}

## Instructions
Assess whether this news causes the market to resolve YES more likely, less likely, or is not relevant.

Be realistic about whether this is truly new information or something the market has already priced in.

Respond ONLY with valid JSON matching this schema exactly:
{{
  "direction": "YES" | "NO" | "NEUTRAL",
  "confidence": <float 0.0 to 1.0>,
  "materiality": <float 0.0 to 1.0>,
  "novelty_score": <float 0.0 to 1.0>,
  "time_sensitivity": "instant" | "short-term" | "long-term",
  "reasoning": "<one concise sentence>"
}}

Field definitions:
- direction: does this make YES more likely, NO more likely, or is it irrelevant?
- confidence: how certain are you that the direction is correct? (0=uncertain, 1=definitive)
- materiality: how much should this actually move the price? (0=noise, 1=game-changer)
- novelty_score: is this genuinely new information? (0=already known/priced in, 1=completely new)
- time_sensitivity: how quickly will markets react? (instant=seconds, short-term=hours/days, long-term=weeks+)
- reasoning: one concise sentence explaining your assessment
"""


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ClassificationPass:
    direction: str         # "YES", "NO", "NEUTRAL"
    confidence: float
    materiality: float
    novelty_score: float
    time_sensitivity: str
    reasoning: str
    latency_ms: int
    error: bool = False


@dataclass
class Classification:
    """Aggregated result from multi-pass voting."""
    direction: str              # majority vote
    confidence: float           # mean of agreeing passes
    materiality: float          # mean across passes
    novelty_score: float        # mean across passes
    time_sensitivity: str       # most common vote
    reasoning: str              # from highest-confidence pass
    consistency: float          # fraction of passes that agreed on direction
    passes: list[ClassificationPass] = field(default_factory=list)
    total_latency_ms: int = 0
    model: str = ""

    @property
    def is_actionable(self) -> bool:
        """True when all quality gates pass."""
        return (
            self.direction != "NEUTRAL"
            and self.confidence >= config.MIN_CONFIDENCE
            and self.materiality >= config.MATERIALITY_THRESHOLD
            and self.novelty_score >= config.MIN_NOVELTY
            and self.consistency >= config.CONSISTENCY_THRESHOLD
        )

    # Back-compat with V2 callers that used "bullish"/"bearish" terminology
    @property
    def direction_v2(self) -> str:
        mapping = {"YES": "bullish", "NO": "bearish", "NEUTRAL": "neutral"}
        return mapping.get(self.direction, "neutral")


# ── Single pass ────────────────────────────────────────────────────────────────

async def _single_pass(
    client,
    headline: str,
    market: Market,
    source: str,
) -> ClassificationPass:
    start = time.monotonic()
    yes_odds = (1.0 / market.yes_price) if market.yes_price > 0 else 1.0
    prompt = _PROMPT.format(
        question=market.question,
        yes_price=market.yes_price,
        yes_odds=yes_odds,
        headline=headline,
        source=source,
    )
    try:
        async with _groq_semaphore:
            if config.USE_GROQ:
                response = await client.chat.completions.create(
                    model=config.CLASSIFICATION_MODEL,
                    max_tokens=256,
                    temperature=0.15,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.choices[0].message.content.strip()
            else:
                response = await client.messages.create(
                    model=config.CLASSIFICATION_MODEL,
                    max_tokens=256,
                    temperature=0.15,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        latency = int((time.monotonic() - start) * 1000)

        direction = result.get("direction", "NEUTRAL").upper()
        if direction not in ("YES", "NO", "NEUTRAL"):
            direction = "NEUTRAL"

        ts = result.get("time_sensitivity", "short-term")
        if ts not in ("instant", "short-term", "long-term"):
            ts = "short-term"

        return ClassificationPass(
            direction=direction,
            confidence=max(0.0, min(1.0, float(result.get("confidence", 0.5)))),
            materiality=max(0.0, min(1.0, float(result.get("materiality", 0.0)))),
            novelty_score=max(0.0, min(1.0, float(result.get("novelty_score", 0.5)))),
            time_sensitivity=ts,
            reasoning=result.get("reasoning", ""),
            latency_ms=latency,
        )

    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        log.debug(f"[classifier] pass error: {e}")
        return ClassificationPass(
            direction="NEUTRAL",
            confidence=0.0,
            materiality=0.0,
            novelty_score=0.0,
            time_sensitivity="short-term",
            reasoning=f"error: {type(e).__name__}",
            latency_ms=latency,
            error=True,
        )


# ── Multi-pass aggregation ─────────────────────────────────────────────────────

async def classify_async(
    headline: str,
    market: Market,
    source: str = "unknown",
    n_passes: int | None = None,
) -> Classification:
    """
    Run N independent classification passes concurrently, then aggregate.
    Returns a Classification with consistency score and majority direction.
    """
    n = n_passes or config.CLASSIFICATION_PASSES
    client = _get_client()
    wall_start = time.monotonic()

    # Fan out passes concurrently
    tasks = [_single_pass(client, headline, market, source) for _ in range(n)]
    passes = await asyncio.gather(*tasks, return_exceptions=False)

    valid = [p for p in passes if not p.error]
    if not valid:
        return Classification(
            direction="NEUTRAL",
            confidence=0.0,
            materiality=0.0,
            novelty_score=0.0,
            time_sensitivity="short-term",
            reasoning="all classification passes failed",
            consistency=0.0,
            passes=list(passes),
            total_latency_ms=int((time.monotonic() - wall_start) * 1000),
            model=config.CLASSIFICATION_MODEL,
        )

    # Majority vote on direction
    direction_counts = Counter(p.direction for p in valid)
    majority_direction, majority_count = direction_counts.most_common(1)[0]
    consistency = majority_count / len(valid)

    # Aggregate metrics from agreeing passes only (reduces noise from outlier passes)
    agreeing = [p for p in valid if p.direction == majority_direction]
    mean_confidence = sum(p.confidence for p in agreeing) / len(agreeing)
    mean_materiality = sum(p.materiality for p in valid) / len(valid)
    mean_novelty = sum(p.novelty_score for p in valid) / len(valid)

    # Time sensitivity: most common among agreeing passes
    ts_counts = Counter(p.time_sensitivity for p in agreeing)
    best_ts = ts_counts.most_common(1)[0][0]

    # Reasoning: from the highest-confidence agreeing pass
    best_pass = max(agreeing, key=lambda p: p.confidence)
    reasoning = best_pass.reasoning

    total_latency = int((time.monotonic() - wall_start) * 1000)

    result = Classification(
        direction=majority_direction,
        confidence=mean_confidence,
        materiality=mean_materiality,
        novelty_score=mean_novelty,
        time_sensitivity=best_ts,
        reasoning=reasoning,
        consistency=consistency,
        passes=list(passes),
        total_latency_ms=total_latency,
        model=config.CLASSIFICATION_MODEL,
    )

    log.info(
        f"[classifier] {majority_direction} conf={mean_confidence:.2f} "
        f"mat={mean_materiality:.2f} nov={mean_novelty:.2f} "
        f"consistency={consistency:.0%} latency={total_latency}ms"
    )
    return result


def classify(
    headline: str,
    market: Market,
    source: str = "unknown",
) -> Classification:
    """Synchronous wrapper for use in backtest / CLI contexts."""
    return asyncio.get_event_loop().run_until_complete(
        classify_async(headline, market, source)
    )


# ── Self-test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    from markets import Market

    test_market = Market(
        condition_id="test",
        question="Will OpenAI release GPT-5 before August 2026?",
        category="ai",
        yes_price=0.62,
        no_price=0.38,
        volume=450_000,
        end_date="2026-08-01",
        active=True,
        tokens=[],
    )

    async def main():
        result = await classify_async(
            headline="OpenAI announces GPT-5 is in final safety review, release imminent",
            market=test_market,
            source="The Information",
        )
        print(f"Direction:    {result.direction}")
        print(f"Confidence:   {result.confidence:.2f}")
        print(f"Materiality:  {result.materiality:.2f}")
        print(f"Novelty:      {result.novelty_score:.2f}")
        print(f"Time sens:    {result.time_sensitivity}")
        print(f"Consistency:  {result.consistency:.0%}")
        print(f"Actionable:   {result.is_actionable}")
        print(f"Reasoning:    {result.reasoning}")
        print(f"Latency:      {result.total_latency_ms}ms")
        for i, p in enumerate(result.passes):
            print(f"  Pass {i+1}: {p.direction} conf={p.confidence:.2f} {p.latency_ms}ms")

    asyncio.run(main())
