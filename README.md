# Polymarket Signal Pipeline v3

Event-driven NLP infrastructure for binary prediction markets. Ingests breaking news from 7 concurrent sources, semantically matches events to markets via hybrid scoring (semantic + entity + keyword), runs 3-tier classification (watchlist → LightGBM → LLM with rule-based fallback), computes edge via sigmoid-dampened price adjustment, sizes positions through fractional Kelly with drawdown scaling, and executes through Polymarket CLOB and Kalshi REST — all within a 5-second latency target.

**Status:** Shadow mode by default (`DRY_RUN=true`). Live trading requires manual approval gating. **228 tests, 0 failures.**

**Stack:** Python 3.11+ · asyncio · Groq/DeepSeek (OpenAI-compatible) · sentence-transformers · LightGBM · spaCy · VADER · FastAPI + WebSocket · SQLite (WAL, 15 tables) · React + Vite + Tailwind · Polymarket CLOB · Kalshi

---

## Architecture

```
                         ┌──────────────────────────┐
                         │    7 News Sources         │
                         │  RSS · NewsAPI · GNews    │
                         │  GDELT · Reddit · Twitter │
                         │  Telegram                 │
                         └──────────┬───────────────┘
                                    │ NewsEvent
                                    ▼
                         ┌──────────────────────────┐
                         │  NLP ENRICHMENT           │
                         │  65 custom regex patterns │
                         │  spaCy NER · VADER        │
                         │  impact scoring (no decay)│
                         └──────────┬───────────────┘
                                    │
                                    ▼
                         ┌──────────────────────────┐
                         │  HYBRID MARKET MATCHER    │
                         │  semantic + entity + kw   │
                         │  score = max(sem,kw)      │
                         │    + entity×0.25 + kw×0.15│
                         └──────────┬───────────────┘
                                    │ MarketMatch[]
                                    ▼
              ┌──────────────────────────────────────────┐
              │  3-TIER CLASSIFIER (with fallback)        │
              │  Tier 1: Watchlist (80 phrases, <1ms)     │
              │  Tier 2: LightGBM (40 features, <1ms)     │
              │  Tier 3: Sequential LLM passes (~300ms)   │
              │  Fallback: Rule-based on API rate-limit   │
              └────────────────────┬─────────────────────┘
                                   │ Classification
                                   ▼
              ┌──────────────────────────────────────────┐
              │  EDGE MODEL + ENSEMBLE + PORTFOLIO        │
              │  sigmoid-dampened adj, fractional Kelly   │
              │  news(0.6) + momentum(0.4) voting         │
              │  drawdown-scaled allocation               │
              └────────────────────┬─────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
         ┌──────────────────┐          ┌──────────────────┐
         │  EXECUTION ENGINE│          │  SAFETY GATES    │
         │  Polymarket CLOB │          │  manual approval │
         │  Kalshi REST     │          │  8 circuit break │
         │  Order FSM (11)  │          │  hard-stop       │
         │  Position FSM (8)│          │  proposal expiry │
         └────────┬─────────┘          └──────────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────┐ ┌──────────┐ ┌──────────────┐
│RECON   │ │SETTLEMENT│ │MARKET SYNC   │
│6-state │ │6-stage   │ │5 health      │
│FSM     │ │FSM       │ │states        │
│exch-   │ │active    │ │self-healing  │
│author  │ │polling   │ │sequence-gap  │
└────────┘ └──────────┘ └──────────────┘
                  │
                  ▼
         ┌──────────────────┐
         │  OBSERVABILITY   │
         │  trace IDs (8 FSM)│
         │  rejection analytics│
         │  replay reconstruction│
         │  DLQ · health monitors│
         │  EVA analysis        │
         │  SQLite WAL (15 tbl) │
         │  FastAPI 36 endpoints│
         └──────────────────┘
```

## Directory Structure

