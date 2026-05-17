"""
Settlement Engine — authoritative market resolution and PnL finalization.

States: RESOLUTION_PENDING → RESOLUTION_CONFIRMED → PAYOUT_VERIFIED
→ SETTLED / DISPUTED / REFUNDED

Never relies solely on websocket events. Actively polls for resolution.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx

import config

log = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


class SettlementStage(Enum):
    RESOLUTION_PENDING = 1
    RESOLUTION_CONFIRMED = 2
    PAYOUT_VERIFIED = 3
    SETTLED = 4
    DISPUTED = 5
    REFUNDED = 6


SETTLEMENT_TERMINAL = {SettlementStage.SETTLED, SettlementStage.DISPUTED, SettlementStage.REFUNDED}


@dataclass
class SettlementRecord:
    settlement_id: str
    market_id: str
    market_question: str
    resolved_yes: bool = False
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    entry_price: float = 0.0
    side: str = ""
    size_usd: float = 0.0
    contracts: float = 0.0
    position_id: str | None = None
    signal_trace_id: str | None = None
    current_stage: SettlementStage = SettlementStage.RESOLUTION_PENDING
    resolution_source: str = ""      # "gamma_api" | "websocket" | "manual"
    resolved_at: float | None = None
    settled_at: float | None = None
    metadata: dict = field(default_factory=dict)

    def confirm(self, source: str = "gamma_api") -> None:
        self.current_stage = SettlementStage.RESOLUTION_CONFIRMED
        self.resolution_source = source
        self.resolved_at = time.monotonic()

    def verify_payout(self, expected_payout: float) -> bool:
        actual_payout = self.realized_pnl + self.size_usd if self.size_usd > 0 else self.size_usd
        if abs(actual_payout - expected_payout) < 0.01:
            self.current_stage = SettlementStage.PAYOUT_VERIFIED
            return True
        return False

    def finalize(self) -> None:
        self.current_stage = SettlementStage.SETTLED
        self.settled_at = time.monotonic()

    def dispute(self, reason: str) -> None:
        self.current_stage = SettlementStage.DISPUTED
        self.metadata["dispute_reason"] = reason

    def is_terminal(self) -> bool:
        return self.current_stage in SETTLEMENT_TERMINAL


class SettlementEngine:
    """Polls for market resolutions and finalizes PnL deterministically."""

    def __init__(self, check_interval: float = 120.0):
        self.check_interval = check_interval
        self._settlements: dict[str, SettlementRecord] = {}
        self._settled_count: int = 0
        self._disputed_count: int = 0
        self._init_db()

    def _init_db(self):
        from observability.logger import _conn
        conn = _conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settlements (
                settlement_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                market_question TEXT NOT NULL,
                position_id TEXT,
                signal_trace_id TEXT,
                resolved_yes INTEGER NOT NULL,
                exit_price REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                entry_price REAL NOT NULL,
                side TEXT NOT NULL,
                size_usd REAL NOT NULL,
                contracts REAL,
                current_stage TEXT NOT NULL,
                resolution_source TEXT,
                resolved_at REAL,
                settled_at REAL,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_settlements_market ON settlements(market_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_settlements_stage ON settlements(current_stage)")
        conn.commit()
        conn.close()

    def register_position(self, position, signal_trace_id: str | None = None) -> SettlementRecord:
        sid = f"settle-{position.position_id}"
        record = SettlementRecord(
            settlement_id=sid,
            market_id=position.market_id,
            market_question=position.market_question,
            position_id=position.position_id,
            signal_trace_id=signal_trace_id,
            resolved_yes=False,
            exit_price=0.0,
            realized_pnl=0.0,
            entry_price=position.entry_price,
            side=position.side,
            size_usd=position.size_usd,
            contracts=position.contracts,
        )
        self._settlements[sid] = record
        self._persist(record)
        return record

    async def run(self, pipeline) -> None:
        """Background coroutine: periodic settlement checks."""
        log.info("[settlement] Starting (interval=%ss)", self.check_interval)
        while True:
            try:
                await self._check_resolutions(pipeline)
            except Exception as e:
                log.error("[settlement] Check error: %s", e)
            await asyncio.sleep(self.check_interval)

    async def _check_resolutions(self, pipeline) -> None:
        """Check for resolved markets among tracked positions."""
        from execution.position_lifecycle import get_position_ledger
        p_ledger = get_position_ledger()

        for pos in p_ledger.get_active_positions():
            sid = f"settle-{pos.position_id}"
            if sid in self._settlements:
                if self._settlements[sid].is_terminal():
                    continue

            # Check resolution via Gamma API
            try:
                resolved_yes, exit_price = await self._fetch_resolution(pos.market_id)
                if resolved_yes is not None:
                    record = self._settlements.get(sid)
                    if record is None:
                        record = self.register_position(pos)
                    record.resolved_yes = resolved_yes
                    record.exit_price = exit_price
                    record.confirm(source="gamma_api")

                    # Compute PnL and settle
                    realized = pos.settle(exit_price)
                    record.realized_pnl = realized
                    record.finalize()
                    self._settled_count += 1
                    self._persist(record)

                    log.info(
                        "[settlement] SETTLED: %s → %s pnl=$%.2f (%s)",
                        pos.market_question[:40],
                        "YES" if resolved_yes else "NO",
                        realized,
                        record.resolution_source,
                    )

                    # Release risk slot
                    try:
                        from portfolio.risk import RiskManager
                        RiskManager.instance().on_trade_closed(
                            condition_id=pos.market_id,
                            category=pos.category,
                            pnl=realized,
                        )
                    except Exception:
                        pass

            except Exception as e:
                log.debug("[settlement] Resolution check failed for %s: %s", pos.market_id, e)

    async def _fetch_resolution(self, market_id: str) -> tuple[bool | None, float]:
        """Fetch market resolution from Gamma API. Returns (resolved_yes, exit_price)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{GAMMA_API}/markets",
                    params={"condition_id": market_id},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data if isinstance(data, list) else data.get("data", [])
                if not items:
                    return None, 0.0

                market_data = items[0]
                if not market_data.get("closed", False):
                    return None, 0.0

                outcome_prices = market_data.get("outcomePrices", "")
                if isinstance(outcome_prices, str):
                    prices = json.loads(outcome_prices)
                else:
                    prices = outcome_prices

                if not prices or len(prices) < 2:
                    return None, 0.0

                exit_price = float(prices[0])
                resolved_yes = exit_price > 0.5
                return resolved_yes, exit_price

        except Exception as e:
            log.debug("[settlement] Gamma API error for %s: %s", market_id, e)
            return None, 0.0

    def _persist(self, record: SettlementRecord):
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT OR REPLACE INTO settlements
                   (settlement_id, market_id, market_question, position_id,
                    signal_trace_id, resolved_yes, exit_price, realized_pnl,
                    entry_price, side, size_usd, contracts, current_stage,
                    resolution_source, resolved_at, settled_at, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record.settlement_id, record.market_id, record.market_question,
                 record.position_id, record.signal_trace_id,
                 1 if record.resolved_yes else 0,
                 record.exit_price, record.realized_pnl,
                 record.entry_price, record.side, record.size_usd,
                 record.contracts, record.current_stage.value,
                 record.resolution_source, record.resolved_at,
                 record.settled_at, json.dumps(record.metadata)),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def status(self) -> dict:
        pending = sum(1 for s in self._settlements.values() if not s.is_terminal())
        return {
            "total_registered": len(self._settlements),
            "settled": self._settled_count,
            "disputed": self._disputed_count,
            "pending": pending,
        }


_settlement_engine = SettlementEngine()


def get_settlement_engine() -> SettlementEngine:
    return _settlement_engine
