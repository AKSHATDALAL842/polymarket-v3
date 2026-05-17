from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from observability.rejection import RejectionRecord, RejectionReason, RejectionSeverity

log = logging.getLogger(__name__)

TRACE_SCHEMA_VERSION = 1


class SignalStage(Enum):
    INGESTED = 1
    NLP_PROCESSED = 2
    MARKET_MATCHED = 3
    SCORED = 4
    VALIDATED = 5
    SIZED = 6
    EXECUTED = 7
    SETTLED = 8
    REJECTED = 9
    EXPIRED = 10


VALID_TRANSITIONS: dict[SignalStage, set[SignalStage]] = {
    SignalStage.INGESTED:        {SignalStage.NLP_PROCESSED, SignalStage.REJECTED, SignalStage.EXPIRED},
    SignalStage.NLP_PROCESSED:   {SignalStage.MARKET_MATCHED, SignalStage.REJECTED, SignalStage.EXPIRED},
    SignalStage.MARKET_MATCHED:  {SignalStage.SCORED, SignalStage.REJECTED, SignalStage.EXPIRED},
    SignalStage.SCORED:          {SignalStage.VALIDATED, SignalStage.REJECTED, SignalStage.EXPIRED},
    SignalStage.VALIDATED:       {SignalStage.SIZED, SignalStage.REJECTED, SignalStage.EXPIRED},
    SignalStage.SIZED:           {SignalStage.EXECUTED, SignalStage.REJECTED, SignalStage.EXPIRED},
    SignalStage.EXECUTED:        {SignalStage.SETTLED, SignalStage.REJECTED},
    SignalStage.SETTLED:         set(),
    SignalStage.REJECTED:        set(),
    SignalStage.EXPIRED:         set(),
}


def generate_trace_id() -> str:
    return f"sig-{uuid.uuid4().hex[:12]}"


def generate_dlq_id() -> str:
    return f"dlq-{uuid.uuid4().hex[:8]}"


def generate_news_id() -> str:
    return f"news-{uuid.uuid4().hex[:12]}"


@dataclass
class TraceContext:
    trace_id: str
    parent_trace_id: str | None = None
    market_id: str | None = None
    news_id: str | None = None
    source_id: str | None = None
    execution_id: str | None = None
    position_id: int | None = None


@dataclass
class MarketMatchTrace:
    trace_id: str
    market_id: str
    market_question: str
    similarity_score: float
    matched_entities: list[str] = field(default_factory=list)
    keywords_hit: list[str] = field(default_factory=list)
    embedding_distance: float = 0.0
    rank_position: int = 0
    match_method: str = ""
    rejected_alternatives: list[dict] = field(default_factory=list)


@dataclass
class LifecycleEvent:
    stage: SignalStage
    status: str  # "passed" | "rejected" | "error"
    timestamp_ms: int
    detail: dict | None = None


@dataclass
class SignalTrace:
    trace_id: str
    headline: str
    source: str
    context: TraceContext
    created_at: float
    current_stage: SignalStage = SignalStage.INGESTED
    final_status: str = "in_progress"
    rejection: RejectionRecord | None = None
    match_trace: MarketMatchTrace | None = None
    lifecycle: list[LifecycleEvent] = field(default_factory=list)
    stage_timings: list[dict] = field(default_factory=list)
    total_latency_ms: int = 0

    def transition(self, to_stage: SignalStage, status: str = "passed",
                   detail: dict | None = None) -> bool:
        allowed = VALID_TRANSITIONS.get(self.current_stage, set())
        if to_stage not in allowed:
            log.error(
                "[tracer] ILLEGAL TRANSITION: %s -> %s (trace=%s, headline=%.60s)",
                self.current_stage.name, to_stage.name,
                self.trace_id, self.headline,
            )
            return False
        elapsed = int((time.monotonic() - self.created_at) * 1000)
        self.lifecycle.append(LifecycleEvent(
            stage=to_stage, status=status,
            timestamp_ms=elapsed, detail=detail,
        ))
        self.current_stage = to_stage
        return True

    def reject(self, reason: RejectionReason, threshold: float | None = None,
               actual: float | None = None, snapshot: dict | None = None,
               detail: str | None = None) -> None:
        self.rejection = RejectionRecord(
            trace_id=self.trace_id,
            reason=reason,
            severity=reason.severity,
            subsystem=reason.subsystem,
            threshold_value=threshold,
            actual_value=actual,
            threshold_snapshot=snapshot or {},
            detail=detail,
            timestamp=time.monotonic(),
        )
        self.transition(SignalStage.REJECTED, status="rejected", detail={
            "reason": reason.name,
            "threshold": threshold,
            "actual": actual,
            "detail": detail,
        })

    def set_match_trace(self, mt: MarketMatchTrace) -> None:
        self.match_trace = mt

    def add_stage_timing(self, stage: str, latency_us: int) -> None:
        self.stage_timings.append({"stage": stage, "latency_us": latency_us})

    def finalize(self) -> dict:
        self.total_latency_ms = int((time.monotonic() - self.created_at) * 1000)
        if self.current_stage not in (SignalStage.REJECTED, SignalStage.SETTLED, SignalStage.EXPIRED):
            self.final_status = "completed" if self.current_stage == SignalStage.EXECUTED else "in_progress"
        else:
            self.final_status = self.current_stage.name.lower()
        return self.to_row()

    def to_row(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "parent_trace_id": self.context.parent_trace_id,
            "headline": self.headline,
            "source": self.source,
            "news_id": self.context.news_id,
            "source_id": self.context.source_id,
            "market_id": self.context.market_id,
            "market_question": self.context.market_id,
            "direction": None,
            "final_stage": self.current_stage.name,
            "final_status": self.final_status,
            "rejection_reason": self.rejection.reason.name if self.rejection else None,
            "rejection_severity": self.rejection.severity.name if self.rejection else None,
            "rejection_detail": None,
            "match_trace": None,
            "stage_timings": None,
            "total_latency_ms": self.total_latency_ms,
            "execution_id": self.context.execution_id,
            "position_id": self.context.position_id,
        }