```
├── alpha/                     Strategy layer
│   ├── signal.py              AlphaSignal, AggregatedSignal
│   ├── news_alpha.py          LLM-driven news alpha
│   ├── momentum_alpha.py      BTC momentum (CoinGecko, 60s)
│   └── ensemble.py            Weighted voting (news=0.6, mom=0.4)
├── control/                   Runtime controls
│   ├── trading_mode.py        LIVE/DRY_RUN toggle
│   └── safety_guard.py        Drawdown + cooldown checks
├── execution/                 Order placement + hardening
│   ├── executor.py            Polymarket CLOB execution
│   ├── execution_engine.py    Signal → order bridge
│   ├── kalshi_executor.py     Kalshi REST execution
│   ├── slippage_model.py      Market impact estimation
│   ├── smart_router.py        Spread/momentum routing
│   ├── order_lifecycle.py     ★ 11-state Order FSM, idempotency, append-only ledger
│   ├── position_lifecycle.py  ★ 8-state Position FSM, PnL, orphan detection
│   ├── circuit_breakers.py    ★ 8 breakers, kill-switch, fail-safe
│   ├── reconciliation.py      ★ 6-state FSM, exchange-authoritative, auto-repair
│   ├── settlement.py          ★ 6-stage FSM, active Gamma API polling
│   ├── risk_accounting.py     ★ Exposure limits, concentration detection
│   ├── market_sync.py         ★ Self-healing, 5 health states, sequence gaps
│   ├── task_supervisor.py     ★ 7-state lifecycle, restart, heartbeat
│   └── live_safety.py         ★ Pre-flight, hard-stop, manual approval, expiry
├── ingestion/                 Data input
│   ├── news_stream.py         7 async news sources
│   ├── market_watcher.py      WebSocket + REST market data
│   ├── markets.py             Polymarket Gamma + CLOB API
│   ├── kalshi_markets.py      Kalshi (fixed dollar-format parser)
│   ├── scraper.py             RSS (feedparser) + NewsAPI
│   ├── categories.py          8 category definitions
│   └── reddit_source.py       Adaptive subreddit selector
├── observability/             Telemetry + diagnostics
│   ├── tracer.py              ★ Trace IDs, 8-stage FSM, causal correlation, DLQ
│   ├── rejection.py           ★ 19 rejection reasons, 4 severity levels
│   ├── stage_timer.py         ★ Ring buffer, latency distributions, measure() CM
│   ├── inspector.py           ★ PipelineInspection, PipelineHeatmap, QueueDepths
│   ├── health_monitor.py      ★ 4 watchdog types, dual emission (log + WS)
│   ├── signal_attrition.py    ★ Waterfall chart, per-stage drop-off rates
│   ├── market_audit.py        ★ Per-headline matching diagnostics
│   ├── market_universe.py     ★ Filter pipeline audit
│   ├── signal_review.py       ★ 11-label review queue, SQLite persistence
│   ├── soak_monitor.py        ★ 29-metric snapshots, trend analysis
│   ├── soak_report.py         ★ Post-soak health assessment, readiness gate
│   ├── exchange_logger.py     ★ Raw REST/WS payload capture
│   ├── eva_analysis.py        ★ Expected vs Actual measurements
│   ├── incidents.py           ★ Incident reports, root cause, blast radius
│   ├── logger.py              SQLite (15 tables), trace/dead-letter persistence
│   ├── metrics.py             Rolling Sharpe, latency p50/p95/p99
│   ├── calibrator.py          Brier/ECE calibration
│   ├── backtest.py            Strategy replay
│   └── broadcaster.py         7 typed events, heartbeat, fail-open
├── portfolio/                 Risk + sizing
│   ├── portfolio_manager.py   Central decision engine
│   ├── allocator.py           Drawdown-scaled Kelly sizing
│   ├── risk.py                RiskManager (total_exposure added)
│   ├── risk_engine.py         Validation wrapper
│   ├── _paper.py              Paper portfolio simulation
│   └── exposure_tracker.py    Read-only exposure queries
├── providers/                 Platform adapters
│   ├── polymarket.py          Polymarket adapter
│   └── kalshi.py              Kalshi adapter
├── signal/                    Signal generation
│   ├── classifier.py          Sequential LLM passes + rule-based fallback
│   ├── fast_classifier.py     3-tier hot path, expanded certainty words
│   ├── cold_path.py           Labeling flywheel
│   ├── watchlist.py           80 phrases (expanded financial/news terms)
│   ├── edge_model.py          Sigmoid-dampened adjustment
│   ├── matcher.py             Hybrid: semantic + entity + keyword scoring
│   └── nlp_processor.py       65 custom regex entities + spaCy NER
├── tests/                     8 test suites, 228 tests
├── dashboard/                 React + Vite + Tailwind
│   └── src/components/
│       ├── RiskControlConsole.jsx  ★ Wired kill-switch, real exposure data
│       ├── SignalFeed.jsx, HeroCommandCenter.jsx, ExecutionPipeline.jsx
│       ├── OperatorConsole.jsx, MarketTable.jsx, EquityCurve.jsx
│       └── VirtualMoney.jsx, TradingModeControl.jsx, PredictionTool.jsx
├── config.py                  All settings + 17-key runtime override system
├── pipeline.py                10 supervised background tasks
├── cli.py                     15 commands
├── api.py                     36 REST + 2 WebSocket endpoints
├── docs/
│   ├── paper.md               Research paper (17 sections)
│   └── presentation.md        Presentation blueprint (23 slides, scripts, Q&A)
└── models/                    LightGBM model + labels.jsonl
```

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env              # fill in GROQ_API_KEY
python cli.py preflight           # 9-point validation
python cli.py watch               # shadow mode (DRY_RUN=true)
python api.py                     # FastAPI on :8000
```

Dashboard:
```bash
cd dashboard && npm install && npm run dev    # :3000, proxies API to :8000
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `watch` | Event-driven pipeline (shadow by default, `--live` for real) |
| `preflight` | 9-point validation before live trading |
| `hard-stop` | EMERGENCY: immediate execution freeze |
| `debug-dashboard` | Rejection analytics, bottlenecks, DLQ |
| `signal-attrition` | Stage-by-stage drop-off waterfall |
| `soak-report` | Operational health + live-capital readiness |
| `review-queue` | Signal quality labeling (11 labels) |
| `dashboard` | Terminal dashboard (read-only) |
| `backtest`, `calibrate`, `verify`, `scrape`, `markets`, `trades`, `stats`, `niche` | Utilities |

