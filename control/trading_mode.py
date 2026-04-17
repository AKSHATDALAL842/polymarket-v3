# control/trading_mode.py
"""
Runtime trading mode controller.
Allows toggling DRY_RUN ↔ LIVE at runtime via the API without restart.
"""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Optional

import config
from control.safety_guard import SafetyGuard

log = logging.getLogger(__name__)

_VALID_MODES = ("DRY_RUN", "LIVE")


class TradingMode:
    """
    Manages the runtime trading mode (DRY_RUN or LIVE).
    Singleton: TradingMode.instance().
    """
    _singleton: Optional["TradingMode"] = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "TradingMode":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
        return cls._singleton

    def __init__(self):
        # Initialise from config (respects .env setting at startup)
        self._mode = "LIVE" if not config.DRY_RUN else "DRY_RUN"
        self._safety_guard = SafetyGuard()
        self._history: list[dict] = []
        self._mode_lock = Lock()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_live(self) -> bool:
        return self._mode == "LIVE"

    @property
    def is_paper(self) -> bool:
        return self._mode == "DRY_RUN"

    def set_mode(self, mode: str, confirm: bool = False) -> dict:
        """
        Switch trading mode.

        Returns:
            {"success": True} or {"success": False, "error": "..."}
        """
        if mode not in _VALID_MODES:
            return {"success": False, "error": f"Invalid mode {mode!r}. Must be LIVE or DRY_RUN."}

        with self._mode_lock:
            if mode == "DRY_RUN":
                self._apply_mode("DRY_RUN")
                return {"success": True, "mode": "DRY_RUN"}

            if not confirm:
                return {
                    "success": False,
                    "error": "Live trading requires confirm=true in request body."
                }

            safety = self._safety_guard.check()
            if not safety.safe:
                log.warning(f"[trading_mode] Live trading blocked: {safety.reason}")
                return {"success": False, "error": safety.reason}

            self._apply_mode("LIVE")
            log.warning("[trading_mode] LIVE TRADING ENABLED — real money at risk")
            return {"success": True, "mode": "LIVE"}

    def get_history(self) -> list[dict]:
        """Return list of all mode switches (most recent last)."""
        return list(self._history)

    def _apply_mode(self, mode: str):
        """Apply mode change and update config.DRY_RUN."""
        previous = self._mode
        self._mode = mode
        config.DRY_RUN = (mode == "DRY_RUN")

        entry = {
            "from":      previous,
            "to":        mode,
            "timestamp": time.time(),
        }
        self._history.append(entry)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        log.info(f"[trading_mode] Mode changed: {previous} → {mode}")
