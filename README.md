# Polymarket Signal Pipeline v3

Event-driven trading system for binary prediction markets. Ingests breaking news from 7 concurrent sources, routes events to semantically-matched markets, runs 3-tier classification to score market impact, applies a signal-weighted edge model against live CLOB quotes, and executes limit orders — all within a 5-second latency target.

**Status:** Dry-run mode by default (`DRY_RUN=true`). Live trading requires a funded Polymarket account.

**Stack:** Python 3.11+ · asyncio · Groq (llama-3.3-70b) / Anthropic fallback · sentence-transformers · LightGBM · FastAPI + WebSocket · SQLite (WAL) · Polymarket CLOB · Kalshi

---

## Architecture

```
                         ┌──────────────────────────┐
                         │    7 News Sources        │
                         │  Twitter · Telegram · RSS│
                         │  NewsAPI · GNews · GDELT │
                         │  Reddit (adaptive)       │
                         └──────────┬───────────────┘
                                    │ NewsEvent
                                    ▼
                         ┌──────────────────────────┐
                         │  NLP GATE                │
                         │  spaCy NER · VADER       │
                         │  impact scoring · decay  │
                         └──────────┬───────────────┘
                                    │ enriched event
                                    ▼
                         ┌──────────────────────────┐
                         │  MARKET MATCHER          │
                         │ sentence-transformers    │
                         │ cosine similarity · top-K│
                         └──────────┬───────────────┘
                                    │ MarketMatch[]
                                    ▼
              ┌──────────────────────────────────────────┐
              │  THREE-TIER CLASSIFIER                   │
              │  Tier 1: Watchlist (65 phrases, <1ms)    │
              │  Tier 2: LightGBM (40 features, <1ms)    │
              │  Tier 3: 3-pass LLM vote (~300ms)        │
              │  Gates: conf≥0.55 mat≥0.30 nov≥0.20      │
              └────────────────────┬─────────────────────┘
                                   │ Classification
                                   ▼
              ┌──────────────────────────────────────────┐
              │  EDGE MODEL                              │
              │  Sigmoid-dampened price adjustment       │
              │  adj = room × (1 − exp(−2·raw))          │
              │  EV_net = |p_true − p_market| − slippage │
              │  Kelly sizing: K × EV × confidence × BR  │
              └────────────────────┬─────────────────────┘
                                   │ Signal
                                   ▼
              ┌──────────────────────────────────────────┐
              │  ALPHA + ENSEMBLE                        │
              │  NewsAlpha (LLM) · MomentumAlpha (BTC)   │
              │  Weighted voting (news=0.6 mom=0.4)      │
              │  multipliers: agreement=1.0 single=0.6   │
              └────────────────────┬─────────────────────┘
                                   │ AggregatedSignal
                                   ▼
              ┌──────────────────────────────────────────┐
              │  PORTFOLIO MANAGER                       │
              │  Allocator (drawdown-scaled Kelly)       │
              │  RiskEngine (atomic slot reservation)    │
              │  ExecutionEngine (smart routing)         │
              └────────────────────┬─────────────────────┘
                                   │
                                   ▼
              ┌──────────────────────────────────────────┐
              │  EXECUTION                               │
              │  Polymarket CLOB ←→ Kalshi REST          │
              │  Limit orders ·retry (3x) ·slippage gate │
              └────────────────────┬─────────────────────┘
                                   │ ExecutionResult
                                   ▼
              ┌──────────────────────────────────────────┐
              │  OBSERVABILITY                           │
              │  SQLite WAL · real-time metrics          │
              │  Brier score · ECE calibration           │
              │  WebSocket broadcast · FastAPI REST      │
              │  Cold-path labeling → model retraining   │
              └──────────────────────────────────────────┘
```

### Component Details

