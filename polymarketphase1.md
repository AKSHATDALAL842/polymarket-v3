# SYSTEM AUDIT — CALL 1
## Phases 1–3: Inventory, Pipeline Integrity, Risk System

---

## PHASE 1: FULL CODEBASE INVENTORY

---

### Root Level

```
┌─────────────────────────────────────────────────────────────┐
│ File: config.py                                             │
│ Purpose: All env var loading, constants, feature flags      │
│ Status: CRITICAL                                            │
│ Depends on: python-dotenv, .env file                        │
│ Called by: Every module in the project                      │
│ Healthy: UNCERTAIN — SIZING_K is hardcoded (not env var),   │
│          HOT_PATH_ENABLED/FAST_CLASSIFIER_MIN_CONFIDENCE/   │
│          STALENESS_THRESHOLD newly added but not in .env    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: pipeline.py                                           │
│ Purpose: Main async orchestration — news → signal → trade   │
│ Status: CRITICAL                                            │
│ Depends on: 12+ modules, all listed below                   │
│ Called by: run_pipeline_v2() called by cli.py               │
│ Healthy: NO — 3 known fatal bugs (documented in Phase 2/3)  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: api.py                                                │
│ Purpose: FastAPI REST server for status/control             │
│ Status: SUPPORTING                                          │
│ Depends on: observability.logger, portfolio, pipeline status │
│ Called by: cli.py or standalone                             │
│ Healthy: UNCERTAIN — fastapi/uvicorn not in requirements.txt│
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: cli.py                                                │
│ Purpose: Rich terminal UI + pipeline entry point            │
│ Status: SUPPORTING                                          │
│ Depends on: rich, pipeline, observability.logger            │
│ Called by: User (main entry point)                          │
│ Healthy: UNCERTAIN — imports not fully verified             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: dashboard.py                                          │
│ Purpose: WebSocket dashboard server                         │
│ Status: SUPPORTING                                          │
│ Depends on: observability.logger, observability.broadcaster │
│ Called by: Standalone process or cli.py                     │
│ Healthy: UNCERTAIN                                          │
└─────────────────────────────────────────────────────────────┘
```

---

### alpha/

```
┌─────────────────────────────────────────────────────────────┐
│ File: alpha/signal.py                                       │
│ Purpose: AlphaSignal + AggregatedSignal dataclasses         │
│ Status: CRITICAL                                            │
│ Depends on: time (stdlib)                                   │
│ Called by: ensemble, news_alpha, momentum_alpha, tests      │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: alpha/ensemble.py                                     │
│ Purpose: Weighted multi-strategy signal aggregation         │
│ Status: CRITICAL                                            │
│ Depends on: alpha/signal.py                                 │
│ Called by: pipeline._process_market()                       │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: alpha/news_alpha.py                                   │
│ Purpose: Convert edge_model.Signal → AlphaSignal            │
│ Status: CRITICAL                                            │
│ Depends on: alpha/signal.py                                 │
│ Called by: pipeline._process_market()                       │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: alpha/momentum_alpha.py                               │
│ Purpose: Detect price momentum, generate momentum signals   │
│ Status: SUPPORTING                                          │
│ Depends on: ingestion/market_watcher.py                     │
│ Called by: pipeline.run() (asyncio.gather)                  │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: alpha/base_alpha.py                                   │
│ Purpose: BaseAlpha ABC                                      │
│ Status: UTILITY                                             │
│ Depends on: nothing                                         │
│ Called by: NewsAlpha, MomentumAlpha                         │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘
```

---

### signal/

```
┌─────────────────────────────────────────────────────────────┐
│ File: signal/classifier.py                                  │
│ Purpose: LLM 3-pass consensus classifier (Groq or Anthropic)│
│ Status: CRITICAL                                            │
│ Depends on: Groq/Anthropic API, config, asyncio             │
│ Called by: pipeline._process_market() (cold path)           │
│ Healthy: UNCERTAIN — semaphore created at module level,     │
│          no API timeout on individual calls                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: signal/edge_model.py                                  │
│ Purpose: Compute EV, bet sizing, produce Signal object      │
│ Status: CRITICAL                                            │
│ Depends on: config, signal/classifier.py, ingestion/markets │
│ Called by: pipeline._process_market()                       │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: signal/matcher.py                                     │
│ Purpose: Sentence-transformer semantic market matching      │
│ Status: CRITICAL                                            │
│ Depends on: sentence-transformers, numpy                    │
│ Called by: pipeline._handle_event(), pipeline.run()         │
│ Healthy: UNCERTAIN                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: signal/fast_classifier.py                             │
│ Purpose: LightGBM hot-path classifier, 40-feature extractor │
│ Status: CRITICAL (when HOT_PATH_ENABLED=true)               │
│ Depends on: lightgbm, numpy, signal/watchlist.py            │
│ Called by: pipeline._process_market() (hot path)            │
│ Healthy: YES — rule-based fallback works without model file  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: signal/watchlist.py                                   │
│ Purpose: O(1) 70-phrase YES/NO watchlist lookup             │
│ Status: CRITICAL (hot path component)                       │
│ Depends on: nothing                                         │
│ Called by: signal/fast_classifier.py                        │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: signal/cold_path.py                                   │
│ Purpose: Async LLM labeler for borderline/loss trades       │
│ Status: CRITICAL (self-training feedback loop)              │
│ Depends on: signal/classifier.py, ingestion/markets.py      │
│ Called by: pipeline.run() (asyncio.gather), submit() calls  │
│ Healthy: NO — is_loss_trade flag always True (see Phase 2)  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: signal/nlp_processor.py                               │
│ Purpose: spaCy NER + VADER sentiment + impact scoring       │
│ Status: SUPPORTING                                          │
│ Depends on: spacy (optional), vaderSentiment (optional)     │
│ Called by: pipeline._handle_event()                         │
│ Healthy: YES — gracefully degrades without optional deps    │
└─────────────────────────────────────────────────────────────┘
```

---

### portfolio/

```
┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/risk.py (RiskManager)                       │
│ Purpose: Enforce daily loss, position, category, cooldown   │
│ Status: CRITICAL                                            │
│ Depends on: config, observability/logger (BROKEN import)    │
│ Called by: executor.py, risk_engine.py, pipeline.py         │
│ Healthy: NO — on_trade_closed() never called, daily loss   │
│          circuit breaker broken (wrong import path)         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/risk_engine.py                              │
│ Purpose: Validate signal against RiskManager before execute  │
│ Status: CRITICAL                                            │
│ Depends on: portfolio/risk.py                               │
│ Called by: portfolio_manager.py                             │
│ Healthy: YES — logic correct, inherits risk.py bugs         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/portfolio_manager.py                        │
│ Purpose: Central decision engine: size → risk → execute     │
│ Status: CRITICAL                                            │
│ Depends on: allocator, risk_engine, execution_engine        │
│ Called by: pipeline._process_market()                       │
│ Healthy: UNCERTAIN — delegates to broken risk subsystem     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/allocator.py                                │
│ Purpose: Kelly-fraction position sizing                     │
│ Status: CRITICAL                                            │
│ Depends on: alpha/signal.py                                 │
│ Called by: portfolio_manager.py                             │
│ Healthy: YES — math is correct, floor/ceiling enforced      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/_paper.py                                   │
│ Purpose: Paper portfolio simulation, P&L tracking           │
│ Status: CRITICAL                                            │
│ Depends on: observability/logger.py, ingestion/market_watcher│
│ Called by: executor.execute_trade() (DRY_RUN=true)          │
│ Healthy: UNCERTAIN — fresh MarketWatcher in                 │
│          get_unrealized_pnl() always returns 0 unrealized   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/kelly_table.py                              │
│ Purpose: Pre-baked Kelly lookup table (EV × conf × spread)  │
│ Status: UTILITY                                             │
│ Depends on: numpy, config                                   │
│ Called by: NOTHING — never imported anywhere               │
│ Healthy: NO — dead code, orphaned from HFT redesign         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: portfolio/exposure_tracker.py                         │
│ Purpose: Read-only query view over RiskManager state        │
│ Status: UTILITY                                             │
│ Depends on: portfolio/risk.py                               │
│ Called by: Imported in portfolio/__init__.py, never used    │
│ Healthy: UNCERTAIN — functional but unused                  │
└─────────────────────────────────────────────────────────────┘
```

---

### execution/

```
┌─────────────────────────────────────────────────────────────┐
│ File: execution/executor.py                                 │
│ Purpose: Final trade routing — dry_run / paper / live       │
│ Status: CRITICAL                                            │
│ Depends on: config, observability/logger, signal/edge_model │
│ Called by: execution_engine.execute()                       │
│ Healthy: NO — order retry has no idempotency key            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: execution/execution_engine.py                         │
│ Purpose: Singleton orchestrator; converts AggSig → Signal   │
│ Status: CRITICAL                                            │
│ Depends on: execution/executor.py, execution/smart_router   │
│ Called by: portfolio_manager.process_signal()               │
│ Healthy: NO — _get_microstructure() hardcoded (0.04, 0.0)  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: execution/smart_router.py                             │
│ Purpose: Spread-based routing: aggressive/passive/reject    │
│ Status: SUPPORTING                                          │
│ Depends on: nothing                                         │
│ Called by: execution_engine.execute()                       │
│ Healthy: YES — but receives hardcoded inputs (see above)    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: execution/slippage_model.py                           │
│ Purpose: Slippage estimation                                │
│ Status: UTILITY                                             │
│ Depends on: unclear                                         │
│ Called by: UNKNOWN — not found in grep results              │
│ Healthy: UNKNOWN — may be dead code                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: execution/kalshi_executor.py                          │
│ Purpose: Kalshi-specific order placement                    │
│ Status: SUPPORTING                                          │
│ Depends on: observability/logger, config (Kalshi creds)     │
│ Called by: executor.execute_trade() for kalshi markets      │
│ Healthy: UNCERTAIN — modified in git, not fully audited     │
└─────────────────────────────────────────────────────────────┘
```

---

### ingestion/

```
┌─────────────────────────────────────────────────────────────┐
│ File: ingestion/market_watcher.py                           │
│ Purpose: WS price feed + HTTP order book + snapshots        │
│ Status: CRITICAL                                            │
│ Depends on: httpx, websockets, certifi (NOT in reqs!)       │
│ Called by: pipeline.run(), portfolio/_paper.py (NEW INST.)  │
│ Healthy: UNCERTAIN — certifi not in requirements.txt        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: ingestion/news_stream.py                              │
│ Purpose: Multi-source news aggregator (RSS/API/WS)          │
│ Status: CRITICAL                                            │
│ Depends on: feedparser, aiohttp, tweepy, config             │
│ Called by: pipeline.run()                                   │
│ Healthy: UNCERTAIN                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: ingestion/markets.py                                  │
│ Purpose: Market dataclass, Polymarket API fetch             │
│ Status: CRITICAL                                            │
│ Depends on: httpx, config                                   │
│ Called by: market_watcher, execution/executor               │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: ingestion/kalshi_markets.py                           │
│ Purpose: Fetch Kalshi prediction markets                    │
│ Status: SUPPORTING                                          │
│ Depends on: config (Kalshi credentials), httpx              │
│ Called by: market_watcher.refresh_markets()                 │
│ Healthy: UNCERTAIN — modified in git                        │
└─────────────────────────────────────────────────────────────┘
```

---

### observability/

```
┌─────────────────────────────────────────────────────────────┐
│ File: observability/logger.py                               │
│ Purpose: SQLite persistence for trades, positions, metrics  │
│ Status: CRITICAL                                            │
│ Depends on: sqlite3 (stdlib), pathlib                       │
│ Called by: executor.py, portfolio/_paper.py, dashboard.py   │
│ Healthy: YES — init_db() called at module level (line 472)  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: observability/metrics.py                              │
│ Purpose: In-memory trade/latency/EV snapshot tracking       │
│ Status: SUPPORTING                                          │
│ Depends on: nothing                                         │
│ Called by: pipeline.py                                      │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: observability/broadcaster.py                          │
│ Purpose: WebSocket broadcast to dashboard clients           │
│ Status: SUPPORTING                                          │
│ Depends on: asyncio                                         │
│ Called by: pipeline._process_market()                       │
│ Healthy: YES                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: observability/backtest.py                             │
│ Purpose: Event-driven historical backtester                 │
│ Status: UTILITY                                             │
│ Depends on: observability/logger.py                         │
│ Called by: cli.py, api.py (partially)                       │
│ Healthy: UNCERTAIN — not wired into live pipeline           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: observability/calibrator.py                           │
│ Purpose: Probability calibration against resolved outcomes  │
│ Status: UTILITY                                             │
│ Depends on: observability/logger.py                         │
│ Called by: cli.py (partially) — NOT called from pipeline    │
│ Healthy: UNCERTAIN — never runs during live trading         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ File: observability/scorer.py                               │
│ Purpose: Brier/log-loss scoring                             │
│ Status: UTILITY                                             │
│ Depends on: observability/logger.py                         │
│ Called by: cli.py, api.py (partially)                       │
│ Healthy: UNCERTAIN — analysis tool, not pipeline-integrated │
└─────────────────────────────────────────────────────────────┘
```