## API Reference (36 endpoints)

### Core
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Pipeline uptime, events, signals, risk |
| GET | `/portfolio` | Full portfolio state |
| GET | `/signals/recent` | Recent trade log |
| GET | `/markets`, `/stats`, `/sources`, `/categories` | Market/stat/source data |
| POST | `/trading/mode` | DRY_RUN ↔ LIVE |
| WS | `/ws/signals` | Real-time signal stream |

### Observability (12 endpoints)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/debug/traces` | Signal lifecycle traces |
| GET | `/debug/traces/{id}` | Full trace reconstruction |
| GET | `/debug/rejections` | Rejection analytics |
| GET | `/debug/pipeline` | Live pipeline inspection |
| GET | `/debug/heatmap` | Rejection hotspots, bottlenecks |
| GET | `/debug/stages` | Per-stage latency distributions |
| GET | `/debug/queues` | Queue depths |
| GET | `/debug/dlq` | Dead-letter queue |
| GET | `/debug/health` | Watchdog status |
| GET | `/debug/supervisor` | Task health, reconciliation, breakers |
| WS | `/ws/debug` | Real-time pipeline events |

### Live Safety (6 endpoints)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/live/pending` | Pending trade proposal |
| POST | `/live/approve` | Approve pending trade |
| POST | `/live/reject` | Reject pending trade |
| POST | `/live/hard-stop` | Emergency halt |
| POST | `/live/clear-stop` | Resume after investigation |
| GET | `/live/snapshot` | Runtime state dump |
| GET | `/live/eva` | Expected vs Actual analysis |

