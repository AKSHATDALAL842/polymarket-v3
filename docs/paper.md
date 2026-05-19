# Event-Driven NLP Infrastructure for Autonomous Prediction Market Trading: Architecture, Safety Mechanisms, and Staged Deployment

**Akshat Dalal**

---

## Abstract

Autonomous financial agents operating on prediction markets face a fundamental tension: the speed and scale advantages of automation are offset by the catastrophic risk of silent failure modes, state corruption, and unobservable decision-making. We present the architecture and operational validation of an event-driven NLP pipeline for binary prediction market trading that evolved from a hallucination-prone autonomous prototype into a supervised, deterministic, replayable infrastructure system. Over 22 development iterations, we identified and remediated a series of failure modes including temporal-decay-induced signal collapse, semantic matching brittleness, non-deterministic execution paths, and exchange state divergence. The resulting system enforces deterministic order and position finite-state machines, append-only execution ledgers, exchange-authoritative reconciliation loops, and a staged live-capital deployment framework with manual approval gating. We contribute (1) a taxonomy of failure modes in autonomous prediction-market agents, (2) an architecture for replayable observability that enables post-hoc signal lifecycle reconstruction, (3) a reconciliation engine that treats exchange state as authoritative, and (4) a safety framework for bounded-risk live deployment. Our core finding is that operational reliability, replayable correctness, and deterministic infrastructure provide strictly more value than raw autonomy in financial-agent systems.

---

## 1. Introduction

Prediction markets present a compelling domain for automated trading systems. Binary outcome contracts with well-defined resolution criteria, continuous order books, and real-time news-driven price discovery create an environment where NLP-based signal extraction could theoretically generate edge. However, the gap between a prototype that "looks correct" and an infrastructure system that is *provably correct under operational stress* is vast.

This paper chronicles the architectural evolution of a prediction-market trading system across five major workstreams: observability and diagnostics (Workstream A), signal pipeline reconstruction (Workstream C), execution and settlement hardening (Workstream D), operational durability validation, and controlled live-capital deployment. Each workstream exposed failure modes that naive implementations would silently absorb.

The system processes breaking news from seven concurrent sources (RSS, NewsAPI, GNews, GDELT, Reddit, Twitter/X, Telegram), enriches headlines through NLP entity extraction and sentiment analysis, semantically matches events to prediction markets across Polymarket and Kalshi, classifies market impact through a three-tier pipeline, computes edge using sigmoid-dampened price adjustment, sizes positions via fractional Kelly criterion, and executes through exchange APIs—all under a 5-second latency target.

**Central Thesis:** In autonomous financial systems, deterministic infrastructure, replayability, reconciliation, and operational discipline are more important than raw autonomy.

### 1.1 Contributions

1. A taxonomy of failure modes in autonomous prediction-market agents, discovered through systematic observability instrumentation
2. An architecture for replayable observability enabling full signal lifecycle reconstruction from persisted events
3. A reconciliation engine treating exchange state as authoritative with severity-graded auto-repair
4. A staged live-capital safety framework with manual approval gating, proposal expiry, and constrained exposure limits
5. Empirical evidence that rule-based fallback classifiers with calibrated thresholds can sustain signal throughput when LLM APIs are rate-limited

---

## 2. Related Work

### 2.1 Prediction Markets and Automated Trading

Prediction markets aggregate dispersed information through continuous double auctions [1,2]. The efficient market hypothesis suggests that prices should reflect all available information [3], yet empirical studies demonstrate predictable biases including favorite-longshot bias [4] and overreaction to salient news [5]. Automated systems attempting to exploit these inefficiencies face challenges distinct from traditional financial markets: binary payoff structures, wide bid-ask spreads in niche markets, and the semantic complexity of mapping unstructured news to specific market contracts.

### 2.2 NLP for Financial Signal Extraction

Financial NLP has advanced significantly with transformer-based architectures [6,7]. However, prediction markets present unique challenges: market questions are often idiosyncratic ("Will SpaceX complete an orbital test flight before August 2026?"), entity linking requires domain-specific knowledge, and temporal relevance decays rapidly (half-life of 14 minutes in our measurements).