| Module | Role |
|--------|------|
| `pipeline.py` | Main orchestrator — concurrent event dispatch, shutdown management, latency accounting |
| `ingestion/news_stream.py` | 7-source aggregator with dedup router (Twitter, Telegram, RSS, NewsAPI, Reddit, GNews, GDELT) |
| `ingestion/market_watcher.py` | Live microstructure: WebSocket price feed, REST order book, momentum gate, 5-min market refresh |
| `ingestion/markets.py` | Polymarket Gamma API + CLOB fallback market fetching, category inference, token ID lookup |
| `ingestion/kalshi_markets.py` | Kalshi market fetching with RSA/JWT auth, cent-to-prob conversion, pagination |
| `ingestion/scraper.py` | Synchronous RSS scraper (feedparser), NewsAPI polling, deduplication |
| `ingestion/categories.py` | 8 category definitions with keywords, Twitter/RSS/NewsAPI/Reddit source mappings |
| `ingestion/reddit_source.py` | Adaptive weighted subreddit sampling with SQLite-backed performance tracking |
| `signal/classifier.py` | 3-pass concurrent LLM voting via Groq (25 RPM token bucket, semaphore=3), majority direction, consistency scoring |
| `signal/fast_classifier.py` | 3-tier hot path: watchlist → LightGBM (40 features) → rule-based fallback |
| `signal/cold_path.py` | Async labeling worker — runs slow classifier on pipeline trades, writes labels to JSONL, triggers retraining every 50 labels |
| `signal/watchlist.py` | 65 high-signal phrase patterns with direction/confidence, longest-match semantics |
| `signal/edge_model.py` | Sigmoid-dampened price adjustment with asymmetric boundary correction, EV computation, Kelly sizing |
| `signal/matcher.py` | Semantic routing via sentence-transformers (all-MiniLM-L6-v2, 384-dim) or OpenAI embeddings, cached market vectors |
| `signal/nlp_processor.py` | spaCy NER, VADER sentiment, keyword category classification, weighted impact scoring, exponential temporal decay |
| `alpha/news_alpha.py` | Converts edge model Signal → AlphaSignal with horizon mapping |
| `alpha/momentum_alpha.py` | BTC price momentum via CoinGecko (60s poll), generates signals for Bitcoin-tagged markets |
| `alpha/ensemble.py` | Weighted directional voting (news=0.6, momentum=0.4), conflict/agreement detection, size multiplier |
| `alpha/signal.py` | AlphaSignal and AggregatedSignal dataclasses with validation |
| `portfolio/portfolio_manager.py` | Central decision engine — syncs capital, computes size, validates risk, delegates execution |
| `portfolio/allocator.py` | Dynamic position sizing with drawdown scaling (linear reduction, zero at 50%) |
| `portfolio/risk_engine.py` | Thin RiskManager wrapper with atomic `try_open_position()` slot reservation |
| `portfolio/risk.py` | RiskManager singleton: position limits, category exposure, consecutive loss cooldown, daily loss cap |
| `portfolio/_paper.py` | Paper portfolio simulation: balance tracking, mark-to-market, PnL, position lifecycle |
| `portfolio/exposure_tracker.py` | Read-only exposure state queries |
| `execution/executor.py` | Polymarket CLOB order execution with retry logic, limit price computation, risk gate checks |
| `execution/execution_engine.py` | Bridges alpha signals to execution — converts AggregatedSignal → order, applies smart routing |
| `execution/kalshi_executor.py` | Kalshi order execution with cent-based pricing, RSA/JWT auth, retry logic |
| `execution/slippage_model.py` | Linear market-impact estimate: (size / depth) × spread |
| `execution/smart_router.py` | Spread/momentum-based routing: aggressive / passive / reject |
| `control/trading_mode.py` | LIVE/DRY_RUN runtime toggle with SafetyGuard and mode history |
| `control/safety_guard.py` | Drawdown check (<20%) and RiskManager cooldown gate for live trading |
| `observability/logger.py` | SQLite WAL logging: trades, outcomes, positions, calibration, pipeline_runs, news_events |
| `observability/metrics.py` | In-memory rolling metrics: Sharpe, drawdown, latency p50/p95/p99, trades/hour |
| `observability/calibrator.py` | Resolution checking via Gamma API, Brier score, ECE bucketing, per-source accuracy |
| `observability/backtest.py` | Strategy replay against resolved markets with simulated latency/slippage/fills |
| `observability/broadcaster.py` | Non-blocking fan-out pub/sub for WebSocket signal streaming |
| `providers/polymarket.py` | Thin market provider adapter |
| `providers/kalshi.py` | Thin market provider adapter |

