# Multi-Market Category-Aware Trading Platform — Design Spec
**Date:** 2026-04-12  
**Status:** Approved for implementation

---

## 1. Goal

Transform the existing single-market event pipeline into a multi-market, category-aware trading platform that:

- Supports Polymarket and Kalshi behind a unified provider abstraction
- Filters markets and news by user-selected categories at startup
- Replaces dry-run logging with a full paper trading engine ($1M virtual balance)
- Tracks portfolio state, P&L, Sharpe, and drawdown per category
- Exposes new API endpoints for portfolio and category management

---

## 2. Constraints

- Do not modify or replace existing execution/routing logic in `executor.py` or `kalshi_executor.py`
- Do not break any currently working pipeline path
- Paper trading replaces `_dry_run_execution`; live trading path unchanged
- No runtime category switching — restart required for category changes
- Keep `positions` and `trades` as separate SQLite tables

---

## 3. New Files

### `providers/__init__.py`
Exports `PolymarketProvider`, `KalshiProvider`, and `get_providers(categories)`.

### `providers/base.py`
Abstract base class (Protocol) for all market providers:

```python
class MarketProvider(ABC):
    name: str  # "polymarket" | "kalshi"

    def fetch_markets(self, limit: int = 200) -> list[Market]: ...
    def get_price(self, market_id: str) -> float | None: ...
    def simulate_trade(self, signal: Signal) -> ExecutionResult: ...
    def execute_trade(self, signal: Signal) -> ExecutionResult: ...
```

`get_price` looks up live price from `MarketWatcher` snapshots (no extra API call). Providers obtain the watcher via `from market_watcher import MarketWatcher; w = MarketWatcher()` — `MarketWatcher.__init__` returns the existing singleton if already running, so no second watcher is created.  
`simulate_trade` delegates to `portfolio.simulate_trade(signal)`.  
`execute_trade` delegates to the existing routing in `executor.execute_trade(signal)`.

### `providers/polymarket.py`
Thin wrapper around `markets.fetch_active_markets` and the Polymarket execution path:

```python
class PolymarketProvider(MarketProvider):
    name = "polymarket"

    def fetch_markets(self, limit=200) -> list[Market]:
        return fetch_active_markets(limit=limit)

    def get_price(self, market_id: str) -> float | None:
        # reads from MarketWatcher.snapshots[market_id].yes_price
        ...

    def simulate_trade(self, signal: Signal) -> ExecutionResult:
        from portfolio import get_portfolio
        return get_portfolio().simulate_trade(signal)

    def execute_trade(self, signal: Signal) -> ExecutionResult:
        from executor import execute_trade
        return execute_trade(signal)
```

### `providers/kalshi.py`
Thin wrapper around `kalshi_markets.fetch_kalshi_markets` and Kalshi execution path. Same interface as above, `name = "kalshi"`.

### `categories.py`
Central registry for all category-aware configuration. This module has no side effects on import.

**Category registry:**
```python
CATEGORIES = {
    "crypto":     { keywords, rss_feeds, reddit_subs, newsapi_queries, twitter_keywords },
    "politics":   { ... },
    "economics":  { ... },
    "weather":    { ... },
    "sports":     { ... },
    "science":    { ... },
    "ai":         { ... },
    "technology": { ... },
}
```

**Category → keyword maps (examples):**

| Category   | Keywords (subset)                                          |
|------------|------------------------------------------------------------|
| crypto     | Bitcoin, Ethereum, Solana, crypto, DeFi, SEC crypto        |
| politics   | election, Trump, Congress, Senate, tariff, White House     |
| economics  | inflation, Fed, interest rate, CPI, FOMC, GDP              |
| weather    | temperature, storm, hurricane, NOAA, tornado, flood        |
| sports     | match, league, score, championship, NBA, NFL, MLB          |
| science    | NASA, SpaceX, research, discovery, climate                 |
| ai         | OpenAI, GPT, Anthropic, Claude, Gemini, LLM                |
| technology | Apple, Microsoft, NVIDIA, Google, startup, software        |

