from __future__ import annotations

import logging
from typing import Optional

import numpy as np

import config

log = logging.getLogger(__name__)

_EV_BUCKETS = np.array([0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30])
_CONF_BUCKETS = np.array([0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00])
_SPREAD_BUCKETS = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08])


def _compute_kelly(ev: float, confidence: float, spread: float) -> float:
    ev_net = max(0.0, ev - spread / 2.0)
    raw = config.SIZING_K * ev_net * confidence * config.BANKROLL_USD
    return round(min(config.MAX_BET_USD, max(1.0, raw)), 2)


class KellyTable:

    def __init__(self) -> None:
        self._table: dict[tuple[int, int, int], float] = {}
        self._build()

    def _build(self) -> None:
        for i, ev in enumerate(_EV_BUCKETS):
            for j, conf in enumerate(_CONF_BUCKETS):
                for k, spread in enumerate(_SPREAD_BUCKETS):
                    self._table[(i, j, k)] = _compute_kelly(float(ev), float(conf), float(spread))

    def lookup(self, ev: float, confidence: float, spread: float) -> float:
        raw_i = int(np.searchsorted(_EV_BUCKETS, ev, side="right")) - 1
        i = max(0, min(raw_i, len(_EV_BUCKETS) - 1))
        if raw_i >= len(_EV_BUCKETS):
            log.debug(f"[kelly] EV {ev:.3f} above max bucket {_EV_BUCKETS[-1]:.2f} — clamped")
        j = max(0, min(int(np.searchsorted(_CONF_BUCKETS, confidence, side="right")) - 1, len(_CONF_BUCKETS) - 1))
        k = max(0, min(int(np.searchsorted(_SPREAD_BUCKETS, spread, side="right")) - 1, len(_SPREAD_BUCKETS) - 1))
        return self._table[(i, j, k)]


_table: Optional[KellyTable] = None


def get_kelly_table() -> KellyTable:
    global _table
    if _table is None:
        _table = KellyTable()
    return _table