---

## Directory Structure

```
├── alpha/                  Strategy layer (news + momentum alpha signals)
│   ├── signal.py           AlphaSignal, AggregatedSignal dataclasses
│   ├── base_alpha.py       Abstract base
│   ├── news_alpha.py       LLM-driven news alpha
│   ├── momentum_alpha.py   BTC price-driven momentum alpha
│   └── ensemble.py         Weighted voting combiner
├── control/                Runtime safety controls
│   ├── trading_mode.py     LIVE/DRY_RUN toggle
│   └── safety_guard.py     Drawdown + cooldown checks
├── execution/              Order placement
│   ├── executor.py         Polymarket CLOB execution
│   ├── execution_engine.py Signal → order bridge
│   ├── kalshi_executor.py  Kalshi order execution
│   ├── slippage_model.py   Market impact estimation
│   └── smart_router.py     Spread/momentum routing
├── ingestion/              Data input
│   ├── news_stream.py      7 async news sources
│   ├── market_watcher.py   WebSocket + REST market data
│   ├── markets.py          Market fetching + models
│   ├── kalshi_markets.py   Kalshi adapter
│   ├── scraper.py          Sync RSS scraper
│   ├── categories.py       8 category definitions
│   └── reddit_source.py    Adaptive subreddit selector
├── observability/          Logging + analytics
│   ├── logger.py           SQLite WAL ORM
│   ├── metrics.py          Rolling performance metrics
│   ├── calibrator.py       Brier/ECE calibration
│   ├── backtest.py         Strategy replay
│   └── broadcaster.py      WebSocket pub/sub
├── portfolio/              Risk + sizing
│   ├── portfolio_manager.py Central decision engine
│   ├── allocator.py        Drawdown-scaled Kelly sizing
│   ├── risk.py             RiskManager singleton
│   ├── risk_engine.py      Validation wrapper
│   ├── _paper.py           Paper portfolio simulation
│   └── exposure_tracker.py Read-only exposure
├── providers/              Platform adapters
│   ├── base.py             Abstract provider
│   ├── polymarket.py       Polymarket adapter
│   └── kalshi.py           Kalshi adapter
├── signal/                 Signal generation
│   ├── classifier.py       3-pass LLM voting
│   ├── fast_classifier.py  3-tier hot path
│   ├── cold_path.py        Labeling flywheel
│   ├── watchlist.py        65-phrase index
│   ├── edge_model.py       Price adjustment formula
│   ├── matcher.py          Semantic market matching
│   └── nlp_processor.py    NLP enrichment
├── tests/                  Test suite (87 tests)
├── models/                 Fast classifier model + labels
│   └── labels.jsonl        Training labels
├── config/                 Configuration files
│   └── rss_feeds.json      RSS feed URLs
├── dashboard/              React web dashboard (Vite + Tailwind)
├── docs/                   Archived plans
├── config.py               All settings from .env
├── pipeline.py             Main orchestrator
├── cli.py                  CLI interface (argparse)
├── api.py                  FastAPI server
├── dashboard.py            Rich terminal dashboard
├── requirements.txt        Python dependencies
├── pytest.ini              Pytest configuration
└── .env.example            Environment template
```

---

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env   # fill in GROQ_API_KEY at minimum

# 3. Verify setup
python cli.py verify

# 4. Run pipeline (dry-run by default)
python cli.py watch

# 5. Launch terminal dashboard (read-only display)
python cli.py dashboard

# 6. Start API server
python api.py           # FastAPI + WebSocket on :8000

