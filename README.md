# Polymarket V3 — Quant-Grade Event-Driven Trading System

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  NEWS INGEST                                                      │
│  news_stream.py  ←  Twitter API v2 / Telegram / RSS fallback     │
│  (async generator, <1s latency)                                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ NewsEvent
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MARKET MAPPING   matcher.py                                      │
│  sentence-transformers embeddings (all-MiniLM-L6-v2, 384-dim)   │
│  cosine similarity → top-k markets above threshold               │
│  fallback: keyword overlap                                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ MarketMatch[]
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EVENT INTELLIGENCE   classifier.py                              │
│  3 concurrent LLM passes (claude-haiku, temp=0.15)               │
│  outputs: direction / confidence / materiality /                 │
│           novelty_score / time_sensitivity / consistency          │
│  rejects: consistency < 0.6, confidence < 0.6, novelty < 0.4    │
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
│  rejects: EV_net < 0.06, spread > 8%, low liquidity             │
│  size = min(MAX_BET, K * EV * confidence * bankroll)             │
└────────────────────────────┬────────────────────────────────────┘
                             │ Signal
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  RISK LAYER   risk.py                                             │
│  daily loss cap / max concurrent positions /                     │
│  per-category exposure / consecutive loss cooldown               │
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
│  logger.py      — SQLite (trades, news, calibration, latency)   │
│  calibrator.py  — predicted vs actual, Brier score, ECE          │
│  metrics.py     — rolling Sharpe, drawdown, latency p50/p95/p99  │
│  backtest.py    — realistic replay (slippage + partial fills)    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Reference

| Module | Role | Key Changes from V2 |
|--------|------|---------------------|
| `classifier.py` | Multi-pass LLM voting | 3 concurrent passes, consistency score, novelty_score, confidence field |
| `matcher.py` | Semantic market routing | sentence-transformers embeddings + cosine similarity, keyword fallback |
| `edge_model.py` | Edge estimation | NEW: p_true adjustment model, EV_net after slippage, capped fractional sizing |
| `market_watcher.py` | Microstructure | Order book depth, spread, momentum gate, slippage estimation |
| `executor.py` | Smart order placement | Limit orders near spread, retry logic, partial fills, latency tracking |
| `risk.py` | Risk controls | NEW: category exposure, concurrent position cap, cooldown after losses |
| `calibrator.py` | Accuracy tracking | Per-source/category/confidence-bucket, Brier score, ECE, calibration curve |
| `backtest.py` | Strategy validation | Simulated latency (1–5s), spread model, partial fills, Sharpe + drawdown |
| `metrics.py` | Live performance | NEW: rolling Sharpe, drawdown, latency distribution (p50/p95/p99) |
| `pipeline.py` | Orchestrator | Concurrent event handling, microstructure gates, full latency accounting |
| `config.py` | Settings | All V3 params: edge model weights, risk limits, execution config |

---

## Configuration

### Edge Model
| Setting | Default | Description |
|---------|---------|-------------|
| `EDGE_ALPHA` | 0.40 | Weight on materiality in price adjustment |
| `EDGE_BETA` | 0.30 | Weight on confidence |
| `EDGE_GAMMA` | 0.30 | Weight on novelty score |
| `EDGE_THRESHOLD` | 0.06 | Min net EV to trade |
| `MIN_CONFIDENCE` | 0.60 | Min LLM confidence |
| `MIN_NOVELTY` | 0.40 | Skip if likely already priced in |

### Risk Controls
| Setting | Default | Description |
|---------|---------|-------------|
| `DAILY_LOSS_LIMIT_USD` | 100 | Hard stop |
| `MAX_CONCURRENT_POSITIONS` | 5 | Max open positions |
| `MAX_EXPOSURE_PER_CATEGORY_USD` | 60 | Per-category cap |
| `CONSECUTIVE_LOSS_COOLDOWN` | 3 | N losses → pause |
| `COOLDOWN_MINUTES` | 30 | Pause duration |

### Execution
| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_SPREAD_FRACTION` | 0.08 | Skip if spread > 8% |
| `MAX_SLIPPAGE_FRACTION` | 0.03 | Reject if slippage > 3% |
| `LIMIT_ORDER_OFFSET` | 0.01 | Place limit 1¢ inside spread |
| `ORDER_RETRY_ATTEMPTS` | 3 | Max retry count |

---

## End-to-End Trade Flow

```
T+0ms    Twitter stream receives: "Fed signals unexpected rate cut"
T+50ms   NewsEvent dispatched to pipeline
T+55ms   semantic match → 3 candidate markets found
         (e.g. "Will Fed cut rates before June 2025?" sim=0.82)
T+60ms   3 concurrent LLM passes launched (haiku, temp=0.15)
T+350ms  Passes complete: YES/YES/YES, conf=0.78, mat=0.71,
         novelty=0.82, consistency=100%
T+355ms  Order book fetch: spread=0.04, depth=$850, liq=0.85
T+356ms  Momentum check: Δprice=+0.02 (below 0.05 threshold, OK)
T+357ms  Edge model: p_market=0.42 → p_true=0.58, EV_net=0.14
         size = min($25, 0.25 * 0.14 * 0.78 * $1000) = $25
T+358ms  Risk gates: daily_ok, positions=2/5, category_ok, no_cooldown
T+380ms  Limit order: BUY YES @0.44 (mid-spread/2 + 0.01 offset)
T+410ms  Order confirmed: order_id=0xabc, filled $25 @0.443
         slippage=+0.003 (within limit)
T+410ms  Trade logged → SQLite
         Metrics updated: latency=360ms ✓ (target=5000ms)
```

---

## Further Optimization Opportunities

### Speed
- **Rust CLOB client**: Replace py_clob_client with a Rust extension for order signing — eliminates GIL and reduces execution overhead from ~30ms to ~3ms
- **Parallel inference**: Run LLM passes against 2–3 Anthropic API endpoints in parallel (same model, different API keys) — reduces classification from 300ms to 100ms
- **Pre-warm embeddings**: Load sentence-transformers at startup and keep GPU warm with periodic no-op inference

### Edge Model
- **Bayesian updating**: Treat each classification pass as a Bayesian update to a Beta prior; more principled than majority vote
- **Historical calibration multiplier**: Weight the p_true adjustment by empirical accuracy per source/category (from calibrator)
- **Micro-feature engineering**: Add bid/ask imbalance, recent volume spike, time-to-resolution decay to adjustment function

### Market Selection
- **Resolution predictor**: Train a small model on historical data to predict which markets are most likely to move in the next 30 minutes
- **Correlation filter**: Avoid correlated positions (e.g., two crypto markets at once) — diversification within the position cap

### Infrastructure
- **Redis pub/sub**: Replace asyncio queues with Redis for multi-process pipelines
- **Co-location**: Deploy on a VPS in same region as Polymarket CLOB servers (US-East)
- **Prometheus + Grafana**: Export metrics for real-time monitoring dashboard
