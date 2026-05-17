"""
Exchange Payload Logger — persists raw exchange interactions for operational research.

Captures: REST responses, WS payloads, fills, acks, auth responses,
rate-limit events, settlements, reconnects. All with timestamps and trace linkage.

This dataset is strategically valuable for understanding real exchange behavior.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ExchangePayload:
    payload_id: str
    trace_id: str | None
    direction: str              # "request" | "response" | "event"
    endpoint: str               # e.g. "/book", "/order", "ws:price_change"
    method: str                 # GET | POST | WS
    raw_body: str               # JSON string
    status_code: int | None = None
    latency_ms: int = 0
    timestamp: float = field(default_factory=time.monotonic)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ExchangeLogger:
    """Persists raw exchange payloads for operational research."""

    def __init__(self, max_payloads: int = 10_000):
        self._payloads: list[ExchangePayload] = []
        self._max_payloads = max_payloads
        self._init_db()

    def _init_db(self):
        from observability.logger import _conn
        conn = _conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exchange_payloads (
                payload_id TEXT PRIMARY KEY,
                trace_id TEXT,
                direction TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                raw_body TEXT NOT NULL,
                status_code INTEGER,
                latency_ms INTEGER,
                timestamp REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exchange_trace ON exchange_payloads(trace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exchange_direction ON exchange_payloads(direction)")
        conn.commit()
        conn.close()

    def log_request(self, trace_id: str | None, endpoint: str, method: str,
                    body: dict | str) -> str:
        import uuid
        pid = f"exp-{uuid.uuid4().hex[:8]}"
        raw = json.dumps(body) if isinstance(body, dict) else body
        payload = ExchangePayload(
            payload_id=pid, trace_id=trace_id, direction="request",
            endpoint=endpoint, method=method, raw_body=raw[:5000],
        )
        self._store(payload)
        return pid

    def log_response(self, trace_id: str | None, endpoint: str, method: str,
                     body: dict | str, status_code: int, latency_ms: int) -> str:
        import uuid
        pid = f"exp-{uuid.uuid4().hex[:8]}"
        raw = json.dumps(body) if isinstance(body, dict) else str(body)
        payload = ExchangePayload(
            payload_id=pid, trace_id=trace_id, direction="response",
            endpoint=endpoint, method=method, raw_body=raw[:5000],
            status_code=status_code, latency_ms=latency_ms,
        )
        self._store(payload)
        return pid

    def log_ws_event(self, event_type: str, body: dict | str) -> str:
        import uuid
        pid = f"exp-{uuid.uuid4().hex[:8]}"
        raw = json.dumps(body) if isinstance(body, dict) else str(body)
        payload = ExchangePayload(
            payload_id=pid, trace_id=None, direction="event",
            endpoint=f"ws:{event_type}", method="WS", raw_body=raw[:2000],
        )
        self._store(payload)
        return pid

    def _store(self, payload: ExchangePayload):
        self._payloads.append(payload)
        if len(self._payloads) > self._max_payloads:
            self._payloads = self._payloads[-self._max_payloads:]

        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT INTO exchange_payloads
                   (payload_id, trace_id, direction, endpoint, method, raw_body,
                    status_code, latency_ms, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (payload.payload_id, payload.trace_id, payload.direction,
                 payload.endpoint, payload.method, payload.raw_body,
                 payload.status_code, payload.latency_ms, payload.timestamp),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_by_trace(self, trace_id: str) -> list[ExchangePayload]:
        return [p for p in self._payloads if p.trace_id == trace_id]

    def get_recent(self, n: int = 50) -> list[ExchangePayload]:
        return self._payloads[-n:]


_exchange_logger = ExchangeLogger()


def get_exchange_logger() -> ExchangeLogger:
    return _exchange_logger
