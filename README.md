# Polymarket V3 — Quant-Grade Event-Driven Trading System

An autonomous, event-driven trading pipeline for [Polymarket](https://polymarket.com) prediction markets. Ingests news from 7 sources, semantically matches headlines to markets, runs multi-pass LLM classification, estimates edge, applies microstructure and risk filters, and executes limit orders — all within a 5-second target latency.

> **Status:** Dry-run mode (`DRY_RUN=true`). All trades are simulated. Live trading requires a funded Polymarket account and setting `DRY_RUN=false`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  NEWS INGEST   news_stream.py                                     │
│  Twitter API v2 / Telegram / RSS / NewsAPI / Reddit /            │
│  GNews / GDELT  (7 sources, async, <1s latency)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ NewsEvent
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  NLP ENRICHMENT   nlp_processor.py                               │
│  Named entity recognition, sentiment, impact score,             │
│  temporal decay — drops low-relevance events early              │
└────────────────────────────┬────────────────────────────────────┘
                             │ enriched NewsEvent
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MARKET MAPPING   matcher.py                                      │
│  sentence-transformers embeddings (all-MiniLM-L6-v2, 384-dim)   │
│  cosine similarity → top-k markets above threshold               │
│  short-duration markets prioritized (≤30 days to resolution)    │
└────────────────────────────┬────────────────────────────────────┘
                             │ MarketMatch[]
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EVENT INTELLIGENCE   classifier.py                              │
│  3 concurrent LLM passes (llama-3.3-70b via Groq, temp=0.15)    │
│  outputs: direction / confidence / materiality /                 │
│           novelty_score / time_sensitivity / consistency          │
│  rejects: consistency < 0.6, confidence < 0.55, novelty < 0.20  │
└────────────────────────────┬────────────────────────────────────┘
                             │ Classification
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MICROSTRUCTURE   market_watcher.py                              │
│  WebSocket price feed → momentum gate (skip if already moving)  │
│  CLOB REST → order book depth, spread, liquidity score          │
│  estimated slippage per side + size                              │
└────────────────────────────┬────────────────────────────────────┘
                             │ OrderBookSnapshot
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EDGE MODEL   edge_model.py                                       │
│  p_true = p_market + f(direction, materiality, novelty, conf)    │
│  EV_net = |p_true - p_market| - slippage                        │
│  price adjustment capped at 12% (prevents LLM overconfidence)   │
│  size = min(MAX_BET, K * EV * confidence * bankroll)             │
└────────────────────────────┬────────────────────────────────────┘
                             │ Signal
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  RISK LAYER   risk.py                                             │
│  daily loss cap / max concurrent positions /                     │
│  per-category exposure / consecutive loss cooldown               │
│  per-market 10-min cooldown (prevents duplicate signals)         │
└────────────────────────────┬────────────────────────────────────┘
                             │ approved Signal
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EXECUTION   executor.py                                          │
│  limit orders at mid ± OFFSET (avoid crossing spread)           │
│  slippage estimation & rejection                                  │
│  retry logic (3 attempts) + partial fill handling                │
│  full latency tracking: event → classification → execution       │
└────────────────────────────┬────────────────────────────────────┘
                             │ ExecutionResult
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY                                                    │
│  logger.py      — SQLite WAL (trades, news, calibration)        │
│  calibrator.py  — predicted vs actual, Brier score, ECE          │
│  metrics.py     — rolling Sharpe, drawdown, latency p50/p95/p99  │
│  api.py         — FastAPI real-time signal broadcast (WebSocket) │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your API keys (see Configuration section)
```

### 3. Run in dry-run mode

```bash
python cli.py watch
```

### 4. Check calibration report

```bash
python cli.py calibrate
```

### 5. Run backtest

```bash
python cli.py backtest
```

---

## Environment Variables

```bash
# LLM (primary — free tier)
GROQ_API_KEY=your_groq_key

# Fallback LLM (optional)
ANTHROPIC_API_KEY=your_anthropic_key

# Polymarket CLOB (required for live trading)
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=
POLYMARKET_PRIVATE_KEY=

# News sources (optional — more = better coverage)
TWITTER_BEARER_TOKEN=
GNEWS_API_KEY=
NEWSAPI_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_IDS=

# Trading settings
DRY_RUN=true          # set false for live trading
MAX_BET_USD=25
BANKROLL_USD=1000
DAILY_LOSS_LIMIT_USD=100
```

---

## Module Reference

| Module | Role |
|--------|------|
| `pipeline.py` | Main orchestrator — concurrent event handling, full latency accounting |
| `news_stream.py` | 7-source news aggregator (Twitter, Telegram, RSS, NewsAPI, Reddit, GNews, GDELT) |
| `nlp_processor.py` | NER, sentiment, impact scoring, temporal decay |
| `matcher.py` | Semantic market routing via sentence-transformers embeddings |
| `classifier.py` | 3-pass LLM voting with consistency scoring |
| `edge_model.py` | Price adjustment model, EV calculation, position sizing |
| `market_watcher.py` | Live microstructure: WebSocket prices, order book, momentum gate |
| `executor.py` | Limit order placement with retry + partial fill handling |
| `risk.py` | Daily loss cap, position limits, category exposure, cooldowns |
| `calibrator.py` | Brier score, ECE, per-source/category accuracy breakdown |
| `backtest.py` | Strategy replay with simulated slippage and partial fills |
| `metrics.py` | Rolling Sharpe, drawdown, latency distribution |
| `logger.py` | SQLite WAL logging with indexed queries |
| `scorer.py` | Market scoring against news for CLI reporting |
| `api.py` | FastAPI server + WebSocket signal broadcaster |
| `config.py` | All settings, thresholds, and API keys |

---

## Configuration

### Edge Model
| Setting | Default | Description |
|---------|---------|-------------|
| `EDGE_ALPHA` | 0.40 | Weight on materiality in price adjustment |
| `EDGE_BETA` | 0.30 | Weight on confidence |
| `EDGE_GAMMA` | 0.30 | Weight on novelty score |
| `EDGE_THRESHOLD` | 0.03 | Min net EV to trade |
| `EDGE_MAX_ADJUSTMENT` | 0.12 | Max price adjustment (12% cap) |
| `MIN_CONFIDENCE` | 0.55 | Min LLM confidence to proceed |
| `MIN_NOVELTY` | 0.20 | Skip if likely already priced in |

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
| `ORDER_RETRY_ATTEMPTS` | 3 | Max retry count |

### Market Selection
| Setting | Default | Description |
|---------|---------|-------------|
| `MIN_VOLUME_USD` | 1,000 | Min market volume |
| `MAX_VOLUME_USD` | 500,000 | Max market volume (avoid over-efficient) |
| `PREFER_SHORT_DURATION_DAYS` | 30 | Prioritize markets resolving within N days |
| `MARKET_CATEGORIES` | ai, technology, crypto, politics, science | Categories to track |

---

## End-to-End Trade Flow

```
T+0ms    Twitter stream receives: "Fed signals unexpected rate cut"
T+50ms   NewsEvent dispatched to pipeline
T+52ms   NLP: sentiment=+0.71, impact=0.68, entities=[Fed, rate]
T+55ms   semantic match → 3 candidate markets found
         (e.g. "Will Fed cut rates before June 2025?" sim=0.82)
T+60ms   3 concurrent LLM passes launched (llama-3.3-70b, temp=0.15)
T+350ms  Passes complete: YES/YES/YES, conf=0.78, mat=0.71,
         novelty=0.82, consistency=100%
T+355ms  Order book fetch: spread=0.04, depth=$850, liq=0.85
T+356ms  Momentum check: Δprice=+0.02 (below 0.05 threshold, OK)
T+357ms  Edge model: p_market=0.42 → p_true=0.54, EV_net=0.10
         size = min($25, 0.25 * 0.10 * 0.78 * $1000) = $19.50
T+358ms  Risk gates: daily_ok, positions=2/5, category_ok, no_cooldown
T+380ms  Limit order: BUY YES @0.44 (mid − offset)
T+410ms  Order confirmed: filled $19.50 @0.443, slippage=+0.003
T+410ms  Trade logged → SQLite, signal broadcast → WebSocket
```

---

## Further Optimization Opportunities

### Speed
- **Rust CLOB client**: Replace py_clob_client with a Rust extension — eliminates GIL overhead, reduces execution from ~30ms to ~3ms
- **Parallel inference**: Run LLM passes against multiple Groq API keys simultaneously — reduces classification from 300ms to 100ms
- **Pre-warm embeddings**: Keep sentence-transformers warm at startup with periodic no-op inference

### Edge Model
- **Bayesian updating**: Treat each classification pass as a Bayesian update to a Beta prior — more principled than majority vote
- **Historical calibration multiplier**: Weight p_true adjustment by empirical accuracy per source/category (from calibrator)
- **Micro-feature engineering**: Add bid/ask imbalance, volume spike, time-to-resolution decay to adjustment function

### Market Selection
- **Resolution predictor**: Train a small model on historical data to predict which markets are most likely to move soon
- **Correlation filter**: Avoid correlated positions (e.g., two crypto markets simultaneously)

### Infrastructure
- **Redis pub/sub**: Replace asyncio queues with Redis for multi-process pipelines and cross-restart dedup
- **Co-location**: Deploy on a VPS in same region as Polymarket CLOB servers (US-East) for lower latency
- **Prometheus + Grafana**: Export metrics for real-time monitoring dashboard