**Functions:**
```python
def is_relevant_event(event: NewsEvent, selected: list[str]) -> bool:
    """True if headline contains any keyword from any selected category."""

def get_twitter_keywords(categories: list[str]) -> list[str]:
    """Union of twitter_keywords across selected categories."""

def get_rss_feeds(categories: list[str]) -> list[str]:
    """Union of rss_feeds across selected categories."""

def get_newsapi_queries(categories: list[str]) -> list[str]:
    """Union of newsapi_queries across selected categories."""

def get_reddit_subreddits(categories: list[str]) -> list[str]:
    """Union of reddit_subs across selected categories."""

def get_category(event_or_market) -> str:
    """Infer category from text — delegates to markets._infer_category."""
```

`is_relevant_event` checks the headline (lowercased) for any keyword from any selected category's keyword list. Returns `True` on first match. Returns `True` for all events if `selected == ["all"]`.

### `portfolio.py`
Paper trading engine. Module-level singleton via `get_portfolio()`.

`get_portfolio()` is lazily initialized on first call using `config.PAPER_BALANCE`. If a `positions` table with `status='open'` entries exists in SQLite at startup, those positions are loaded into the in-memory `Portfolio.positions` dict to survive restarts. The singleton is module-level (`_portfolio: Portfolio | None = None`).

**State (in-memory + persisted to SQLite `positions` table):**
```python
@dataclass
class Portfolio:
    balance: float              # current virtual cash
    initial_balance: float      # $1,000,000
    positions: dict[str, Position]  # market_id → Position
    daily_returns: list[float]  # for Sharpe computation
```

**Position dataclass:**
```python
@dataclass
class Position:
    position_id: int
    market_id: str
    market_question: str
    platform: str           # "polymarket" | "kalshi"
    category: str
    side: str               # "YES" | "NO"
    entry_price: float
    size_usd: float
    contracts: float
    opened_at: datetime
    closed_at: datetime | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None
    status: str = "open"    # "open" | "closed" | "expired"
```

**Methods:**
```python
def simulate_trade(signal: Signal) -> ExecutionResult:
    """
    Open or add to a position. Deducts from balance.
    Calls logger.log_position() and logger.log_trade() (with status="paper").
    Returns ExecutionResult with status="paper".
    """

def mark_to_market(market_id: str, current_price: float) -> float:
    """Return unrealized P&L for an open position at current_price."""

def close_position(market_id: str, exit_price: float) -> float:
    """
    Close an open position. Returns realized P&L.
    Updates balance. Calls logger.update_position_closed().
    """

def get_unrealized_pnl() -> float:
    """Sum mark_to_market across all open positions using watcher snapshots."""

def get_portfolio_state() -> dict:
    """
    Returns full snapshot for /portfolio endpoint:
    { balance, initial_balance, total_value, unrealized_pnl, realized_pnl,
      open_positions, closed_positions, win_rate, sharpe_ratio, max_drawdown,
      total_return_pct, by_category: {cat: {pnl, trades, win_rate}} }
    """

def get_sharpe_ratio() -> float | None:
    """
    Annualized Sharpe from daily returns on closed positions.
    Returns None if fewer than 2 days of data.
    Formula: (mean_daily_return / std_daily_return) * sqrt(252)
    """

def get_max_drawdown() -> float:
    """Peak-to-trough as fraction of peak portfolio value. Range [0, 1]."""
```

**P&L accounting:**
- Opening a position: `balance -= size_usd`
- Closing YES position at exit: `realized_pnl = size_usd * (exit_price - entry_price) / entry_price`
- Closing NO position at exit: `realized_pnl = size_usd * (entry_price - exit_price) / entry_price`
- Balance on close: `balance += size_usd + realized_pnl`
- Unrealized: same formula using current market price
- Portfolio total value: `balance + sum(unrealized for all open positions)`

