"""
Position Lifecycle FSM — deterministic state machine for every position.

States: OPENING → OPEN → REDUCING → CLOSED → SETTLING → SETTLED
→ ORPHANED → RECONCILING

Every position links to originating signal, orders, market state, and settlement.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class PositionStage(Enum):
    OPENING = 1
    OPEN = 2
    REDUCING = 3
    CLOSED = 4
    SETTLING = 5
    SETTLED = 6
    ORPHANED = 7
    RECONCILING = 8


VALID_POSITION_TRANSITIONS: dict[PositionStage, set[PositionStage]] = {
    PositionStage.OPENING:     {PositionStage.OPEN, PositionStage.ORPHANED},
    PositionStage.OPEN:        {PositionStage.REDUCING, PositionStage.CLOSED,
                                 PositionStage.ORPHANED},
    PositionStage.REDUCING:    {PositionStage.CLOSED, PositionStage.OPEN,
                                 PositionStage.ORPHANED},
    PositionStage.CLOSED:      {PositionStage.SETTLING, PositionStage.OPEN,
                                 PositionStage.ORPHANED},
    PositionStage.SETTLING:    {PositionStage.SETTLED, PositionStage.ORPHANED},
    PositionStage.SETTLED:     set(),
    PositionStage.ORPHANED:    {PositionStage.RECONCILING, PositionStage.CLOSED,
                                 PositionStage.SETTLED},
    PositionStage.RECONCILING: {PositionStage.OPEN, PositionStage.CLOSED,
                                 PositionStage.SETTLED, PositionStage.ORPHANED},
}


def generate_position_id() -> str:
    return f"pos-{uuid.uuid4().hex[:12]}"


@dataclass
class Position:
    position_id: str
    market_id: str
    market_question: str
    category: str
    platform: str              # polymarket | kalshi
    signal_trace_id: str       # originating signal
    order_ids: list[str]        # linked orders
    side: str                  # YES | NO
    entry_price: float
    size_usd: float
    contracts: float
    current_stage: PositionStage = PositionStage.OPENING
    opened_at: float = field(default_factory=time.monotonic)
    closed_at: float | None = None
    exit_price: float | None = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    settlement_event_id: str | None = None
    reconciliation_count: int = 0
    last_reconciled_at: float | None = None

    def transition(self, to_stage: PositionStage) -> bool:
        allowed = VALID_POSITION_TRANSITIONS.get(self.current_stage, set())
        if to_stage not in allowed:
            log.error(
                "[position_lifecycle] ILLEGAL POSITION TRANSITION: %s → %s (pos=%s)",
                self.current_stage.name, to_stage.name, self.position_id,
            )
            return False
        self.current_stage = to_stage
        if to_stage in (PositionStage.CLOSED, PositionStage.SETTLED):
            self.closed_at = time.monotonic()
        return True

    def mark_to_market(self, current_price: float) -> float:
        if self.current_stage in (PositionStage.SETTLED, PositionStage.ORPHANED):
            return self.realized_pnl
        if self.side == "YES":
            self.unrealized_pnl = self.contracts * (current_price - self.entry_price)
        else:
            self.unrealized_pnl = self.contracts * (self.entry_price - current_price)
        return self.unrealized_pnl

    def settle(self, exit_price: float) -> float:
        if self.side == "YES":
            self.realized_pnl = self.contracts * (exit_price - self.entry_price)
        else:
            self.realized_pnl = self.contracts * (self.entry_price - exit_price)
        self.exit_price = exit_price
        self.unrealized_pnl = 0.0
        if self.current_stage in (PositionStage.OPEN, PositionStage.REDUCING):
            self.transition(PositionStage.CLOSED)
        self.transition(PositionStage.SETTLING)
        self.transition(PositionStage.SETTLED)
        return self.realized_pnl

    def flag_orphaned(self, reason: str) -> None:
        log.warning("[position_lifecycle] Orphaned position %s: %s", self.position_id, reason)
        self.transition(PositionStage.ORPHANED)
        self.reconciliation_count += 1

    def is_active(self) -> bool:
        return self.current_stage in (PositionStage.OPENING, PositionStage.OPEN,
                                       PositionStage.REDUCING)

    def is_terminal(self) -> bool:
        return self.current_stage in (PositionStage.SETTLED,)

    def to_row(self) -> dict:
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "market_question": self.market_question,
            "category": self.category,
            "platform": self.platform,
            "signal_trace_id": self.signal_trace_id,
            "order_ids": json.dumps(self.order_ids),
            "side": self.side,
            "entry_price": self.entry_price,
            "size_usd": self.size_usd,
            "contracts": self.contracts,
            "current_stage": self.current_stage.name,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "reconciliation_count": self.reconciliation_count,
        }


class PositionLedger:
    """Manages all positions. Links to OrderLedger for order→position mapping."""

    def __init__(self):
        self._positions: dict[str, Position] = {}
        self._by_market: dict[str, str] = {}  # market_id → position_id
        self._by_signal: dict[str, str] = {}  # signal_trace_id → position_id

    def open_position(self, market_id: str, market_question: str, category: str,
                      platform: str, signal_trace_id: str, side: str,
                      entry_price: float, size_usd: float, contracts: float) -> Position:
        position_id = generate_position_id()
        pos = Position(
            position_id=position_id,
            market_id=market_id,
            market_question=market_question,
            category=category,
            platform=platform,
            signal_trace_id=signal_trace_id,
            order_ids=[],
            side=side,
            entry_price=entry_price,
            size_usd=size_usd,
            contracts=contracts,
        )
        pos.transition(PositionStage.OPENING)
        pos.transition(PositionStage.OPEN)
        self._positions[position_id] = pos
        self._by_market[market_id] = position_id
        self._by_signal[signal_trace_id] = position_id
        return pos

    def get_position(self, position_id: str) -> Position | None:
        return self._positions.get(position_id)

    def get_by_market(self, market_id: str) -> Position | None:
        pid = self._by_market.get(market_id)
        return self._positions.get(pid) if pid else None

    def get_active_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.is_active()]

    def get_orphaned(self) -> list[Position]:
        return [p for p in self._positions.values()
                if p.current_stage == PositionStage.ORPHANED]

    def total_exposure(self) -> float:
        return sum(p.size_usd for p in self.get_active_positions())

    def category_exposure(self, category: str) -> float:
        return sum(p.size_usd for p in self.get_active_positions()
                   if p.category == category)

    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self._positions.values())


_position_ledger = PositionLedger()


def get_position_ledger() -> PositionLedger:
    return _position_ledger
