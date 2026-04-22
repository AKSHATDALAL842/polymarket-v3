# Polymarket Signal Pipeline

Event-driven trading system for binary prediction markets. Ingests breaking news from 7 concurrent sources, routes events to semantically-matched markets, runs 3-pass LLM voting to score market impact, applies a signal-weighted edge model against live CLOB quotes, and executes limit orders — all within a 5-second latency target.

**Status:** Dry-run mode by default (`DRY_RUN=true`). Live trading requires a funded Polymarket account.

**Stack:** Python 3.11 · asyncio · Groq (llama-3.3-70b) · sentence-transformers · FastAPI · SQLite · Polymarket CLOB

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  NEWS INGEST   news_stream.py                                   │
│  Twitter API v2 / Telegram / RSS / NewsAPI / Reddit /           │
│  GNews / GDELT  (7 sources, async, concurrent)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ NewsEvent
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  NLP ENRICHMENT   nlp_processor.py                              │
│  Named entity recognition (spaCy), VADER sentiment,             │
│  composite impact score, exponential temporal decay             │
│  relevance(t) = impact × exp(−0.05 × age_minutes)               │
└────────────────────────────┬────────────────────────────────────┘
                             │ enriched event
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MARKET MAPPING   matcher.py                                    │
│  sentence-transformers embeddings (all-MiniLM-L6-v2, 384-dim)   │
│  cosine similarity → top-k markets above threshold              │
│  short-duration markets prioritized (≤30 days to resolution)    │
└────────────────────────────┬────────────────────────────────────┘
                             │ MarketMatch[]
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EVENT INTELLIGENCE   classifier.py                             │
│  3 concurrent LLM passes (llama-3.3-70b via Groq, temp=0.15)    │
│  outputs: direction / confidence / materiality /                │
│           novelty_score / time_sensitivity / consistency        │
│  rejects: consistency < 0.6, confidence < 0.55, novelty < 0.20  │
└────────────────────────────┬────────────────────────────────────┘
                             │ Classification
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MICROSTRUCTURE   market_watcher.py                             │
│  WebSocket price feed → momentum gate (skip if already moving)  │
│  CLOB REST → order book depth, spread, liquidity score          │
│  estimated slippage per side + size                             │
└────────────────────────────┬────────────────────────────────────┘
                             │ OrderBookSnapshot
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EDGE MODEL   edge_model.py                                     │
│  p_true = p_market + f(direction, materiality, novelty, conf)   │
│  sigmoid-dampened, asymmetric boundary correction               │
│  EV_net = |p_true − p_market| − slippage                        │
│  size = min(MAX_BET, K × EV × confidence × bankroll)            │
└────────────────────────────┬────────────────────────────────────┘
                             │ Signal
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  RISK LAYER   risk.py                                           │
│  daily loss cap / max concurrent positions /                    │
│  per-category exposure / consecutive loss cooldown              │
│  per-market 10-min signal cooldown                              │
└────────────────────────────┬────────────────────────────────────┘
                             │ approved Signal
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EXECUTION   executor.py                                        │
│  limit orders at mid ± offset (avoid crossing spread)           │
│  slippage gate, retry logic (3 attempts), partial fill handling │
│  full latency tracking: event → classification → execution      │
└────────────────────────────┬────────────────────────────────────┘
                             │ ExecutionResult
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY                                                  │
│  logger.py      — SQLite WAL (trades, news, calibration)        │
│  calibrator.py  — predicted vs actual, Brier score, ECE         │
│  metrics.py     — rolling Sharpe, drawdown, latency p50/p95/p99 │
│  api.py         — FastAPI + WebSocket real-time signal feed     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env   # fill in API keys

# 3. Run (dry-run by default)
python cli.py watch

# 4. Other commands
python cli.py stats       # trading summary
python cli.py markets     # tracked market list
python cli.py calibrate   # probability calibration report
python cli.py backtest    # strategy replay
python api.py             # start FastAPI + WebSocket server on :8000
```

---

## Environment Variables

```bash
# LLM — primary (free tier)
GROQ_API_KEY=

# LLM — fallback (optional)
ANTHROPIC_API_KEY=

# Polymarket CLOB (required for live trading only)
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=
POLYMARKET_PRIVATE_KEY=

# News sources (more = better coverage; all optional)
TWITTER_BEARER_TOKEN=      # requires Basic tier ($100/mo) for stream access
NEWSAPI_KEY=               # 100 req/day free
GNEWS_API_KEY=             # 100 req/day free
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_IDS=

# Trading controls
DRY_RUN=true
MAX_BET_USD=25
BANKROLL_USD=1000
DAILY_LOSS_LIMIT_USD=100
```

---

## Key Algorithms

### Edge Model

The price adjustment is computed as:

```
raw = α·materiality + β·confidence + γ·novelty    (α=0.40, β=0.30, γ=0.30)
room = distance from p_market to boundary (0.05 or 0.95)
adj = room × (1 − exp(−2·raw))                    (sigmoid dampening)
adj = min(adj, 0.12)                               (hard cap at 12%)
p_true = p_market ± adj
EV_net = |p_true − p_market| − estimated_slippage
```

Position sizing uses a conservative Kelly variant:
```
size = min(MAX_BET, K × EV_net × confidence × bankroll)   K=0.25
```

### 3-Pass LLM Voting

Each news × market pair runs 3 independent Groq inference calls concurrently (bounded by a semaphore at 9 in-flight to stay within the 30 RPM free tier). Results are majority-voted on direction; metrics are averaged over agreeing passes only. A classification is actionable only when all four gates pass: `confidence ≥ 0.55`, `materiality ≥ 0.30`, `novelty ≥ 0.20`, `consistency ≥ 0.60`.

### NLP Impact Score

```
impact = 0.20·source_reliability
       + 0.20·|sentiment|·sentiment_confidence
       + 0.20·entity_importance
       + 0.25·novelty_score        (upweighted — already-priced news has near-zero alpha)
       + 0.15·velocity_score