# 7. Other commands
python cli.py stats                     # Trading summary
python cli.py stats --since 2026-05-01  # Filter by date
python cli.py trades                    # Recent trade log
python cli.py trades --since 2026-05-01 # Filter by date
python cli.py markets                   # Tracked market list
python cli.py niche                     # Niche markets only
python cli.py calibrate                 # Probability calibration report
python cli.py backtest                  # Strategy replay
python cli.py scrape                    # Test news scraper
```

---

## CLI Reference

| Command | Description | Key Flags |
|---------|-------------|-----------|
| `watch` | Event-driven pipeline | `--live` enable trading, `--threshold FLOAT`, `--categories LIST` |
| `run` | Deprecated — use `watch` | |
| `dashboard` | Terminal dashboard | `--speed SECONDS` (default 60) |
| `backtest` | Strategy replay | `--limit N` (default 30), `--category STR` |
| `calibrate` | Brier/ECE accuracy report | |
| `niche` | Browse niche markets | |
| `verify` | Check API keys + connections | |
| `scrape` | Test news scraper | `--hours N` (default 6) |
| `markets` | View all tracked markets | `--max N` (default 50) |
| `trades` | View trade log | `--limit N`, `--since ISO_DATE` |
| `stats` | Performance statistics | `--since ISO_DATE` |
| `--verbose` | DEBUG log output | (global flag) |
| `--quiet` | Errors-only log output | (global flag) |

---

## API Reference

Start the server:
```bash
python api.py                    # default :8000
API_PORT=9000 python api.py      # custom port
```

### REST Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Health check |
| `GET` | `/status` | Yes | Pipeline uptime, events, signals, risk state |
| `GET` | `/signals/recent?limit=20` | Yes | Recent trade log |
| `GET` | `/markets?category=&source=` | Yes | Tracked markets with prices/volume |
| `GET` | `/stats?category=` | Yes | Trade stats, calibration, latency |
| `GET` | `/portfolio` | Yes | Full portfolio state (balance, positions, PnL, Sharpe) |
| `GET` | `/categories` | Yes | Available/selected categories with counts |
| `GET` | `/sources` | Yes | News source status and event counts |
| `GET` | `/subreddit-stats` | Yes | Adaptive subreddit performance |
| `GET` | `/prediction?event=TEXT` | Yes | Classify a headline against tracked markets (rate limited) |
| `POST` | `/trading/mode` | Yes | Switch LIVE/DRY_RUN |
| `GET` | `/trading/status` | Yes | Current mode + switch history |
| `WS` | `/ws/signals` | No | Real-time signal stream |

### Authentication

Set `API_SECRET_KEY` in `.env` to enable authentication. Clients must send `X-API-Key: <key>` header on protected endpoints. When `API_SECRET_KEY` is unset, all endpoints are open (dev mode).

### WebSocket

Connect to `ws://localhost:8000/ws/signals` for real-time signal JSON:
```json
{
  "type": "signal",
  "side": "YES",
  "market": "Will BTC exceed $100K...",
  "market_id": "0x...",
  "p_market": 0.42,
  "p_true": 0.54,
  "ev": 0.10,
  "bet_usd": 19.50,
  "status": "paper",
  "source": "rss",
  "headline": "Bitcoin surges past...",
  "latency_ms": 410,
  "strategies": ["news"],
  "timestamp": "2026-05-10T12:00:00Z"
}
```
Heartbeats: `{"type": "ping"}` every 30s.

---

## Environment Variables

### LLM Backend
```bash
GROQ_API_KEY=                   # Primary — Groq API (free tier, 30 RPM)
# ANTHROPIC_API_KEY=sk-ant-...   # Fallback — Anthropic (used when Groq unset)
```

### Polymarket CLOB (required for live trading)
```bash
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=
POLYMARKET_PRIVATE_KEY=
```

