# Complete Logic Reference — Polymarket Quant Trading Engine

Every decision rule, control flow, guard condition, fallback path, state machine,
and design rationale in the system. Module-by-module.

---

## Table of Contents

1. [System Architecture & Boot Sequence](#1-system-architecture--boot-sequence)
2. [Market Discovery & Prioritization](#2-market-discovery--prioritization)
3. [Market Watcher — Microstructure & WebSocket](#3-market-watcher--microstructure--websocket)
4. [News Ingestion — 7-Source Aggregator](#4-news-ingestion--7-source-aggregator)
5. [Event Pre-filtering](#5-event-pre-filtering)
6. [NLP Enrichment Layer](#6-nlp-enrichment-layer)
7. [Semantic Market Matching](#7-semantic-market-matching)
8. [LLM Classification — Multi-Pass Voting](#8-llm-classification--multi-pass-voting)
9. [Edge Model — Price Adjustment & EV](#9-edge-model--price-adjustment--ev)
10. [Alpha Layer — Unified Signal Schema](#10-alpha-layer--unified-signal-schema)
11. [News Alpha](#11-news-alpha)
12. [Momentum Alpha](#12-momentum-alpha)
13. [Ensemble Combiner](#13-ensemble-combiner)
14. [Portfolio Manager — Central Decision Engine](#14-portfolio-manager--central-decision-engine)
15. [Allocator — Dynamic Position Sizing](#15-allocator--dynamic-position-sizing)
16. [Risk Engine](#16-risk-engine)
17. [Risk Manager — Global State Controller](#17-risk-manager--global-state-controller)
18. [Execution Engine](#18-execution-engine)
19. [Smart Router](#19-smart-router)
20. [Slippage Model](#20-slippage-model)
21. [Paper Portfolio — Trade Simulation](#21-paper-portfolio--trade-simulation)
22. [Executor — Live Order Placement](#22-executor--live-order-placement)
23. [Trading Mode Controller](#23-trading-mode-controller)
24. [Safety Guard](#24-safety-guard)
25. [API Layer](#25-api-layer)
26. [WebSocket Broadcaster](#26-websocket-broadcaster)
27. [Calibration System](#27-calibration-system)
28. [Complete Signal Lifecycle — Step-by-Step](#28-complete-signal-lifecycle--step-by-step)
29. [All Guard Conditions (Master Reference)](#29-all-guard-conditions-master-reference)
30. [All Singleton Patterns](#30-all-singleton-patterns)
31. [Concurrency Model](#31-concurrency-model)

---

## 1. System Architecture & Boot Sequence

### Boot Order

When `python api.py` is run:

```
1. FastAPI app created, lifespan context registered
2. lifespan START:
     a. Pipeline() instantiated:
          - MarketWatcher() created
          - asyncio.Queue created for news events
          - RiskManager.instance() retrieved (creates singleton)
          - MetricsTracker created
          - MomentumAlpha() instantiated
          - NewsAlpha() instantiated
     b. asyncio.create_task(pipeline.run()) — non-blocking
3. Uvicorn begins serving HTTP requests
4. pipeline.run() executes:
     a. watcher.refresh_markets() — fetch markets from Polymarket + Kalshi
     b. update_market_embeddings() — embed all market questions
     c. NewsAggregator(queue) instantiated
     d. asyncio.gather(
          watcher.run(),           — WebSocket + periodic refresh
          news_aggregator.run(),   — 7 news sources concurrently
          _consume_news_queue(),   — processes incoming events
          momentum_alpha.run(),    — polls CoinGecko every 60s
        )
5. lifespan END (on shutdown):
     Nothing — pipeline tasks are cancelled by asyncio cleanup
```

### Process Topology

```
┌──────────────────────────────────────────────────────────────────┐
│ Single Python process, single thread, asyncio event loop         │
│                                                                  │
│  [news_sources × 7]   [CoinGecko]   [MarketWatcher WebSocket]   │
│        │                   │                    │                │
│        ▼                   ▼                    ▼                │
│  asyncio.Queue      MomentumAlpha         price_ticks            │
│        │            _signal_buffer         snapshots             │
│        ▼                                                         │
│  _consume_news_queue()                                           │
│        │                                                         │
│        ▼ (asyncio.create_task per event)                         │
│  _handle_event()                                                 │
│        │                                                         │
│        ▼ (asyncio.gather per market match)                       │
│  _process_market()  ──→  LLM classify ──→  alpha ──→  execute   │
└──────────────────────────────────────────────────────────────────┘
```

**Key design:** every event is processed as an independent asyncio task.
Multiple events can be in-flight simultaneously. No global event lock.

---

## 2. Market Discovery & Prioritization

### Source 1: Polymarket (Gamma API)

- Fetches up to 50 active, non-closed markets ordered by volume descending
- Parses `outcomePrices` (JSON string) for YES/NO prices
- Falls back to CLOB API if Gamma API fails

### Source 2: Kalshi

- Fetches up to 200 open Kalshi markets
- Merged into the same `tracked_markets` list as Polymarket markets
- Tagged with `source="kalshi"` on the Market object

### Short-Duration Prioritization

After merging both sources, markets are ranked by time-to-resolution:

```
priority_markets = [m for m in all_markets if days_to_end(m) ≤ 30]
remaining        = [m for m in all_markets if days_to_end(m) > 30]
tracked_markets  = priority_markets + remaining[:fill_to_limit]
```

**Why:** Short-duration markets have higher price sensitivity to news — a market
ending in 3 days reacts much more sharply to new information than one ending in a year.
This amplifies our edge per trade.

### Niche Market Filter

The system filters to "niche" markets, deliberately avoiding ultra-liquid markets
dominated by professional traders and algo desks:

```
- Minimum volume threshold applied (low-volume markets filtered out)
- Category filter: only SELECTED_CATEGORIES from config
- Result: 18–25 tracked markets at any given time
```

**Rationale:** Liquid mainstream markets (e.g. "Will X win the election?") are
efficiently priced and offer minimal edge. Niche markets in specific categories
have wider spreads and slower price discovery, creating opportunities.

### Embedding Update

After market list is built, all market questions are batch-embedded:

```
update_market_embeddings(tracked_markets)
```

Only new markets (not in cache) are re-embedded. Stale markets are pruned.

---

## 3. Market Watcher — Microstructure & WebSocket

### Responsibilities

1. **Price feed** — WebSocket connection to Polymarket CLOB for real-time YES prices
2. **Order book** — REST fetch of bid/ask depth for each market before a trade
3. **Momentum detection** — flag markets that are already moving
4. **Snapshot cache** — latest microstructure data per market

### WebSocket Logic

```
Connect to wss://ws-subscriptions-clob.polymarket.com/ws/market

On CONNECT:
  Send subscribe message for all tracked_market condition_ids

On MESSAGE:
  Parse price_change events
  Update _snapshots[condition_id].price_ticks deque (maxlen=30)
  Update _snapshots[condition_id].yes_price

On DISCONNECT:
  Log warning, attempt reconnect on next watcher.run() cycle
```

### Momentum Gate (is_moving)

A market is flagged as "already moving" if its recent price ticks show rapid movement:

```python
is_moving = abs(latest_price - price_N_ticks_ago) / price_N_ticks_ago > MOMENTUM_THRESHOLD
```

If `is_moving = True`, the pipeline skips that market entirely:

```python
if snap and snap.is_moving:
    log.info("Market already moving, skipping")
    return
```

**Why:** If the market is already repricing rapidly, our edge is likely already
being arbed away. We'd be buying into a moving market, increasing slippage and
reducing expected alpha. It's better to wait for the market to stabilize.

### Order Book Fetch

Before each trade, the system fetches the current CLOB order book:

```
GET /book?token_id={yes_token_id}

Parse response:
  bids → sorted descending by price, take top 3 levels
  asks → sorted ascending by price, take top 3 levels
  bid_depth_usd = sum(price × size for top-3 bids)
  ask_depth_usd = sum(price × size for top-3 asks)
  spread = best_ask - best_bid
  mid = (best_bid + best_ask) / 2
  liquidity_score = computed from depth and spread
```

### Liquidity Score Calculation

```python
depth_score = min(1.0, total_depth_usd / LIQUIDITY_DEPTH_THRESHOLD)
spread_score = max(0.0, 1.0 - spread / 0.20)   # 0% spread → 1.0, 20% spread → 0.0
liquidity_score = 0.6 * depth_score + 0.4 * spread_score
```

This produces a [0, 1] score where:
- 1.0 = deep book, tight spread (very liquid)
- 0.0 = empty book or very wide spread (illiquid)

### Market Refresh Cycle

```
Every 60 seconds:
  watcher.refresh_markets()
  → re-fetch Polymarket markets
  → re-fetch Kalshi markets
  → merge and re-prioritize
  → update_market_embeddings() for any new markets
  → re-subscribe WebSocket for new market IDs
```

---

## 4. News Ingestion — 7-Source Aggregator

All 7 sources run as concurrent asyncio tasks. Each pushes `NewsEvent` objects
into the shared `asyncio.Queue`. The pipeline consumer picks them up independently.

### Source 1: Twitter/X API v2 Filtered Stream

```
Logic:
  Setup rules: keywords → OR-grouped filter rules (max 5 per rule)
  Connect to streaming endpoint
  On tweet arrival: emit NewsEvent(source="twitter")

Failure mode:
  429 Too Many Requests → "requires Basic tier ($100/mo)" — logs warning, falls back to RSS only
  Any other error → exponential backoff, retry
```

### Source 2: Telegram Channel Monitor

```
Logic:
  Polls configured channel list every N seconds
  Parses message text, deduplicates by message_id
  Emits NewsEvent(source="telegram")

Disabled if:
  No bot token or channel list in config → skips entirely
```

### Source 3: RSS Feed Aggregator

```
Logic:
  Polls list of RSS feed URLs every 30s
  Parses <item> elements: title, link, pubDate
  Deduplicates by URL hash
  Emits NewsEvent(source="rss")

Sources include:
  Reuters, Bloomberg, FT, BBC, AP, Guardian, and domain-specific feeds
```

### Source 4: NewsAPI

```
Logic:
  Polls /v2/everything every 30s
  Query: top headlines in selected categories
  On 429 rate limit: slows down poll interval
  Emits NewsEvent(source="newsapi")
```

### Source 5: Reddit

```
Logic:
  Adaptive weighted sampling across subreddits
  Weights adjust based on historical signal quality per subreddit
  Polls /r/{sub}/new.json
  Emits NewsEvent(source="reddit")
```

### Source 6: GNews

```
Logic:
  Polls every 15 minutes (free tier: 100 req/day limit)
  Fetches top headlines across configured topics
  Emits NewsEvent(source="gnews")
```

### Source 7: GDELT

```
Logic:
  Polls 8 queries every 5 minutes (free, no API key required)
  Queries: GKG (Global Knowledge Graph) for event-driven news
  Emits NewsEvent(source="gdelt")
```

### Deduplication

News events are deduplicated at the queue consumer level using a short-lived
set of recent headlines (fingerprint = first 80 chars lowercased). Duplicates
from different sources covering the same story are dropped.

---

## 5. Event Pre-filtering

Before NLP or LLM work is done, an event must pass these fast checks in order:

### Check 1: Daily Loss Cap

```python
if not risk.can_trade_daily():
    skip event entirely
```

If we've already lost ≥$100 today, no new events are processed. The check is
cached for 30 seconds to avoid database queries on every event.

### Check 2: Cooldown

```python
if risk.in_cooldown():
    skip event
```

If we've had ≥3 consecutive losses, we're in a 30-minute cooldown. All events
are dropped during this window.

### Check 3: Category Filter

```python
if not is_relevant_event(event, config.SELECTED_CATEGORIES):
    skip event
```

Events that don't match any configured category (politics, macro, tech, conflict,
crypto) are dropped before any compute work.

### Check 4: NLP Impact Gate

```python
if config.NLP_ENABLED:
    nlp = nlp_processor.process(headline, source, age_seconds)
    if nlp.relevance < config.NLP_MIN_IMPACT:
        skip event
```

The NLP pipeline (NER + sentiment + impact scoring + temporal decay) runs fast
(CPU-only). Events with low relevance scores (stale, low-impact, noise) are
filtered here before spawning LLM API calls.

**This is the most important cost-reduction step.** Most RSS headlines are
noise. The NLP gate drops them cheaply before any expensive LLM work.

---

## 6. NLP Enrichment Layer

For events that pass the category filter, the NLP pipeline runs synchronously
(no I/O, pure CPU):

### Named Entity Recognition (NER)

```
Backend: spaCy en_core_web_sm
Process:
  1. Run spaCy pipeline on headline text
  2. Extract named entities: PERSON, ORG, GPE, LAW, EVENT, MONEY, etc.
  3. Deduplicate by (text, label) pair
  4. Assign importance weight by label type
  5. entity_importance = max(importance) across all entities

Graceful degradation:
  If spaCy not installed → entity_importance = 0.0, NER disabled
```

### Sentiment Analysis (VADER)

```
Backend: vaderSentiment (rule-based, no model download)
Process:
  1. Run VADER on headline text
  2. Returns: neg, neu, pos, compound ∈ [-1, +1]
  3. polarity = compound
  4. sentiment_confidence = |compound|  (distance from neutral)

Graceful degradation:
  If VADER not installed → polarity = 0.0, confidence = 0.0
```

### Category Tagging

```
Process:
  1. Lowercase headline + entity texts
  2. For each category (politics, macro, tech, conflict, crypto):
     count keyword matches in headline and entity texts
  3. Category = argmax(keyword_count)
  4. If no matches: category = "other"

Example:
  "Fed raises rates 25bps" → matches: rate hike, fed, interest rate → category = "macro"
```

### Velocity Score

Set externally by a separate velocity tracker (not detailed here) that counts
how many times the same story has been seen across sources in the last 10 minutes.
High velocity = story spreading fast = higher impact.

### Impact Score

```
Impact = 0.20·R(source) + 0.20·|polarity|·sentiment_confidence
       + 0.20·entity_importance + 0.25·novelty_score + 0.15·velocity_score
```

### Temporal Decay → Relevance

```
Relevance = Impact · exp(−0.05 · age_minutes)
```

Events older than ~14 minutes have their relevance halved. Events older than ~28
minutes are quarter relevance, and so on.

---

## 7. Semantic Market Matching

For each event that passes NLP gating, we find matching prediction markets.

### Embedding-Based Matching (Primary)

```
1. Embed the headline: query_vec = embed_fn([headline])[0]  → shape (384,)
2. Retrieve all cached market vectors: matrix → shape (N, 384)
3. Cosine similarity: scores = matrix @ query_vec  → shape (N,)
   (works because vectors are pre-normalized → dot product = cosine similarity)
4. Sort descending by score
5. Return top-k matches above threshold:
     k = config.MATCHER_TOP_K (typically 3–5)
     threshold = config.MATCHER_MIN_SIMILARITY (typically 0.35–0.45)
```

**Model:** `all-MiniLM-L6-v2` (22M parameters, 384-dim embeddings, ~15ms per encode)

**Pre-normalization:** Market embeddings are L2-normalized at cache build time.
Query vector is also normalized. This makes the dot product exactly equal to
cosine similarity without division at query time.

### Keyword Fallback (Secondary)

If sentence-transformers is not installed:

```
1. Extract keywords from market.question (remove stopwords, keep >2 char words)
2. Count keyword hits in headline (lowercased)
3. Score = hits / total_keywords
4. Return top-k markets with score > 0
```

Much weaker signal but zero dependencies.

### Match Result

Each match returns `MarketMatch(market, similarity, match_method)`.
The similarity score is not used downstream (binary: match or no match).
Only markets above the threshold proceed.

---

## 8. LLM Classification — Multi-Pass Voting

For each `(event, market)` pair that matches, the LLM classifier runs.

### Per-Market Cooldown Check (First)

```python
last = _last_signal_time.get(market.condition_id, 0.0)
if time.monotonic() - last < 600:   # 10-minute cooldown
    skip this market
```

This fires **before** the LLM call — saves API cost.

### Prompt Construction

The prompt includes:
- Market question (exact text)
- Current YES price as percentage + implied odds (1/p)
- Breaking headline
- Source name
- Schema with field definitions

**Temperature = 0.15** — near-deterministic but allows slight variation between
passes. Lower temperature means passes tend to agree more, making the consistency
score more discriminating.

### N=3 Concurrent Passes

```python
tasks = [_single_pass(client, headline, market, source) for _ in range(3)]
passes = await asyncio.gather(*tasks)
```

All 3 pass to the LLM API simultaneously. Wall time = max(pass_latency) ≈ 1–2s.

**Why 3 passes?** 1 pass has no consistency information. 2 passes can only be
50% consistent. 3 passes allow:
- 3/3 agree → consistency = 1.00 (very stable)
- 2/3 agree → consistency = 0.67 (acceptable)
- 1/3 agree → consistency = 0.33 (below threshold, rejected)

### API Rate Limiting

```python
_groq_semaphore = asyncio.Semaphore(9)
```

Maximum 9 concurrent API calls. With 3 passes per market × up to 3 markets per
event = 9 potential in-flight calls. Within Groq free tier (30 RPM).

### Aggregation Logic

```
Step 1: Filter valid passes (no errors)
Step 2: Majority vote on direction
         direction_counts = Counter([p.direction for p in valid])
         majority_direction = most_common()[0]
         consistency = majority_count / len(valid)

Step 3: Only agreeing passes contribute to confidence
         agreeing = [p for p in valid if p.direction == majority_direction]
         mean_confidence = mean([p.confidence for p in agreeing])

Step 4: All passes (including disagreeing) contribute to materiality and novelty
         mean_materiality = mean([p.materiality for p in valid])
         mean_novelty     = mean([p.novelty_score for p in valid])

Step 5: Time sensitivity = most common among agreeing passes
Step 6: Reasoning = from the highest-confidence agreeing pass
```

**Why disagreeing passes contribute to materiality/novelty?**
If 2 passes say YES with high materiality and 1 says NO with low materiality,
the materiality score should still reflect the 2-pass signal. Disagreement on
direction doesn't mean the event is low-impact.

### Actionability Check

A `Classification` is actionable only if ALL of:

```python
direction != "NEUTRAL"
confidence >= 0.55           (MIN_CONFIDENCE)
materiality >= MATERIALITY_THRESHOLD
novelty_score >= 0.20        (MIN_NOVELTY)
consistency >= CONSISTENCY_THRESHOLD
```

If any condition fails, `is_actionable = False` → pipeline returns early,
no order book fetch, no trade.

---

## 9. Edge Model — Price Adjustment & EV

### Flow After Actionable Classification

```
1. compute_edge(market, classification, liquidity_score, spread, estimated_slippage)
2. Returns Signal or None
```

### Order Book Fetch (Before Edge Compute)

```python
ob = await watcher.fetch_order_book(market)
snap = watcher.get_snapshot(market.condition_id)

if snap and snap.is_moving:
    skip  # market already repricing, our edge is stale

spread = ob.spread if ob.spread > 0.001 else (snap.spread if snap else 0.05)
```

**Why use 0.05 as default spread?** 5% is a conservative default that avoids
overestimating edge when the order book fetch fails. It's wide enough to be safe.

### Minimum Depth Guard

```python
if ob.bid_depth_usd < MIN_ORDERBOOK_DEPTH_USD and ob.bid_depth_usd > 0:
    skip  # too thin to absorb our order
```

Only fires if depth > 0 (prevents false rejection when CLOB returns empty book
for valid thin markets — we prefer to let the slippage model handle those).

### Slippage Estimation

```python
slippage = snap.estimated_slippage(direction, 25.0) if snap else 0.0
```

Estimated using the order book snapshot before the trade size is finalized.
Uses $25 as the reference order size (max bet).

### Trade Acceptance Gates in compute_edge

In order of application:

```
1. direction == NEUTRAL → None
2. not classification.is_actionable → None
3. After adjustment: EV_net < 0.03 → None
4. liquidity_score < 0.20 → None
5. spread > 0.08 → None
```

All gates must pass. First failure returns None immediately (short-circuit).

---

## 10. Alpha Layer — Unified Signal Schema

### AlphaSignal Fields

```python
market_id:        str        # condition_id
market_question:  str        # human-readable question text
direction:        str        # "YES" or "NO" — validated
confidence:       float      # [0, 1] — validated
expected_edge:    float      # EV estimate
horizon:          str        # "5m", "1h", "1d" — validated
strategy:         str        # "news" or "momentum" — validated
timestamp:        float      # time.time() at creation
market:           Market     # original market object (optional)
raw_signal:       Signal     # original edge_model.Signal (news only, optional)
```

### Validation Rules (AlphaSignal.__post_init__)

```python
if direction not in ("YES", "NO"):
    raise ValueError(...)
if not 0.0 <= confidence <= 1.0:
    raise ValueError(...)
if horizon not in ("5m", "1h", "1d"):
    raise ValueError(...)
if strategy not in ("news", "momentum"):
    raise ValueError(...)
if not market_id:
    raise ValueError(...)
```

Any invalid signal raises immediately. No silent failures.

### AggregatedSignal Fields

```python
market_id:        str
market_question:  str
direction:        str        # "YES" or "NO"
confidence:       float      # weighted aggregate [0, 1]
expected_edge:    float      # weighted aggregate
size_multiplier:  float      # 0.4, 0.6, or 1.0
strategies:       list[str]  # e.g. ["news", "momentum"]
signals:          list[AlphaSignal]   # source signals
market:           Market
```

### size_multiplier Semantics

```
1.0 → all strategies agree AND more than one strategy present
      → system has high confidence → full position
0.6 → single strategy only
      → no corroboration → reduced position (40% smaller)
0.4 → strategies conflict (one says YES, another says NO)
      → still trade the majority direction but very cautiously
```

---

## 11. News Alpha

### Logic of to_alpha_signal(signal)

```python
def to_alpha_signal(signal) -> AlphaSignal | None:

    if signal is None:
        return None

    try:
        cls = signal.classification

        # Map time_sensitivity to horizon code
        horizon = _HORIZON_MAP.get(
            getattr(cls, "time_sensitivity", "short-term"), "1h"
        )
        # "immediate" → "5m", "short-term" → "1h", "long-term" → "1d"

        return AlphaSignal(
            market_id      = signal.market.condition_id,
            market_question = signal.market.question,
            direction      = signal.side,        # "YES" or "NO"
            confidence     = cls.confidence,     # from LLM multi-pass
            expected_edge  = signal.ev,          # EV_net from edge model
            horizon        = horizon,
            strategy       = "news",
            market         = signal.market,
            raw_signal     = signal,
        )

    except (ValueError, AttributeError) as e:
        log.warning(f"[news_alpha] Failed to convert signal: {e}")
        return None
```

**Fallback:** If any field is missing or AlphaSignal validation fails, returns
None. The pipeline then broadcasts the signal with `status="filtered"` so it
still appears in the signal feed, but no trade is placed.

---

## 12. Momentum Alpha

### State

```python
_price_history:  deque(maxlen=10)    # (timestamp, price_usd) pairs
_signal_buffer:  dict[str, AlphaSignal]  # market_id → latest signal
_signal_ttl:     180.0               # seconds before signal expires
```

### Background Task Logic (run())

Runs forever with 60-second sleep between cycles:

```
LOOP every 60 seconds:
  1. _fetch_btc_price()
       → GET CoinGecko /simple/price?ids=bitcoin&vs_currencies=usd
       → Parse response["bitcoin"]["usd"]
       → Return float or None on error

  2. if price is not None:
       append (time.time(), price) to _price_history

  3. momentum = _compute_momentum()
       → Need ≥3 data points (guard)
       → Find newest price at-or-before 5-minute cutoff (reference price)
       → momentum = (current_price - reference_price) / reference_price
       → Return None if no reference found

  4. if momentum is not None:
       _update_buffer(watcher, momentum)
```

### _compute_momentum() — Reference Price Search

```python
cutoff = now - 300  # 5 minutes ago

old_price = None
for ts, price in self._price_history:   # oldest → newest
    if ts <= cutoff:
        old_price = price   # keep updating: want NEWEST price BEFORE the cutoff
    else:
        break               # stop: we've passed into the recent window

if old_price is None:
    return None   # no data old enough to compare against

momentum = (current_price - old_price) / old_price
```

**Why oldest-to-newest with continuous update?**
The deque stores (oldest, ..., newest). Iterating forward while updating `old_price`
whenever `ts ≤ cutoff` ensures we get the most recent price that is still ≥5 minutes
old. This is the correct 5-minute return anchor.

### _update_buffer() — Signal Generation Per Market

```
if |momentum| < 0.02:
    _signal_buffer.clear()  # clear stale signals when momentum subsides
    return

direction = "YES" if momentum > 0 else "NO"

btc_markets = [m for m in watcher.tracked_markets
               if "bitcoin" or "btc" in m.question.lower()]

for market in btc_markets:
    sig = to_alpha_signal(market, direction, momentum)
    if sig:
        _signal_buffer[market.condition_id] = sig
```

**Why only BTC markets?**
The momentum signal is specifically from BTC price movement. Only markets whose
questions reference Bitcoin/BTC are plausibly correlated. Applying BTC momentum
to unrelated markets would be noise.

### get_signal() — TTL-Checked Retrieval

```python
sig = _signal_buffer.get(market_id)
if sig is None:
    return None
if time.time() - sig.timestamp > 180:
    del _signal_buffer[market_id]
    return None
return sig
```

Signals expire after 3 minutes. A stale momentum signal (from a price move
that happened 4 minutes ago) is no longer actionable — momentum at that
timescale is typically mean-reverting.

---

## 13. Ensemble Combiner

### Input

A non-empty list of `AlphaSignal` objects for the **same market** from different strategies.

### Step-by-Step Logic

**Step 1: Validate**
```python
if not signals:
    raise ValueError("combine() requires at least one signal")
```

**Step 2: Deduplication — keep best per strategy**
```python
by_strategy = {}
for sig in signals:
    existing = by_strategy.get(sig.strategy)
    if existing is None or sig.confidence > existing.confidence:
        by_strategy[sig.strategy] = sig
deduped = list(by_strategy.values())
```

If somehow two news signals arrive for the same market (shouldn't happen, but
handled), keep only the more confident one per strategy.

**Step 3: Weighted directional vote**
```python
yes_score = Σ w(s)·confidence(s)   for all s where direction == "YES"
no_score  = Σ w(s)·confidence(s)   for all s where direction == "NO"
```

**Step 4: Direction with tie-break**
```python
if yes_score > no_score:   direction = "YES"
elif no_score > yes_score: direction = "NO"
else:                      direction = max(deduped, key=λ s: s.confidence).direction
```

The tie-break falls to the single most confident signal's direction, not an
arbitrary default. This prevents the tie-break from always producing YES.

**Step 5: Winning-direction signal aggregation**
```python
winning_sigs = [s for s in deduped if s.direction == direction]
if not winning_sigs:
    winning_sigs = deduped  # fallback: shouldn't happen, but safe
w_conf = weighted_avg(winning_sigs, "confidence")
w_edge = weighted_avg(winning_sigs, "expected_edge")
```

Only signals that agree with the final direction contribute to the aggregated
confidence and edge estimates.

**Step 6: Size multiplier**
```python
if len(deduped) == 1:
    multiplier = 0.6      # single strategy: no corroboration
elif len({s.direction for s in deduped}) > 1:
    multiplier = 0.4      # conflict: hedge position
else:
    multiplier = 1.0      # all agree: full conviction
```

---

## 14. Portfolio Manager — Central Decision Engine

### Singleton Pattern

```python
_singleton = None
_lock = Lock()

@classmethod
def instance(cls):
    with cls._lock:
        if cls._singleton is None:
            cls._singleton = cls()
    return cls._singleton
```

Thread-safe lazy initialization. All calls throughout the system use
`PortfolioManager.instance()`.

### process_signal_async()

Runs the synchronous `process_signal()` in a thread pool executor:

```python
return await asyncio.get_running_loop().run_in_executor(
    None, self.process_signal, signal
)
```

**Why executor?** `process_signal` is pure CPU (no I/O) but may take non-trivial
time. Running in an executor prevents it from blocking the event loop during
the computation.

### process_signal() — Decision Pipeline

```
1. Get current drawdown from paper portfolio
2. Compute position size: size_usd = allocator.compute_size(signal, drawdown)
3. Risk validation: decision = risk_engine.validate(signal, size_usd)
   → If rejected: log, audit-log, return rejected_result
4. Build order: {"signal": signal, "size_usd": size_usd}
5. Execute: result = ExecutionEngine.instance().execute(order)
6. Audit-log the decision
7. Return result
```

### Decision Audit Log

Every decision (approve or reject) is stored in memory:

```python
self._decisions.append({
    "market_id":  signal.market_id,
    "direction":  signal.direction,
    "strategies": signal.strategies,
    "size_usd":   size_usd,
    "status":     status,     # "paper", "rejected", reason string
    "elapsed_ms": elapsed_ms,
    "timestamp":  time.time(),
})
```

Capped at 500 entries (rolling window). Accessible via `get_recent_decisions()`.

### Rejected Result

When risk engine rejects:

```python
ExecutionResult(
    trade_id=None,
    status=reason,    # e.g. "risk_rejected", "daily_loss_limit"
    filled_size=0.0,
    fill_price=0.0,
    slippage=0.0,
    latency_ms=0,
)
```

The status string carries the rejection reason, visible in the signal feed.

---

## 15. Allocator — Dynamic Position Sizing

### compute_size() Decision Tree

```
INPUT: AggregatedSignal, current_drawdown (float)

1. base = SIZING_K × edge × confidence × BANKROLL
        = 0.25 × signal.expected_edge × signal.confidence × 1000

2. sized = base × signal.size_multiplier
         = base × {0.4 | 0.6 | 1.0}

3. drawdown_scalar = max(0.0, 1.0 - drawdown × 2.0)
   Examples:
     drawdown=0.00 → scalar=1.00  (full size)
     drawdown=0.10 → scalar=0.80  (20% reduction)
     drawdown=0.25 → scalar=0.50  (half size)
     drawdown=0.50 → scalar=0.00  (but floor applies)

4. dd_scaled = sized × drawdown_scalar

5. final = max(1.0, min(MAX_BET_USD, dd_scaled))
         = clamp to [$1, $25]

OUTPUT: final (float, 2 decimal places)
```

### Minimum $1 Floor

`max(1.0, ...)` ensures we always place at least a $1 trade even during severe
drawdown. This keeps the system "in the market" — useful for calibration data
collection even when not profitable.

---

## 16. Risk Engine

### validate(signal, size_usd) — Wrapper Around RiskManager

```python
def validate(signal, size_usd) -> RiskDecision:

    rm = RiskManager.instance()

    if not rm.can_trade_daily():
        return RiskDecision(approved=False, reason="daily_loss_limit")

    if not rm.can_open_position():
        return RiskDecision(approved=False, reason="max_positions_reached")

    if not rm.can_trade_category(signal.market.category, size_usd):
        return RiskDecision(approved=False, reason="category_exposure_limit")

    if rm.in_cooldown():
        return RiskDecision(approved=False, reason="consecutive_loss_cooldown")

    return RiskDecision(approved=True, reason="ok")
```

Checks are evaluated in priority order. The most restrictive (daily loss) is
checked first so we don't waste time on position counting if we're already at
the daily cap.

---

## 17. Risk Manager — Global State Controller

### State

```python
_open_positions:     dict[str, float]      # condition_id → bet_amount_usd
_category_exposure:  defaultdict(float)    # category → total_usd_open
_consecutive_losses: int
_cooldown_until:     float                 # monotonic timestamp
_daily_pnl_cache:    float                 # cached from SQLite
```

### can_trade_daily()

```
Check: |min(0, daily_PnL)| < DAILY_LOSS_LIMIT_USD ($100)

Daily PnL is fetched from SQLite (logger.get_daily_pnl()).
Result is cached for 30 seconds to avoid hitting the DB on every event.
```

### can_open_position()

```
Check: len(_open_positions) < MAX_CONCURRENT_POSITIONS (5)
```

### can_trade_category()

```
Check: _category_exposure[cat] + new_bet ≤ MAX_EXPOSURE_PER_CATEGORY_USD ($60)
```

### in_cooldown()

```
Check: time.monotonic() < _cooldown_until
```

Monotonic clock is used (not wall clock) to avoid issues with system clock changes.

### on_trade_opened()

```python
with _state_lock:
    _open_positions[condition_id] = amount_usd
    _category_exposure[category] += amount_usd
```

Called from `pipeline._process_market()` after a successful execution.

### on_trade_closed()

```python
with _state_lock:
    amount = _open_positions.pop(condition_id, 0.0)
    _category_exposure[category] = max(0.0, _category_exposure[category] - amount)

    if pnl < 0:
        _consecutive_losses += 1
        if _consecutive_losses >= CONSECUTIVE_LOSS_COOLDOWN (3):
            _cooldown_until = now + COOLDOWN_MINUTES × 60 (30 min)
    else:
        _consecutive_losses = 0   # reset on any win
```

**Thread safety:** Both open and close operations are wrapped in `_state_lock`
(threading.Lock). Multiple asyncio tasks can call these concurrently via the
thread pool executor.

---

## 18. Execution Engine

### Singleton Pattern

Same pattern as PortfolioManager: class-level `_singleton` + `_lock`.

### execute(order) Logic

```
INPUT: order = {"signal": AggregatedSignal, "size_usd": float}

1. Extract signal and size_usd from order
2. Get microstructure defaults:
   spread   = 0.04  (4% default — conservative)
   momentum = 0.0   (no momentum data available without MarketWatcher ref)

3. routing = smart_router.get_routing_strategy(spread, momentum)
   → "aggressive", "passive", or "reject"

4. if routing == "reject":
   return ExecutionResult(status="rejected_spread")

5. slippage = slippage_model.estimate(size_usd, book_depth=500, spread)
   (book_depth defaults to $500 — conservative assumption)

6. exec_signal = _build_signal(signal, size_usd)

7. if config.DRY_RUN:
   result = paper_portfolio.simulate_trade(exec_signal)
else:
   result = execute_trade_async(exec_signal)  # live order

8. return result
```

### _build_signal() — Copy Before Mutate

```python
raw = copy.copy(alpha_sig.raw_signal)   # SHALLOW copy of Signal object
raw.bet_amount = size_usd               # mutate the copy, not the original
return raw
```

**Critical:** The original `raw_signal` must not be mutated. If the same signal
is processed multiple times (e.g. in retry scenarios), the original bet_amount
must remain intact. `copy.copy()` creates a new Signal object with the same
field values.

### Yes Price Safety

```python
entry_price = getattr(market, 'yes_price', 0.5)
```

Uses `getattr` with fallback 0.5 to prevent AttributeError if the market
object doesn't have `yes_price` set (e.g. Kalshi markets with different schema).

---

## 19. Smart Router

### Decision Tree

```
IF spread > 0.08 (8%):
    → "reject"
    Reason: cost to execute exceeds any realistic edge

ELIF |momentum| > 0.03 (3%):
    → "aggressive"
    Reason: race condition — fast-moving market, must act immediately
            or miss the opportunity entirely

ELIF spread < 0.02 (2%):
    → "aggressive"
    Reason: tight spread means crossing the book is cheap

ELSE (spread 2–8%, no momentum urgency):
    → "passive"
    Reason: post limit orders to improve on the mid price
```

### Aggressive vs Passive Execution

- **Aggressive:** marketable limit order — crosses the spread, immediate fill
- **Passive:** limit order posted at/near best bid or ask — waits for counterparty

**Effect on P&L:**
- Aggressive costs ~0.5× spread per trade (pay the spread)
- Passive may earn ~0.5× spread but risks non-fill and missing the signal window

---

## 20. Slippage Model

### Logic

```python
if book_depth_usd <= 0:
    return 0.0   # unknown depth: assume no slippage (optimistic but safe)

impact = (order_size / book_depth_usd) × spread
result = clamp(impact, 0.0, 0.20)
```

### Why 0.0 for Unknown Depth?

If the order book fetch failed or returned empty, we don't know the depth.
Returning 0.0 (not rejecting) allows the trade to proceed if EV is high enough.
The EV_net threshold (≥3%) provides a safety buffer against unknown slippage.

### 20% Cap

No matter how thin the market, we never estimate slippage above 20%. This
prevents a very thin market with $10 of depth from producing a 500% slippage
estimate that looks unrealistic. The spread gate (>8%) typically rejects
truly thin markets before slippage is even computed.

---

## 21. Paper Portfolio — Trade Simulation

### Duplicate Position Guard

```python
if market_id in self.positions and self.positions[market_id].status == "open":
    return ExecutionResult(status="rejected_duplicate_position", filled_size=0.0)
```

We cannot open two positions in the same market simultaneously. If a second
signal arrives for a market we already have a position in, it's rejected.

**Why:** In a binary market, adding to an open position doesn't change the
fundamental exposure — we either have a YES position or we don't. Doubling
a position doubles risk without doubling edge (the edge is set at entry time).

### Contract Calculation

```python
if side == "YES":
    contracts = bet_usd / entry_price        # e.g. $10 / 0.40 = 25 YES contracts
else:
    no_price = 1.0 - entry_price
    contracts = bet_usd / no_price           # e.g. $10 / 0.60 = 16.67 NO contracts
```

Each YES contract pays $1 if the market resolves YES. Buying 25 YES contracts
at $0.40 = $10 cost, $25 payout if YES, $0 if NO.

### Mark-to-Market (Unrealized P&L)

```python
def mark_to_market(market_id, current_price):
    pos = positions[market_id]
    if pos.side == "YES":
        unrealized_pnl = contracts × (current_price - entry_price)
    else:
        unrealized_pnl = contracts × ((1 - current_price) - (1 - entry_price))
                       = contracts × (entry_price - current_price)
```

### Max Drawdown Tracking

```python
total_value = balance + unrealized_pnl + realized_pnl

self._peak_value = max(self._peak_value, total_value)
drawdown = (self._peak_value - total_value) / self._peak_value
max_drawdown = max(max_drawdown_ever, drawdown)
```

---

## 22. Executor — Live Order Placement

### DRY_RUN vs LIVE Decision

```python
if config.DRY_RUN:
    result = get_portfolio().simulate_trade(signal)
else:
    result = await _live_execute(signal)   # calls Polymarket/Kalshi CLOB API
```

`config.DRY_RUN` is a runtime-mutable flag (changed by TradingMode.set_mode()).

### ExecutionResult.success Property

```python
@property
def success(self) -> bool:
    return self.status in ("executed", "dry_run", "paper")
```

Three successful statuses:
- `"executed"` — live order filled
- `"dry_run"` — legacy dry-run mode (pre-paper-portfolio)
- `"paper"` — paper portfolio simulation (post-portfolio-manager)

**Why include "paper"?**
The `pipeline._process_market()` calls `risk.on_trade_opened()` only when
`result.success = True`. Without "paper" in the tuple, the risk manager would
never see paper trades, so category exposure and position counts wouldn't update
properly. This was a bug found in the final code review and fixed.

---

## 23. Trading Mode Controller

### Singleton Pattern

Same as PortfolioManager. Class-level `_lock` for singleton creation;
instance-level `_mode_lock` for mode changes (separate locks to avoid
deadlocks).

### set_mode() State Machine

```
INPUT: mode ("LIVE" or "DRY_RUN"), confirm (bool)

┌─────────────────────────────────────────────────────────┐
│  set_mode("DRY_RUN", ...)                               │
│    → _apply_mode("DRY_RUN")                             │
│    → return {"success": True, "mode": "DRY_RUN"}        │
│    (no confirmation required to go back to paper)        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  set_mode("LIVE", confirm=False)                        │
│    → return {"success": False, "error": "requires confirm=true"}
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  set_mode("LIVE", confirm=True)                         │
│    safety = safety_guard.check()                        │
│    if not safety.safe:                                  │
│        return {"success": False, "error": safety.reason}│
│    → _apply_mode("LIVE")                                │
│    → return {"success": True, "mode": "LIVE"}           │
└─────────────────────────────────────────────────────────┘
```

### _apply_mode()

```python
self._mode = mode
config.DRY_RUN = (mode == "DRY_RUN")   # mutates global config flag

self._history.append({
    "from": previous, "to": mode, "timestamp": time.time()
})
if len(self._history) > 100:
    self._history = self._history[-100:]
```

Mutating `config.DRY_RUN` is the key action — this flag is read by
`executor.py` on every trade, so it takes effect immediately for the
next trade after the mode switch.

### History

Full audit trail of every mode switch, capped at 100 entries.
Accessible via `GET /trading/status` → `history`.

---

## 24. Safety Guard

### check() Logic

```
1. _check_drawdown():
     drawdown = get_portfolio().get_max_drawdown()
     if drawdown > 0.20:
         return SafetyCheckResult(safe=False, reason="drawdown too high: X%")

2. _check_cooldown():
     if RiskManager.instance().in_cooldown():
         return SafetyCheckResult(safe=False, reason="in consecutive-loss cooldown")

3. All passed:
     return SafetyCheckResult(safe=True, reason="ok")
```

### Why These Two Checks?

- **Drawdown check:** Don't enable real money if the strategy has already
  lost 20%+ of its virtual portfolio. This is a crucial sanity check —
  a strategy losing 20% on paper should not be trusted with real money.

- **Cooldown check:** Don't enable real money if the system just had 3
  consecutive losses. This indicates a potentially broken signal pipeline
  (bad API response, stale data, etc.) that should be investigated.

### Lazy Imports

All imports (`from portfolio._paper import ...`, `from risk import ...`) are
inside method bodies. This prevents circular import issues at module load time
since `safety_guard.py` is imported early in the boot sequence.

---

## 25. API Layer

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check + system info |
| GET | `/api/status` | Pipeline status, risk metrics, uptime |
| GET | `/api/stats` | Trading stats (win rate, P&L, Sharpe) |
| GET | `/api/markets` | Currently tracked markets |
| GET | `/api/portfolio` | Full portfolio state (positions, P&L, metrics) |
| GET | `/api/signals/recent` | Recent signals from SQLite |
| GET | `/api/sources` | News source health/activity |
| GET | `/api/trading/status` | Current mode (DRY_RUN/LIVE) + history |
| POST | `/api/trading/mode` | Switch trading mode |
| WS | `/ws/signals` | Real-time signal WebSocket feed |

### POST /api/trading/mode Logic

```python
class TradingModeRequest(BaseModel):
    mode: str        # "LIVE" or "DRY_RUN"
    confirm: bool = False

@app.post("/trading/mode")
async def set_trading_mode(request: TradingModeRequest):
    result = TradingMode.instance().set_mode(request.mode, confirm=request.confirm)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
```

Returns 400 with error detail if:
- Invalid mode string
- Switching to LIVE without `confirm=true`
- Safety checks fail (drawdown, cooldown)

### WebSocket Endpoint Logic

```
On WS connect:
  broadcaster.register(websocket)
  Send all recent signals from SQLite (initial state for new clients)

On message from client:
  Ignore (read-only feed)

On WS disconnect:
  broadcaster.unregister(websocket)
```

---

## 26. WebSocket Broadcaster

### Registry Pattern

```python
_connections: set[WebSocket] = set()

def register(ws):    _connections.add(ws)
def unregister(ws):  _connections.discard(ws)

def broadcast(payload: dict):
    message = json.dumps(payload)
    dead = set()
    for ws in _connections:
        try:
            asyncio.create_task(ws.send_text(message))
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connections.discard(ws)
```

### Signal Payload Schema

```json
{
  "type":       "signal",
  "side":       "YES" | "NO",
  "market":     "Will X happen?",
  "market_id":  "condition_id",
  "p_market":   0.3500,
  "p_true":     0.4500,
  "ev":         0.0800,
  "bet_usd":    12.50,
  "status":     "paper" | "filtered" | "rejected" | ...,
  "source":     "rss",
  "headline":   "Breaking news text...",
  "latency_ms": 1240,
  "strategies": ["news"] | ["news", "momentum"],
  "timestamp":  "2026-04-18T12:00:00Z"
}
```

**status values and their meanings:**
- `"paper"` — trade placed in paper portfolio
- `"executed"` — live trade placed (LIVE mode)
- `"filtered"` — failed NewsAlpha conversion
- `"rejected_spread"` — spread too wide for routing
- `"daily_loss_limit"` — daily cap hit
- `"max_positions_reached"` — 5 positions open
- `"category_exposure_limit"` — category cap hit
- `"consecutive_loss_cooldown"` — in cooldown
- `"rejected_duplicate_position"` — market already held

---

## 27. Calibration System

### Resolution Checking Logic

```
1. Fetch last 200 trades from SQLite
2. Filter: status in ("dry_run", "executed") AND has classification data
3. For each unresolved trade:
     GET Gamma API /markets?condition_id={market_id}
     If market is closed:
       Parse outcomePrices[0] as YES resolution (1.0 = resolved YES, 0.0 = resolved NO)
       resolved_yes = exit_price > 0.5
       predicted_yes = classification == "YES"
       correct = predicted_yes == resolved_yes
       logger.log_calibration(...)
```

### Report Generation Logic

```
1. If < 10 resolved trades: return early with "need more data" message
2. Load up to 500 calibrated trades from SQLite
3. For each trade:
     Compute Brier score contribution
     Accumulate by_source and by_category stats
     Place into confidence bucket [0.5-0.6, 0.6-0.7, ..., 0.9-1.0]
4. Compute overall accuracy, mean Brier, ECE
5. Generate recommendation string based on accuracy thresholds
```

### Recommendation Thresholds

```
accuracy ≥ 0.65 → "Strong edge — consider modest size increase"
accuracy ≥ 0.55 → "Moderate edge — hold current sizing"
accuracy ≥ 0.48 → "Weak edge — review novelty scoring and sources"
accuracy < 0.48 → "NEGATIVE edge — PAUSE live trading, audit prompts"
```

---

## 28. Complete Signal Lifecycle — Step-by-Step

Here is the exact sequence of every check and transformation from raw news to trade:

```
[News arrives from RSS/Twitter/etc.]
        ↓
  NewsEvent pushed to asyncio.Queue
        ↓
  _consume_news_queue() dequeues it
        ↓
  asyncio.create_task(_handle_event(event))
        ↓
  ┌─ GUARD: risk.can_trade_daily()? ───────────────→ [DROP] if daily cap hit
  ├─ GUARD: risk.in_cooldown()? ───────────────────→ [DROP] if in cooldown
  ├─ GUARD: is_relevant_event(categories)? ────────→ [DROP] if wrong category
  └─ GUARD: nlp.relevance ≥ NLP_MIN_IMPACT? ───────→ [DROP] if low impact
        ↓
  match_news_to_markets(headline, tracked_markets)
        ↓
  GUARD: matches not empty? ───────────────────────→ [DROP] if no market match
        ↓
  asyncio.gather([_process_market(m) for m in matches])
        ↓
  [Per market, concurrently:]
        ↓
  GUARD: market cooldown ≥ 600s? ──────────────────→ [SKIP] this market
        ↓
  classify_async(headline, market, source)   [3 concurrent LLM calls]
        ↓
  GUARD: classification.is_actionable? ───────────→ [SKIP] if not actionable
  [confidence, materiality, novelty, consistency all checked]
        ↓
  fetch_order_book(market)
        ↓
  GUARD: snap.is_moving? ──────────────────────────→ [SKIP] if already repricing
  GUARD: ob.bid_depth_usd ≥ MIN_DEPTH? ───────────→ [SKIP] if too thin
        ↓
  compute_edge(market, classification, liquidity, spread, slippage)
        ↓
  GUARD: EV_net ≥ 0.03? ───────────────────────────→ [None] if insufficient edge
  GUARD: liquidity_score ≥ 0.20? ──────────────────→ [None] if illiquid
  GUARD: spread ≤ 0.08? ───────────────────────────→ [None] if wide spread
        ↓
  [Signal object created with side, p_market, p_true, ev, bet_amount]
        ↓
  Set _last_signal_time[market_id] = now   (starts 10-min cooldown)
        ↓
  news_alpha.to_alpha_signal(signal)
        ↓
  GUARD: news_alpha_sig not None? ─────────────────→ [BROADCAST filtered, SKIP]
        ↓
  momentum_sig = momentum_alpha.get_signal(market_id)
  [Optional: add momentum AlphaSignal if available and fresh]
        ↓
  aggregated = ensemble.combine([news_alpha_sig, ...])
  [Weighted vote, size multiplier, aggregated confidence/edge]
        ↓
  PortfolioManager.instance().process_signal_async(aggregated)
        ↓
  drawdown = paper_portfolio.get_max_drawdown()
  size_usd = allocator.compute_size(aggregated, drawdown)
        ↓
  decision = risk_engine.validate(aggregated, size_usd)
  GUARD: approved? ────────────────────────────────→ [rejected_result, BROADCAST rejected]
        ↓
  ExecutionEngine.instance().execute({"signal": aggregated, "size_usd": size_usd})
        ↓
  routing = smart_router.get_routing_strategy(spread, momentum)
  GUARD: routing != "reject"? ─────────────────────→ [BROADCAST rejected_spread]
        ↓
  slippage = slippage_model.estimate(size_usd, depth, spread)
  exec_signal = copy(raw_signal), set bet_amount = size_usd
        ↓
  if DRY_RUN:  paper_portfolio.simulate_trade(exec_signal)
  else:        live executor → CLOB API
        ↓
  GUARD: result.success and filled_size > 0?
    → YES: risk.on_trade_opened(condition_id, category, amount)
    →      metrics.record_trade(pnl=0, ev, latency)
        ↓
  broadcaster.broadcast({...signal payload...})
        ↓
  [Signal visible in dashboard feed]
```

---

## 29. All Guard Conditions (Master Reference)

Every place in the code where a signal/event is dropped, sorted by stage:

| Stage | Condition | Drop Reason | Code Location |
|-------|-----------|-------------|---------------|
| Event handler | `not risk.can_trade_daily()` | Daily loss cap hit | `pipeline._handle_event` |
| Event handler | `risk.in_cooldown()` | Consecutive loss cooldown | `pipeline._handle_event` |
| Event handler | `not is_relevant_event(categories)` | Wrong category | `pipeline._handle_event` |
| Event handler | `nlp.relevance < NLP_MIN_IMPACT` | Low NLP impact | `pipeline._handle_event` |
| Event handler | `not matches` | No market matched | `pipeline._handle_event` |
| Market processing | `cooldown < 600s` | Per-market 10-min cooldown | `pipeline._process_market` |
| Classification | `not is_actionable` | LLM confidence/materiality/novelty/consistency | `pipeline._process_market` |
| Microstructure | `snap.is_moving` | Market already repricing | `pipeline._process_market` |
| Microstructure | `depth < MIN_DEPTH` | Insufficient order book depth | `pipeline._process_market` |
| Edge model | `direction == NEUTRAL` | LLM said irrelevant | `edge_model.compute_edge` |
| Edge model | `EV_net < 0.03` | Insufficient edge | `edge_model.compute_edge` |
| Edge model | `liquidity_score < 0.20` | Illiquid market | `edge_model.compute_edge` |
| Edge model | `spread > 0.08` | Spread too wide | `edge_model.compute_edge` |
| News alpha | `to_alpha_signal() → None` | Field error or validation failure | `alpha/news_alpha.py` |
| Momentum alpha | `TTL expired (>180s)` | Stale signal | `alpha/momentum_alpha.py` |
| Momentum alpha | `\|r\| < 0.02` | Below threshold | `alpha/momentum_alpha.py` |
| Risk engine | `not can_trade_daily()` | Daily cap (second check) | `portfolio/risk_engine.py` |
| Risk engine | `not can_open_position()` | 5 positions open | `portfolio/risk_engine.py` |
| Risk engine | `category_exposure limit` | Category cap | `portfolio/risk_engine.py` |
| Risk engine | `in_cooldown()` | Consecutive losses | `portfolio/risk_engine.py` |
| Smart router | `spread > 0.08` | Routing reject | `execution/smart_router.py` |
| Paper portfolio | Duplicate position | Same market already held | `portfolio/_paper.py` |
| Safety guard | `drawdown > 0.20` | Blocks LIVE mode switch | `control/safety_guard.py` |
| Safety guard | `in_cooldown()` | Blocks LIVE mode switch | `control/safety_guard.py` |
| Trading mode | `confirm = False` | Blocks LIVE without explicit confirmation | `control/trading_mode.py` |

---

## 30. All Singleton Patterns

Four singletons in the system. All use the same pattern:

```python
_singleton: ClassVar = None
_lock = Lock()   # class-level, for singleton creation

@classmethod
def instance(cls):
    with cls._lock:
        if cls._singleton is None:
            cls._singleton = cls()
    return cls._singleton
```

| Singleton | Module | Purpose |
|-----------|--------|---------|
| `RiskManager` | `risk.py` | Global risk state — positions, exposure, cooldowns |
| `PortfolioManager` | `portfolio/portfolio_manager.py` | Central trade decision engine |
| `ExecutionEngine` | `execution/execution_engine.py` | Order execution gateway |
| `TradingMode` | `control/trading_mode.py` | Runtime DRY_RUN ↔ LIVE toggle |

**Why singletons?**
These components maintain state that must be consistent across the entire
application. Multiple instances would create diverging state — two RiskManagers
would each think they hold half the positions, leading to double the allowed
exposure.

**Thread safety:**
The class-level `_lock` ensures safe creation in multi-threaded contexts
(pipeline runs asyncio tasks that may spawn thread pool workers). The lock is
held only during initialization, not during normal operation.

---

## 31. Concurrency Model

### Event Loop Structure

```
Single asyncio event loop (uvicorn)
├── Pipeline.run() task
│   ├── watcher.run() — WebSocket + periodic refresh
│   ├── news_aggregator.run() — 7 source coroutines via gather
│   ├── _consume_news_queue() — queue consumer, spawns event tasks
│   └── momentum_alpha.run() — 60s poll loop
│
├── Per-event tasks (asyncio.create_task, unbounded)
│   └── _handle_event() → _process_market() × N
│       └── classify_async() — fan-out 3 LLM calls via gather
│
└── HTTP request handlers (FastAPI/uvicorn workers)
```

### Thread Pool Usage

```
asyncio.get_running_loop().run_in_executor(None, ...)
```

Used in `PortfolioManager.process_signal_async()` to run synchronous CPU
work (allocator, risk engine) without blocking the event loop.

The default executor is `ThreadPoolExecutor(max_workers=min(32, os.cpu_count()+4))`.

### Locking Strategy

```
Threading Locks (threading.Lock):
  RiskManager._state_lock       — on_trade_opened / on_trade_closed
  PortfolioManager._lock        — singleton creation
  ExecutionEngine._lock         — singleton creation
  TradingMode._lock             — singleton creation
  TradingMode._mode_lock        — set_mode() critical section

asyncio Semaphore:
  _groq_semaphore (Semaphore(9)) — limit concurrent Groq API calls

asyncio Locks:
  None (asyncio tasks don't preempt each other within a single coroutine)
```

### Queue Backpressure

```
Queue depth monitoring:
  if queue.qsize() > 50:
      log.warning("Queue depth=N — events may lag")
```

The queue is unbounded (`asyncio.Queue()` with no maxsize). If the news sources
produce events faster than the pipeline can process them (classifier is the
bottleneck at ~1–2s per market), the queue grows. The warning at depth=50
signals that the system is falling behind real-time.

**No backpressure mechanism is currently implemented.** Events are never
dropped due to queue depth. This is acceptable for the current news volume
but would need a bounded queue or event dropping for very high-throughput
scenarios.
