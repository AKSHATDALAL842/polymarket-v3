from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

import config

log = logging.getLogger(__name__)


class RiskManager:
    _singleton: Optional["RiskManager"] = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "RiskManager":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
        return cls._singleton

    def __init__(self):
        self._open_positions: dict[str, float] = {}
        self._category_exposure: dict[str, float] = defaultdict(float)
        self._consecutive_losses: int = 0
        self._cooldown_until: float = 0.0
        self._daily_pnl_cache: float = 0.0
        self._daily_pnl_last_check: float = 0.0
        self._state_lock = Lock()
        self._restore_from_db()

    _DAILY_PNL_CACHE_TTL = 30.0  # re-query logger at most every 30s

    def can_trade_daily(self) -> bool:
        now = time.monotonic()
        if now - self._daily_pnl_last_check > self._DAILY_PNL_CACHE_TTL:
            try:
                from observability import logger as lg
                self._daily_pnl_cache = lg.get_daily_pnl()
                self._daily_pnl_last_check = now
            except Exception:
                pass
        loss = min(0.0, self._daily_pnl_cache)
        if abs(loss) >= config.DAILY_LOSS_LIMIT_USD:
            log.warning(f"[risk] Daily loss cap hit: ${abs(loss):.2f}")
            return False
        return True

    def can_open_position(self) -> bool:
        n = len(self._open_positions)
        if n >= config.MAX_CONCURRENT_POSITIONS:
            log.debug(f"[risk] Max concurrent positions ({n}/{config.MAX_CONCURRENT_POSITIONS})")
            return False
        return True

    def can_trade_category(self, category: str, amount_usd: float) -> bool:
        current = self._category_exposure.get(category, 0.0)
        if current + amount_usd > config.MAX_EXPOSURE_PER_CATEGORY_USD:
            log.debug(
                f"[risk] Category exposure exceeded: {category} "
                f"${current:.2f} + ${amount_usd:.2f} > ${config.MAX_EXPOSURE_PER_CATEGORY_USD}"
            )
            return False
        return True

    def try_open_position(self, condition_id: str, category: str, amount_usd: float) -> str | None:
        """Atomically check position/category limits and reserve the slot.

        Returns None if the position was successfully reserved, or a rejection
        reason string if any limit is exceeded. Callers must NOT call
        on_trade_opened() after a successful try_open_position() — the slot is
        already reserved.
        """
        with self._state_lock:
            n = len(self._open_positions)
            if n >= config.MAX_CONCURRENT_POSITIONS:
                log.debug(f"[risk] Max concurrent positions ({n}/{config.MAX_CONCURRENT_POSITIONS})")
                return "rejected_max_positions"
            current_cat = self._category_exposure.get(category, 0.0)
            if current_cat + amount_usd > config.MAX_EXPOSURE_PER_CATEGORY_USD:
                log.debug(
                    f"[risk] Category cap: {category} "
                    f"${current_cat:.2f} + ${amount_usd:.2f} > ${config.MAX_EXPOSURE_PER_CATEGORY_USD}"
                )
                return f"rejected_category_exposure_{category}"
            self._open_positions[condition_id] = amount_usd
            self._category_exposure[category] = current_cat + amount_usd
        log.debug(
            f"[risk] Position reserved: {condition_id[:12]} ${amount_usd:.2f} "
            f"category={category} open={len(self._open_positions)}"
        )
        return None

    def release_position_slot(self, condition_id: str, category: str) -> None:
        """Release a reserved slot on execution failure without recording P&L."""
        with self._state_lock:
            amount = self._open_positions.pop(condition_id, 0.0)
            self._category_exposure[category] = max(
                0.0, self._category_exposure.get(category, 0.0) - amount
            )
        log.debug(f"[risk] Position slot released (failed exec): {condition_id[:12]}")

    def in_cooldown(self) -> bool:
        if time.monotonic() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.monotonic())
            log.debug(f"[risk] In cooldown for {remaining}s")
            return True
        return False

    def on_trade_opened(self, condition_id: str, category: str, amount_usd: float):
        """Legacy: only call this when NOT using try_open_position()."""
        with self._state_lock:
            self._open_positions[condition_id] = amount_usd
            self._category_exposure[category] = self._category_exposure.get(category, 0.0) + amount_usd
        log.debug(
            f"[risk] Position opened: {condition_id[:12]} ${amount_usd:.2f} "
            f"category={category} open={len(self._open_positions)}"
        )

    def on_trade_closed(self, condition_id: str, category: str, pnl: float):
        with self._state_lock:
            amount = self._open_positions.pop(condition_id, 0.0)
            self._category_exposure[category] = max(
                0.0, self._category_exposure.get(category, 0.0) - amount
            )

            if pnl < 0:
                self._consecutive_losses += 1
                if self._consecutive_losses >= config.CONSECUTIVE_LOSS_COOLDOWN:
                    cooldown_secs = config.COOLDOWN_MINUTES * 60
                    self._cooldown_until = time.monotonic() + cooldown_secs
                    log.warning(
                        f"[risk] {self._consecutive_losses} consecutive losses — "
                        f"entering {config.COOLDOWN_MINUTES}min cooldown"
                    )
            else:
                self._consecutive_losses = 0

    def status(self) -> dict:
        cooldown = self.in_cooldown()
        return {
            "open_positions": len(self._open_positions),
            "consecutive_losses": self._consecutive_losses,
            "in_cooldown": cooldown,
            "category_exposure": dict(self._category_exposure),
            "can_trade": (
                self.can_trade_daily()
                and self.can_open_position()
                and not cooldown
            ),
        }

    def reset_daily(self):
        self._consecutive_losses = 0
        self._cooldown_until = 0.0
        log.info("[risk] Daily state reset")

    def _restore_from_db(self):
        """Re-populate open position slots from the positions table on startup."""
        try:
            from observability.logger import get_open_positions
            rows = get_open_positions()
            for row in rows:
                market_id = row.get("market_id", "")
                category = row.get("category", "unknown")
                size_usd = float(row.get("size_usd", 0.0))
                if market_id and size_usd > 0:
                    self._open_positions[market_id] = size_usd
                    self._category_exposure[category] = (
                        self._category_exposure.get(category, 0.0) + size_usd
                    )
            if self._open_positions:
                log.info(
                    f"[risk] Restored {len(self._open_positions)} open position(s) from DB"
                )
        except Exception as e:
            log.warning(f"[risk] Could not restore positions from DB: {e}")