### News Sources (all optional — more sources = better coverage)
```bash
TWITTER_BEARER_TOKEN=           # Twitter API v2 (requires Basic tier)
TELEGRAM_BOT_TOKEN=             # Telegram bot for channel monitoring
TELEGRAM_CHANNEL_IDS=           # Comma-separated channel IDs
NEWSAPI_KEY=                    # NewsAPI.org (100 req/day free)
GNEWS_API_KEY=                  # GNews (100 req/day free)
```

### Kalshi (optional second platform)
```bash
KALSHI_EMAIL=                   # JWT auth
KALSHI_PASSWORD=
KALSHI_API_KEY_ID=              # RSA auth (alternative)
KALSHI_PRIVATE_KEY_PATH=
KALSHI_DEMO=true                # Use demo API (default: true)
```

### API Server
```bash
API_SECRET_KEY=                 # Enables X-API-Key auth on all sensitive endpoints
API_PORT=8000                   # Server port
API_WORKERS=1                   # Uvicorn workers (keep at 1 per account)
```

### Pipeline Settings
```bash
DRY_RUN=true                    # Paper trading mode
MAX_BET_USD=25                  # Max position size per trade
BANKROLL_USD=1000               # Capital figure in Kelly sizing formula
PAPER_BALANCE=1000000           # Initial paper portfolio balance
EDGE_THRESHOLD=0.03             # Minimum net EV to generate a signal
EDGE_MAX_ADJUSTMENT=0.12        # Maximum price adjustment cap
```

### Market Filters
```bash
MAX_VOLUME_USD=500000           # Max market volume (avoid over-efficient markets)
MIN_VOLUME_USD=1000             # Min market volume
MATERIALITY_THRESHOLD=0.30      # Min LLM materiality score
SPEED_TARGET_SECONDS=5          # Target latency from event to execution
SELECTED_CATEGORIES=all         # Comma-separated: crypto,politics,economics,ai...
```

### Risk Controls
```bash
DAILY_LOSS_LIMIT_USD=100        # Hard daily stop
MAX_CONCURRENT_POSITIONS=5      # Max open positions
MAX_EXPOSURE_PER_CATEGORY_USD=60 # Per-category cap
CONSECUTIVE_LOSS_COOLDOWN=3     # N consecutive losses → pause
COOLDOWN_MINUTES=30             # Pause duration
```

### Execution
```bash
ORDER_TYPE=limit                # Order type
MAX_SPREAD_FRACTION=0.08        # Skip if spread > 8%
MAX_SLIPPAGE_FRACTION=0.03      # Reject if slippage > 3%
LIMIT_ORDER_OFFSET=0.01         # Place limit 1¢ inside spread
ORDER_RETRY_ATTEMPTS=3          # Max retries per order
```

### Hot Path (Fast Classifier)
```bash
HOT_PATH_ENABLED=true           # Enable 3-tier fast classification
FAST_CLASSIFIER_MIN_CONFIDENCE=0.60  # Min confidence for hot path to pass
STALENESS_THRESHOLD=0.50        # Abort if market already moved 50%+ of predicted move
HOT_PATH_CONSISTENCY=0.70       # Synthetic consistency for fast classifier outputs
```

### Other
```bash
NLP_ENABLED=true                # NLP enrichment gate
NLP_MIN_IMPACT=0.10             # Minimum impact score to pass NLP gate
EMBEDDING_BACKEND=sentence_transformers  # sentence_transformers | openai
OPENAI_API_KEY=                 # Required if EMBEDDING_BACKEND=openai
HF_TOKEN=                       # HuggingFace token (avoids rate limiting)
```

---

## Key Algorithms

### Edge Model

The price adjustment is computed as:

```
raw  = α·materiality + β·confidence + γ·novelty    (α=0.40, β=0.30, γ=0.30)
room = distance from p_market to boundary (0.05 or 0.95)
adj  = room × (1 − exp(−2·raw))                    (sigmoid dampening)
adj  = min(adj, 0.12)                               (hard cap)
p_true = p_market ± adj
EV_net = |p_true − p_market| − estimated_slippage
```

