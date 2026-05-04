from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "trades.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            market_question TEXT NOT NULL,
            claude_score REAL NOT NULL,
            market_price REAL NOT NULL,
            edge REAL NOT NULL,
            side TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            order_id TEXT,
            status TEXT NOT NULL DEFAULT 'dry_run',
            reasoning TEXT,
            headlines TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            -- V2 columns
            news_source TEXT,
            classification TEXT,
            materiality REAL,
            news_latency_ms INTEGER,
            classification_latency_ms INTEGER,
            total_latency_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL REFERENCES trades(id),
            resolved_at TEXT,
            result TEXT,
            pnl REAL,
            UNIQUE(trade_id)
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            markets_scanned INTEGER DEFAULT 0,
            signals_found INTEGER DEFAULT 0,
            trades_placed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS news_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headline TEXT NOT NULL,
            source TEXT NOT NULL,
            received_at TEXT NOT NULL,
            latency_ms INTEGER,
            matched_markets INTEGER DEFAULT 0,
            triggered_trades INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER REFERENCES trades(id),
            classification TEXT,
            materiality REAL,
            entry_price REAL,
            exit_price REAL,
            actual_direction TEXT,
            correct INTEGER,
            resolved_at TEXT,
            UNIQUE(trade_id)
        );

        CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at);
        CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades(market_id);
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        CREATE INDEX IF NOT EXISTS idx_calibration_correct ON calibration(correct);

        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id       TEXT    NOT NULL,
            market_question TEXT    NOT NULL,
            platform        TEXT    NOT NULL,
            category        TEXT    NOT NULL,
            side            TEXT    NOT NULL,
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
    """)
    _migrate_v2_columns(conn)
    conn.close()


def _migrate_v2_columns(conn):
    """Add V2 columns to trades table if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cursor.fetchall()}
    new_cols = [
        ("news_source", "TEXT"),
        ("classification", "TEXT"),
        ("materiality", "REAL"),
        ("news_latency_ms", "INTEGER"),
        ("classification_latency_ms", "INTEGER"),
        ("total_latency_ms", "INTEGER"),
        ("category", "TEXT"),
        ("platform", "TEXT"),
        ("mode", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in columns:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
    conn.commit()


def log_trade(
    market_id: str,
    market_question: str,
    claude_score: float,
    market_price: float,
    edge: float,
    side: str,
    amount_usd: float,
    order_id: str | None = None,
    status: str = "dry_run",
    reasoning: str = "",
    headlines: str = "",
    news_source: str | None = None,
    classification: str | None = None,
    materiality: float | None = None,
    news_latency_ms: int | None = None,
    classification_latency_ms: int | None = None,
    total_latency_ms: int | None = None,
    category: str | None = None,
    platform: str | None = None,
    mode: str | None = None,
) -> int:
    import config as _cfg
    if mode is None:
        mode = "paper" if _cfg.DRY_RUN else "live"
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO trades
           (market_id, market_question, claude_score, market_price, edge,
            side, amount_usd, order_id, status, reasoning, headlines,
            news_source, classification, materiality,
            news_latency_ms, classification_latency_ms, total_latency_ms,
            category, platform, mode)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (market_id, market_question, claude_score, market_price, edge,
         side, amount_usd, order_id, status, reasoning, headlines,
         news_source, classification, materiality,
         news_latency_ms, classification_latency_ms, total_latency_ms,
         category, platform, mode),
    )
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def log_news_event(
    headline: str,
    source: str,
    received_at: str,
    latency_ms: int = 0,
    matched_markets: int = 0,
    triggered_trades: int = 0,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO news_events
           (headline, source, received_at, latency_ms, matched_markets, triggered_trades)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (headline, source, received_at, latency_ms, matched_markets, triggered_trades),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    return event_id


def log_calibration(
    trade_id: int,
    classification: str,
    materiality: float,
    entry_price: float,
    exit_price: float | None = None,
    actual_direction: str | None = None,
    correct: bool | None = None,
    resolved_at: str | None = None,
):
    conn = _conn()
    conn.execute(
        """INSERT OR REPLACE INTO calibration
           (trade_id, classification, materiality, entry_price, exit_price,
            actual_direction, correct, resolved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, classification, materiality, entry_price, exit_price,
         actual_direction, 1 if correct else (0 if correct is not None else None),
         resolved_at),
    )
    conn.commit()
    conn.close()


def log_run_start() -> int:
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO pipeline_runs (started_at) VALUES (?)", (now,)
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def log_run_end(run_id: int, markets_scanned: int, signals_found: int, trades_placed: int, status: str = "completed"):
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE pipeline_runs
           SET finished_at=?, markets_scanned=?, signals_found=?, trades_placed=?, status=?
           WHERE id=?""",
        (now, markets_scanned, signals_found, trades_placed, status, run_id),
    )
    conn.commit()
    conn.close()


def get_daily_pnl(mode: str | None = None) -> float:
    """
    Returns net P&L for today.
    Uses outcomes table when available; falls back to -amount_usd (capital at risk)
    for trades without resolved outcomes.
    Pass mode='paper' or mode='live' to restrict to a single mode.
    """
    conn = _conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if mode:
        row = conn.execute(
            """SELECT
                   COALESCE(SUM(o.pnl), 0) as resolved_pnl,
                   COALESCE(SUM(CASE WHEN o.pnl IS NULL AND t.status IN ('executed','dry_run')
                                     THEN -t.amount_usd ELSE 0 END), 0) as open_exposure
               FROM trades t
               LEFT JOIN outcomes o ON o.trade_id = t.id
               WHERE t.created_at LIKE ? AND (t.mode = ? OR t.mode IS NULL)""",
            (f"{today}%", mode),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT
                   COALESCE(SUM(o.pnl), 0) as resolved_pnl,
                   COALESCE(SUM(CASE WHEN o.pnl IS NULL AND t.status IN ('executed','dry_run')
                                     THEN -t.amount_usd ELSE 0 END), 0) as open_exposure
               FROM trades t
               LEFT JOIN outcomes o ON o.trade_id = t.id
               WHERE t.created_at LIKE ?""",
            (f"{today}%",),
        ).fetchone()
    conn.close()
    return (row["resolved_pnl"] or 0.0) + (row["open_exposure"] or 0.0)


def get_recent_trades(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_calibrated_trades(limit: int = 500) -> list[dict]:
    """Return trades that have calibration records with resolved outcomes."""
    conn = _conn()
    rows = conn.execute(
        """SELECT t.*, c.correct, c.exit_price, c.actual_direction
           FROM trades t
           JOIN calibration c ON c.trade_id = t.id
           WHERE c.correct IS NOT NULL
           ORDER BY t.created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_news_events(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM news_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_stats() -> dict:
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) as c FROM trades").fetchone()["c"]
    by_status = conn.execute(
        "SELECT status, COUNT(*) as c FROM trades GROUP BY status"
    ).fetchall()
    conn.close()
    return {
        "total_trades": total,
        "by_status": {r["status"]: r["c"] for r in by_status},
    }


def get_calibration_stats() -> dict:
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) as c FROM calibration WHERE correct IS NOT NULL").fetchone()["c"]
    if total == 0:
        conn.close()
        return {"total": 0, "accuracy": 0.0, "by_source": {}, "by_classification": {}}

    correct = conn.execute("SELECT COUNT(*) as c FROM calibration WHERE correct = 1").fetchone()["c"]

    by_source = {}
    rows = conn.execute("""
        SELECT t.news_source as source, COUNT(*) as total,
               SUM(CASE WHEN c.correct = 1 THEN 1 ELSE 0 END) as wins
        FROM calibration c JOIN trades t ON c.trade_id = t.id
        WHERE c.correct IS NOT NULL AND t.news_source IS NOT NULL
        GROUP BY t.news_source
    """).fetchall()
    for r in rows:
        by_source[r["source"]] = round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0

    by_cls = {}
    rows = conn.execute("""
        SELECT classification, COUNT(*) as total,
               SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as wins
        FROM calibration WHERE correct IS NOT NULL
        GROUP BY classification
    """).fetchall()
    for r in rows:
        by_cls[r["classification"]] = round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0

    conn.close()
    return {
        "total": total,
        "accuracy": round(correct / total * 100, 1),
        "by_source": by_source,
        "by_classification": by_cls,
    }


def get_latency_stats() -> dict:
    conn = _conn()
    row = conn.execute("""
        SELECT
            AVG(total_latency_ms) as avg_total,
            MIN(total_latency_ms) as min_total,
            MAX(total_latency_ms) as max_total,
            AVG(news_latency_ms) as avg_news,
            AVG(classification_latency_ms) as avg_class,
            COUNT(*) as count
        FROM trades
        WHERE total_latency_ms IS NOT NULL
    """).fetchone()
    conn.close()
    if not row or row["count"] == 0:
        return {"avg_total_ms": 0, "min_total_ms": 0, "max_total_ms": 0,
                "avg_news_ms": 0, "avg_class_ms": 0, "count": 0}
    return {
        "avg_total_ms": round(row["avg_total"] or 0),
        "min_total_ms": round(row["min_total"] or 0),
        "max_total_ms": round(row["max_total"] or 0),
        "avg_news_ms": round(row["avg_news"] or 0),
        "avg_class_ms": round(row["avg_class"] or 0),
        "count": row["count"],
    }


def log_position(
    market_id: str,
    market_question: str,
    platform: str,
    category: str,
    side: str,
    entry_price: float,
    size_usd: float,
    contracts: float,
    opened_at: str,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO positions
           (market_id, market_question, platform, category, side,
            entry_price, size_usd, contracts, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (market_id, market_question, platform, category, side,
         entry_price, size_usd, contracts, opened_at),
    )
    position_id = cur.lastrowid
    conn.commit()
    conn.close()
    return position_id


def update_position_closed(
    position_id: int,
    exit_price: float,
    realized_pnl: float,
    closed_at: str,
):
    conn = _conn()
    cur = conn.execute(
        """UPDATE positions
           SET exit_price=?, realized_pnl=?, closed_at=?, status='closed'
           WHERE id=?""",
        (exit_price, realized_pnl, closed_at, position_id),
    )
    if cur.rowcount == 0:
        conn.close()
        raise ValueError(f"update_position_closed: no position found with id={position_id}")
    conn.commit()
    conn.close()


def get_open_positions() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status='open' ORDER BY opened_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_closed_positions(limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status='closed' ORDER BY closed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_category_stats() -> dict:
    """Returns win_rate, total_pnl, trade_count per category from closed positions."""
    conn = _conn()
    rows = conn.execute(
        """SELECT category,
                  COUNT(*) as trade_count,
                  SUM(realized_pnl) as total_pnl,
                  SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins
           FROM positions
           WHERE status='closed'
           GROUP BY category"""
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        count = r["trade_count"]
        wins = r["wins"] or 0
        result[r["category"]] = {
            "trade_count": count,
            "total_pnl": round(r["total_pnl"] or 0.0, 2),
            "win_rate": round(wins / count, 3) if count > 0 else 0.0,
        }
    return result


init_db()