### 2.3 Reliable Distributed Systems

Our approach draws heavily from reliability engineering principles. The concept of reconciliation loops treating external state as authoritative echoes the "source of truth" pattern in distributed databases [8]. Append-only ledgers for execution events parallel event sourcing architectures [9]. Circuit breakers for operational safety are adapted from microservice resilience patterns [10].

### 2.4 AI Safety in Financial Systems

Recent work on AI safety emphasizes the importance of human oversight, bounded autonomy, and interpretable decision-making [11,12]. Our staged deployment approach—shadow execution, observation mode, manual approval, constrained exposure, gradual scaling—operationalizes these principles for prediction-market trading.

---

## 3. System Architecture

The system follows an event-driven pipeline architecture with 10 concurrent supervised background tasks. Figure 1 illustrates the high-level data flow.

```
                    ┌──────────────────────────────┐
                    │     7 Concurrent Sources       │
                    │  RSS · NewsAPI · GNews · GDELT │
                    │  Reddit · Twitter/X · Telegram │
                    └──────────────┬───────────────┘
                                   │ NewsEvent
                                   ▼
                    ┌──────────────────────────────┐
                    │        NLP ENRICHMENT         │
                    │  spaCy NER · custom regex     │
                    │  VADER sentiment · impact     │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │      MARKET MATCHING          │
                    │  sentence-transformers        │
                    │  hybrid: semantic+entity+kw   │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │   3-TIER CLASSIFICATION        │
                    │  Watchlist → LightGBM → LLM    │
                    │  Rule-based fallback on API    │
                    │  rate-limit                    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                              │
                    ▼                              ▼
         ┌──────────────────┐          ┌──────────────────┐
         │   EDGE MODEL     │          │  MOMENTUM ALPHA  │
         │  sigmoid-dampened│          │  BTC 5-min return│
         │  price adjustment│          │  CoinGecko poll   │
         └────────┬─────────┘          └────────┬─────────┘
                  │                              │
                  └──────────┬───────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  ENSEMBLE VOTING     │
                  │  news=0.6 mom=0.4    │
                  │  conflict multiplier │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  PORTFOLIO MANAGER   │
                  │  Kelly sizing · draw │
                  │  down scaling · risk │
                  └──────────┬───────────┘
                             │
              ┌──────────────┴───────────────┐
              │                              │
              ▼                              ▼
   ┌──────────────────┐          ┌──────────────────┐
   │  EXECUTION ENGINE│          │   SAFETY GATES   │
   │  Polymarket CLOB │          │  manual approval │
   │  Kalshi REST     │          │  circuit breakers│
   └──────────────────┘          │  hard-stop       │
                                 └──────────────────┘
```

**Figure 1: High-level system architecture showing the signal processing pipeline from news ingestion through execution, with safety gates at every stage.**

### 3.1 Runtime Architecture

The system runs 10 supervised background tasks via Python's `asyncio`:

| Task | Interval | Purpose |
|------|----------|---------|
| Market Watcher | Continuous | WebSocket price feed + REST snapshots |
| News Aggregator | Continuous | 7-source concurrent ingestion |
| News Consumer | Continuous | Event dispatch + signal processing |
| Momentum Alpha | 60s | BTC price momentum via CoinGecko |
| Cold Path | Continuous | Classifier labeling flywheel |
| Health Monitor | 30s | Stall/anomaly/ingestion watchdogs |
| Reconciliation | 300s | Exchange-authoritative state sync |
| Settlement | 120s | Active Gamma API resolution polling |
| Market Sync | 30s | Stale-quote detection, self-healing |
| Task Supervisor | 30s | Heartbeat monitoring, auto-restart |

All telemetry components are fail-open: a telemetry failure never blocks trading execution.

---

## 4. Signal Pipeline

### 4.1 News Ingestion

Seven concurrent async sources feed a deduplication router that normalizes headlines and assigns source credibility priors:

| Source | Credibility | Interval |
|--------|-------------|----------|
| GNews | 0.88 | 900s |
| GDELT | 0.85 | 300s |
| NewsAPI | 0.85 | 30s |
| RSS | 0.80 | 60s |
| Twitter/X | 0.65 | Streaming |
| Telegram | 0.60 | Polling |
| Reddit | 0.50 | 45s (adaptive) |