class DeadLetter:
    def __init__(self, payload: dict, exception: str, subsystem: str,
                 trace_id: str | None = None):
        self.dlq_id = generate_dlq_id()
        self.payload = payload
        self.exception = exception
        self.subsystem = subsystem
        self.trace_id = trace_id
        self.retry_count = 0
        self.first_seen = time.monotonic()
        self.last_seen = time.monotonic()
        self.status = "pending"


class DeadLetterQueue:
    def __init__(self, maxlen: int = 500):
        self._queue: deque[DeadLetter] = deque(maxlen=maxlen)
        self._by_subsystem: dict[str, int] = {}

    def push(self, dl: DeadLetter) -> None:
        self._queue.append(dl)
        self._by_subsystem[dl.subsystem] = self._by_subsystem.get(dl.subsystem, 0) + 1

    def pop(self) -> DeadLetter | None:
        try:
            dl = self._queue.popleft()
            self._by_subsystem[dl.subsystem] = max(0, self._by_subsystem.get(dl.subsystem, 1) - 1)
            return dl
        except IndexError:
            return None

    def bury(self, dlq_id: str) -> bool:
        for dl in self._queue:
            if dl.dlq_id == dlq_id:
                dl.status = "dead"
                return True
        return False

    def stats(self) -> dict:
        counts = {"pending": 0, "dead": 0}
        for dl in self._queue:
            counts[dl.status] = counts.get(dl.status, 0) + 1
        return {
            "total": len(self._queue),
            "by_status": counts,
            "by_subsystem": dict(self._by_subsystem),
        }


_active_traces: dict[str, SignalTrace] = {}
_dlq = DeadLetterQueue()


def create_trace(headline: str, source: str, parent_trace_id: str | None = None,
                 news_id: str | None = None, source_id: str | None = None) -> SignalTrace:
    trace_id = generate_trace_id()
    trace = SignalTrace(
        trace_id=trace_id,
        headline=headline,
        source=source,
        context=TraceContext(
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            news_id=news_id,
            source_id=source_id,
        ),
        created_at=time.monotonic(),
    )
    _active_traces[trace_id] = trace
    if len(_active_traces) > 500:
        oldest = min(_active_traces.keys(), key=lambda k: _active_traces[k].created_at)
        del _active_traces[oldest]
    return trace


def get_trace(trace_id: str) -> SignalTrace | None:
    return _active_traces.get(trace_id)


def remove_trace(trace_id: str) -> None:
    _active_traces.pop(trace_id, None)


def get_active_traces() -> list[SignalTrace]:
    return list(_active_traces.values())


def get_dlq() -> DeadLetterQueue:
    return _dlq


def reconstruct_trace(trace_id: str, row: dict) -> dict:
    """Reconstruct full signal lifecycle from a persisted SQLite row."""
    import json
    lifecycle = [
        {"stage": "INGESTED", "status": "passed", "timestamp_ms": 0}
    ]
    if row.get("stage_timings"):
        try:
            timings = json.loads(row["stage_timings"])
            for t in timings:
                lifecycle.append({"stage": t["stage"], "status": t.get("status", "passed"),
                                  "timestamp_ms": t.get("latency_us", 0) // 1000})
        except (json.JSONDecodeError, KeyError):
            pass
    rejection = None
    if row.get("rejection_detail"):
        try:
            rejection = json.loads(row["rejection_detail"])
        except json.JSONDecodeError:
            rejection = {"raw": row["rejection_detail"]}
    match_trace = None
    if row.get("match_trace"):
        try:
            match_trace = json.loads(row["match_trace"])
        except json.JSONDecodeError:
            match_trace = {"raw": row["match_trace"]}
    return {
        "trace_id": row["trace_id"],
        "parent_trace_id": row.get("parent_trace_id"),
        "headline": row["headline"],
        "source": row["source"],
        "market_id": row.get("market_id"),
        "final_stage": row["final_stage"],
        "final_status": row["final_status"],
        "rejection": rejection,
        "match_trace": match_trace,
        "lifecycle": lifecycle,
        "total_latency_ms": row.get("total_latency_ms"),
        "created_at": row["created_at"],
        "schema_version": TRACE_SCHEMA_VERSION,
    }