---

### providers/

```
┌─────────────────────────────────────────────────────────────┐
│ File: providers/ (all 4 files)                              │
│ Purpose: Abstract provider layer for Poly/Kalshi markets    │
│ Status: UNKNOWN                                             │
│ Depends on: ingestion/markets.py, execution/executor.py     │
│ Called by: NOTHING — zero imports found in pipeline, api,  │
│            cli, or any non-providers file                   │
│ Healthy: NO — dead code, entire package is orphaned         │
└─────────────────────────────────────────────────────────────┘
```

---

### Phase 1 Anomaly Summary

#### Files defined but never called from pipeline

| File | Why It Matters |
|---|---|
| `portfolio/kelly_table.py` | Created in HFT redesign but never wired in — allocator.py still uses its own formula |
| `providers/` (all 4 files) | Entire abstraction layer is dead code — zero calls found anywhere |
| `portfolio/exposure_tracker.py` | Imported in `__init__.py`, never instantiated anywhere |
| `execution/slippage_model.py` | Cannot confirm it is called from any active code path |
| `observability/calibrator.py` | Only accessible via CLI/API, never from live pipeline |
| `observability/scorer.py` | Same as above |
| `observability/backtest.py` | Same as above |

#### Wrong module path (broken import)

- `portfolio/risk.py:40` — `import logger as lg` — **no root-level `logger.py` exists**. Only `api.py`, `cli.py`, `config.py`, `dashboard.py`, `pipeline.py` exist at root. Every other module correctly uses `from observability import logger`.
- `tests/test_portfolio.py:8` — `import logger as lg` — test will fail on import for the same reason.

#### Env vars in code but missing from .env

| Config Key | Used In | Present in .env |
|---|---|---|
| `HOT_PATH_ENABLED` | `pipeline.py`, `config.py` | NO |
| `FAST_CLASSIFIER_MIN_CONFIDENCE` | `pipeline.py`, `config.py` | NO |
| `STALENESS_THRESHOLD` | `pipeline.py`, `config.py` | NO |
| `PAPER_BALANCE` | `portfolio/_paper.py` | NO |
| `SIZING_K` | `allocator.py` (hardcoded in config.py, not env var) | NO |

---

## PHASE 2: PIPELINE INTEGRITY CHECK

### 2a. Data Flow Integrity — Stage by Stage

#### Stage 1: News Ingest → Queue

**Enter:** Nothing (external event sources)  
**Exit:** `NewsEvent` object pushed to `asyncio.Queue`  
**Schema validation:** None. `NewsEvent` is a dataclass; fields are set by the aggregator. `event.age_seconds()` is called downstream — if this method throws, the whole event is dropped in the fire-and-forget task.

**Silent failure:** `event.receive_latency_ms` is accessed via `getattr(event, "receive_latency_ms", 0)` at `pipeline.py:93`. If the event was constructed without this attribute, it silently defaults to 0. News latency tracking is wrong without any warning.

---

#### Stage 2: Category Filter

**Enter:** `NewsEvent`  
**Exit:** continues or returns  
**Check:** `is_relevant_event(event, config.SELECTED_CATEGORIES)` at `pipeline.py:96`

**Silent failure:** `SELECTED_CATEGORIES` defaults to `["all"]` if unset in .env. With `["all"]`, ALL events pass the filter. The system processes headlines from all 14 RSS feeds even if they are unrelated to any tracked market. Wasted LLM calls are the consequence.

---

#### Stage 3: NLP Gate

**Enter:** `headline`, `source`, `age_seconds`  
**Exit:** `NLPResult.relevance` float  
**Check:** `nlp.relevance < config.NLP_MIN_IMPACT` at `pipeline.py:108`

**Silent failure:** `nlp_processor.process()` never raises — it degrades gracefully when spaCy and VADER are not installed. With neither installed, `relevance ≈ 0.20 * 0.60 = 0.12`, which is above `NLP_MIN_IMPACT=0.10`. **Most events pass the NLP gate even without any NLP libraries installed.** Both `spacy` and `vaderSentiment` are absent from `requirements.txt`.

---

#### Stage 4: Market Matching

**Enter:** `headline: str`, `markets: list[Market]`  
**Exit:** `list[MatchResult]` (each with `.market: Market`, `.similarity: float`)

**Silent failure (MEDIUM):** If `update_market_embeddings` was never called (e.g., market refresh failed), the matcher operates on a stale or empty index and returns no matches — silently dropping all events. `pipeline.py:119` only logs at `debug` level.

**Silent failure (MEDIUM):** `MATCHER_MIN_SIMILARITY=0.30` is very low. A 30% cosine similarity is cosmetically related, not specifically matching. A headline about "Apple stock" could match a market about "Apple cider" at this threshold.

---

#### Stage 5: Hot Path Classification (HOT_PATH_ENABLED=true)

**Enter:** `event.headline: str`, `event.source: str`, `market.yes_price: float`  
**Exit:** `ClassifierResult` → `Classification` shim via `build_classification()`

**Silent failure (FATAL):** The `build_classification()` shim at `fast_classifier.py:238-250` always sets `consistency=1.0`:

```python
# fast_classifier.py:242
return Classification(
    ...
    consistency=1.0,    # hard-coded — bypasses CONSISTENCY_THRESHOLD check
    ...
)
```

`Classification.is_actionable` at `classifier.py:106` requires `consistency >= config.CONSISTENCY_THRESHOLD (0.6)`. With consistency always forced to 1.0, the consistency filter is completely bypassed for hot-path trades. **Any low-quality hot-path signal that meets only confidence + materiality thresholds will execute.**

---

#### Stage 6: Edge Computation

**Enter:** `market: Market`, `classification: Classification`, `liquidity_score`, `spread`, `estimated_slippage`  
**Exit:** `Signal | None`

**Silent failure:** `spread` at `pipeline.py:195`:
```python
spread = ob.spread if ob.spread > 0.001 else (snap.spread if snap else 0.05)
```
If order book fetch fails AND no snapshot exists (new market), `spread = 0.05`. This is just below `MAX_SPREAD_FRACTION=0.08`, so it will not be rejected. Edge calculation proceeds with an assumed spread that may be far from reality.

**Silent failure:** `estimated_slippage` at `pipeline.py:205`:
```python
estimated_slippage=snap.estimated_slippage(classification.direction, 25.0) if snap else 0.0
```
If snap is None, slippage is assumed 0.0. For new markets with no order book data, EV is overestimated by the full slippage amount.

---

#### Stage 7: Alpha + Ensemble

**Enter:** `Signal` (from edge_model)  
**Exit:** `AggregatedSignal`

**Silent failure:** `self._news_alpha.to_alpha_signal(signal)` at `pipeline.py:234` can return `None` if EV is below threshold. The code then broadcasts a "filtered" signal to the UI and returns. The broadcast includes `strategies: ["news"]`, which may mislead the UI into showing activity that never became a trade.

**Data flow gap:** For momentum-only signals, `agg.market` can be `None`. `execution_engine._build_signal()` returns `None` in that case → silent rejection with only `log.warning`. A momentum signal silently fails to execute.

---

#### Stage 8: PortfolioManager → ExecutionEngine → Executor

**Silent failure (HIGH):** `ExecutionEngine._get_microstructure()` at `execution_engine.py:83`:
```python
def _get_microstructure(self, market_id: str) -> tuple[float, float]:
    return 0.04, 0.0    # HARDCODED — never reads live data
```
This hardcoded value (spread=0.04, momentum=0.0) is fed to `get_routing_strategy()`. Since 0.04 falls between `SPREAD_AGGRESSIVE_THRESHOLD (0.02)` and `SPREAD_REJECT_THRESHOLD (0.08)`, routing is always "passive". Real spread/momentum data from `MarketWatcher` is never consulted. The smart router does nothing.

---

### 2b. Failure Mode Analysis

#### Silent Failures

| Stage | Failure | Code Location | Consequence |
|---|---|---|---|
| Hot classifier | `consistency=1.0` hardcoded | `fast_classifier.py:242` | All hot-path trades skip consistency filter |
| Slippage estimation | `estimated_slippage=0.0` when no snap | `pipeline.py:205` | EV overestimated for new markets |
| Spread fallback | `spread=0.05` when no ob + no snap | `pipeline.py:195` | Wrong spread used in edge calculation |
| Risk gate | Daily loss counter stuck at 0 | `portfolio/risk.py:40` | Circuit breaker never fires |
| Smart router | Hardcoded microstructure | `execution_engine.py:83` | Routing never adapts to market conditions |
| Market matching | Low similarity threshold 0.30 | `config.py:84` | False positive market matches |

#### Loud Failures

| Failure | Caught? | Fail-safe or Fail-dangerous? | Evidence |
|---|---|---|---|
| Groq API exception | YES | Fail-safe: returns NEUTRAL Classification | `classifier.py:183` |
| WebSocket disconnect | YES | Fail-safe: reconnects after 5s | `market_watcher.py:319` |
| Order placement failure | YES | Fail-safe: logs error, retries 3x | `executor.py:185-196` |
| Order book fetch failure | YES | Fail-safe: returns empty OrderBookSnapshot | `market_watcher.py:275` |
| All LLM passes fail | YES | Fail-safe: returns NEUTRAL, no trade | `classifier.py:212-224` |
| Logger `import logger` fails | YES (exception swallowed) | **FAIL-DANGEROUS**: circuit breaker stays at 0 | `portfolio/risk.py:43` |

#### Missing Failures

1. **HTTP 200 with error body:** `fetch_active_markets()` calls `.raise_for_status()` but does not validate response structure. If the API returns `{"status": "error", "data": null}`, the code tries to iterate over `None` → silent crash → no markets tracked.

2. **Order placed but API response times out:** `_execute_live()` places an order, but if the HTTP response is lost (network timeout), the code falls through to retry logic and places a *second* order for the same market. No idempotency key exists. The `for attempt in range(ORDER_RETRY_ATTEMPTS)` loop on a timeout error would retry all 3 times.

3. **Risk check passes because state never updates:** `on_trade_closed()` is never called. `_open_positions` grows monotonically. After 5 trades placed lifetime, `can_open_position()` returns False forever — surfaced only as a `log.debug` message, not an alert or alert-level log.

---

### 2c. Concurrency and Race Conditions

**Components running concurrently:**

```python
# pipeline.py:56-63
results = await asyncio.gather(
    self.watcher.run(),           # periodic market refresh + WS price feed
    self._news_aggregator.run(),  # multi-source news polling
    self._consume_news_queue(),   # dequeues and fires tasks
    self._momentum_alpha.run(self.watcher),  # 60s momentum scan
    self._cold_path.run(),        # async LLM labeling worker
)
```

Within `_consume_news_queue()`, each event spawns a fire-and-forget task:
```python
asyncio.create_task(self._handle_event(event))
```

Multiple `_handle_event` coroutines run concurrently. Each calls `_process_market` for multiple markets. In a busy news cycle with 5 events in flight simultaneously, up to 25 concurrent `_process_market` coroutines can be active.

---

#### Race Condition #1 — Position Limit (FATAL)

The check-then-act sequence on position limits is not atomic:

```python
# RiskManager.can_open_position() — checking (risk.py:51-55)
def can_open_position(self) -> bool:
    n = len(self._open_positions)            # read under _state_lock
    if n >= config.MAX_CONCURRENT_POSITIONS: # compare
        return False
    return True

# pipeline.py:264 — acting (much later, after execution completes)
self.risk.on_trade_opened(
    condition_id=market.condition_id, ...
)
```

Between the `can_open_position()` check and `on_trade_opened()`, asyncio yields at every `await`. With `MAX_CONCURRENT_POSITIONS=5` and 4 positions open:

```
Coroutine A: can_open_position() → True (4 < 5) — await classify_async → await execute → ...
Coroutine B: can_open_position() → True (4 < 5) — await classify_async → await execute → ...
Coroutine A: on_trade_opened() → 5 positions
Coroutine B: on_trade_opened() → 6 positions  ← EXCEEDS LIMIT
```

This same race applies to `MAX_EXPOSURE_PER_CATEGORY_USD`.

---

#### Race Condition #2 — `_last_signal_time` dict (MEDIUM)

```python
# pipeline.py:147-149
last = self._last_signal_time.get(market.condition_id, 0.0)
if time.monotonic() - last < MARKET_SIGNAL_COOLDOWN_SECONDS:
    return
# ...
# pipeline.py:220
self._last_signal_time[market.condition_id] = time.monotonic()
```

Two coroutines for the same market can both pass the cooldown check before either writes the new timestamp. The per-market cooldown does not reliably prevent duplicate trades on the same market within a short window.

---

#### Race Condition #3 — execute_trade in ThreadPoolExecutor (MEDIUM)

`PortfolioManager.process_signal_async()` runs `process_signal` in a thread executor:
```python
# portfolio_manager.py:39-41
async def process_signal_async(self, signal: AggregatedSignal):
    return await asyncio.get_running_loop().run_in_executor(
        None, self.process_signal, signal
    )
```