Reddit uses an adaptive weighted subreddit selector with SQLite-backed performance tracking: `weight = base_weight × (1 + alpha)` where `alpha = profitable_trades / max(1, trades_triggered)`.

### 4.2 NLP Enrichment

Headlines undergo multi-stage enrichment:

1. **Custom Regex Entity Extraction** (65 patterns): AI companies (OpenAI, Anthropic), crypto assets (Bitcoin, Ethereum, Solana), central banks (Fed, ECB, BOJ), exchanges, ETFs, tech companies, pharma, indicators
2. **spaCy NER** (`en_core_web_sm`): Standard named entity recognition
3. **VADER Sentiment**: Compound polarity score
4. **Impact Scoring**: `0.20 × reliability + 0.20 × |sentiment| × confidence + 0.20 × entity_importance + 0.25 × novelty + 0.15 × velocity`

**Critical finding:** spaCy's `en_core_web_sm` model fails to recognize domain-specific entities such as "OpenAI," "GPT-5," "ETF," and "SEC." The custom regex layer increased entity coverage from approximately 40% to near 100% for financial and technology headlines.

### 4.3 Market Matching

Markets are matched using a hybrid scoring engine:

```
final_score = max(semantic_score, keyword_score) + entity_bonus × 0.25 + keyword_bonus × 0.15
```

- **Semantic:** `all-MiniLM-L6-v2` embeddings (384-dim), cosine similarity
- **Entity Overlap:** Jaccard-like scoring between headline entities and market question text
- **Keyword Overlap:** Jaccard similarity between extracted keyword sets
- **Threshold:** `MATCHER_MIN_SIMILARITY = 0.20` (evidence-calibrated from 0.30)

**Key insight:** Semantic embedding scores for prediction market questions are systematically low with general-purpose models (median 0.20). The hybrid approach recovers matches through entity and keyword overlap that purely semantic matching would miss.

### 4.4 Three-Tier Classification

| Tier | Method | Latency | Gates |
|------|--------|---------|-------|
| 1 | Watchlist (80 phrases) | <1ms | Source credibility ≥ 0.65 |
| 2 | LightGBM (40 features) | <1ms | Multiclass: NEUTRAL/NO/YES |
| 3 | LLM voting (Groq/DeepSeek) | ~300ms | Majority direction, conf ≥ 0.55, mat ≥ 0.30, nov ≥ 0.20 |

**Operational adaptation:** When the Groq API proved consistently rate-limited on the free tier, we implemented (a) sequential rather than concurrent LLM passes to respect rate limits, (b) immediate fallback to the rule-based classifier upon first rate-limit detection, and (c) confidence floors for rule-based results to maintain signal throughput. This pragmatic adaptation kept the pipeline operational when the primary classifier was unavailable—a pattern we argue is essential for production financial systems.

### 4.5 Edge Model

Price adjustment uses sigmoid-dampened scaling:

```
raw    = 0.40 × materiality + 0.30 × confidence + 0.30 × novelty_score
room   = 0.95 - p_market (YES)  or  p_market - 0.05 (NO)
adj    = room × (1 - exp(-2 × raw)), capped at 0.12
p_true = clamp(p_market ± adj, 0.02, 0.98)
EV_net = |p_true - p_market| - estimated_slippage
```

Position sizing uses fractional Kelly: `size = min(MAX_BET, K × EV × confidence × bankroll)` with `K = 0.25`, followed by drawdown scaling: `size × max(0, 1 - 2 × drawdown)`.

---

## 5. Observability & Replayability Layer

The observability layer was the first workstream implemented, reflecting our finding that diagnostics must precede optimization. Every signal receives a globally unique `trace_id` and passes through a strict 8-stage finite-state machine:

```
INGESTED → NLP_PROCESSED → MARKET_MATCHED → SCORED →
VALIDATED → SIZED → EXECUTED → SETTLED
```

Any stage can transition to REJECTED (with structured rejection metadata) or EXPIRED.

### 5.1 Rejection Analytics

