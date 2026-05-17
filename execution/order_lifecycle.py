"""
Order Lifecycle FSM — strict state machine for every order.

States: CREATED → VALIDATED → SUBMITTED → ACKNOWLEDGED
→ PARTIALLY_FILLED → FILLED → CANCEL_PENDING → CANCELLED
→ REJECTED → EXPIRED → SETTLED

Uses append-only ledger with idempotency keys for every operation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class OrderStage(Enum):
    CREATED = 1
    VALIDATED = 2
    SUBMITTED = 3
    ACKNOWLEDGED = 4
    PARTIALLY_FILLED = 5
    FILLED = 6
    CANCEL_PENDING = 7
    CANCELLED = 8
    REJECTED = 9
    EXPIRED = 10
    SETTLED = 11


VALID_ORDER_TRANSITIONS: dict[OrderStage, set[OrderStage]] = {
    OrderStage.CREATED:          {OrderStage.VALIDATED, OrderStage.REJECTED, OrderStage.EXPIRED},
    OrderStage.VALIDATED:        {OrderStage.SUBMITTED, OrderStage.REJECTED},
    OrderStage.SUBMITTED:        {OrderStage.ACKNOWLEDGED, OrderStage.REJECTED, OrderStage.EXPIRED},
    OrderStage.ACKNOWLEDGED:     {OrderStage.PARTIALLY_FILLED, OrderStage.FILLED,
                                   OrderStage.CANCEL_PENDING, OrderStage.REJECTED, OrderStage.EXPIRED},
    OrderStage.PARTIALLY_FILLED: {OrderStage.FILLED, OrderStage.CANCEL_PENDING,
                                   OrderStage.REJECTED, OrderStage.EXPIRED},
    OrderStage.FILLED:           {OrderStage.SETTLED, OrderStage.REJECTED},
    OrderStage.CANCEL_PENDING:   {OrderStage.CANCELLED, OrderStage.FILLED, OrderStage.REJECTED},
    OrderStage.CANCELLED:        {OrderStage.SETTLED},
    OrderStage.REJECTED:         set(),
    OrderStage.EXPIRED:          set(),
    OrderStage.SETTLED:          set(),
}


def generate_order_id() -> str:
    return f"ord-{uuid.uuid4().hex[:12]}"


def generate_idempotency_key(signal_trace_id: str, market_id: str, side: str,
                              size: float, price: float) -> str:
    """Deterministic idempotency key — same input produces same key."""
    raw = f"{signal_trace_id}|{market_id}|{side}|{size:.4f}|{price:.4f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class OrderEvent:
    """Immutable event in the append-only order ledger."""
    order_id: str
    event_id: str               # "oevt-{uuid_hex[:8]}"
    idempotency_key: str
    from_stage: str
    to_stage: str
    timestamp: float
    exchange_response: dict | None = None
    error: str | None = None
    retry_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class Order:
    order_id: str
    market_id: str
    signal_trace_id: str
    idempotency_key: str
    side: str                   # YES | NO
    size_usd: float
    limit_price: float
    created_at: float
    current_stage: OrderStage = OrderStage.CREATED
    exchange_order_id: str | None = None
    filled_size: float = 0.0
    fill_price: float = 0.0
    slippage: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    ledger: list[OrderEvent] = field(default_factory=list)
    rejection_reason: str | None = None

    def transition(self, to_stage: OrderStage, exchange_response: dict | None = None,
                   error: str | None = None) -> bool:
        allowed = VALID_ORDER_TRANSITIONS.get(self.current_stage, set())
        if to_stage not in allowed:
            log.error(
                "[order_lifecycle] ILLEGAL ORDER TRANSITION: %s → %s (order=%s)",
                self.current_stage.name, to_stage.name, self.order_id,
            )
            return False

        event = OrderEvent(
            order_id=self.order_id,
            event_id=f"oevt-{uuid.uuid4().hex[:8]}",
            idempotency_key=self.idempotency_key,
            from_stage=self.current_stage.name,
            to_stage=to_stage.name,
            timestamp=time.monotonic(),
            exchange_response=exchange_response,
            error=error,
            retry_count=self.retry_count,
        )
        self.ledger.append(event)
        self.current_stage = to_stage
        if exchange_response:
            self.exchange_order_id = exchange_response.get("order_id") or exchange_response.get("id")
            self.filled_size = float(exchange_response.get("filled_size", exchange_response.get("sizeMatched", self.filled_size)))
            self.fill_price = float(exchange_response.get("fill_price", exchange_response.get("price", self.limit_price)))
        if error:
            self.rejection_reason = error
        self._persist_event(event)
        return True

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def record_retry(self) -> None:
        self.retry_count += 1

    def is_terminal(self) -> bool:
        return self.current_stage in (OrderStage.FILLED, OrderStage.CANCELLED,
                                       OrderStage.REJECTED, OrderStage.EXPIRED,
                                       OrderStage.SETTLED)

    def is_active(self) -> bool:
        return not self.is_terminal()

    def to_row(self) -> dict:
        return {
            "order_id": self.order_id,
            "market_id": self.market_id,
            "signal_trace_id": self.signal_trace_id,
            "idempotency_key": self.idempotency_key,
            "side": self.side,
            "size_usd": self.size_usd,
            "limit_price": self.limit_price,
            "current_stage": self.current_stage.name,
            "exchange_order_id": self.exchange_order_id,
            "filled_size": self.filled_size,
            "fill_price": self.fill_price,
            "slippage": self.slippage,
            "retry_count": self.retry_count,
            "rejection_reason": self.rejection_reason,
        }

    def _persist_event(self, event: OrderEvent):
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT INTO order_ledger
                   (order_id, event_id, idempotency_key, from_stage, to_stage,
                    timestamp, exchange_response, error, retry_count, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.order_id, event.event_id, event.idempotency_key,
                 event.from_stage, event.to_stage, event.timestamp,
                 json.dumps(event.exchange_response) if event.exchange_response else None,
                 event.error, event.retry_count,
                 json.dumps(event.metadata)),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


class OrderLedger:
    """Append-only ledger of all order events. Source of truth for order state."""

    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._by_idempotency: dict[str, str] = {}  # idempotency_key → order_id
        self._init_table()

    def _init_table(self):
        from observability.logger import _conn
        conn = _conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_ledger (
                order_id TEXT NOT NULL,
                event_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                from_stage TEXT NOT NULL,
                to_stage TEXT NOT NULL,
                timestamp REAL NOT NULL,
                exchange_response TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_order_ledger_order ON order_ledger(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_order_ledger_idem ON order_ledger(idempotency_key)")
        conn.commit()
        conn.close()

    def create_order(self, market_id: str, signal_trace_id: str,
                     side: str, size_usd: float, limit_price: float) -> Order:
        order_id = generate_order_id()
        idem_key = generate_idempotency_key(signal_trace_id, market_id, side, size_usd, limit_price)

        # Idempotency: if same key exists, return existing order
        existing_id = self._by_idempotency.get(idem_key)
        if existing_id and existing_id in self._orders:
            log.info("[order_ledger] Idempotent: returning existing order %s", existing_id)
            return self._orders[existing_id]

        order = Order(
            order_id=order_id,
            market_id=market_id,
            signal_trace_id=signal_trace_id,
            idempotency_key=idem_key,
            side=side,
            size_usd=size_usd,
            limit_price=limit_price,
            created_at=time.monotonic(),
        )
        self._orders[order_id] = order
        self._by_idempotency[idem_key] = order_id
        order.transition(OrderStage.CREATED)
        return order

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_active_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.is_active()]

    def get_orders_by_market(self, market_id: str) -> list[Order]:
        return [o for o in self._orders.values() if o.market_id == market_id]

    def total_active_exposure(self) -> float:
        return sum(o.size_usd for o in self.get_active_orders())

    def reconstruct_order(self, order_id: str) -> Order | None:
        """Reconstruct an order's full lifecycle from the append-only ledger."""
        from observability.logger import _conn
        conn = _conn()
        rows = conn.execute(
            "SELECT * FROM order_ledger WHERE order_id = ? ORDER BY timestamp ASC",
            (order_id,),
        ).fetchall()
        conn.close()

        if not rows:
            return None

        first = dict(rows[0])
        order = Order(
            order_id=first["order_id"],
            market_id="",  # will be filled from events
            signal_trace_id="",
            idempotency_key=first["idempotency_key"],
            side="",
            size_usd=0.0,
            limit_price=0.0,
            created_at=first["timestamp"],
        )

        for row in rows:
            r = dict(row)
            try:
                from_stage = OrderStage[r["from_stage"]]
                to_stage = OrderStage[r["to_stage"]]
                order.current_stage = from_stage
                order.retry_count = r["retry_count"]
                resp = json.loads(r["exchange_response"]) if r.get("exchange_response") else None
                order.transition(to_stage, exchange_response=resp, error=r.get("error"))
            except (KeyError, ValueError):
                pass

        return order


_ledger = OrderLedger()


def get_order_ledger() -> OrderLedger:
    return _ledger