`process_signal` calls `ExecutionEngine.execute()` → `execute_trade()` → `_check_risk_gates()`. `RiskManager._state_lock` protects individual mutations but not the read-check-execute sequence. Multiple threads executing simultaneously can all pass `can_open_position()` before any call `on_trade_opened()`.

---

## PHASE 3: RISK SYSTEM VERIFICATION

### Position Limits

**Where defined:** `config.py:103` — `MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "5"))`

**Where enforced:** Two separate checks:
1. `RiskEngine.validate()` at `portfolio/risk_engine.py:25` — before execution
2. `executor._check_risk_gates()` at `executor.py:40` — redundant second check inside executor

#### FATAL BUG — `on_trade_closed()` is never called anywhere in the codebase

Evidence from grep — only one result found (the definition):
```
portfolio/risk.py:84:    def on_trade_closed(self, condition_id: str, category: str, pnl: float):
```

Consequence:
- `_open_positions` dict grows monotonically: positions are added via `on_trade_opened()` but **NEVER removed**
- After exactly 5 trades are placed (ever, including from previous process runs), ALL future trades are permanently rejected with `"rejected_max_positions"`
- `_category_exposure` also only increases, eventually hitting `MAX_EXPOSURE_PER_CATEGORY_USD` for every category permanently
- `_consecutive_losses` is always 0 — cooldowns based on loss streaks **never trigger**
- This appears as normal operation: `log.debug` messages say "max positions reached", the system keeps running, zero trades execute

**What happens if limit is 0:** `len({}) >= 0` is `True` → `can_open_position()` returns `False` → no trades ever execute. Safe default (blocks trading), not dangerous.

**Can rapid small orders bypass the check?** No — the limit is on open positions per market (one dict key per `condition_id`). But the race condition in Phase 2c means two simultaneous coroutines can both open positions on the same market before either check completes.

---

### Category Exposure Caps

**How categories are defined:** `config.MARKET_CATEGORIES = ["ai", "technology", "crypto", "politics", "science"]`

**Who assigns category:** `ingestion/markets.py:104` — `_infer_category(question, tags)` keyword-matching heuristic. No validation against the defined list.

**What category for no-match market:** `filter_by_categories()` at `ingestion/markets.py:185` filters out any market whose category is not in `MARKET_CATEGORIES`. Non-matching markets never reach the trading stage.

**Is there an uncapped bucket?** No. The "unknown" category is capped by `MAX_EXPOSURE_PER_CATEGORY_USD ($60)`. However, since categories are inferred by keyword matching, incorrect categorization could accumulate exposure in the wrong bucket with no audit trail.

**Same `on_trade_closed()` bug applies:** Category exposure values only ever increase. Each category will eventually hit $60 and permanently block trading for that category.

---

### Daily Loss Circuit Breaker

**Exact code tracking cumulative daily loss — `portfolio/risk.py:36-49`:**

```python
def can_trade_daily(self) -> bool:
    now = time.monotonic()
    if now - self._daily_pnl_last_check > self._DAILY_PNL_CACHE_TTL:
        try:
            import logger as lg              # ← LINE 40: FATAL WRONG IMPORT
            self._daily_pnl_cache = lg.get_daily_pnl()
            self._daily_pnl_last_check = now
        except Exception:
            pass                             # ← SILENT FAILURE
    loss = min(0.0, self._daily_pnl_cache)
    if abs(loss) >= config.DAILY_LOSS_LIMIT_USD:
        log.warning(f"[risk] Daily loss cap hit: ${abs(loss):.2f}")
        return False
    return True
```

**FATAL BUG:** `import logger as lg` fails with `ModuleNotFoundError` because there is no root-level `logger.py`. Every other module in the codebase correctly uses `from observability import logger`. The `except Exception: pass` silently swallows the `ModuleNotFoundError`. Because `_daily_pnl_last_check` is NOT updated on failure, every call retries and fails again. `_daily_pnl_cache` stays at `0.0` forever. `can_trade_daily()` always returns `True`.

**Is daily loss persisted to disk?** Yes — `observability/logger.py:247` queries SQLite. If the import were fixed, the circuit breaker would survive restarts because it re-queries the DB on each check after the cache expires. **The restart-reset problem does NOT exist in this system** — the DB design is correct.

**Is circuit breaker checked before or after order placement?** Before. It is checked three separate times:

```
pipeline._process_market()
  → [line 84]  risk.can_trade_daily()                    ← CHECK 1
  → PortfolioManager.process_signal_async()
      → RiskEngine.validate()
          → [risk_engine.py:22] rm.can_trade_daily()     ← CHECK 2
      → ExecutionEngine.execute()
          → executor.execute_trade()
              → [executor.py:37] rm.can_trade_daily()    ← CHECK 3
```

All three checks are broken by the same `import logger` bug.

---

### Drawdown-Based Scaling

**Formula (`allocator.py:32-35`):**
```python
base = sizing_k * signal.expected_edge * signal.confidence * bankroll
sized = base * signal.size_multiplier
dd_scaled = sized * max(0.0, 1.0 - drawdown * 2.0)
final = max(1.0, min(max_bet, dd_scaled))
```

**Minimum position size:** `max(1.0, ...)` enforces a $1 floor. At extreme drawdown (≥50%), the formula produces 0 but the floor prevents it going below $1. No negative positions possible.

**Can it produce NaN?** If `drawdown = float('nan')`: `1.0 - nan * 2.0 = nan` → `max(0.0, nan) = nan` → `max(1.0, nan) = nan` in Python. **NaN bet size is possible** if drawdown is NaN. No explicit guard exists. In practice the drawdown source does not produce NaN today, but there is no defensive check.

**Is bankroll updated in real-time?** No. `self.bankroll` in Allocator is set once at init from `config.BANKROLL_USD` and only modified by `update_capital()` which is never called anywhere. As actual paper balance changes from trades, the sizing formula does not adapt.

**Drawdown calculation accuracy:** `_get_current_drawdown()` at `portfolio_manager.py:65` calls `get_paper_portfolio().get_max_drawdown()`. `get_max_drawdown()` computes `(peak - current_value) / peak` where `current_value = balance + unrealized_pnl`. Since `get_unrealized_pnl()` creates a fresh `MarketWatcher()` with no loaded snapshots, it always returns `0.0`. Therefore:
- **Drawdown is always underestimated** — unrealized losses from open positions are invisible
- Only losses already realized through balance deductions are counted

---

### Risk System Structural Summary

| Control | Defined | Enforced | Working? | Failure Mode |
|---|---|---|---|---|
| Daily loss cap | `config.py:101` | `risk.py:36` | **NO** | `import logger` error silently bypassed |
| Max concurrent positions | `config.py:103` | `risk.py:51` | **PARTIALLY** | positions never released (`on_trade_closed` never called) |
| Category exposure cap | `config.py:104` | `risk.py:58` | **PARTIALLY** | exposure never released |
| Consecutive loss cooldown | `config.py:104` | `risk.py:92` | **NO** | `on_trade_closed()` never called |
| Per-market signal cooldown | `config.py:108` | `pipeline.py:147` | **YES (raceable)** | race condition allows duplicate signals |
| Spread filter | `config.py:109` | `edge_model.py:113` | **YES** | falls back to hardcoded value in execution engine |
| Slippage filter | `config.py:111` | `executor.py:49` | **YES** | assumed 0.0 if no snapshot |
| Drawdown-based scaling | `allocator.py:32` | `portfolio_manager.py:48` | **PARTIALLY** | unrealized P&L not counted; bankroll static |

---

## Call 1 Complete — Findings Summary

### FATAL Issues (Direct Financial Risk)

| # | Issue | Location | Evidence |
|---|---|---|---|
| F1 | `on_trade_closed()` never called — positions accumulate forever, all trading halts after 5 trades | `portfolio/risk.py:84` | grep returns exactly 1 result (definition only, no callers) |
| F2 | Daily loss circuit breaker silently broken — `import logger as lg` fails, always returns True | `portfolio/risk.py:40` | No root-level `logger.py`; `except Exception: pass` swallows the error |
| F3 | Concurrent position limit race — multiple coroutines pass check before any updates state | `pipeline.py:264` + `risk.py:52` | asyncio fire-and-forget tasks + no atomic check-act |
| F4 | Hot-path `consistency=1.0` hardcoded — consistency filter completely bypassed for all hot-path trades | `fast_classifier.py:242` | `build_classification()` sets `consistency=1.0` unconditionally |

### HIGH Issues

| # | Issue | Location |
|---|---|---|
| H1 | `is_loss_trade` flag inverted — ALL successfully executed trades submitted to cold path as "losses", corrupting LightGBM training labels | `pipeline.py:272` |
| H2 | Fresh `MarketWatcher()` in `get_unrealized_pnl()` — unrealized P&L always 0, drawdown always underestimated | `portfolio/_paper.py:142` |
| H3 | Order retry creates duplicate orders — no idempotency key, 3 retries on timeout may place 3 orders | `executor.py:144-196` |
| H4 | `ExecutionEngine._get_microstructure()` hardcoded — smart router never adapts to real spread/momentum | `execution_engine.py:83` |
| H5 | `py_clob_client` not in requirements.txt — live trading silently fails with ImportError on fresh install | `requirements.txt` |
| H6 | `kelly_table.py` and `providers/` package are dead code — HFT redesign partially wired | codebase-wide |

### MEDIUM Issues

| # | Issue | Location |
|---|---|---|
| M1 | `signal/` package name shadows stdlib `signal` module | directory name |
| M2 | `certifi` not in requirements.txt — WebSocket may fail in clean environment | `market_watcher.py:286` |
| M3 | `spacy` and `vaderSentiment` not in requirements.txt — NLP gate effectively disabled without them | `nlp_processor.py` |
| M4 | `MATCHER_MIN_SIMILARITY=0.30` too low — false-positive market matches likely | `config.py:84` |
| M5 | `Allocator.bankroll` never updated — position sizing does not adapt to growing/shrinking balance | `portfolio_manager.py:30` |
| M6 | `filter_by_categories` uses static `MARKET_CATEGORIES` list but events filtered by env-driven `SELECTED_CATEGORIES` — potential mismatch | `pipeline.py:96` vs `market_watcher.py:203` |

### LOW Issues

| # | Issue | Location |
|---|---|---|
| L1 | `classify()` sync wrapper and `detect_edge_v2()` are dead code | `signal/classifier.py`, `signal/edge_model.py` |
| L2 | `_groq_semaphore` also throttles Anthropic API calls unnecessarily | `signal/classifier.py:18` |
| L3 | `calibrator.py`, `scorer.py`, `backtest.py` never auto-run during live trading — calibration is manual-only | `observability/` |
| L4 | `portfolio/exposure_tracker.py` imported in `__init__.py` but never instantiated | `portfolio/__init__.py` |
| L5 | `tests/test_portfolio.py:8` — `import logger as lg` will fail on import (same wrong path as risk.py) | `tests/test_portfolio.py` |

---

*End of Call 1. Call 2 covers Phases 4–7: External APIs, Logging, Paper vs Live, Deployment.*

---

# SYSTEM AUDIT — CALL 2
## Phases 4–7: External APIs, Logging, Paper vs Live, Deployment

---

## PHASE 4: EXTERNAL DEPENDENCY AUDIT

---

### LLM API (Groq / Anthropic)

**No timeout on API calls — `signal/classifier.py` lines 74–80:**
```python
resp = await client.chat.completions.create(
    model=config.CLASSIFICATION_MODEL,
    messages=[...],
    max_tokens=200,
    temperature=0.2,
)
```
There is no `timeout=` parameter. The `_groq_semaphore` is set to 9 permits. If 9 Groq requests hang simultaneously (e.g., Groq has a partial outage where connections are accepted but responses never arrive), the semaphore is permanently exhausted. Every subsequent classification call blocks forever waiting for a permit that will never be released. The system appears to be running — news events are ingested, matched, and queued — but zero trades execute. **This is a silent failure.**

**`openai` package missing from `requirements.txt`:**
`signal/classifier.py:10–12` imports `from openai import AsyncOpenAI` when `USE_GROQ` is True. On a fresh install `pip install -r requirements.txt`, the `openai` package is not installed. The `except Exception: return None` at line ~55 silently catches the `ImportError`. All classification passes return None; `classify_async()` falls back to NEUTRAL on every event. The system runs but never trades.

**What happens at exact 0.5 probability:**
`signal/edge_model.py` `compute_edge()` uses `abs(p_true - p_market) > config.EDGE_THRESHOLD` (default 0.03). If LLM returns 0.5 and market is at 0.47, edge = 0.03 — exactly at threshold. The check is `>` not `>=`, so 0.03 does **not** pass. Edge = 0.03 is silently dropped. This is correct behavior, but it means the threshold is exclusive and borderline signals are discarded.

**What happens on HTTP 429 (rate limit):**
No specific 429 handling exists. The `openai` client raises `openai.RateLimitError`. This is caught by the bare `except Exception: return None` in `_classify_single_pass()`. The pass returns None, contributing to NEUTRAL on that pass. With 3 passes and all returning None on a rate-limit storm, the signal is NEUTRAL and skipped. **This is safe but silent** — no warning is logged and the rate limit is never surfaced to the operator.