19 rejection reasons are enumerated with severity levels (INFO, SOFT_REJECT, HARD_REJECT, SYSTEM_FAILURE), subsystem attribution, threshold snapshots, and actual vs. threshold values. This enables precise diagnosis of signal attrition.

### 5.2 Replay Reconstruction

Every signal lifecycle can be reconstructed entirely from persisted SQLite events:

```python
reconstruct_trace(trace_id, sqlite_row) → {
    trace_id, parent_trace_id, lifecycle[],
    rejection, match_trace, stage_timings,
    total_latency_ms, schema_version
}
```

Parent/child causal correlation via `parent_trace_id` enables multi-market reasoning reconstruction.

### 5.3 Dead-Letter Queue

Unhandled exceptions are captured in an in-memory DLQ (capped at 500 entries) with SQLite persistence. Each dead letter records the serialized payload, exception traceback, subsystem, and retry count. The DLQ integrates with the health monitor for alerting.

### 5.4 Runtime Health Monitors

Four watchdog types continuously monitor system health:

- **StallWatchdog:** Detects idle queues (thresholds: news=120s, cold_path=300s, settlement=600s)
- **FrozenWSWatchdog:** Detects WebSocket disconnection
- **ZeroSignalWatchdog:** Alerts if no signals generated in 15 minutes
- **IngestionOutageWatchdog:** Alerts if no new events in 10 minutes

All watchdogs emit dual alerts: structured log + WebSocket broadcast.

---

## 6. Execution Architecture

### 6.1 Order Lifecycle FSM

Every order follows a deterministic 11-state FSM with strict transition validation:

```
CREATED → VALIDATED → SUBMITTED → ACKNOWLEDGED →
PARTIALLY_FILLED → FILLED → CANCEL_PENDING → CANCELLED →
REJECTED → EXPIRED → SETTLED
```

Illegal transitions (e.g., CREATED → FILLED) are logged at ERROR level and rejected. Each order carries a SHA256-based idempotency key derived from `(signal_trace_id, market_id, side, size, price)`, preventing duplicate order creation.

### 6.2 Position Lifecycle FSM

Positions follow an 8-state FSM with explicit orphan detection:

```
OPENING → OPEN → REDUCING → CLOSED → SETTLING → SETTLED
                                           ↓
                                       ORPHANED → RECONCILING
```

Every position maps to its originating signal, order(s), market state, and settlement outcome. Orphaned positions (market closed unexpectedly, exchange state divergence) are flagged and enter a reconciliation cycle.

### 6.3 Append-Only Execution Ledger

All order events are persisted to an immutable `order_ledger` table. Full order lifecycle reconstruction is supported through ledger replay. The schema includes `idempotency_key`, `exchange_response`, `retry_count`, and `metadata` columns for complete auditability.

### 6.4 Circuit Breakers

Eight circuit breakers protect against execution anomalies:

| Breaker | Threshold | Cooldown |
|---------|-----------|----------|
| Rapid losses | $50/5min | 600s |
| Execution anomalies | 3 events | 300s |
| Duplicate orders | 2 events | 600s |
| Runaway retries | 10 retries | 300s |
| Excessive slippage | 5% | 300s |
| Stale market data | 1 event | 120s |
| Reconciliation drift | 3 events | 600s |
| Abnormal latency | 10s | 300s |

Each breaker cycles through CLOSED → OPEN → HALF_OPEN states. The master kill-switch (`can_execute()`) blocks all execution when any breaker is OPEN. All breakers fail-safe (default to OPEN).

---

## 7. Reconciliation & Settlement Design

### 7.1 Exchange-Authoritative Reconciliation

The reconciliation engine operates on a fundamental premise: **exchange state is authoritative; local state is a cached projection only.** A 6-state FSM governs the reconciliation lifecycle:

```
CLEAN → DIVERGED → REPAIRING → RECONCILED → ESCALATED → QUARANTINED
```

Periodic loops (configurable, default 300s) compare local order, position, fill, and market projections against exchange state. Anomalies receive severity classifications (INFO/WARNING/ERROR/CRITICAL) with auto-repair for safe anomalies and escalation for dangerous ones. All reconciliation events are journaled to a `reconciliation_events` table for post-hoc analysis.

