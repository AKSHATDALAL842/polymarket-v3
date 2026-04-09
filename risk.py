"""
Risk Management Layer — stateful risk controller for the live pipeline.

Enforces:
  1. Daily loss cap (hard stop)
  2. Max concurrent open positions
  3. Per-category exposure limit
  4. Cooldown after N consecutive losses

All state is in-memory (resets on restart). The daily P&L is cross-checked
against logger.get_daily_pnl() so it survives module reloads.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

import config

log = logging.getLogger(__name__)


class RiskManager:
    """
    Singleton risk controller. Get the shared instance via RiskManager.instance().
    """
    _singleton: Optional["RiskManager"] = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "RiskManager":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
        return cls._singleton

    def __init__(self):
        self._open_positions: dict[str, float] = {}      # condition_id → bet_amount
        self._category_exposure: dict[str, float] = defaultdict(float)  # category → USD open
        self._consecutive_losses: int = 0
        self._cooldown_until: float = 0.0                # monotonic time
        self._daily_pnl_cache: float = 0.0
        self._daily_pnl_last_check: float = 0.0

    # ── Checks ─────────────────────────────────────────────────────────────────

    def can_trade_daily(self) -> bool:
        """Check daily loss cap by querying logger."""
        try:
            import logger as lg
            pnl = lg.get_daily_pnl()
            loss = min(0.0, pnl)                          # only count losses
            if abs(loss) >= config.DAILY_LOSS_LIMIT_USD:
                log.warning(f"[risk] Daily loss cap hit: ${abs(loss):.2f}")
                return False
        except Exception:
            pass
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

    def in_cooldown(self) -> bool:
        if time.monotonic() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.monotonic())
            log.debug(f"[risk] In cooldown for {remaining}s")
            return True
        return False

    # ── State updates ───────────────────────────────────────────────────────────

    def on_trade_opened(self, condition_id: str, category: str, amount_usd: float):
        self._open_positions[condition_id] = amount_usd
        self._category_exposure[category] = self._category_exposure.get(category, 0.0) + amount_usd
        log.debug(
            f"[risk] Position opened: {condition_id[:12]} ${amount_usd:.2f} "
            f"category={category} open={len(self._open_positions)}"
        )

    def on_trade_closed(self, condition_id: str, category: str, pnl: float):
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

    # ── Status ──────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "open_positions": len(self._open_positions),
            "consecutive_losses": self._consecutive_losses,
            "in_cooldown": self.in_cooldown(),
            "category_exposure": dict(self._category_exposure),
            "can_trade": (
                self.can_trade_daily()
                and self.can_open_position()
                and not self.in_cooldown()
            ),
        }

    def reset_daily(self):
        """Call at midnight to reset daily state."""
        self._consecutive_losses = 0
        self._cooldown_until = 0.0
        log.info("[risk] Daily state reset")
