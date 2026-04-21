"""
Adaptive Reddit source — alpha-weighted subreddit sampling with SQLite-backed performance tracking.

Key design:
- Base weights encode prior belief about each subreddit's signal quality.
- After each cycle, weights are updated: new_weight = base * (1 + alpha_score)
  where alpha_score = profitable_trades / max(1, trades_triggered).
- is_high_signal() filters posts by title patterns before they enter the pipeline.
- AdaptiveSubredditSelector picks the next subreddit via weighted random choice.
"""
from __future__ import annotations

import random
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# Base weights — prior belief about signal quality per subreddit
BASE_WEIGHTS: dict[str, float] = {
    "CryptoCurrency": 0.25,
    "Bitcoin":        0.20,
    "ethereum":       0.15,
    "worldnews":      0.15,
    "politics":       0.10,
    "stocks":         0.10,
    "economy":        0.05,
}

# Phrases that strongly indicate a high-signal post
_HIGH_SIGNAL_PHRASES = {
    "announced", "announces", "approved", "approves",
    "banned", "bans", "launched", "launches", "launch",
    "hack", "hacked", "hacking", "breached", "breach",
    "regulation", "regulated", "legislation", "bill passed",
    "SEC", "Fed", "Federal Reserve", "rate hike", "rate cut",
    "crash", "surges", "plunges", "spikes", "collapses",
    "ETF", "IPO", "bankruptcy", "acquisition", "merger",
    "indicted", "arrested", "charged", "sanctions",
}

# Phrases that indicate low-signal discussion posts to skip
_LOW_SIGNAL_PHRASES = {
    "what do you think", "opinion", "discussion",
    "should i", "should I", "thoughts", "thoughts?",
    "advice", "help me", "am i", "am I",
    "anyone else", "unpopular opinion", "hot take",
    "eli5", "explain", "question",
}

DB_PATH = Path(__file__).parent / "trades.db"

# Module-level persistent connection — avoids re-opening on every record call.
# WAL mode is set once at startup; the connection is reused for the process lifetime.
_db: sqlite3.Connection = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.execute("PRAGMA journal_mode=WAL")


def _ensure_table():
    _db.execute("""
        CREATE TABLE IF NOT EXISTS subreddit_stats (
            subreddit TEXT PRIMARY KEY,
            base_weight REAL NOT NULL DEFAULT 0.10,
            posts_seen INTEGER NOT NULL DEFAULT 0,
            trades_triggered INTEGER NOT NULL DEFAULT 0,
            profitable_trades INTEGER NOT NULL DEFAULT 0,
            alpha_score REAL NOT NULL DEFAULT 0.0,
            current_weight REAL NOT NULL DEFAULT 0.10,
            last_updated TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Seed rows for all known subreddits
    for sub, w in BASE_WEIGHTS.items():
        _db.execute(
            """INSERT OR IGNORE INTO subreddit_stats (subreddit, base_weight, current_weight)
               VALUES (?, ?, ?)""",
            (sub, w, w),
        )
    _db.commit()


_ensure_table()


def is_high_signal(title: str) -> bool:
    """
    Return True if the post title looks like actionable breaking news.
    Rejects discussion/opinion posts; passes event-driven headlines.
    """
    lower = title.lower()

    # Reject explicit low-signal patterns
    for phrase in _LOW_SIGNAL_PHRASES:
        if phrase in lower:
            return False

    # Accept if any high-signal phrase is present
    for phrase in _HIGH_SIGNAL_PHRASES:
        if phrase.lower() in lower:
            return True

    # Heuristic: short declarative titles (no question mark, no "I/we") tend to be news
    if "?" not in title and len(title.split()) >= 5:
        first_word = title.split()[0].lower()
        if first_word not in {"i", "we", "my", "our", "how", "why", "what", "when", "where", "who"}:
            return True

    return False


class AdaptiveSubredditSelector:
    """
    Picks the next subreddit to poll using weighted random sampling.
    Weights are loaded from SQLite on construction and refreshed after each update.
    """

    def __init__(self):
        self._weights: dict[str, float] = {}
        self._refresh_weights()

    def _refresh_weights(self):
        rows = _db.execute(
            "SELECT subreddit, current_weight FROM subreddit_stats"
        ).fetchall()
        if rows:
            self._weights = {r["subreddit"]: max(r["current_weight"], 0.001) for r in rows}
        else:
            self._weights = dict(BASE_WEIGHTS)

    def get_next(self) -> str:
        subs = list(self._weights.keys())
        weights = [self._weights[s] for s in subs]
        return random.choices(subs, weights=weights, k=1)[0]

    def record_post_seen(self, subreddit: str):
        _db.execute(
            """UPDATE subreddit_stats
               SET posts_seen = posts_seen + 1,
                   last_updated = datetime('now')
               WHERE subreddit = ?""",
            (subreddit,),
        )
        _db.commit()

    def record_trade_triggered(self, subreddit: str):
        _db.execute(
            """UPDATE subreddit_stats
               SET trades_triggered = trades_triggered + 1,
                   last_updated = datetime('now')
               WHERE subreddit = ?""",
            (subreddit,),
        )
        _db.commit()

    def record_profitable_trade(self, subreddit: str):
        _db.execute(
            """UPDATE subreddit_stats
               SET profitable_trades = profitable_trades + 1,
                   last_updated = datetime('now')
               WHERE subreddit = ?""",
            (subreddit,),
        )
        _db.commit()
        self._update_weights()

    def _update_weights(self):
        """Recompute alpha scores and current weights, then normalize."""
        rows = _db.execute(
            "SELECT subreddit, base_weight, trades_triggered, profitable_trades FROM subreddit_stats"
        ).fetchall()

        updates = []
        for r in rows:
            alpha = r["profitable_trades"] / max(1, r["trades_triggered"])
            new_w = r["base_weight"] * (1.0 + alpha)
            updates.append((alpha, new_w, r["subreddit"]))

        # Normalize so weights sum to 1
        total = sum(u[1] for u in updates) or 1.0
        normalized = [(a, w / total, sub) for a, w, sub in updates]

        for alpha, weight, sub in normalized:
            _db.execute(
                """UPDATE subreddit_stats
                   SET alpha_score = ?, current_weight = ?, last_updated = datetime('now')
                   WHERE subreddit = ?""",
                (alpha, weight, sub),
            )

        _db.commit()
        self._refresh_weights()
        log.debug("[reddit] Weights updated: %s", {s: round(w, 3) for s, w in self._weights.items()})


def get_subreddit_stats() -> list[dict]:
    """Return current stats for all tracked subreddits (for CLI display)."""
    rows = _db.execute(
        """SELECT subreddit, base_weight, posts_seen, trades_triggered,
                  profitable_trades, alpha_score, current_weight, last_updated
           FROM subreddit_stats ORDER BY current_weight DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