### 7.2 Settlement Engine

The settlement engine actively polls the Polymarket Gamma API for market resolutions (120s interval), never relying solely on WebSocket events. A 6-stage FSM governs settlements:

```
RESOLUTION_PENDING → RESOLUTION_CONFIRMED → PAYOUT_VERIFIED →
SETTLED / DISPUTED / REFUNDED
```

Deterministic PnL finalization includes payout verification: expected payout must match actual within a tolerance before transition to SETTLED.

### 7.3 Market State Synchronizer

A self-healing market synchronizer maintains 5 health states (HEALTHY → DEGRADED → STALE → DISCONNECTED → HEALING) with sequence-gap detection on WebSocket price feeds. Stale quotes are detected at 60s; periodic full snapshots refresh at 300s intervals. The synchronizer auto-heals by triggering `watcher.refresh_markets()` when health degrades.

---

## 8. Runtime Supervision & Fault Tolerance

### 8.1 Task Supervisor

A centralized task supervisor tracks 7 lifecycle states (STARTING → RUNNING → STALLED → RECOVERING → STOPPING → STOPPED → FAILED) for all background tasks. Auto-restart with configurable `max_restarts` and cooldown delays prevents silent task death. Heartbeat-based stall detection (default 300s threshold) surfaces degraded tasks. Permanent task failure broadcasts a CRITICAL health alert.

### 8.2 Fail-Open Telemetry

All observability components are designed to fail-open. We verified through 24 adversarial tests that telemetry failures in the stage timer, trace persistence, inspector, broadcaster, and health monitor never propagate to the execution path. A `measure()` context manager swallows all internal exceptions:

```python
@contextmanager
def measure(self, trace_id, stage, critical=False):
    t0 = time.monotonic()
    try:
        yield
    finally:
        try:
            elapsed_us = int((time.monotonic() - t0) * 1_000_000)
            self.record(trace_id, stage, elapsed_us, critical=critical)
        except Exception:
            pass  # fail-open
```

---

## 9. Live-Capital Safety Framework

### 9.1 Staged Deployment

Live-capital deployment follows a strictly constrained progression:

| Phase | Max Bet | Max Positions | Daily Loss | Manual Approval |
|-------|---------|---------------|------------|-----------------|
| 0 (Shadow) | $0 | 0 | N/A | N/A |
| 1 (Minimal) | $2 | 1 | $5 | Required |
| 2 (Constrained) | $5 | 2 | $10 | Required |
| 3 (Validated) | TBD | TBD | TBD | Optional |

Phase transitions require: zero critical anomalies, stable reconciliation, deterministic settlement, bounded resource behavior, and proven replay consistency.

### 9.2 Manual Approval Workflow

Every live trade passes through: signal → proposal → review → approval → execution. Proposals expire after 5 minutes, requiring re-scoring and re-validation. Only one proposal is pending at a time (approval locking).

### 9.3 Emergency Hard-Stop

A single command (`python cli.py hard-stop "reason"`) immediately freezes all execution, dumps runtime state to JSON, and persists a `.hard_stop` file checked at every pipeline event. Recovery requires explicit clearance.

### 9.4 Pre-Flight Validation

Before any live execution, a 9-point pre-flight check verifies: CLOB connectivity, WebSocket readiness, task health, circuit breaker state, SQLite writability, stale position absence, orphan order absence, reconciliation cleanliness, and market sync health.

---

## 10. Operational Validation Methodology

### 10.1 Testing Infrastructure

The system is validated through 228 automated tests spanning 8 test suites:

| Suite | Tests | Focus |
|-------|-------|-------|
| `test_observability` | 43 | FSM transitions, trace lifecycle, DLQ, stage timer |
| `test_validation` | 24 | Stress (10K burst), fail-open, FSM integrity, replay determinism |
| `test_adversarial` | 15 | Duplicate storms, overflow, malformed inputs, contradictory signals |
| `test_execution` | 30 | Order/position FSM, idempotency, circuit breakers |
| `test_hardening` | 14 | Reconciliation, settlement, risk accounting |
| `test_durability` | 15 | Market sync, task supervisor |
| Existing suites | 87 | Allocator, alpha signals, ensemble, classifier, portfolio, trading mode |

