from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field

import config
from ingestion.markets import Market

log = logging.getLogger(__name__)

_client = None

# Concurrency cap: 3 in-flight at once to spread RPM budget across the window.
_groq_semaphore = asyncio.Semaphore(3)

# Token-bucket rate limiter: max 25 calls per 60-second rolling window.
# Groq free tier is 30 RPM; leave 5 RPM headroom for retries.
_GROQ_MAX_RPM = 25
_groq_call_times: collections.deque = collections.deque()
_groq_rate_lock = asyncio.Lock()


async def _wait_for_rate_limit():
    """Block until a Groq call slot is available within the 25 RPM budget."""
    async with _groq_rate_lock:
        now = time.monotonic()
        # Evict timestamps older than 60 seconds
        while _groq_call_times and now - _groq_call_times[0] > 60.0:
            _groq_call_times.popleft()
        if len(_groq_call_times) >= _GROQ_MAX_RPM:
            wait = 60.0 - (now - _groq_call_times[0]) + 0.05
            log.debug(f"[classifier] RPM budget full — waiting {wait:.1f}s")
            await asyncio.sleep(wait)
            # Re-evict after sleep
            now = time.monotonic()
            while _groq_call_times and now - _groq_call_times[0] > 60.0:
                _groq_call_times.popleft()
        _groq_call_times.append(time.monotonic())


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
  "time_sensitivity": "immediate" | "short-term" | "long-term",
  "reasoning": "<one concise sentence>"
}}

Field definitions:
- direction: does this make YES more likely, NO more likely, or is it irrelevant?
- confidence: how certain are you that the direction is correct? (0=uncertain, 1=definitive)
- materiality: how much should this actually move the price? (0=noise, 1=game-changer)
- novelty_score: is this genuinely new information? (0=already known/priced in, 1=completely new)
- time_sensitivity: how quickly will markets react? (immediate=seconds, short-term=hours/days, long-term=weeks+)
- reasoning: one concise sentence explaining your assessment
"""


@dataclass
class ClassificationPass:
    direction: str
    confidence: float
    materiality: float
    novelty_score: float
    time_sensitivity: str
    reasoning: str
    latency_ms: int
    error: bool = False


@dataclass
class Classification:
    direction: str
    confidence: float
    materiality: float
    novelty_score: float
    time_sensitivity: str
    reasoning: str
    consistency: float
    passes: list[ClassificationPass] = field(default_factory=list)
    total_latency_ms: int = 0
    model: str = ""

    @property
    def is_actionable(self) -> bool:
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
        if config.USE_GROQ:
            await _wait_for_rate_limit()
        async with _groq_semaphore:
            if config.USE_GROQ:
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=config.CLASSIFICATION_MODEL,
                        max_tokens=256,
                        temperature=0.15,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=15.0,
                )
                raw = response.choices[0].message.content.strip()
            else:
                response = await asyncio.wait_for(
                    client.messages.create(
                        model=config.CLASSIFICATION_MODEL,
                        max_tokens=256,
                        temperature=0.15,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=15.0,
                )
                raw = response.content[0].text.strip()

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
        if ts not in ("immediate", "short-term", "long-term"):
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

    except asyncio.TimeoutError:
        latency = int((time.monotonic() - start) * 1000)
        log.warning("[classifier] LLM call timed out after 15s — semaphore released")
        return ClassificationPass(
            direction="NEUTRAL", confidence=0.0, materiality=0.0,
            novelty_score=0.0, time_sensitivity="short-term",
            reasoning="timeout", latency_ms=latency, error=True,
        )
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        if "429" in str(e) or "RateLimitError" in type(e).__name__:
            log.warning(f"[classifier] LLM rate limited: {type(e).__name__}")
        else:
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


async def classify_async(
    headline: str,
    market: Market,
    source: str = "unknown",
    n_passes: int | None = None,
) -> Classification:
    n = n_passes or config.CLASSIFICATION_PASSES
    client = _get_client()
    wall_start = time.monotonic()

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

    direction_counts = Counter(p.direction for p in valid)
    majority_direction, majority_count = direction_counts.most_common(1)[0]
    consistency = majority_count / n

    agreeing = [p for p in valid if p.direction == majority_direction]
    mean_confidence = sum(p.confidence for p in agreeing) / len(agreeing)
    mean_materiality = sum(p.materiality for p in agreeing) / len(agreeing)
    mean_novelty = sum(p.novelty_score for p in agreeing) / len(agreeing)

    ts_counts = Counter(p.time_sensitivity for p in agreeing)
    best_ts = ts_counts.most_common(1)[0][0]

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




if __name__ == "__main__":
    import asyncio
    from ingestion.markets import Market

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