**What happens on HTTP 500:**
Same path as 429 — caught by `except Exception`, returns None, aggregates to NEUTRAL. Silent.

**API key validation on startup:**
`config.py` loads keys at module level. `cli.py`'s `cmd_verify()` only checks `if not config.GROQ_API_KEY` — key presence, not key validity. No test call is made. A rotated or invalid key will not be detected until the first live classification attempt, at which point the error is silently swallowed.

---

### News Sources

Seven sources are defined in `ingestion/news_stream.py`:

| # | Source | Method | Notes |
|---|--------|--------|-------|
| 1 | RSS feeds (14 URLs in config.py) | feedparser polling | ~5-min interval |
| 2 | NewsAPI | HTTP REST | Requires NEWSAPI_KEY |
| 3 | Reddit | pushshift/HTTP | r/worldnews, r/politics |
| 4 | GNews | HTTP REST | Requires GNEWS_API_KEY |
| 5 | GDELT | HTTP REST | Free, no key |
| 6 | Twitter/X | Tweepy v2 streaming | Disabled on first 429 |
| 7 | Telegram | Bot polling | Requires TELEGRAM_BOT_TOKEN |

**Source failure behavior:**
Each source runs as an independent coroutine via `asyncio.gather(return_exceptions=True)` in `NewsAggregator.run()`. If one source throws an exception, the others continue. The pipeline continues on remaining sources.

**Deduplication:**
`_dedup_router()` uses `headline[:80].lower()` as cache key with a 1-hour TTL. This deduplicates identical or near-identical headlines from multiple sources. However: two headlines about the same event with different wording (e.g., AP vs Reuters) will **not** be deduplicated and can trigger two separate signals on the same market.

**Staleness threshold:**
`news_stream.py` does not enforce a staleness cutoff at ingestion. The NLP processor checks `age_seconds` but only affects `relevance` score. The main gate is `config.NLP_MIN_IMPACT` (default 0.10) which could still pass a 6-hour-old article.

**`event.age_seconds()` uses `received_at` not `published_at`:**
`NewsEvent.age_seconds()` computes `time.time() - self.received_at`. For RSS articles published hours ago but ingested now, age_seconds ≈ 0 (just received). A 5-hour-old Reuters article polled on first startup will appear as breaking news with age = 0 seconds. The NLP decay lambda will not penalize it. The LLM will classify it. The system will trade on stale news.

**Twitter permanent 429 disable:**
In `_stream_twitter()`, on `tweepy.errors.TooManyRequests`, the code logs a warning and `return`s permanently. Twitter streaming is dead for the session. No reconnect attempt, no alert.

**Telegram token in log strings:**
`news_stream.py` constructs the Telegram polling URL as `f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"`. This URL string appears in exception messages that are passed to `log.error(...)`. If log level is ERROR or below and logs are written to disk or shipped to a log aggregator, the bot token is exposed in plaintext.

---

### Polymarket / Kalshi APIs

**Polymarket — no idempotency key:**
`execution/executor.py` `_execute_live()` constructs `OrderArgs(...)` with no client order ID. The retry loop (`ORDER_RETRY_ATTEMPTS = 3`) can fire the same order up to 3 times. If the first attempt succeeds but the response times out before the client reads it, the retry will place a second order. This is a **duplicate order risk**.

**Kalshi — idempotency correct:**
`execution/kalshi_executor.py` uses `client_order_id=str(uuid4())` generated once before the retry loop. Retries reuse the same UUID. The Kalshi API will deduplicate. This is safe.

**Polymarket order timeout behavior:**
No explicit timeout is set on `py_clob_client` calls. On a network timeout, `requests.exceptions.Timeout` (or similar) propagates to the retry loop. The retry fires again — potentially placing a duplicate.

**Market resolves mid-trade:**
No check for market resolution state at order placement time. If a market resolves between signal fire and order fill, the Polymarket API will reject the order with an error. This is caught by `except Exception` in the retry loop and logged. Final result: `TradeResult(success=False, status="error")`. Risk counters are not incremented. Safe.

**Credential validation on startup:**
`cmd_verify()` in `cli.py` checks key string presence only. No test API call is made for Polymarket or Kalshi on startup.

---

## PHASE 5: LOGGING AND OBSERVABILITY AUDIT

---

**Trade logging completeness:**
`observability/logger.py` `log_trade()` writes: timestamp, market_id, market_question, signal_source, llm_confidence, order_size, fill_price (recorded as 0.0 — never updated from actual fill), pnl (recorded as 0.0 at open). The `update_trade_pnl()` function exists but is never called from the pipeline — actual fill price and P&L are never persisted to the DB.

**Skipped trade logging:**
The pipeline logs skipped trades via `log.debug(...)` only. Debug messages are suppressed by default (logging level is typically INFO in production). Skipped trades due to risk gates, NLP filter, or low edge produce **no INFO-level record** and are invisible in production logs.