### 10.2 Key Metrics

| Metric | Value | Context |
|--------|-------|---------|
| Offline match rate | 83.3% | 15/18 diverse headlines matched to markets |
| Live match rate | 96.7% | 29/30 live signals matched in shadow run |
| NLP gate pass rate | 100% | After temporal-decay fix (was 4%) |
| Rule-based fallback reliability | 6 trades generated | During Groq rate-limit period |
| Reconciliation anomalies | 0 | Clean state across test runs |
| DLQ entries | 0 | No unhandled exceptions in shadow runs |
| Circuit breaker trips | 0 | No false positives in testing |
| Pre-flight checks | 9/9 PASS | Stable across 3 consecutive runs |
| Adversarial recovery | 82/82 | All fail-open tests pass |

### 10.3 Live-Only Failure Mode Discovery

The temporal-decay-induced NLP gate collapse was discovered exclusively through live shadow operation. Offline audit used `age_seconds=0` (fresh news), producing 100% NLP pass rates. Live RSS feeds with 1-6 hour article ages experienced `relevance = impact × exp(-0.05 × age_min)`, collapsing relevance to near-zero. The fix separated the impact gate from temporal decay: `impact_score` (constant) gates eligibility; `relevance` (decayed) affects sizing. This failure mode would have remained undetected without live shadow operation.

---

## 11. Failure Modes & Lessons Learned

### 11.1 Taxonomy of Discovered Failure Modes

| Failure Mode | Discovery Method | Impact | Fix |
|-------------|------------------|--------|-----|
| Temporal-decay NLP collapse | Live shadow run | 96% signal kill rate | Gate on impact_score, not relevance |
| Kalshi parser field mismatch | Market universe audit | 200 markets at $0 volume | Parse dollar-format API fields |
| MAX_VOLUME_USD over-filtering | Market universe audit | 9 high-quality markets excluded | Raise to $5M, platform-specific thresholds |
| spaCy entity blindness | Per-headline audit | "OpenAI GPT-5" → zero entities | 65 custom regex patterns |
| Purely semantic matching | Offline audit | 60% of valid matches <0.30 similarity | Hybrid: semantic + entity + keyword |
| Concurrent LLM rate-limiting | Live operation | All 3 passes rate-limited | Sequential passes + rule-based fallback |
| `/api` prefix mismatch | Frontend polling | All dashboard data fetch 404 | Restore proxy-compatible prefix |
| Task supervisor early exit | Live operation | Pipeline shutdown in 1s | `_running` default to True |
| Hard-stop file persistence | Multiple runs | Pipeline blocked on restart | Auto-cleanup on clear |

### 11.2 Key Lessons

1. **Observability must precede optimization.** Without trace IDs, rejection analytics, and stage timing, the temporal-decay bug would have remained invisible.

2. **Live shadow operation discovers failure modes that offline testing cannot.** The NLP temporal-decay collapse and Groq rate-limit cascade were both discovered during live runs, not during offline audits.

3. **Deterministic FSMs catch integration bugs at development time.** Illegal state transitions (INGESTED → SCORED skip) were immediately logged and flagged, preventing silent progression through incomplete pipelines.

4. **Exchange-authoritative reconciliation is non-negotiable.** Local state drifts from exchange reality within minutes. Reconciliation loops must run at intervals shorter than the expected drift horizon.

5. **Rule-based fallbacks sustain operations when ML APIs fail.** The pipeline produced 6 paper trades during a period of complete Groq unavailability using only the rule-based classifier.

6. **Manual approval gating prevents autonomous errors from becoming financial losses.** Every live trade requires explicit human sign-off, creating a natural review checkpoint.

---

## 12. Discussion

### 12.1 Operational Discipline Over Raw Autonomy

The system's evolution reflects a broader principle: in financial-agent systems, operational reliability provides strictly more value than sophisticated autonomy. The initial architecture prioritized autonomous decision-making but lacked observability, replayability, and safety mechanisms. Each subsequent workstream added a layer of operational discipline: trace IDs and rejection analytics (understanding failures), FSM enforcement (preventing illegal states), reconciliation (detecting drift), circuit breakers (bounding damage), and manual approval (human oversight).