## Key Algorithms

### Hybrid Market Matching
```
score = max(semantic_score, keyword_score) + entity_bonus × 0.25 + keyword_bonus × 0.15
```
Semantic: all-MiniLM-L6-v2 (384-dim). Entity: Jaccard-like overlap. Keyword: Jaccard similarity. Threshold: 0.20 (evidence-calibrated from 0.30).

### Edge Model
```
raw  = 0.40·materiality + 0.30·confidence + 0.30·novelty
adj  = room × (1 − exp(−2·raw)), capped at 0.12
EV   = |p_true − p_market| − estimated_slippage
size = min(MAX_BET, K × EV × confidence × bankroll), K=0.25
```

### Position Sizing (with drawdown scaling)
```
dd_scale = max(0, 1 − drawdown × 2)     → zero at 50% drawdown
final    = clamp(size × multiplier × dd_scale, $1.00, MAX_BET)
```

## Execution Hardening

### Finite State Machines
- **Signal:** 8 states (INGESTED → SETTLED), strict transitions
- **Order:** 11 states (CREATED → SETTLED), SHA256 idempotency keys
- **Position:** 8 states (OPENING → SETTLED), orphan detection
- **Reconciliation:** 6 states (CLEAN → QUARANTINED)
- **Settlement:** 6 stages (PENDING → SETTLED/DISPUTED/REFUNDED)
- **Market Sync:** 5 health states (HEALTHY → HEALING)

### Safety Infrastructure
- 8 circuit breakers (rapid losses, duplicate orders, excessive slippage, etc.)
- Manual approval gating (propose → review → approve → execute)
- Proposal expiry (5 min), approval locking (1 pending max)
- Emergency hard-stop (`python cli.py hard-stop`)
- Pre-flight validation (9 checks before live execution)
- Append-only order ledger (full reconstruction)
- Exchange-authoritative reconciliation (auto-repair + escalation)

## Live Deployment Phases

| Phase | Max Bet | Positions | Daily Loss | Manual Approval |
|-------|---------|-----------|------------|-----------------|
| 0 (Shadow) | $0 | 0 | N/A | N/A |
| 1 (Minimal) | $2 | 1 | $5 | Required |
| 2 (Constrained) | $5 | 2 | $10 | Required |
| 3 (Validated) | TBD | TBD | TBD | Optional |

## Testing

```bash
python -m pytest tests/ -v    # 228 tests, 0 failures
```

| Suite | Tests | Focus |
|-------|-------|-------|
| test_observability | 43 | FSM, traces, DLQ, stage timer |
| test_validation | 24 | Stress (10K burst), fail-open, replay |
| test_adversarial | 15 | Duplicate storms, overflow, malformed |
| test_execution | 30 | Order/position FSM, idempotency, breakers |
| test_hardening | 14 | Reconciliation, settlement, risk accounting |
| test_durability | 15 | Market sync, task supervisor |
| Existing suites | 87 | Allocator, alpha, ensemble, classifier, portfolio |

## Key Metrics

| Metric | Value |
|--------|-------|
| Offline match rate | 83.3% |
| Live match rate (shadow) | 96.7% |
| NLP gate pass rate | 100% (was 4%) |
| Market universe | 27 (was 5) |
| Automated tests | 228 (0 failures) |
| Background tasks | 10 |
| Rejection reasons | 19 |
| Circuit breakers | 8 |
| Pre-flight checks | 9/9 PASS |
| Reconciliation anomalies | 0 |
| DLQ entries | 0 |