**Risk rule trigger logging:**
`portfolio/risk.py` `can_trade_daily()` logs a warning via `log.warning()` — but only if the broken import `import logger as lg` is bypassed (it's in a `try/except` that catches ModuleNotFoundError). The warning goes to the Python logger, not the SQLite DB. No structured record of "daily limit hit at $X" is persisted.

**Log destination:**
SQLite DB at `observability/logger.py` `DB_PATH` for trade records. Python `logging` module to stdout for runtime logs. **No file handler is configured anywhere in the codebase.** If the terminal is closed or output is not redirected, all runtime logs are lost. The SQLite DB survives process restarts.

**Last 60 seconds recoverability:**
SQLite trade records are written synchronously and survive crashes. Python logger stdout is lost unless piped. For a crash mid-trade (after DB write but before fill confirmation), the trade record exists with fill_price=0 and pnl=0.

**Sensitive data in logs:**
- Telegram bot token exposed in exception log messages (described in Phase 4)
- Account balance and position sizes are logged at INFO level in `portfolio/risk.py` (when the import is fixed)
- API keys are NOT logged (config values are never passed to logger)

**Log rotation:**
No `RotatingFileHandler` or `TimedRotatingFileHandler` is configured. Since there is no file handler at all, there is no disk space risk from log files specifically. The SQLite DB will grow unbounded — with 100 trades/day at ~500 bytes/record, 30-day growth is ~1.5MB, which is negligible.

---

## PHASE 6: PAPER TRADING vs LIVE TRADING GAP ANALYSIS

---

**Mode switching:**
`config.DRY_RUN` is the primary flag (loaded from env). `cli.py watch --live` sets `config.DRY_RUN = False` directly at line 53 **without** going through SafetyGuard. SafetyGuard is defined in `control/safety_guard.py` with a confirmation prompt and checks, but it is bypassed by the CLI flag path.

**Code paths that only execute in live mode:**
1. `execution/executor.py` `_execute_live()` — only reached when `not config.DRY_RUN and not self.paper`
2. `execution/kalshi_executor.py` `_execute_live()` — same condition
3. `portfolio/_paper.py` `_simulate_fill()` — only in paper mode (opposite)

**Paper trading assumptions that won't hold live:**
1. **Instant fills at yes_price** — `_paper.py` fills at `market.yes_price` with no slippage model. Live orders route through the CLOB and may partially fill or miss entirely.
2. **No spread cost** — paper P&L uses mid-price. Live fills include spread.
3. **Full liquidity** — paper assumes any size can fill. Live order book may have insufficient depth.
4. **No gas/fee cost** — Polymarket charges ~1% maker/taker fees. Paper doesn't model this.
5. **Instant settlement** — paper marks the trade closed immediately. Live trades remain open until market resolution.

**P&L separation:**
`portfolio/_paper.py` tracks paper positions separately from `execution/executor.py` live positions. They write to different data structures. The SQLite logger writes all trades (paper and live) to the same `trades` table with no `mode` column. **Paper and live P&L are mixed in the DB.** `get_daily_pnl()` will sum both. This means if you paper trade during the day and then switch to live, the daily loss counter already reflects paper losses.

**Steps to switch paper → live (undocumented gaps):**
1. Set `DRY_RUN=false` in `.env` or use `--live` flag
2. Set valid Polymarket credentials (POLYMARKET_PRIVATE_KEY etc.)
3. **UNDOCUMENTED**: Must manually clear `RiskManager` state — it retains paper trade position counts and category exposure from the paper session, causing live trading to start with artificial position limits already consumed
4. **UNDOCUMENTED**: Must clear or tag SQLite records so daily P&L counter starts clean

---

## PHASE 7: ENVIRONMENTAL AND DEPLOYMENT AUDIT

---

**Environment variables required:**

| Variable | Validated on Startup | Missing Behavior | Safe Default |
|----------|---------------------|-----------------|--------------|
| `ANTHROPIC_API_KEY` | No — string check only in cli.py | Silent — falls back to Groq if GROQ_API_KEY set | None |
| `GROQ_API_KEY` | No | All classification returns NEUTRAL | None |
| `POLYMARKET_PRIVATE_KEY` | No | Live execution crashes at runtime | None |
| `POLYMARKET_API_KEY` | No | Same | None |
| `POLYMARKET_API_SECRET` | No | Same | None |
| `POLYMARKET_API_PASSPHRASE` | No | Same | None |
| `KALSHI_EMAIL` or `KALSHI_API_KEY_ID` | No | KALSHI_ENABLED=False, silently skips | None |
| `KALSHI_PRIVATE_KEY_PATH` | No | Kalshi execution crashes at runtime | None |
| `GNEWS_API_KEY` | No | GNews source silently disabled | None |
| `NEWSAPI_KEY` | No | NewsAPI source silently disabled | None |
| `TWITTER_BEARER_TOKEN` | No | Twitter source silently disabled | None |
| `TELEGRAM_BOT_TOKEN` | No | Telegram source silently disabled | None |
| `DRY_RUN` | No | Defaults to "true" | "true" |
| `BANKROLL_USD` | No | Defaults to 1000.0 | 1000.0 |
| `DAILY_LOSS_LIMIT_USD` | No | Defaults to 100.0 | 100.0 |
| `MAX_BET_USD` | No | Defaults to 25.0 | 25.0 |

**Python version:**
Not enforced anywhere. Code uses `from __future__ import annotations`, walrus operator, and `asyncio.TaskGroup`-style patterns. Requires Python 3.10+. No `.python-version`, no `pyproject.toml` `requires-python`, no runtime check.

**Dependencies with no version pins:**
All dependencies in `requirements.txt` use `>=` (lower bound only). `sentence-transformers>=2.7.0` could install 4.x which has breaking API changes. `lightgbm>=4.3.0` could install 5.x. No upper bounds.

**Missing from `requirements.txt`:**
- `openai` — required when `USE_GROQ=True` (current default config)
- `fastapi` — required by `api.py`
- `uvicorn` — required to serve `api.py`
- `certifi` — imported in `ingestion/market_watcher.py`
- `spacy` — imported in `signal/nlp_processor.py` (optional but undocumented)

**Duplicate process guard:**
None. Running `python cli.py watch` twice creates two instances both writing to the same SQLite DB, both connecting to the same WebSocket feed, both placing orders. No file lock, no PID file, no port conflict guard.

**SIGTERM handling:**
`pipeline.py` `run_pipeline_v2()` catches `KeyboardInterrupt` only. `SIGTERM` (sent by `systemd`, Docker, or `kill`) propagates as an unhandled exception, terminating the event loop immediately. Open positions are not closed. No cleanup handler runs. Any in-flight order submissions are abandoned without confirmation.

**RiskManager state on restart:**
`RiskManager.instance()` initializes `_open_positions = {}`, `_daily_loss_usd = 0.0`, `_consecutive_losses = 0` from scratch every time. `get_daily_pnl()` in `observability/logger.py` reads from SQLite and would give the correct daily P&L — but `RiskManager` never calls it on init. The daily loss counter **resets to 0.0 on every restart**, defeating the circuit breaker. The system can be restarted to reset the daily loss limit.

**Graceful shutdown:**
No `atexit`, no `signal.signal(signal.SIGTERM, ...)`, no `try/finally` around the main event loop beyond KeyboardInterrupt. Docker `SIGTERM` → process dies hard.

---

*End of Call 2. Call 3 covers Phases 8–10: Fix Matrix, Auto-Fix, Scorecard.*

---

# SYSTEM AUDIT — CALL 3
## Phases 8–10: Fix Priority Matrix, Auto-Fix, System Health Scorecard

---

## PHASE 8: FIX PRIORITY MATRIX

```
┌────┬──────────────────────────────────────────────────────────────┬──────────┬────────────┐
│ #  │ Issue                                                        │ Severity │ Fix Time   │
├────┼──────────────────────────────────────────────────────────────┼──────────┼────────────┤
│ F1 │ on_trade_closed() never called — positions accumulate        │ FATAL    │ 2h         │
│    │ forever; system blocks all trading after 5 positions         │          │            │
│ F2 │ `import logger as lg` in risk.py — ModuleNotFoundError       │ FATAL    │ 0.5h       │
│    │ silently caught; daily loss circuit breaker always True      │          │            │
│ F3 │ RiskManager daily_loss resets to 0 on restart — circuit      │ FATAL    │ 1h         │
│    │ breaker defeated by process restart                          │          │            │
│ F4 │ _groq_semaphore permanently exhausted on 9 hung requests     │ FATAL    │ 1h         │
│    │ — all classification silently blocks forever                 │          │            │
├────┼──────────────────────────────────────────────────────────────┼──────────┼────────────┤
│ H1 │ is_loss_trade flag inverted in pipeline.py:272 — every       │ HIGH     │ 0.5h       │
│    │ successful trade submitted to cold path as a "loss"          │          │            │
│ H2 │ Polymarket retries have no idempotency key — 3 retries       │ HIGH     │ 1h         │
│    │ can place 3 duplicate orders                                 │          │            │
│ H3 │ Concurrent asyncio tasks + non-atomic check-then-act on      │ HIGH     │ 2h         │
│    │ RiskManager — two events can both pass position limit check  │          │            │
│ H4 │ get_unrealized_pnl() creates fresh MarketWatcher with        │ HIGH     │ 1h         │
│    │ no snapshots — always returns 0.0; drawdown permanently      │          │            │
│    │ underestimated, drawdown scaling never activates             │          │            │
│ H5 │ consistency=1.0 hardcoded in fast_classifier                 │ HIGH     │ 0.5h       │
│    │ build_classification() — CONSISTENCY_THRESHOLD bypassed      │          │            │
│    │ for all hot-path trades                                      │          │            │
│ H6 │ event.age_seconds() uses received_at not published_at        │ HIGH     │ 1h         │
│    │ — 5-hour-old RSS articles appear as age=0, treated as        │          │            │
│    │ breaking news, NLP decay never applies                       │          │            │
│ H7 │ `import broadcaster` wrong in api.py:275 — NameError on      │ HIGH     │ 0.5h       │
│    │ first WebSocket /ws/signals connection                       │          │            │
│ H8 │ openai package missing from requirements.txt — on fresh      │ HIGH     │ 0.5h       │
│    │ install, all Groq classification silently returns NEUTRAL    │          │            │
│ H9 │ No timeout on Groq/Anthropic API calls — hung requests       │ HIGH     │ 1h         │
│    │ exhaust semaphore, blocking all future classification         │          │            │
│ H10│ SIGTERM not handled — Docker/systemd kills process mid-trade  │ HIGH     │ 1h         │
│    │ with no cleanup, open positions abandoned                    │          │            │
│ H11│ cli.py watch --live bypasses SafetyGuard entirely —          │ HIGH     │ 0.5h       │
│    │ sets DRY_RUN=False directly without confirmation             │          │            │
│ H12│ RiskManager not restored from DB on startup — starts with    │ HIGH     │ 2h         │
│    │ 0 positions even if 5 are open in DB; limits are phantom     │          │            │
├────┼──────────────────────────────────────────────────────────────┼──────────┼────────────┤
│ M1 │ update_trade_pnl() never called — fill_price=0, pnl=0        │ MEDIUM   │ 2h         │
│    │ in all DB trade records; P&L reporting always wrong          │          │            │
│ M2 │ Skipped trades only logged at DEBUG — invisible in           │ MEDIUM   │ 1h         │
│    │ production; impossible to audit why system didn't trade      │          │            │
│ M3 │ Paper and live trades written to same DB table with no       │ MEDIUM   │ 1h         │
│    │ mode column — P&L is mixed; daily loss counter is wrong      │          │            │
│    │ during paper→live transitions                                │          │            │
│ M4 │ execution_engine._get_microstructure() hardcoded to          │ MEDIUM   │ 1h         │
│    │ (0.04, 0.0) — smart router never adapts to actual spread     │          │            │
│ M5 │ Telegram bot token exposed in exception log messages         │ MEDIUM   │ 0.5h       │
│ M6 │ No file log handler — runtime logs lost if terminal closes   │ MEDIUM   │ 0.5h       │
│ M7 │ All deps unpinned (>= only) — silent breaking changes        │ MEDIUM   │ 0.5h       │
│    │ on next install                                              │          │            │
│ M8 │ Paper P&L includes fee-free fills, no spread model,          │ MEDIUM   │ 3h         │
│    │ full-size instant fills — paper performance misleading        │          │            │
│ M9 │ No startup credential validation via test API call           │ MEDIUM   │ 1h         │
│ M10│ Twitter streaming permanently disabled on first 429          │ MEDIUM   │ 0.5h       │
│    │ with no reconnect attempt                                    │          │            │
├────┼──────────────────────────────────────────────────────────────┼──────────┼────────────┤
│ L1 │ providers/ package entirely orphaned — dead code             │ LOW      │ 0.5h       │
│ L2 │ kelly_table.py never imported — dead code                    │ LOW      │ 0.25h      │
│ L3 │ classify() sync wrapper and detect_edge_v2() are dead        │ LOW      │ 0.25h      │
│ L4 │ portfolio/exposure_tracker.py imported but never used        │ LOW      │ 0.25h      │
│ L5 │ tests/test_portfolio.py:8 import logger as lg will fail      │ LOW      │ 0.25h      │
│ L6 │ No Python version enforcement (requires 3.10+)               │ LOW      │ 0.25h      │
│ L7 │ No duplicate-process guard — two instances corrupt DB        │ LOW      │ 1h         │
│ L8 │ _groq_semaphore also throttles Anthropic calls               │ LOW      │ 0.5h       │
│ L9 │ SIZING_K hardcoded in config (not env var)                   │ LOW      │ 0.25h      │
└────┴──────────────────────────────────────────────────────────────┴──────────┴────────────┘
```

---

## PHASE 9: AUTO-FIX PLAN

---

### FATAL FIXES

---

#### F1 — `on_trade_closed()` never called

**Broken code — `pipeline.py:263–269`:**
```python
if result.success and result.filled_size > 0:
    self.risk.on_trade_opened(
        condition_id=market.condition_id,
        category=market.category,
        amount_usd=result.filled_size,
    )
```
Positions are opened and never closed. After 5 trades, `can_open_position()` returns False permanently for the session.

**Minimum viable fix** — add 24h position expiry sweep to `portfolio/risk.py`:

Step 1: Change `_open_positions` to store `(amount, opened_at_monotonic)` tuples.
```python
# portfolio/risk.py — in __init__:
self._open_positions: dict[str, tuple[float, float]] = {}
```

Step 2: Add sweep helper and call it in `can_open_position()`:
```python
import time as _time

def _sweep_expired_positions(self) -> None:
    now = _time.monotonic()
    expired = [
        cid for cid, (amt, opened_at) in self._open_positions.items()
        if now - opened_at > 86400
    ]
    for cid in expired:
        del self._open_positions[cid]

def can_open_position(self, condition_id: str, category: str, amount_usd: float) -> bool:
    self._sweep_expired_positions()
    # ... rest of existing logic unchanged
```

Step 3: Update `on_trade_opened()` to store the timestamp:
```python
def on_trade_opened(self, condition_id: str, category: str, amount_usd: float) -> None:
    self._open_positions[condition_id] = (amount_usd, _time.monotonic())
    # ... rest of existing logic unchanged
```

Step 4: Update all reads of `_open_positions` that expect a plain float:
```python
# Wherever _open_positions[cid] is read as a dollar amount, change to:
amount = self._open_positions[cid][0]
```

Step 5 (permanent fix): In `portfolio/portfolio_manager.py`, after a position closes, call:
```python
RiskManager.instance().on_trade_closed(
    condition_id=position.condition_id,
    category=position.category,
    pnl_usd=realized_pnl,
)
```

**Test:** Run 6 paper trades with `MAX_CONCURRENT_POSITIONS=5`; confirm 6th trade executes after `on_trade_closed()` is called on the 1st.

---

#### F2 — `import logger as lg` silently breaks daily loss circuit breaker

**Broken code — `portfolio/risk.py:40`:**
```python
try:
    import logger as lg
    _logger_available = True
except Exception:
    _logger_available = False
```
No `logger.py` exists at root level. `_logger_available = False` forever. The `lg.log_trade(...)` calls inside `on_trade_closed()` never execute.

**Fixed code — `portfolio/risk.py:40`:**
```python
try:
    from observability import logger as lg
    _logger_available = True
except Exception:
    _logger_available = False
```

**Also fix `tests/test_portfolio.py:8`:**
```python
# Before:
import logger as lg
# After:
from observability import logger as lg
```

**Test:** `python -c "from portfolio.risk import RiskManager; print(RiskManager._logger_available)"` should print `True`.

---

#### F3 — Daily loss counter resets to 0 on restart

**Broken code — `portfolio/risk.py` `__init__`:**
```python
self._daily_loss_usd: float = 0.0
```

**Fixed code — add to `RiskManager.__init__()` after setting defaults:**
```python
import datetime as _dt
try:
    from observability import logger as _obs_logger
    today = _dt.date.today().isoformat()
    persisted_pnl = _obs_logger.get_daily_pnl(today)
    self._daily_loss_usd = abs(min(0.0, persisted_pnl))
except Exception:
    self._daily_loss_usd = 0.0
```

`get_daily_pnl()` already exists in `observability/logger.py` and queries SQLite by date — it survives restarts.

**Test:** Persist a $50 paper loss to SQLite; restart the process; confirm `RiskManager.instance()._daily_loss_usd == 50.0`.

---

#### F4 — `_groq_semaphore` permanently exhausted on hung requests

**Broken code — `signal/classifier.py` (no timeout on API call):**
```python
resp = await client.chat.completions.create(
    model=config.CLASSIFICATION_MODEL,
    messages=[...],
    max_tokens=200,
    temperature=0.2,
)
```

**Fixed code — wrap with `asyncio.wait_for` and improve error logging:**
```python
try:
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=config.CLASSIFICATION_MODEL,
            messages=[...],
            max_tokens=200,
            temperature=0.2,
        ),
        timeout=15.0,
    )
except asyncio.TimeoutError:
    log.warning(f"[classifier] LLM call timed out after 15s")
    return None
except Exception as exc:
    if "429" in str(exc) or "RateLimitError" in type(exc).__name__:
        log.warning(f"[classifier] Rate limited: {exc!r}")
    else:
        log.warning(f"[classifier] LLM call failed: {exc!r}")
    return None
```

**Test:** Mock the LLM client to hang for 20s; confirm `_classify_single_pass()` returns None after 15s and the semaphore value is unchanged post-call (permit was released).

---

### HIGH FIXES

---

#### H1 — `is_loss_trade` flag inverted

**Broken code — `pipeline.py:272`:**
```python
is_loss = result.filled_size > 0 and result.status not in ("filled", "partial")
```
Actual success statuses are `"executed"`, `"dry_run"`, `"paper"`. Every successful trade is marked as a loss.

**Fixed code:**
```python
is_loss = result.filled_size == 0 or result.status in ("error", "rejected", "skipped")
```

**Test:** Place a paper trade; assert `is_loss_trade=False` in the `ColdPathJob` submitted.

---

#### H2 — Polymarket retries duplicate orders

**Broken code — `execution/executor.py` `_execute_live()` (no client_order_id before retry loop).**

**Fixed code:**
```python
import uuid

client_order_id = str(uuid.uuid4())  # one ID, reused across all retry attempts

for attempt in range(config.ORDER_RETRY_ATTEMPTS):
    try:
        order_args.client_order_id = client_order_id
        result = self._client.create_order(order_args)
        ...
```

**Test:** Mock client to fail on attempt 1 and succeed on attempt 2; assert both calls used the identical `client_order_id`.

---

#### H3 — Concurrent position limit race condition

**Fixed code — add `asyncio.Lock` to `RiskManager` and expose atomic `try_open_position()`:**

```python
# portfolio/risk.py — in __init__:
self._trade_lock: asyncio.Lock = asyncio.Lock()

# New method:
async def try_open_position(
    self, condition_id: str, category: str, amount_usd: float
) -> bool:
    """Atomic check-and-reserve. Returns True if the slot was acquired."""
    async with self._trade_lock:
        if not self.can_open_position(condition_id, category, amount_usd):
            return False
        self.on_trade_opened(condition_id, category, amount_usd)
        return True
```

In `portfolio/portfolio_manager.py` and `portfolio/risk_engine.py`, replace:
```python
if risk.can_open_position(...):
    risk.on_trade_opened(...)
```
with:
```python
if not await risk.try_open_position(...):
    return  # slot not acquired
```

**Test:** Fire 10 concurrent `_process_market()` coroutines with `MAX_CONCURRENT_POSITIONS=5`; assert exactly 5 succeed.

---

#### H4 — `get_unrealized_pnl()` always returns 0

**Broken code — `portfolio/_paper.py:142` creates a fresh `MarketWatcher()` with no price snapshots.**

**Fixed code — inject the shared watcher at construction:**

```python
# portfolio/_paper.py — update __init__:
def __init__(self, watcher=None):
    self._watcher = watcher
    # ... rest unchanged

def get_unrealized_pnl(self) -> float:
    if self._watcher is None:
        return 0.0
    total = 0.0
    for pos in self._positions.values():
        snap = self._watcher.get_snapshot(pos.condition_id)
        if snap is None:
            continue
        current_price = snap.yes_price if pos.side == "YES" else (1.0 - snap.yes_price)
        total += (current_price - pos.fill_price) * pos.size_usd
    return total
```

In `pipeline.py`, pass `self.watcher` wherever `PaperPortfolio` is instantiated.

**Test:** Open a paper position at 0.40; update watcher snapshot to 0.55; assert `get_unrealized_pnl() > 0`.

---

#### H5 — `consistency=1.0` hardcoded in fast_classifier

**Broken code — `signal/fast_classifier.py` `build_classification()`:**
```python
consistency=1.0,  # hardcoded — bypasses CONSISTENCY_THRESHOLD
```

**Fixed code — use a configurable default:**
```python
# config.py — add:
HOT_PATH_CONSISTENCY = float(os.getenv("HOT_PATH_CONSISTENCY", "0.70"))

# signal/fast_classifier.py — build_classification():
consistency=config.HOT_PATH_CONSISTENCY,
```

**Test:** Set `HOT_PATH_CONSISTENCY=0.50` and `CONSISTENCY_THRESHOLD=0.60`; confirm hot-path trades are filtered.

---

#### H6 — `event.age_seconds()` uses received_at not published_at

**Broken code — `ingestion/news_stream.py` `NewsEvent.age_seconds()`:**
```python
def age_seconds(self) -> float:
    return time.time() - self.received_at
```

**Fixed code:**
```python
@dataclass
class NewsEvent:
    ...
    published_at: float = 0.0  # unix timestamp from source

def age_seconds(self) -> float:
    if self.published_at > 0:
        return time.time() - self.published_at
    return time.time() - self.received_at
```

In RSS ingest loop, populate `published_at`:
```python
pub = entry.get("published_parsed") or entry.get("updated_parsed")
published_at = time.mktime(pub) if pub else 0.0
event = NewsEvent(..., published_at=published_at)
```

**Test:** Parse an RSS entry with `published_parsed` set to 3 hours ago; assert `event.age_seconds() >= 10800`.

---

#### H7 — `import broadcaster` wrong in api.py

**Broken code — `api.py:275`:**
```python
import broadcaster
```

**Fixed code:**
```python
from observability import broadcaster
```

**Test:** Start FastAPI server; connect WebSocket to `/ws/signals`; assert no `NameError`.

---

#### H8 — `openai` missing from requirements.txt

**Fixed code — add to `requirements.txt`:**
```
openai>=1.30.0
```

**Test:** Fresh virtualenv; `pip install -r requirements.txt`; `python -c "from openai import AsyncOpenAI"` exits with code 0.

---

#### H9 — No LLM API timeout
Covered by F4 fix (same `asyncio.wait_for` wrapper). No separate change needed.

---

#### H10 — SIGTERM not handled

**Broken code — `pipeline.py:321–326`:** only catches `KeyboardInterrupt`.

**Fixed code:**
```python
import signal as _signal

def run_pipeline_v2(dry_run: bool | None = None):
    pipeline = Pipeline(dry_run=dry_run)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_shutdown(sig, frame):
        log.warning(f"[pipeline] Signal {sig} — shutting down")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    _signal.signal(_signal.SIGTERM, _handle_shutdown)
    _signal.signal(_signal.SIGINT, _handle_shutdown)

    try:
        loop.run_until_complete(pipeline.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("[pipeline] Shutdown complete")
    finally:
        risk = RiskManager.instance()
        log.info(f"[pipeline] Open positions at shutdown: {list(risk._open_positions.keys())}")
        loop.close()
```

**Test:** Start pipeline; `kill -SIGTERM <pid>`; assert "Shutdown complete" in logs and process exits 0.

---

#### H11 — `cli.py watch --live` bypasses SafetyGuard

**Broken code — `cli.py:53`:**
```python
config.DRY_RUN = False
```

**Fixed code:**
```python
from control.safety_guard import SafetyGuard
guard = SafetyGuard()
if not guard.confirm_live_trading():
    log.error("[cli] Live trading not confirmed — aborting")
    return
config.DRY_RUN = False
```

**Test:** Run `cli.py watch --live` and decline the SafetyGuard prompt; assert `config.DRY_RUN` remains True.

---

#### H12 — RiskManager not restored from DB on startup

**Fixed code — add to `RiskManager.__init__()` after defaults are set:**
```python
try:
    from observability import logger as _obs_logger
    open_trades = _obs_logger.get_open_trades()
    for trade in open_trades:
        self._open_positions[trade.condition_id] = (trade.amount_usd, _time.monotonic())
        cat = trade.category or "uncategorized"
        self._category_exposure[cat] = (
            self._category_exposure.get(cat, 0.0) + trade.amount_usd
        )
    if open_trades:
        log.info(f"[risk] Restored {len(open_trades)} open positions from DB")
except Exception as exc:
    log.warning(f"[risk] Could not restore positions: {exc!r}")
```

Add `get_open_trades()` to `observability/logger.py`:
```python
from types import SimpleNamespace

def get_open_trades() -> list:
    """Return trades with no recorded close (pnl IS NULL)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT condition_id, amount_usd, category FROM trades WHERE pnl IS NULL"
        ).fetchall()
    return [
        SimpleNamespace(condition_id=r[0], amount_usd=r[1], category=r[2])
        for r in rows
    ]
```

**Test:** Write 3 open trade records to SQLite with `pnl=NULL`; restart process; assert `len(RiskManager.instance()._open_positions) == 3`.

---

### MEDIUM FIXES (one-line explanation each)

**M1** — In `portfolio/portfolio_manager.py`, call `observability.logger.update_trade_pnl(trade_id, fill_price, realized_pnl)` after position resolution to persist actual fill price and P&L.

**M2** — In `pipeline.py`, change all `log.debug(...)` skips that occur after market matching to `log.info(...)` so post-match filter decisions are visible in production logs.

**M3** — Add `mode TEXT DEFAULT 'paper'` column to the `trades` table in `observability/logger.py`; pass `mode="live"` or `mode="paper"` through `log_trade()`; filter by mode in `get_daily_pnl()`.

**M4** — In `execution/execution_engine.py` `_get_microstructure()`, replace the hardcoded `return (0.04, 0.0)` with a live lookup from `watcher.get_snapshot(market_id).spread` so the smart router adapts to actual market conditions.

**M5** — In `ingestion/news_stream.py`, remove the Telegram polling URL from all exception log strings; log only the exception message, not the URL containing the bot token.

**M6** — Add a `RotatingFileHandler` to the root logger in `cli.py` or wherever logging is configured: `logging.handlers.RotatingFileHandler("logs/pipeline.log", maxBytes=10_000_000, backupCount=5)`.

**M7** — Run `pip freeze` in the current working virtualenv and lock all package versions in `requirements.txt` with `==` pins for the next deployment.

**M8** — In `portfolio/_paper.py` `_simulate_fill()`, apply `PAPER_FEE_RATE = 0.01` as a deduction and a configurable slippage constant `PAPER_SLIPPAGE = 0.005` so paper P&L matches realistic live conditions.

**M9** — In `cli.py` `cmd_verify()`, after checking key presence, make a lightweight authenticated API call (e.g., `GET /markets?limit=1`) for each configured exchange and log pass/fail before starting the pipeline.

**M10** — In `ingestion/news_stream.py` `_stream_twitter()`, replace the `return` on `TooManyRequests` with an exponential backoff loop (`await asyncio.sleep(min(300, 60 * attempt))`) so the source reconnects automatically.

---

### LOW FIXES (recommended approach, no implementation needed)

**L1** — Delete `providers/__init__.py`, `providers/base.py`, `providers/kalshi.py`, `providers/polymarket.py` after confirming `grep -r "from providers"` returns no results outside the providers directory itself.

**L2** — Delete `portfolio/kelly_table.py` or archive it to `docs/` as reference material.

**L3** — Delete the `classify()` sync wrapper in `signal/classifier.py` and `detect_edge_v2()` in `signal/edge_model.py`; run tests to confirm nothing breaks.

**L4** — Either wire `ExposureTracker` into risk reporting or remove its export from `portfolio/__init__.py`.

**L5** — Change `import logger as lg` in `tests/test_portfolio.py:8` to `from observability import logger as lg`.

**L6** — Add `python_requires = ">=3.10"` to a `pyproject.toml`, or add `assert sys.version_info >= (3, 10)` at the top of `cli.py`.

**L7** — Add a PID file guard in `cli.py`: write `os.getpid()` to `/tmp/polymarket_pipeline.pid` on start, check for it before launch, register `atexit` to delete it on clean exit.

**L8** — Create separate semaphores for Groq and Anthropic in `signal/classifier.py`: `_groq_sem = asyncio.Semaphore(9)` and `_anthropic_sem = asyncio.Semaphore(5)`, selected based on `config.USE_GROQ`.

**L9** — Add `SIZING_K = float(os.getenv("SIZING_K", "0.25"))` to `config.py` and remove the hardcoded `0.25` from `portfolio/allocator.py`.

---

## PHASE 10: SYSTEM HEALTH SCORECARD

```
┌─────────────────────────────┬────────┬────────────────────────────────────────────────────┐
│ System Component            │ Score  │ Notes                                              │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Pipeline Integrity          │  3/10  │ on_trade_closed() never called (F1) — the system   │
│                             │        │ permanently blocks after 5 trades. Core pipeline    │
│                             │        │ loop is architecturally correct; state machine at   │
│                             │        │ the position lifecycle seam is broken.              │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Risk System                 │  2/10  │ Daily loss circuit breaker silently inert (F2).    │
│                             │        │ Resets to 0 on every restart (F3). Non-atomic       │
│                             │        │ check-then-act enables race through position limit  │
│                             │        │ (H3). Not restored from DB on startup (H12). All    │
│                             │        │ four layers of protection independently defective.  │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ External API Resilience     │  3/10  │ Groq semaphore exhausted by hung calls (F4). No    │
│                             │        │ LLM timeout (H9). openai missing from requirements  │
│                             │        │ breaks Groq on fresh install (H8). Polymarket       │
│                             │        │ retries create duplicate orders (H2). Twitter 429   │
│                             │        │ permanently disables source with no recovery.       │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Logging & Observability     │  4/10  │ SQLite trade persistence survives restarts — the    │
│                             │        │ one strong point. But: fill_price and pnl always    │
│                             │        │ 0 in DB (M1); skipped trades invisible at INFO (M2);│
│                             │        │ paper and live P&L mixed in same table (M3); no     │
│                             │        │ file log handler (M6); Telegram token leaks (M5).  │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Concurrency Safety          │  3/10  │ Non-atomic check-then-act on RiskManager (H3) is   │
│                             │        │ the critical gap. asyncio.gather and fire-and-forget│
│                             │        │ tasks are architecturally sound, but the shared     │
│                             │        │ state they write to has no lock. Two simultaneous   │
│                             │        │ events can bypass all position limits.              │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Paper→Live Transition       │  3/10  │ SafetyGuard bypassed by --live flag (H11).         │
│                             │        │ RiskManager state not cleared between modes (H12).  │
│                             │        │ Paper P&L excludes fees and slippage (M8). Paper    │
│                             │        │ and live trades share one DB table (M3).            │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Deployment Readiness        │  3/10  │ SIGTERM kills process mid-trade (H10). Daily loss  │
│                             │        │ counter resets on restart (F3). No process lock     │
│                             │        │ allows two instances to corrupt shared DB (L7).     │
│                             │        │ Five packages missing from requirements.txt. Python  │
│                             │        │ version unenforced. No startup credential check.   │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ OVERALL                     │  3/10  │ Four independent FATAL bugs, twelve HIGH bugs.      │
│                             │        │ No single fix is sufficient — all four FATAL issues  │
│                             │        │ must be resolved before any live capital is at risk. │
└─────────────────────────────┴────────┴────────────────────────────────────────────────────┘
```

**Score interpretation: 3/10 — Not live-ready. Structural issues need redesign.**

---

**This system is NOT ready to trade real capital because the risk management layer has four independent fatal defects — a broken import silences the daily loss circuit breaker, positions accumulate without ever being released causing permanent trade blocking after 5 trades, the daily loss counter resets to zero on every process restart making the circuit breaker defeatable by restarting, and the LLM classification semaphore can be permanently exhausted by hung API calls — any one of which alone would cause financial loss or undetected system failure.**

---

*End of prior summary (Phases 1–10).*

---

# SYSTEM AUDIT — CALL 3
## Phases 8–13: Alpha/Signal, Execution/Ingestion/Providers, Observability/Dashboard/Control, Tests/Portfolio Utilities

---

## PHASE 8: ALPHA & SIGNAL LAYER

---

### A-1 [HIGH] signal/watchlist.py — First-match shadowing inverts signal direction
**Lines:** 95–99

`WatchlistMatcher.match()` iterates `_PHRASE_INDEX` and returns on the **first** matching phrase. Because `_PHRASE_INDEX` is built from `_WATCHLIST` in insertion order, `"ceasefire"` (YES, 0.85) appears before `"ceasefire collapses"` (NO, 0.90). Any headline containing `"ceasefire collapses"` matches `"ceasefire"` first and produces a YES signal instead of NO. The same pattern affects any multi-word phrase whose prefix also appears in the watchlist.

**Fix:** Use longest-match — iterate all phrases and keep the match with `max(len(phrase))`:
```python
def match(self, headline: str) -> WatchlistHit | None:
    lower = headline.lower()
    best: WatchlistHit | None = None
    for phrase, (direction, confidence) in _PHRASE_INDEX.items():
        if phrase in lower:
            if best is None or len(phrase) > len(best.phrase):
                best = WatchlistHit(direction=direction, phrase=phrase, confidence=confidence)
    return best
```

---

### A-2 [HIGH] signal/fast_classifier.py — `time_sensitivity="instant"` not in `_HORIZON_MAP`
**Line:** 245

`build_classification()` sets `time_sensitivity="instant"` for watchlist hits. `news_alpha.py`'s `_HORIZON_MAP` only accepts `"immediate"`, `"short-term"`, and `"long-term"`. The `.get("instant", "1h")` fallback silently assigns a 1-hour horizon to watchlist hits, when the correct horizon should be 5 minutes.

**Fix:** Change to `time_sensitivity="immediate"`.

---

### A-3 [MEDIUM] signal/matcher.py — Operator precedence bug in HF token assignment
**Line:** 23

```python
hf_token = os.getenv("HF_TOKEN") or config.ANTHROPIC_API_KEY and None
```
Due to Python's `and`/`or` precedence this is `(os.getenv("HF_TOKEN")) or (config.ANTHROPIC_API_KEY and None)`. The result is accidentally correct when `HF_TOKEN` is unset, but the expression is opaque and fragile to any refactor.

**Fix:** `hf_token = os.getenv("HF_TOKEN") or None`

---

### A-4 [MEDIUM] alpha/momentum_alpha.py — Momentum baseline uses wrong anchor price
**Lines:** 91–108

The loop assigns `old_price` to every entry where `ts <= cutoff`, so at loop end `old_price` is the **most recent** entry still within the window, not the oldest. With `POLL_INTERVAL=60` and `WINDOW_SECONDS=300`, the baseline can be only 60 seconds old — effectively making a "5-minute return" a 60-second return and generating false momentum signals.

**Fix:** Use `history_in_window[0][1]` (the oldest sample) as the baseline:
```python
cutoff = time.time() - WINDOW_SECONDS
history_in_window = [(ts, p) for ts, p in self._price_history if ts >= cutoff]
if not history_in_window:
    return None
old_price = history_in_window[0][1]
current_price = self._price_history[-1][1]
return (current_price - old_price) / old_price
```

---

### A-5 [LOW] signal/cold_path.py — `asyncio.get_event_loop()` deprecated on Python 3.13
**Line:** 101

`asyncio.get_event_loop()` is deprecated in Python 3.10 and emits `DeprecationWarning` on 3.12+. The project runs Python 3.13.

**Fix:** `loop = asyncio.get_running_loop()`

---

## PHASE 9: EXECUTION, INGESTION & PROVIDERS

---

### B-1 [HIGH] execution/kalshi_executor.py — NO-side order may use wrong price field
**Lines:** 36–38, 92–94

For a NO-side order the code computes `no_price_cents = 100 - yes_ask_cents` then places `"yes_price": limit_cents` in the order body. If the Kalshi v2 API interprets `yes_price` literally for a `side="no"` order (as the YES limit, not the NO limit), orders are mispriced. Under the spec, `yes_price` for a NO buy should be the YES equivalent (`100 - no_limit`).

**Fix:** Convert correctly for NO side:
```python
if signal.side == "NO":
    body["yes_price"] = max(1, 100 - limit_cents)
```

---

### B-2 [HIGH] ingestion/markets.py — `economics` category silently missing from `_infer_category`
**Lines:** 166–182

`_infer_category()` has branches for `ai`, `crypto`, `politics`, `science`, `technology`, and `other` — but no `economics` branch. Any market referencing Fed/CPI/GDP/inflation is categorized as `"other"` and silently filtered out when `MARKET_CATEGORIES` includes `"economics"`.

**Fix:** Add an `economics` branch (before `politics` to avoid false positives on "fed"):
```python
if any(kw in combined for kw in ["fed", "federal reserve", "inflation",
                                   "interest rate", "gdp", "recession",
                                   "cpi", "fomc", "treasury"]):
    return "economics"
```

---

### B-3 [MEDIUM] providers/base.py — `get_price()` always returns `None`
**Line:** 25

`get_price()` constructs a fresh `MarketWatcher()` with an empty `snapshots` dict. The pipeline's shared watcher with live price data is not accessible via a new instance, so `get_price()` always returns `None`.

**Fix:** Require watcher injection as a parameter, or return `None` immediately with a docstring noting the dependency.

---

### B-4 [MEDIUM] ingestion/reddit_source.py — misleading `trades.db` name inside `ingestion/`
**Line:** 50

`DB_PATH = Path(__file__).parent / "trades.db"` creates a file named `trades.db` inside `ingestion/` that holds subreddit stats — not trades. This collides conceptually with the main `trades.db` in `observability/logger.py`.

**Fix:** Rename to `subreddit_stats.db`.

---

### B-5 [LOW] ingestion/scraper.py — hardcoded NewsAPI query ignores configured categories
**Line:** 127

`scrape_newsapi("AI OR artificial intelligence OR crypto OR blockchain", hours)` always queries the same topics regardless of `config.SELECTED_CATEGORIES`.

**Fix:** Build the query dynamically from `get_newsapi_queries(config.SELECTED_CATEGORIES)`.

---

## PHASE 10: OBSERVABILITY, DASHBOARD & CONTROL

---

### C-1 [FATAL] dashboard.py — `KeyError: 'edge'` crashes dashboard on first signal
**Line:** 228

`render_scanner()` accesses `s['edge']` where `s = sig['score']`, and `sig['score']` is the return value of `score_market()`. `score_market()` returns `confidence`, `reasoning`, and `relevant_headlines` — never `edge`. First real signal render crashes the dashboard loop.

**Fix:**
```python
edge_pct = f"{abs(s['confidence'] - m.yes_price):.0%}"
```

---

### C-2 [HIGH] observability/backtest.py — look-ahead bias makes all metrics invalid
**Lines:** 283–286

The backtest constructs headlines directly from the known resolution outcome:
```python
if resolved_yes:
    headline = f"Reports indicate YES outcome likely: {question[:80]}"
```
The classifier trivially classifies these pre-revealed headlines at high confidence. Every win rate, PnL, and Sharpe ratio produced is meaningless.

**Fix:** Use neutral generic headlines that do not leak outcome, or integrate a historical news archive API.

---

### C-3 [HIGH] observability/calibrator.py — missing `raise_for_status()` silently skips HTTP errors
**Lines:** 79–84

`httpx.get()` is called without `resp.raise_for_status()`. 4xx/5xx responses silently skip resolution updates; `resolved_count` stays zero with no warning.

**Fix:** Add `resp.raise_for_status()` after `httpx.get()`.

---

### C-4 [MEDIUM] observability/calibrator.py — Brier score and ECE use `materiality` as probability
**Lines:** 166, 186

`conf = float(trade.get("materiality", 0.5))` is used as the predicted probability for the Brier score and ECE calibration buckets. Materiality measures market impact (0–0.8), not the model's directional confidence. The calibration report numbers are statistically invalid.

**Fix:** Use `confidence` from the calibration table, not `materiality`.

---

### C-5 [MEDIUM] observability/metrics.py + backtest.py — Sharpe annualization factor inflates results
**Files:** `observability/metrics.py:94`, `observability/backtest.py:212`

Both files multiply per-trade P&L Sharpe by `252 ** 0.5` (the factor for daily returns). This inflates Sharpe by approximately `sqrt(trades_per_day)` and produces numbers non-comparable to any industry standard.

**Fix:** Aggregate P&Ls to daily buckets before computing Sharpe, or label as "per-trade Sharpe" without annualization.

---

### C-6 [MEDIUM] api.py — `ping_task` NameError risk in WebSocket `finally` block
**Lines:** 282–293

`ping_task` is assigned inside the `try` block. If `asyncio.create_task()` raises, `ping_task` is undefined and `ping_task.cancel()` in `finally` raises `NameError`, suppressing the original exception.

**Fix:**
```python
ping_task = None
try:
    ping_task = asyncio.create_task(_ws_ping(websocket))
    ...
finally:
    broadcaster.unsubscribe(q)
    if ping_task is not None:
        ping_task.cancel()
```

---

### C-7 [LOW] api.py — `except (WebSocketDisconnect, Exception): pass` swallows all errors
**Line:** 289

Non-disconnect exceptions are silently discarded, hiding programming errors in the WebSocket handler.

**Fix:** Add `log.debug(f"[ws] error: {e}")` for non-`WebSocketDisconnect` exceptions.

---

## PHASE 11: TESTS & PORTFOLIO UTILITIES

---

### D-1 [HIGH] tests/test_portfolio.py — `RiskManager` singleton bleeds state between tests
**Fixture:** `isolated_db`

The fixture resets `pm._portfolio = None` but does not reset `RiskManager._instance`. Risk state (consecutive losses, cooldown timers, open position counts, category exposure) bleeds across test functions. A test triggering a cooldown can cause all subsequent tests to silently skip trades.

**Fix:** Add `RiskManager._instance = None` (or equivalent) to the `isolated_db` fixture teardown.

---

### D-2 [MEDIUM] tests/test_categories.py — fragile `sys.path` injection
**Lines:** 3–4

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
```
Unnecessary given the project layout; other test files import without it. Order-dependent and duplicates the `sys.path` entry on each collection.

**Fix:** Remove lines 3–4; add `pythonpath = .` to `pytest.ini`.

---

### D-3 [LOW] portfolio/kelly_table.py — silent EV clamp with no log warning
**Lines:** 32–36

When `ev > 0.30` (max bucket), `lookup()` silently clamps to the highest-EV row. An EV far above 0.30 may indicate an upstream bug; no warning is logged.

**Fix:** Add `log.debug(f"[kelly] EV {ev:.3f} out of range, clamped")` when `i >= len(_EV_BUCKETS)`.

---

### D-4 [LOW] tests/ — no coverage for three known-critical paths
No tests for: watchlist phrase shadowing (A-1), fast_classifier horizon mapping (A-2), or Kalshi NO-price conversion (B-1). The watchlist shadowing bug would be caught by a single parametrized test.

---

## PHASE 12: FIX PRIORITY MATRIX

```
┌────┬──────────┬──────────────────────────────────────┬────────┬──────────────────────────────────────────────────────────────┐
│ ID │ Severity │ File                                 │  Line  │ Fix                                                          │
├────┼──────────┼──────────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤
│ C-1│ FATAL    │ dashboard.py                         │   228  │ Replace s['edge'] with abs(s['confidence'] - m.yes_price)    │
│ C-2│ HIGH     │ observability/backtest.py            │ 283-286│ Remove outcome-derived headlines; use neutral placeholder     │
│ A-1│ HIGH     │ signal/watchlist.py                  │  95-99 │ Longest-match: keep phrase with max(len) among all matches   │
│ B-1│ HIGH     │ execution/kalshi_executor.py         │  36-94 │ For NO side use yes_price = 100 - no_limit_cents             │
│ B-2│ HIGH     │ ingestion/markets.py                 │ 166-182│ Add economics branch to _infer_category before politics      │
│ C-3│ HIGH     │ observability/calibrator.py          │  79-84 │ Add resp.raise_for_status() after httpx.get()                │
│ D-1│ HIGH     │ tests/test_portfolio.py              │ fixture│ Reset RiskManager._instance = None in isolated_db teardown   │
│ A-2│ HIGH     │ signal/fast_classifier.py            │   245  │ Change time_sensitivity="instant" to "immediate"             │
│ C-4│ MEDIUM   │ observability/calibrator.py          │ 166,186│ Use confidence column as probability, not materiality        │
│ C-5│ MEDIUM   │ observability/metrics.py+backtest.py │  94,212│ Aggregate to daily P&L before Sharpe; drop 252 factor        │
│ B-3│ MEDIUM   │ providers/base.py                    │    25  │ get_price() always returns None — require watcher injection  │
│ C-6│ MEDIUM   │ api.py                               │ 282-293│ Initialize ping_task = None before try block                 │
│ A-4│ MEDIUM   │ alpha/momentum_alpha.py              │  91-108│ Use history_in_window[0] as baseline, not most-recent entry  │
│ A-3│ MEDIUM   │ signal/matcher.py                    │    23  │ Simplify: hf_token = os.getenv("HF_TOKEN") or None           │
│ B-4│ MEDIUM   │ ingestion/reddit_source.py           │    50  │ Rename trades.db → subreddit_stats.db                       │
│ A-5│ LOW      │ signal/cold_path.py                  │   101  │ get_event_loop() → get_running_loop()                        │
│ B-5│ LOW      │ ingestion/scraper.py                 │   127  │ Build NewsAPI query from get_newsapi_queries(SELECTED_CATS)  │
│ C-7│ LOW      │ api.py                               │   289  │ Log non-WebSocketDisconnect exceptions at debug level        │
│ D-2│ LOW      │ tests/test_categories.py             │   3-4  │ Remove sys.path injection; add pythonpath=. to pytest.ini    │
│ D-3│ LOW      │ portfolio/kelly_table.py             │  32-36 │ Add log.debug when EV clamped out of range                   │
│ D-4│ LOW      │ tests/                               │   —    │ Add tests for watchlist shadowing, horizon mapping, NO price │
└────┴──────────┴──────────────────────────────────────┴────────┴──────────────────────────────────────────────────────────────┘
```

---

## PHASE 13: SYSTEM HEALTH SCORECARD (CALL 3)

```
┌─────────────────────────────┬────────┬────────────────────────────────────────────────────┐
│ Area                        │ Score  │ Notes                                              │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Alpha Layer                 │  8/10  │ Clean design; horizon mapping bug is only defect   │
│ Signal Layer                │  5/10  │ Watchlist inversion is a trade-direction bug;      │
│                             │        │ "instant" horizon unmapped; get_event_loop depr.   │
│ Execution                   │  6/10  │ Slippage and routing clean; Kalshi NO-price needs  │
│                             │        │ API verification before live use                   │
│ Ingestion                   │  6/10  │ Economics category gap silently drops markets;     │
│                             │        │ scraper query hardcoded; reddit DB naming risk     │
│ Observability               │  4/10  │ Backtest look-ahead bias makes metrics useless;   │
│                             │        │ calibrator uses wrong probability proxy; Sharpe    │
│                             │        │ inflated by sqrt(trades_per_day)                   │
│ Dashboard & API             │  5/10  │ Dashboard crashes on first signal; ping_task       │
│                             │        │ NameError risk in WebSocket finally block          │
│ Control                     │  8/10  │ Solid; singleton isolation, SafetyGuard gate clean │
│ Portfolio Utilities         │  8/10  │ Clean and minimal; only minor logging gap          │
│ Providers                   │  5/10  │ get_price() permanently broken — fresh instance    │
│ Tests                       │  6/10  │ Good alpha/signal coverage; RiskManager bleed and  │
│                             │        │ sys.path hack reduce score                         │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ OVERALL                     │  6/10  │ Solid architecture, but three issues block prod:   │
│                             │        │ dashboard KeyError on first signal, watchlist       │
│                             │        │ direction inversion, and backtest look-ahead bias   │
│                             │        │ producing entirely fabricated performance metrics.  │
└─────────────────────────────┴────────┴────────────────────────────────────────────────────┘
```

**Score: 6.1/10 — Architecture is sound, but three issues must be resolved before live use: the dashboard crashes on the first real signal, the watchlist can send trades in the wrong direction, and all backtest performance metrics are invalid due to look-ahead bias.**

---

*End of Call 3. Phases 8–13 complete.*

---

# SYSTEM AUDIT — CALL 4
## Phases 14–18: Smoke-Test Findings, Regression Check, New Issues, Fix Matrix, Scorecard

---

## PHASE 14: SMOKE TEST FIXES

---

### P1 [CRITICAL] signal/classifier.py — Semaphore provides no RPM ceiling; burst saturates Groq free tier
**Lines:** 17–18

`_groq_semaphore = asyncio.Semaphore(9)` caps concurrency but not requests-per-minute. When 96 RSS headlines arrive at once, up to 9 LLM calls fire simultaneously. Groq's free tier is 30 RPM — 9 concurrent calls all completing within a second exhausts the budget instantly. All 9 return `RateLimitError`, all 3 passes are errors, all classifications return NEUTRAL, zero actionable signals are produced even when real market-moving events are present.

**Fix:** Add a module-level token-bucket rate limiter (≤25 RPM) inside `_single_pass()` before the API call. Reduce semaphore from 9 → 3 to further space calls.

---

### P2 [IMPORTANT] pipeline.py:78 — Queue depth WARNING fires once per dequeue, flooding log
**Lines:** 77–80

When `_consume_news_queue()` dequeues items from a 96-deep queue, `qsize > 50` is true for 46 consecutive iterations. Each iteration logs a WARNING. The result is 46 identical WARNING lines printed in under 100ms — masking real errors and filling log files.

**Fix:** Hysteresis flag — warn once when crossing the high-water mark, suppress until depth drops below a low-water mark (10).

---

## PHASE 15: REGRESSION CHECK

All prior fixes verified correct:
- **F1** `on_trade_closed()` called from `close_position()` ✓ (lines 142–150)
- **F2** `from observability import logger as lg` ✓
- **F3** `try_open_position()` atomic; `on_trade_opened()` removed from pipeline; `release_position_slot()` on failure ✓
- **F4** `consistency=config.HOT_PATH_CONSISTENCY` ✓
- **H1** `is_loss` inversion fixed ✓
- **H2** Watcher injection via `set_watcher()` ✓
- **H9** `asyncio.wait_for(..., timeout=15.0)` around both Groq and Anthropic paths ✓
- **A-1** Longest-match watchlist ✓
- **A-2** `"immediate"` horizon ✓
- **A-4** `history_in_window[0]` baseline ✓
- **B-2** `economics` branch in `_infer_category` ✓
- **C-1** Dashboard `edge_pct` computed from confidence delta ✓
- **D-1** `RiskManager._singleton = None` in `isolated_db` teardown ✓
- **Hot-path bypass** `fast_classifier.is_trained()` gate ✓

No regressions found.

---

## PHASE 16: NEW ISSUES FOUND

---

### P3 [IMPORTANT] ingestion/news_stream.py:608 — `asyncio.get_event_loop()` deprecated in Python 3.10+
**Line:** 608

`await asyncio.get_event_loop().run_in_executor(...)` inside a coroutine. Deprecated in 3.10, emits `DeprecationWarning` on 3.12, will raise in a future version.

**Fix:** `asyncio.get_running_loop().run_in_executor(...)`

---

### P4 [IMPORTANT] ingestion/scraper.py:129 — `config.MARKET_CATEGORIES` AttributeError risk
**Line:** 129

`cats or config.MARKET_CATEGORIES` — if `MARKET_CATEGORIES` is not defined in config (e.g., stripped-down config), raises `AttributeError`, silently disabling all NewsAPI queries via the outer `except`.

**Fix:** `cats or getattr(config, 'MARKET_CATEGORIES', [])`

---

### P5 [SUGGESTION] portfolio/risk.py:146,151 — `status()` calls `in_cooldown()` twice
**Lines:** 146, 151

`in_cooldown()` logs a DEBUG line on every call when in cooldown. `status()` calls it twice (once for the dict value, once for `can_trade`), doubling the debug noise on every status poll.

**Fix:** Cache in a local variable.

---

### P6 [SUGGESTION] portfolio/_paper.py:131 — `close_position()` unguarded `ValueError` from DB
**Lines:** 131–134

`lg.update_position_closed()` raises `ValueError` if no DB row is found (e.g., position closed externally between startup and now). No try/except around this call — the `ValueError` propagates to callers of `close_position()`.

**Fix:** Wrap `lg.update_position_closed()` in `try/except ValueError` and log a warning.

---

### P7 [SUGGESTION] signal/fast_classifier.py — `_rule_based()` is always NEUTRAL without a watchlist hit
**Lines:** 166–184

The `_rule_based()` path in `predict()` (no model loaded, no watchlist hit) immediately returns NEUTRAL because the score formula requires `hit is not None` to produce a non-zero `watched` term AND the guard at line 177 returns NEUTRAL if `hit is None`. This function is reachable only when no model exists and no watchlist hit, but always returns NEUTRAL in that case — dead effective branch.

**Fix:** Document the invariant or remove the dead path; no functional change needed.

---

### P8 [SUGGESTION] control/trading_mode.py:74 — `Pipeline.dry_run` stale after mode switch
**Line:** 74

`TradingMode._apply_mode()` mutates `config.DRY_RUN` at runtime. `Pipeline.__init__` captures `self.dry_run = ... config.DRY_RUN` once. If mode switches post-startup, `self.dry_run` is stale. Only used in the startup log message, so no functional impact — but misleading.

**Fix:** Remove `self.dry_run` from Pipeline or read `config.DRY_RUN` directly in the log line.

---

### P9 [SUGGESTION] ingestion/news_stream.py — `NewsAPISource.QUERIES` duplicates `scraper.py` queries
**Lines:** ~217–224

Both `NewsAPISource` (30s polling) and `RSSSource`/`scraper.scrape_newsapi()` hit NewsAPI with overlapping queries. The dedup router catches duplicate headlines, but the API quota (100 req/day free tier) is consumed twice as fast as needed.

**Fix:** Share `get_newsapi_queries()` between both sources, or disable the `RSSSource` NewsAPI path when `NewsAPISource` is active.

---

## PHASE 17: FIX PRIORITY MATRIX

```
┌────┬──────────┬──────────────────────────────────────┬────────┬──────────────────────────────────────────────────────────────┐
│ ID │ Severity │ File                                 │  Line  │ Fix                                                          │
├────┼──────────┼──────────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤
│ P1 │ CRITICAL │ signal/classifier.py                 │  17-18 │ Token-bucket rate limiter ≤25 RPM; semaphore 9 → 3           │
│ P2 │ IMPORTANT│ pipeline.py                          │  78-80 │ Hysteresis: warn once on cross 50, reset at ≤10              │
│ P3 │ IMPORTANT│ ingestion/news_stream.py             │   608  │ get_event_loop() → get_running_loop()                        │
│ P4 │ IMPORTANT│ ingestion/scraper.py                 │   129  │ Use getattr(config, 'MARKET_CATEGORIES', [])                 │
│ P5 │ SUGGESTION│ portfolio/risk.py                   │ 146,151│ Cache in_cooldown() in local var in status()                 │
│ P6 │ SUGGESTION│ portfolio/_paper.py                 │   131  │ Guard update_position_closed() with try/except ValueError    │
│ P7 │ SUGGESTION│ signal/fast_classifier.py           │ 166-184│ Document _rule_based() dead path or remove                   │
│ P8 │ SUGGESTION│ control/trading_mode.py + pipeline  │    74  │ Remove Pipeline.self.dry_run or refresh from config          │
│ P9 │ SUGGESTION│ ingestion/news_stream.py            │ 217-224│ Deduplicate NewsAPI queries between stream and scraper        │
└────┴──────────┴──────────────────────────────────────┴────────┴──────────────────────────────────────────────────────────────┘
```

---

## PHASE 18: SYSTEM HEALTH SCORECARD (CALL 4)

```
┌─────────────────────────────┬────────┬────────────────────────────────────────────────────┐
│ Area                        │ Score  │ Notes                                              │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ Rate limiting / API safety  │  3/10  │ CRITICAL: semaphore is not an RPM limiter; burst   │
│                             │        │ of 96 events saturates Groq free tier instantly     │
│ Queue management            │  5/10  │ Correct logic; flood-warns 46× per batch           │
│ Signal classification       │  7/10  │ Three-pass voting, consistency, error fallbacks     │
│                             │        │ all sound; just needs RPM guard                    │
│ Risk management             │  8/10  │ Atomic slot reservation, caps, cooldown, daily     │
│                             │        │ loss limit all correct post-fix                    │
│ Portfolio / paper trading   │  8/10  │ DB restore, position dedup, unrealized P&L via     │
│                             │        │ live watcher — works correctly                     │
│ Execution engine            │  8/10  │ AggregatedSignal → Signal conversion correct;      │
│                             │        │ dry-run and live paths both sound                  │
│ Fast classifier / hot path  │  7/10  │ is_trained() bypass correct; watchlist longest-    │
│                             │        │ match correct; _rule_based dead path is noise       │
│ Observability               │  8/10  │ mode column, raise_for_status, Brier all correct   │
│ Alpha (momentum/news/ens.)  │  7/10  │ Weighted aggregation, momentum baseline fix,       │
│                             │        │ TTL cleanup all correct                            │
│ Control layer               │  7/10  │ Drawdown gate, cooldown gate work; Pipeline         │
│                             │        │ .dry_run stale post-mode-switch (low impact)        │
├─────────────────────────────┼────────┼────────────────────────────────────────────────────┤
│ OVERALL                     │  6.8/10│ Logic is largely sound after 3 fix rounds. P1      │
│                             │        │ (rate limiter) is the only blocker — without it,   │
│                             │        │ every dry-run with >3 concurrent markets produces   │
│                             │        │ zero signals. Fix P1+P2+P3+P4 → system reaches 8/10│
└─────────────────────────────┴────────┴────────────────────────────────────────────────────┘
```

**Verdict: Fix P1 (rate limiter) and P2 (queue hysteresis) before the next smoke test. P3 and P4 are Important but do not block trading.**

---

*End of Call 4. Phases 14–18 complete.*