### 12.2 The Role of Replayability

Replayability emerged as the single most valuable infrastructure property. The ability to reconstruct any signal's complete lifecycle from persisted events—headline → entities → matched market → classification → edge → execution → settlement—transformed debugging from speculative hypothesis generation into evidence-backed root cause analysis. We argue that replayability should be a first-class architectural requirement, not an afterthought, in any financial-agent system.

### 12.3 Safety Through Staged Deployment

The staged deployment framework (shadow → observe → manual-approve → constrained-live → scaled) provides an operational safety gradient that no amount of pre-deployment testing can match. Each stage surfaces failure modes specific to that level of operational reality, creating a natural progression of confidence building.

---

## 13. Limitations

We acknowledge the following limitations:

1. **Limited live-capital validation:** Live trading has been conducted only in Phase 1 (shadow mode) and Phase 2 (constrained paper trading). No Phase 3+ live-capital trades have been executed as of this writing.

2. **Constrained exposure:** The safety framework intentionally limits exposure to $2 per trade and $5 daily loss. Behavior at larger scale is unknown.

3. **Single exchange focus:** While Kalshi integration exists, the primary operational validation has been against Polymarket's CLOB.

4. **Embedding model quality:** `all-MiniLM-L6-v2` produces systematically low cosine similarities for prediction market questions. A domain-fine-tuned model would likely improve matching precision.

5. **No profitability claims:** We make no claims about the system's ability to generate positive returns. The validation focus has been on operational correctness, not trading performance.

6. **Dependency on exchange APIs:** The system is vulnerable to API changes, rate limits, and authentication edge cases beyond our control.

7. **Remaining operational unknowns:** 24-hour continuous soak testing has not been completed. Long-runtime degradation, memory leaks, and async drift remain potential risks.

---

## 14. Future Work

### 14.1 Operational Durability

Extended 24-hour+ soak testing under live ingestion with reconciliation and settlement active. Monitoring for slow memory leaks, queue buildup, and async task degradation over multi-day runtimes.

### 14.2 Exchange-Behavior Modeling

Building a dataset of expected-vs-actual execution measurements (fill price, slippage, latency, liquidity) to model exchange behavior and improve execution quality predictions.

### 14.3 Embedding Model Upgrade

Evaluating finance-tuned embedding models (e.g., FinBERT variants, domain-adapted sentence transformers) to improve semantic matching quality for prediction market questions.

### 14.4 Cross-Exchange Reconciliation

Extending the reconciliation engine to cross-validate positions across Polymarket and Kalshi for arbitrage detection and exposure consolidation.

### 14.5 Formal Verification

Applying formal verification techniques to the order and position FSMs to prove absence of deadlock, livelock, and illegal state transitions.

### 14.6 Anomaly Prediction

Using the reconciliation anomaly history as training data for predictive models that anticipate state divergence before it occurs.

---

## 15. Conclusion

We have presented the architecture, evolution, and operational validation of an event-driven NLP infrastructure system for prediction market trading. The system evolved through five major workstreams from a hallucination-prone autonomous prototype into a supervised, deterministic, replayable infrastructure with 228 automated tests, exchange-authoritative reconciliation, and a staged live-capital safety framework.

Our core finding is that in autonomous financial systems, operational reliability—manifested through deterministic FSMs, append-only ledgers, reconciliation loops, replayable observability, and staged deployment with human oversight—provides strictly more value than raw autonomy. The system's most important property is not its ability to generate trading signals, but its ability to explain, replay, and recover from every decision it makes.

The architecture, failure mode taxonomy, and safety framework presented here are applicable beyond prediction markets to any domain where autonomous agents interact with external financial infrastructure under real capital constraints.

---

## References

[1] Hanson, R. (2013). Shall We Vote on Values, But Bet on Beliefs? *Journal of Political Philosophy*, 21(2), 151-178.

[2] Wolfers, J., & Zitzewitz, E. (2004). Prediction Markets. *Journal of Economic Perspectives*, 18(2), 107-126.