Position sizing uses a conservative Kelly variant:
```
size = min(MAX_BET, K × EV_net × confidence × bankroll)   K=0.25
```

The Allocator further scales size by drawdown:
```
dd_scale = max(0, 1 − drawdown × 2)       (linear reduction, zero at 50%)
final = clamp(size × multiplier × dd_scale, $1.00, MAX_BET)
```

### Three-Tier Classification

| Tier | Method | Latency | Description |
|------|--------|---------|-------------|
| 1 | Watchlist | <1ms | 65 high-signal phrases with direction/confidence. Longest-match wins. Requires credible source (≥0.65). |
| 2 | LightGBM | <1ms | 40 features (text, NER proxies, source credibility, market context, temporal, novelty). Multiclass: NEUTRAL/NO/YES. |
| 3 | 3-pass LLM | ~300ms | 3 concurrent Groq calls (llama-3.3-70b, temp=0.15). Majority direction. Agreeing passes averaged. Token-bucket: 25 RPM. |

Cold path: borderline + loss trades are re-classified by tier 3. Labels written to `models/labels.jsonl`. LightGBM retrained every 50 new labels.

### NLP Impact Score

```
impact = 0.20·source_reliability
       + 0.20·|sentiment|·sentiment_confidence
       + 0.20·entity_importance
       + 0.25·novelty_score
       + 0.15·velocity_score

relevance(t) = impact × exp(−0.05 × age_minutes)   (half-life ≈ 14 min)
```

Source reliability: GNews 0.88, GDELT 0.85, NewsAPI 0.85, RSS 0.80, Twitter 0.65, Telegram 0.60, Reddit 0.50.

### Ensemble

```
news_weight = 0.6, momentum_weight = 0.4

yes_score = Σ(w × confidence) for YES signals
no_score  = Σ(w × confidence) for NO signals

size_multiplier:
  1.0 = strategies agree on direction
  0.6 = single strategy only
  0.4 = strategies conflict
```

### Smart Router

| Spread | Action |
|--------|--------|
| < 2% | Aggressive (place at mid) |
| 2–8% | Passive (place inside spread) |
| > 8% | Reject (no trade) |

High momentum (>3% move) also triggers aggressive routing.

---

## Risk Management

Six independent risk gates operate on every trade:

1. **Daily loss cap** — hard stop at `DAILY_LOSS_LIMIT_USD`. Cached for 30s, re-queried from SQLite.
2. **Concurrent positions** — max `MAX_CONCURRENT_POSITIONS` open. Enforced atomically via `try_open_position()`.
3. **Category exposure** — max `MAX_EXPOSURE_PER_CATEGORY_USD` per category. Enforced atomically.
4. **Consecutive loss cooldown** — after `CONSECUTIVE_LOSS_COOLDOWN` losses, pause for `COOLDOWN_MINUTES`.
5. **Market signal cooldown** — 10 minutes between signals on the same market.
6. **Drawdown scaling** — Allocator linearly reduces position size as drawdown increases, halting completely at 50%.

SafetyGuard also blocks live trading if drawdown exceeds 20% or RiskManager is in cooldown.

---

## Multi-Platform Support

The system supports two prediction market platforms:

| Platform | Market Data | Order Entry | Auth |
|----------|-------------|-------------|------|
| Polymarket | Gamma API + CLOB REST + WebSocket | `py_clob_client` GTC limit orders | API key + secret + passphrase + private key |
| Kalshi | REST API (paginated) | REST API with cent pricing | JWT (email+password) or RSA (API key + private key) |

Markets from both platforms are merged into a single tracked market list. The `source` field (`"polymarket"` / `"kalshi"`) on each `Market` drives execution routing. Kalshi yes/no prices are converted from cents (1-99) to [0,1] probability. Volume is estimated from contracts × average price.

---

## Observability

### SQLite Schema (trades.db, WAL mode)