---

## 4. Modified Files

### `config.py`
Add:
```python
SELECTED_CATEGORIES = [
    c.strip()
    for c in os.getenv("SELECTED_CATEGORIES", "all").split(",")
    if c.strip()
]
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE", "1000000"))
```

`SELECTED_CATEGORIES = ["all"]` means "no category filter" — preserves current behavior as default.

### `logger.py`

**New `positions` table:**
```sql
CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id       TEXT    NOT NULL,
    market_question TEXT    NOT NULL,
    platform        TEXT    NOT NULL,   -- "polymarket" | "kalshi"
    category        TEXT    NOT NULL,
    side            TEXT    NOT NULL,   -- "YES" | "NO"
    entry_price     REAL    NOT NULL,
    size_usd        REAL    NOT NULL,
    contracts       REAL,
    opened_at       TEXT    NOT NULL,
    closed_at       TEXT,
    exit_price      REAL,
    realized_pnl    REAL,
    status          TEXT    NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS idx_positions_market_id ON positions(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status    ON positions(status);
```

**Migration: add `category` and `platform` to `trades`:**
```sql
ALTER TABLE trades ADD COLUMN category TEXT;
ALTER TABLE trades ADD COLUMN platform TEXT;
```
Added to the existing `_migrate_v2_columns` pattern.

**New logger functions:**
```python
def log_position(position: Position) -> int: ...
def update_position_closed(position_id, exit_price, realized_pnl, closed_at): ...
def get_open_positions() -> list[dict]: ...
def get_closed_positions(limit=100) -> list[dict]: ...
def get_category_stats() -> dict: ...  # win_rate, total_pnl, trade_count per category
```

### `executor.py`
In `execute_trade()`, replace the `DRY_RUN` branch:

```python
# Before:
if config.DRY_RUN:
    return _dry_run_execution(signal, exec_start)

# After:
if config.DRY_RUN:
    from portfolio import get_portfolio
    return get_portfolio().simulate_trade(signal)
```

`_dry_run_execution` is kept as an internal fallback (used if portfolio fails to initialize).

### `pipeline.py`
After receiving a `NewsEvent` from the queue, before the matcher:

```python
from categories import is_relevant_event
import config

if not is_relevant_event(event, config.SELECTED_CATEGORIES):
    continue  # drop — not in selected categories
```

No other changes to the pipeline flow.

### `news_stream.py`
In `NewsAggregator.__init__`, accept an optional `categories: list[str]` parameter. When provided and not `["all"]`, substitute category-aware sources:

```python
from categories import get_twitter_keywords, get_rss_feeds, get_newsapi_queries, get_reddit_subreddits

class NewsAggregator:
    def __init__(self, queue, categories=None):
        cats = categories or config.SELECTED_CATEGORIES
        if cats != ["all"]:
            self.twitter_keywords = get_twitter_keywords(cats)
            self.rss_feeds = get_rss_feeds(cats)
            self.newsapi_queries = get_newsapi_queries(cats)
            self.reddit_subs = get_reddit_subreddits(cats)
        else:
            # existing config defaults
            self.twitter_keywords = config.TWITTER_KEYWORDS
            self.rss_feeds = config.RSS_FEEDS
            ...
```

All downstream source classes (`TwitterStream`, `RSSPoller`, etc.) read from `self.*` rather than directly from `config.*`.

### `api.py`
Four new endpoints:

```
GET /portfolio
    Returns: get_portfolio().get_portfolio_state()
    Fields: balance, total_value, unrealized_pnl, realized_pnl,
            open_positions (list), win_rate, sharpe_ratio, max_drawdown,
            total_return_pct, by_category

GET /categories
    Returns: { available: [...all category names...],
               selected: config.SELECTED_CATEGORIES,
               counts: { cat: market_count } }

GET /markets?category=<cat>&source=<platform>
    Existing endpoint, extended with optional query params.
    Filters watcher.tracked_markets by category and/or source.

GET /stats?category=<cat>
    Existing endpoint, extended. When category given, filters
    logger.get_category_stats() for that category.
```

