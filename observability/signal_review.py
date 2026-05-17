"""
Signal quality review queue — captures sampled signals for human evaluation.

Labels: CORRECT_MATCH, BAD_MATCH, TOO_WEAK, STALE_EVENT, NON_ACTIONABLE,
        HIGH_QUALITY_SIGNAL, LIQUIDITY_TOO_LOW, MARKET_TOO_WEAK,
        TEMPORALLY_STALE, DUPLICATE_EVENT, CONFLICTING_SIGNAL

Persists to signal_reviews table in trades.db.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SignalLabel(Enum):
    CORRECT_MATCH = "correct_match"
    BAD_MATCH = "bad_match"
    TOO_WEAK = "too_weak"
    STALE_EVENT = "stale_event"
    NON_ACTIONABLE = "non_actionable"
    HIGH_QUALITY_SIGNAL = "high_quality_signal"
    LIQUIDITY_TOO_LOW = "liquidity_too_low"
    MARKET_TOO_WEAK = "market_too_weak"
    TEMPORALLY_STALE = "temporally_stale"
    DUPLICATE_EVENT = "duplicate_event"
    CONFLICTING_SIGNAL = "conflicting_signal"


@dataclass
class SignalReview:
    trace_id: str
    headline: str
    source: str
    extracted_entities: list[str]
    matched_market: str
    market_id: str
    alternative_markets: list[dict]
    score_breakdown: dict
    similarity: float
    confidence: float
    materiality: float
    novelty_score: float
    nlp_impact: float
    liquidity_snapshot: dict
    temporal_relevance: float
    rejection_reason: str | None = None
    label: str | None = None
    reviewed_at: str | None = None
    reviewer_notes: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SignalReviewQueue:
    """In-memory queue for sampled signals, with SQLite persistence."""

    def __init__(self, sample_rate: float = 0.20, max_pending: int = 500):
        self.sample_rate = sample_rate
        self.max_pending = max_pending
        self._pending: list[SignalReview] = []
        self._sample_counter: int = 0
        self._captured: int = 0

    def should_sample(self) -> bool:
        self._sample_counter += 1
        if self._sample_counter % max(1, int(1.0 / self.sample_rate)) == 0:
            return True
        return False

    def capture(self, review: SignalReview) -> None:
        self._pending.append(review)
        self._captured += 1
        if len(self._pending) > self.max_pending:
            self._pending = self._pending[-self.max_pending:]
        self._persist(review)

    def label(self, trace_id: str, label: str, notes: str | None = None) -> bool:
        for r in self._pending:
            if r.trace_id == trace_id:
                r.label = label
                r.reviewed_at = datetime.now(timezone.utc).isoformat()
                r.reviewer_notes = notes
                self._update_db(trace_id, label, notes)
                return True
        return False

    def get_pending(self, n: int = 20) -> list[SignalReview]:
        unlabeled = [r for r in self._pending if r.label is None]
        return unlabeled[-n:]

    def get_labeled(self, n: int = 20, label: str | None = None) -> list[SignalReview]:
        labeled = [r for r in self._pending if r.label is not None]
        if label:
            labeled = [r for r in labeled if r.label == label]
        return labeled[-n:]

    def stats(self) -> dict:
        labeled = [r for r in self._pending if r.label is not None]
        unlabeled = [r for r in self._pending if r.label is None]
        label_counts: dict[str, int] = {}
        for r in labeled:
            if r.label:
                label_counts[r.label] = label_counts.get(r.label, 0) + 1
        return {
            "total_captured": self._captured,
            "pending_review": len(unlabeled),
            "reviewed": len(labeled),
            "labels": label_counts,
            "sample_rate": self.sample_rate,
        }

    def _persist(self, review: SignalReview) -> None:
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT OR REPLACE INTO signal_reviews
                   (trace_id, headline, source, extracted_entities, matched_market,
                    market_id, alternative_markets, score_breakdown, similarity,
                    confidence, materiality, novelty_score, nlp_impact,
                    liquidity_snapshot, temporal_relevance, rejection_reason,
                    label, reviewed_at, reviewer_notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (review.trace_id, review.headline, review.source,
                 json.dumps(review.extracted_entities), review.matched_market,
                 review.market_id, json.dumps(review.alternative_markets),
                 json.dumps(review.score_breakdown), review.similarity,
                 review.confidence, review.materiality, review.novelty_score,
                 review.nlp_impact, json.dumps(review.liquidity_snapshot),
                 review.temporal_relevance, review.rejection_reason,
                 review.label, review.reviewed_at, review.reviewer_notes),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _update_db(self, trace_id: str, label: str, notes: str | None) -> None:
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """UPDATE signal_reviews SET label=?, reviewed_at=?, reviewer_notes=?
                   WHERE trace_id=?""",
                (label, datetime.now(timezone.utc).isoformat(), notes, trace_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


_review_queue = SignalReviewQueue()


def get_review_queue() -> SignalReviewQueue:
    return _review_queue


def init_review_table():
    """Create signal_reviews table in trades.db."""
    from observability.logger import _conn
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_reviews (
            trace_id TEXT PRIMARY KEY,
            headline TEXT NOT NULL,
            source TEXT NOT NULL,
            extracted_entities TEXT,
            matched_market TEXT,
            market_id TEXT,
            alternative_markets TEXT,
            score_breakdown TEXT,
            similarity REAL,
            confidence REAL,
            materiality REAL,
            novelty_score REAL,
            nlp_impact REAL,
            liquidity_snapshot TEXT,
            temporal_relevance REAL,
            rejection_reason TEXT,
            label TEXT,
            reviewed_at TEXT,
            reviewer_notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def build_review_from_trace(trace, pipeline=None) -> SignalReview | None:
    """Build a SignalReview from a SignalTrace and pipeline state."""
    try:
        rejection = trace.rejection
        mt = trace.match_trace

        market_q = mt.market_question if mt else "unknown"
        market_id = mt.market_id if mt else "unknown"
        alternatives = mt.rejected_alternatives if mt else []
        score = mt.similarity_score if mt else 0.0
        score_breakdown = getattr(mt, 'score_components', {}) if mt else {}

        # Extract entities from headline
        entities = []
        try:
            from signal.nlp_processor import extract_entities
            for e in extract_entities(trace.headline):
                entities.append(e.text)
        except Exception:
            pass

        # Get liquidity if market watcher available
        liquidity = {}
        if pipeline and hasattr(pipeline, 'watcher'):
            try:
                snap = pipeline.watcher.get_snapshot(market_id)
                if snap:
                    liquidity = {
                        "spread": snap.spread,
                        "liquidity_score": snap.liquidity_score,
                        "bid_depth": snap.order_book.bid_depth_usd,
                        "ask_depth": snap.order_book.ask_depth_usd,
                        "last_price": snap.last_price,
                        "is_moving": snap.is_moving,
                    }
            except Exception:
                pass

        return SignalReview(
            trace_id=trace.trace_id,
            headline=trace.headline,
            source=trace.source,
            extracted_entities=entities,
            matched_market=market_q,
            market_id=market_id,
            alternative_markets=alternatives,
            score_breakdown=score_breakdown,
            similarity=score,
            confidence=rejection.threshold_value if rejection and rejection.threshold_value else 0.0,
            materiality=0.0,
            novelty_score=0.0,
            nlp_impact=0.0,
            liquidity_snapshot=liquidity,
            temporal_relevance=0.0,
            rejection_reason=rejection.reason.name if rejection else None,
        )
    except Exception:
        return None


init_review_table()
