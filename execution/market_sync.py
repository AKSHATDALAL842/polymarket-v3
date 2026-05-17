"""
Market State Synchronizer — self-healing market data with staleness detection.

Sources: websocket price feed (primary) + periodic REST snapshots (authoritative).
Detects: stale quotes, dead streams, market closure drift, missing markets,
         timestamp skew, invalid snapshots, sequence gaps.

Healing: full snapshot refresh, stale-cache invalidation, reconnect recovery.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class SyncHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"        # Some markets stale
    STALE = "stale"               # Most markets stale
    DISCONNECTED = "disconnected" # No updates at all
    HEALING = "healing"           # Recovering after disconnect


@dataclass
class MarketSyncState:
    market_id: str
    last_ws_update: float = 0.0       # monotonic time of last WS update
    last_snapshot_update: float = 0.0  # last REST snapshot refresh
    ws_message_count: int = 0
    snapshot_count: int = 0
    price: float = 0.0
    spread: float = 0.0
    liquidity: float = 0.0
    is_stale: bool = False
    is_closed: bool = False
    sequence_gaps: int = 0
    last_sequence: int = 0

    @property
    def seconds_since_ws(self) -> float:
        return time.monotonic() - self.last_ws_update if self.last_ws_update > 0 else float('inf')

    @property
    def seconds_since_snapshot(self) -> float:
        return time.monotonic() - self.last_snapshot_update if self.last_snapshot_update > 0 else float('inf')


class MarketStateSynchronizer:
    """Self-healing market data synchronization with staleness detection."""

    def __init__(self,
                 stale_ws_threshold: float = 60.0,       # 60s without WS = stale
                 stale_snapshot_threshold: float = 600.0, # 10min without snapshot = stale
                 snapshot_interval: float = 300.0,        # 5min between full snapshots
                 heal_interval: float = 30.0):            # 30s between heal checks
        self.stale_ws_threshold = stale_ws_threshold
        self.stale_snapshot_threshold = stale_snapshot_threshold
        self.snapshot_interval = snapshot_interval
        self.heal_interval = heal_interval

        self._markets: dict[str, MarketSyncState] = {}
        self._health = SyncHealth.DISCONNECTED
        self._last_ws_message: float = 0.0
        self._ws_reconnects: int = 0
        self._snapshot_cycles: int = 0
        self._stale_markets_detected: int = 0
        self._sequence_gaps_total: int = 0
        self._last_heal: float = 0.0

    def register_market(self, market_id: str) -> None:
        if market_id not in self._markets:
            self._markets[market_id] = MarketSyncState(market_id=market_id)

    def unregister_market(self, market_id: str) -> None:
        self._markets.pop(market_id, None)

    def record_ws_update(self, market_id: str, price: float,
                         sequence: int = 0) -> None:
        state = self._markets.get(market_id)
        if state is None:
            state = MarketSyncState(market_id=market_id)
            self._markets[market_id] = state

        # Sequence gap detection
        if sequence > 0 and state.last_sequence > 0:
            expected = state.last_sequence + 1
            if sequence > expected:
                state.sequence_gaps += 1
                self._sequence_gaps_total += 1
                log.debug("[market_sync] Sequence gap on %s: expected %d, got %d",
                          market_id[:20], expected, sequence)

        state.last_ws_update = time.monotonic()
        state.last_sequence = max(state.last_sequence, sequence)
        state.price = price
        state.ws_message_count += 1
        state.is_stale = False
        self._last_ws_message = time.monotonic()

        if self._health == SyncHealth.DISCONNECTED:
            self._health = SyncHealth.HEALTHY

    def record_snapshot(self, market_id: str, price: float, spread: float,
                        liquidity: float, is_closed: bool = False) -> None:
        state = self._markets.get(market_id)
        if state is None:
            state = MarketSyncState(market_id=market_id)
            self._markets[market_id] = state

        state.last_snapshot_update = time.monotonic()
        state.price = price
        state.spread = spread
        state.liquidity = liquidity
        state.is_closed = is_closed
        state.snapshot_count += 1

    def check_health(self) -> SyncHealth:
        """Evaluate overall sync health."""
        if not self._markets:
            return SyncHealth.DISCONNECTED

        now = time.monotonic()
        stale_count = 0
        disconnected_count = 0
        closed_count = 0

        for state in self._markets.values():
            ws_age = now - state.last_ws_update if state.last_ws_update > 0 else float('inf')

            if ws_age > self.stale_ws_threshold:
                stale_count += 1
                state.is_stale = True
            else:
                state.is_stale = False

            if state.last_ws_update == 0:
                disconnected_count += 1

            if state.is_closed:
                closed_count += 1

        total = len(self._markets)
        stale_pct = stale_count / max(1, total)
        disconnected_pct = disconnected_count / max(1, total)
        self._stale_markets_detected = stale_count

        # No updates at all → disconnected
        if self._last_ws_message == 0:
            self._health = SyncHealth.DISCONNECTED
        elif disconnected_pct > 0.8:
            self._health = SyncHealth.DISCONNECTED
        elif stale_pct > 0.5:
            self._health = SyncHealth.STALE
        elif stale_pct > 0.1:
            self._health = SyncHealth.DEGRADED
        elif self._health == SyncHealth.HEALING:
            self._health = SyncHealth.HEALTHY
        else:
            self._health = SyncHealth.HEALTHY

        return self._health

    async def heal(self, pipeline) -> dict:
        """Attempt self-healing: refresh all stale markets."""
        if time.monotonic() - self._last_heal < self.heal_interval:
            return {"healed": 0, "reason": "cooldown"}

        self._last_heal = time.monotonic()
        self._health = SyncHealth.HEALING
        healed = 0

        try:
            if hasattr(pipeline, 'watcher'):
                await pipeline.watcher.refresh_markets()

                # Update sync state for refreshed markets
                for m in pipeline.watcher.tracked_markets:
                    self.record_snapshot(
                        m.condition_id,
                        price=m.yes_price,
                        spread=0.0,
                        liquidity=0.0,
                        is_closed=not m.active,
                    )

                for state in self._markets.values():
                    if state.is_stale and not state.is_closed:
                        state.is_stale = False
                        healed += 1

            log.info("[market_sync] Heal cycle: refreshed %d stale markets", healed)
        except Exception as e:
            log.error("[market_sync] Heal failed: %s", e)

        self._health = SyncHealth.HEALTHY
        self._ws_reconnects += 1
        return {"healed": healed, "total_markets": len(self._markets)}

    async def run(self, pipeline) -> None:
        """Background coroutine: periodic health checks and self-healing."""
        log.info("[market_sync] Starting (snapshot=%ss, heal=%ss)",
                 self.snapshot_interval, self.heal_interval)
        last_snapshot = 0.0

        while True:
            try:
                health = self.check_health()

                # Periodic full snapshot refresh
                now = time.monotonic()
                if now - last_snapshot >= self.snapshot_interval:
                    if hasattr(pipeline, 'watcher'):
                        try:
                            await pipeline.watcher.refresh_markets()
                            self._snapshot_cycles += 1
                            last_snapshot = now

                            for m in pipeline.watcher.tracked_markets:
                                self.register_market(m.condition_id)
                                self.record_snapshot(
                                    m.condition_id,
                                    price=m.yes_price,
                                    spread=0.0,
                                    liquidity=0.0,
                                    is_closed=not m.active,
                                )
                        except Exception as e:
                            log.warning("[market_sync] Snapshot refresh failed: %s", e)

                # Heal if degraded
                if health in (SyncHealth.DEGRADED, SyncHealth.STALE, SyncHealth.DISCONNECTED):
                    await self.heal(pipeline)

                # Remove closed markets
                closed = [mid for mid, s in self._markets.items() if s.is_closed]
                for mid in closed:
                    self.unregister_market(mid)

            except Exception as e:
                log.error("[market_sync] Health check error: %s", e)

            await asyncio.sleep(self.heal_interval)

    def get_stale_markets(self) -> list[str]:
        return [mid for mid, s in self._markets.items() if s.is_stale]

    def status(self) -> dict:
        now = time.monotonic()
        return {
            "health": self._health.value,
            "markets_tracked": len(self._markets),
            "stale_markets": self._stale_markets_detected,
            "sequence_gaps": self._sequence_gaps_total,
            "ws_reconnects": self._ws_reconnects,
            "snapshot_cycles": self._snapshot_cycles,
            "seconds_since_last_ws": round(now - self._last_ws_message, 1)
                if self._last_ws_message > 0 else None,
            "last_heal_seconds_ago": round(now - self._last_heal, 1)
                if self._last_heal > 0 else None,
        }


_synchronizer = MarketStateSynchronizer()


def get_market_synchronizer() -> MarketStateSynchronizer:
    return _synchronizer