relevance(t) = impact × exp(−0.05 × age_minutes)   (half-life ≈ 14 min)
```

---

## Configuration Reference

### Edge Model
| Setting | Default | Description |
|---------|---------|-------------|
| `EDGE_ALPHA` | 0.40 | Materiality weight |
| `EDGE_BETA` | 0.30 | Confidence weight |
| `EDGE_GAMMA` | 0.30 | Novelty weight |
| `EDGE_THRESHOLD` | 0.03 | Min net EV to trade |
| `EDGE_MAX_ADJUSTMENT` | 0.12 | Max price adjustment cap |
| `MIN_CONFIDENCE` | 0.55 | Min LLM confidence |
| `MIN_NOVELTY` | 0.20 | Min novelty score |

### Risk Controls
| Setting | Default | Description |
|---------|---------|-------------|
| `DAILY_LOSS_LIMIT_USD` | 100 | Hard daily stop |
| `MAX_CONCURRENT_POSITIONS` | 5 | Max open positions |
| `MAX_EXPOSURE_PER_CATEGORY_USD` | 60 | Per-category cap |
| `CONSECUTIVE_LOSS_COOLDOWN` | 3 | N losses → pause |
| `COOLDOWN_MINUTES` | 30 | Pause duration |
| `MARKET_SIGNAL_COOLDOWN_SECONDS` | 600 | Min time between signals on same market |

### Execution
| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_SPREAD_FRACTION` | 0.08 | Skip if spread > 8% |
| `MAX_SLIPPAGE_FRACTION` | 0.03 | Reject if slippage > 3% |
| `LIMIT_ORDER_OFFSET` | 0.01 | Place limit 1¢ inside spread |
| `ORDER_RETRY_ATTEMPTS` | 3 | Max retries |

### Market Selection
| Setting | Default | Description |
|---------|---------|-------------|
| `MIN_VOLUME_USD` | 1,000 | Min market volume |
| `MAX_VOLUME_USD` | 500,000 | Avoid over-efficient markets |
| `PREFER_SHORT_DURATION_DAYS` | 30 | Prioritize markets resolving within N days |

---

## Module Reference

| Module | Role |
|--------|------|
| `pipeline.py` | Main orchestrator — concurrent event dispatch, latency accounting |
| `news_stream.py` | 7-source aggregator with dedup router |
| `nlp_processor.py` | NER, sentiment, impact scoring, temporal decay |
| `matcher.py` | Semantic routing via sentence-transformers embeddings |
| `classifier.py` | 3-pass concurrent LLM voting with consistency scoring |
| `edge_model.py` | Price adjustment, EV calculation, position sizing |
| `market_watcher.py` | Live microstructure: WebSocket prices, order book, momentum gate |
| `executor.py` | Limit order placement with retry and partial fill handling |
| `risk.py` | Daily loss cap, position limits, category exposure, cooldowns |
| `calibrator.py` | Brier score, ECE, per-source accuracy breakdown |
| `backtest.py` | Strategy replay with simulated slippage |
| `metrics.py` | Rolling Sharpe, drawdown, latency distribution |
| `logger.py` | SQLite WAL logging |
| `api.py` | FastAPI server + WebSocket signal broadcaster |
| `config.py` | All settings loaded from `.env` |

---

## End-to-End Trade Flow

```
T+0ms    Twitter stream receives: "Fed signals unexpected rate cut"
T+50ms   NewsEvent dispatched to pipeline
T+52ms   NLP: sentiment=+0.71, impact=0.68, entities=[Fed, rate]
T+55ms   Semantic match → 3 candidate markets found
         "Will Fed cut rates before June 2025?" sim=0.82
T+60ms   3 concurrent LLM passes launched (llama-3.3-70b, temp=0.15)
T+350ms  Passes: YES/YES/YES — conf=0.78 mat=0.71 nov=0.82 consistency=100%
T+355ms  Order book: spread=0.04, depth=$850, liq=0.85
T+356ms  Momentum check: Δprice=+0.02 (below 0.05 threshold — OK)
T+357ms  Edge: p_market=0.42 → p_true=0.54, EV_net=0.10
         size = min($25, 0.25 × 0.10 × 0.78 × $1000) = $19.50
T+358ms  Risk gates: daily_ok, positions=2/5, category_ok, no_cooldown
T+380ms  Limit order: BUY YES @0.44 (mid − offset)
T+410ms  Filled $19.50 @0.443, slippage=+0.003
T+410ms  Trade logged → SQLite, signal broadcast → WebSocket
```

---

## Further Optimization

### Speed
- **Rust CLOB client** — replace `py_clob_client`, eliminate GIL overhead, ~30ms → ~3ms execution
- **Parallel Groq keys** — fan passes across multiple API keys, ~300ms → ~100ms classification
- **Pre-warm embeddings** — periodic no-op inference at startup to avoid cold-start latency

### Edge Model
- **Historical calibration multiplier** — weight `p_true` adjustment by empirical accuracy per source/category (from calibrator)
- **Micro-feature engineering** — add bid/ask imbalance, volume spike, time-to-resolution decay
- **Beta prior update** — treat each LLM pass as a conjugate update to a Beta(α, β) prior

### Infrastructure
- **Redis pub/sub** — replace asyncio queues for multi-process pipelines and cross-restart dedup
- **Co-location** — VPS in US-East (same region as Polymarket CLOB) for lower network latency
- **Prometheus + Grafana** — export metrics for real-time monitoring