[3] Fama, E. F. (1970). Efficient Capital Markets: A Review of Theory and Empirical Work. *Journal of Finance*, 25(2), 383-417.

[4] Snowberg, E., & Wolfers, J. (2010). Explaining the Favorite-Longshot Bias: Is it Risk-Love or Misperceptions? *Journal of Political Economy*, 118(4), 723-746.

[5] Tetlock, P. C. (2007). Giving Content to Investor Sentiment: The Role of Media in the Stock Market. *Journal of Finance*, 62(3), 1139-1168.

[6] Devlin, J., et al. (2019). BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. *NAACL-HLT*.

[7] Araci, D. (2019). FinBERT: Financial Sentiment Analysis with Pre-trained Language Models. *arXiv:1908.10063*.

[8] Kleppmann, M. (2017). *Designing Data-Intensive Applications*. O'Reilly Media.

[9] Fowler, M. (2005). Event Sourcing. *martinfowler.com*.

[10] Nygard, M. T. (2007). *Release It!: Design and Deploy Production-Ready Software*. Pragmatic Bookshelf.

[11] Amodei, D., et al. (2016). Concrete Problems in AI Safety. *arXiv:1606.06565*.

[12] Hadfield-Menell, D., et al. (2017). Inverse Reward Design. *NeurIPS*.

[13] Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. *EMNLP-IJCNLP*.

[14] Kelly, J. L. (1956). A New Interpretation of Information Rate. *Bell System Technical Journal*, 35(4), 917-926.

[15] Hutto, C. J., & Gilbert, E. (2014). VADER: A Parsimonious Rule-Based Model for Sentiment Analysis of Social Media Text. *ICWSM*.

[16] Honnibal, M., & Montani, I. (2017). spaCy 2: Natural Language Understanding with Bloom Embeddings, Convolutional Neural Networks and Incremental Parsing.

[17] Ke, G., et al. (2017). LightGBM: A Highly Efficient Gradient Boosting Decision Tree. *NeurIPS*.

---

## Appendix A: System Statistics

| Metric | Value |
|--------|-------|
| Total commits | 22 |
| Files modified/created | 41 |
| Lines of code added | +8,689 |
| Automated tests | 228 (0 failures) |
| Background tasks | 10 concurrent |
| News sources | 7 |
| Rejection reasons enumerated | 19 |
| Circuit breakers | 8 |
| Pre-flight checks | 9 |
| FSM states (total) | 33 (8 signal + 11 order + 8 position + 6 reconciliation) |
| SQLite tables | 15 |
| API endpoints | 36 REST + 2 WebSocket |

## Appendix B: Key Configurable Thresholds

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `MATCHER_MIN_SIMILARITY` | 0.20 | Minimum hybrid match score |
| `NLP_MIN_IMPACT` | 0.10 | Minimum NLP impact to process event |
| `EDGE_THRESHOLD` | 0.03 | Minimum net EV to generate signal |
| `MIN_CONFIDENCE` | 0.55 | Minimum classifier confidence |
| `MAX_BET_USD` | 2.00 | Maximum position size (Phase 1) |
| `MAX_CONCURRENT_POSITIONS` | 1 | Maximum concurrent positions (Phase 1) |
| `DAILY_LOSS_LIMIT_USD` | 5.00 | Hard daily stop (Phase 1) |
| `SIZING_K` | 0.25 | Kelly fraction |
| `PROPOSAL_EXPIRY_SECONDS` | 300 | Stale proposal timeout |
| `RECONCILIATION_INTERVAL` | 60 | Seconds between reconciliation cycles |

## Appendix C: Conference/Workshop Fit

This work is suitable for:

- **AAAI AI for Social Impact** — prediction markets as information aggregation mechanisms
- **ICAIF (ACM International Conference on AI in Finance)** — financial AI infrastructure
- **SysML / MLSys** — ML systems and infrastructure
- **Dependable Systems and Networks (DSN)** — reliability engineering
- **Workshop on Robust AI for Financial Services (RAIFS)** — safety and robustness in financial AI
- **NeurIPS Workshop on AI for Financial Services** — applied financial ML