Log format update in all trade log calls:
```
[TRADE][{category}][{platform}] {side} ${amount:.2f} '{question[:40]}' ev={ev:.3f}
```

### `cli.py`
Add `--categories` to the `watch` subcommand:

```python
p_watch.add_argument(
    "--categories",
    type=str,
    default=None,
    help="Comma-separated categories: crypto,politics,economics (default: all)"
)
```

In `cmd_watch`:
```python
if args.categories:
    config.SELECTED_CATEGORIES = [c.strip() for c in args.categories.split(",")]
```

---

## 5. Data Flow (Updated)

```
NewsEvent (from NewsAggregator — category-configured at startup)
  ↓
categories.is_relevant_event()     [NEW GATE — drops irrelevant events]
  ↓
NLP enrichment (existing)
  ↓
matcher.match_news_to_markets()    [filtered markets already match categories]
  ↓
classifier.classify_async()
  ↓
edge_model.compute_edge()
  ↓
microstructure gate (existing)
  ↓
risk gates (existing)
  ↓
portfolio.simulate_trade()         [NEW — replaces _dry_run_execution]
  or executor.execute_live()       [unchanged live path]
  ↓
logger.log_trade() + log_position()
  ↓
broadcaster.publish()
```

---

## 6. What Is NOT Changing

- `markets.py` — no changes
- `kalshi_markets.py` — no changes
- `kalshi_executor.py` — no changes
- `executor.py` routing logic — only the `DRY_RUN` branch changes
- `matcher.py`, `classifier.py`, `edge_model.py` — no changes
- `risk.py`, `metrics.py`, `market_watcher.py` — no changes
- `MarketWatcher` is not replaced by providers; providers call into it for `get_price`

---

## 7. File Change Summary

| File | Change type | Description |
|------|-------------|-------------|
| `providers/__init__.py` | NEW | Package init, exports |
| `providers/base.py` | NEW | `MarketProvider` abstract base |
| `providers/polymarket.py` | NEW | Polymarket thin adapter |
| `providers/kalshi.py` | NEW | Kalshi thin adapter |
| `categories.py` | NEW | Category registry + `is_relevant_event` |
| `portfolio.py` | NEW | Paper trading engine |
| `config.py` | MODIFY | Add `SELECTED_CATEGORIES`, `PAPER_BALANCE` |
| `logger.py` | MODIFY | Add `positions` table + migration + new functions |
| `executor.py` | MODIFY | DRY_RUN branch → `portfolio.simulate_trade` |
| `pipeline.py` | MODIFY | Inject `is_relevant_event` gate |
| `news_stream.py` | MODIFY | Accept `categories` param, use category sources |
| `api.py` | MODIFY | Add `/portfolio`, `/categories`, extend existing |
| `cli.py` | MODIFY | Add `--categories` flag to `watch` |

---

## 8. Example Usage

```bash
# Paper trade on crypto + politics only
python cli.py watch --categories crypto,politics

# Paper trade on all categories (default)
python cli.py watch

# Check portfolio state
curl http://localhost:8000/portfolio

# Browse markets filtered by category
curl "http://localhost:8000/markets?category=crypto"

# Category performance stats
curl "http://localhost:8000/stats?category=politics"

# List available categories
curl http://localhost:8000/categories
```

---

## 9. Future Extensions (Not in scope)

- Runtime category switching via API (requires `NewsAggregator` hot-reload)
- Full provider consolidation (move execution logic into providers)
- Parallel live + paper trading (dual-mode)
- Reinforcement learning on position sizing
- Cross-market arbitrage detection
