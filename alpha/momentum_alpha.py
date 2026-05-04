from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Optional

import httpx

from alpha.base_alpha import BaseAlpha
from alpha.signal import AlphaSignal

log = logging.getLogger(__name__)

MOMENTUM_THRESHOLD = 0.02    # 2% move in 5 minutes triggers a signal
WINDOW_SECONDS     = 300     # lookback window for momentum calculation
POLL_INTERVAL      = 60
COINGECKO_URL      = "https://api.coingecko.com/api/v3/simple/price"
BTC_KEYWORDS       = ("bitcoin", "btc")


class MomentumAlpha(BaseAlpha):
    name = "momentum"

    def __init__(self):
        self._price_history: deque = deque(maxlen=10)
        self._signal_buffer: dict[str, AlphaSignal] = {}
        self._signal_ttl = 180.0  # discard buffered signals after 3 minutes

    def get_signal(self, market_id: str) -> Optional[AlphaSignal]:
        """Return the latest momentum signal for a market, or None if stale/absent."""
        sig = self._signal_buffer.get(market_id)
        if sig is None:
            return None
        if time.time() - sig.timestamp > self._signal_ttl:
            del self._signal_buffer[market_id]
            return None
        return sig

    def to_alpha_signal(self, market, direction: str, momentum: float) -> Optional[AlphaSignal]:
        if abs(momentum) < MOMENTUM_THRESHOLD:
            return None
        # Confidence scales linearly from 0 at threshold to 0.85 at 5%+
        raw_conf = (abs(momentum) - MOMENTUM_THRESHOLD) / (0.05 - MOMENTUM_THRESHOLD)
        confidence = min(0.85, max(0.30, raw_conf * 0.85))
        expected_edge = min(abs(momentum) * 0.40, 0.08)
        try:
            return AlphaSignal(
                market_id=market.condition_id,
                market_question=market.question,
                direction=direction,
                confidence=confidence,
                expected_edge=expected_edge,
                horizon="5m",
                strategy="momentum",
                market=market,
            )
        except (ValueError, AssertionError) as e:
            log.warning(f"[momentum_alpha] Invalid signal: {e}")
            return None

    async def run(self, watcher):
        """Background coroutine: polls BTC price and updates the signal buffer."""
        log.info("[momentum_alpha] Starting BTC momentum monitor (60s interval)")
        while True:
            try:
                price = await self._fetch_btc_price()
                if price is not None:
                    self._price_history.append((time.time(), price))
                    momentum = self._compute_momentum()
                    if momentum is not None:
                        self._update_buffer(watcher, momentum)
            except Exception as e:
                log.warning(f"[momentum_alpha] Error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def _fetch_btc_price(self) -> Optional[float]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    COINGECKO_URL,
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                resp.raise_for_status()
                return float(resp.json()["bitcoin"]["usd"])
        except Exception as e:
            log.debug(f"[momentum_alpha] Price fetch failed: {e}")
            return None

    def _compute_momentum(self) -> Optional[float]:
        """
        Compute 5-minute return from history.
        Returns None if fewer than 3 data points or no price older than WINDOW_SECONDS.
        """
        if len(self._price_history) < 3:
            return None
        cutoff = time.time() - WINDOW_SECONDS
        history_in_window = [(ts, p) for ts, p in self._price_history if ts >= cutoff]
        if not history_in_window:
            return None
        old_price = history_in_window[0][1]
        current_price = self._price_history[-1][1]
        if old_price == 0:
            return None
        return (current_price - old_price) / old_price

    def _update_buffer(self, watcher, momentum: float):
        if abs(momentum) < MOMENTUM_THRESHOLD:
            self._signal_buffer.clear()
            return
        direction = "YES" if momentum > 0 else "NO"
        btc_markets = [
            m for m in watcher.tracked_markets
            if any(kw in m.question.lower() for kw in BTC_KEYWORDS)
        ]
        for market in btc_markets:
            sig = self.to_alpha_signal(market, direction, momentum)
            if sig:
                self._signal_buffer[market.condition_id] = sig
                log.info(
                    f"[momentum_alpha] {direction} signal: '{market.question[:50]}' "
                    f"momentum={momentum:+.2%} conf={sig.confidence:.2f}"
                )