| Table | Purpose |
|-------|---------|
| `trades` | Every signal with classification, edge, latency, status, category, platform |
| `outcomes` | Resolved trade PnL (linked to trades) |
| `positions` | Open/closed position lifecycle with entry/exit prices and realized PnL |
| `calibration` | Predicted vs actual direction with Brier contribution |
| `pipeline_runs` | Pipeline session metadata |
| `news_events` | Raw news ingestion log |

### Metrics (in-memory, rolling windows)

- Win rate, total PnL, average EV
- Rolling Sharpe ratio (100-trade window, per-trade)
- Current/max drawdown
- Latency p50/p95/p99 (500-point window)
- Trades per hour

### Calibration

`python cli.py calibrate` checks Gamma API for resolved markets, updates the calibration table, and computes:
- **Overall accuracy** — correct direction predictions / total
- **Brier score** — mean squared error of probabilistic predictions
- **ECE (Expected Calibration Error)** — weighted average of |accuracy − confidence| per confidence bucket (0.5–0.6, 0.6–0.7, ..., 0.9–1.0)
- **Per-source accuracy** — accuracy broken down by news source
- **Per-category accuracy** — accuracy broken down by market category

---

## Self-Improving Classifier

The system includes a closed-loop labeling flywheel:

1. Hot path (fast classifier) processes every signal with low latency
2. Pipeline submits every hot-path trade to the cold path worker
3. Cold path runs the full 3-pass LLM classifier to get ground-truth labels
4. Labels are written to `models/labels.jsonl` (JSONL format)
5. Every 50 new labels, LightGBM is retrained in a background thread
6. The new model replaces the old one in-place at `models/fast_classifier.lgbm`

This means classification accuracy improves as the system runs, without manual labeling.

---

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

87 tests covering:

| Suite | What it tests |
|-------|--------------|
| `test_alpha_signal.py` | AlphaSignal/AggregatedSignal validation, direction/confidence/horizon constraints |
| `test_allocator.py` | Kelly sizing with drawdown scaling, max bet cap, conflict reduction, exact arithmetic |
| `test_categories.py` | Category keyword matching, feed/query/subreddit union |
| `test_ensemble.py` | Strategy agreement/conflict, weighted confidence/edge, deduplication, tie-breaking |
| `test_fast_classifier.py` | is_trained(), watchlist short-circuit, build_classification time_sensitivity |
| `test_kalshi_executor.py` | YES/NO order computation, yes_price complement, bounds checking |
| `test_news_alpha.py` | Signal conversion, horizon mapping, error handling |
| `test_portfolio.py` | Balance tracking, mark-to-market, close position PnL, Sharpe computation |
| `test_trading_mode.py` | LIVE/DRY_RUN toggle, confirm gate, SafetyGuard pass/fail |
| `test_watchlist.py` | Longest-match semantics, case insensitivity, overlapping phrase resolution |

---

## Deployment Considerations

- **Single process per account** — the pipeline, API server, and dashboard share RiskManager/Portfolio state in-process. Running multiple processes against one Polymarket account will bypass position limits and risk gates. Use `API_WORKERS=1`.
- **Groq rate limits** — the free tier allows 30 RPM. The classifier's token bucket (25 RPM) leaves 5 RPM headroom for retries. The cold path shares the same rate limit.
- **Co-location** — Polymarket CLOB is in US-East. Running the pipeline on a VPS in the same region minimizes network latency.
- **SQLite** — WAL mode allows concurrent reads during writes. The database file should be backed up regularly. For multi-process access, consider migrating to PostgreSQL.
- **Model files** — `models/fast_classifier.lgbm` and `models/labels.jsonl` persist classifier state. The sentence-transformers model (`all-MiniLM-L6-v2`, ~90MB) is downloaded on first use and cached.
- **NLP optional** — spaCy and VADER are optional dependencies. The pipeline degrades gracefully: if they're not installed, NLP enrichment is skipped (all events pass the NLP gate). Install with `pip install spacy && python -m spacy download en_core_web_sm` and `pip install vaderSentiment`.
