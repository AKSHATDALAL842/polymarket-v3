# alpha/momentum_alpha.py
"""
Momentum Alpha — generates signals from BTC price momentum.

Logic:
  1. Poll CoinGecko every 60s for BTC/USD price.
  2. Keep a rolling deque of (timestamp, price) for the last 5 minutes.
  3. If |5min_return| > MOMENTUM_THRESHOLD (2%):
       - direction = YES if positive, NO if negative
       - confidence = min(|return| / 0.05, 0.85)  — scales from 2% to 5%
       - expected_edge = |return| * 0.4            — conservative estimate
  4. Store the latest signal per market_id in self._signal_buffer.
  5. get_signal(market_id) returns the buffered signal or None.

The pipeline calls get_signal() when processing news events to check
whether momentum corroborates (or conflicts with) the news signal.
MomentumAlpha.run() also runs as a background task in pipeline.run()
to proactively push momentum-only signals.
"""
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

MOMENTUM_THRESHOLD = 0.02    # 2% move in 5 minutes triggers signal
WINDOW_SECONDS     = 300     # 5 minutes
POLL_INTERVAL      = 60      # 1 minute between price fetches
COINGECKO_URL      = "https://api.coingecko.com/api/v3/simple/price"
BTC_KEYWORDS       = ("bitcoin", "btc")


class MomentumAlpha(BaseAlpha):
    """
    BTC price momentum signal generator.
    Runs as an asyncio background task in the pipeline.
    """
    name = "momentum"

    def __init__(self):
        # deque of (unix_timestamp, price_usd)
        self._price_history: deque = deque(maxlen=10)
        # latest signal per market_id
        self._signal_buffer: dict[str, AlphaSignal] = {}
        # signal TTL: discard stale momentum signals after 3 minutes
        self._signal_ttl = 180.0

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_signal(self, market_id: str) -> Optional[AlphaSignal]:
        """
        Return the latest momentum signal for a market, or None if stale/absent.
        Called by pipeline._process_market() to check for momentum confirmation.
        """
        sig = self._signal_buffer.get(market_id)
        if sig is None:
            return None
        if time.time() - sig.timestamp > self._signal_ttl:
            del self._signal_buffer[market_id]
            return None
        return sig

    def to_alpha_signal(self, market, direction: str, momentum: float) -> Optional[AlphaSignal]:
        """
        Create an AlphaSignal from a momentum reading for a specific market.

        Args:
            market: markets.Market object
            direction: "YES" if price rising, "NO" if falling
            momentum: absolute fractional return (e.g. 0.03 for 3%)
        """
        if abs(momentum) < MOMENTUM_THRESHOLD:
            return None

        # Confidence scales linearly from 0 at threshold to 0.85 at 5%+
        raw_conf = (abs(momentum) - MOMENTUM_THRESHOLD) / (0.05 - MOMENTUM_THRESHOLD)
        confidence = min(0.85, max(0.30, raw_conf * 0.85))

        # Conservative edge estimate
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

    # ── Background task ────────────────────────────────────────────────────────

    async def run(self, watcher):
        """
        Background coroutine: polls BTC price and updates signal buffer.
        watcher: market_watcher.MarketWatcher (provides tracked_markets)
        """
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

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _fetch_btc_price(self) -> Optional[float]:
        """Fetch current BTC/USD price from CoinGecko (free, no key required)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    COINGECKO_URL,
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                resp.raise_for_status()
                data = resp.json()
                price = float(data["bitcoin"]["usd"])
                log.debug(f"[momentum_alpha] BTC/USD = ${price:,.2f}")
                return price
        except Exception as e:
            log.debug(f"[momentum_alpha] Price fetch failed: {e}")
            return None

    def _compute_momentum(self) -> Optional[float]:
        """
        Compute 5-minute price return from history.
        Returns signed float (positive = up, negative = down) or None if
        insufficient data (< 3 data points or no point 5min ago).
        """
        if len(self._price_history) < 3:
            return None

        now = time.time()
        cutoff = now - WINDOW_SECONDS  # 5 minutes ago

        # Find the newest price that is at-or-before the 5-minute cutoff
        old_price = None
        for ts, price in self._price_history:
            if ts <= cutoff:
                old_price = price  # keep updating; last match is newest-before-cutoff
            else:
                break  # entries are oldest-to-newest; once we see ts > cutoff, stop

        if old_price is None:
            return None

        current_price = self._price_history[-1][1]
        momentum = (current_price - old_price) / old_price
        log.debug(f"[momentum_alpha] 5m momentum = {momentum:+.3%}")
        return momentum

    def _update_buffer(self, watcher, momentum: float):
        """Update signal buffer for all tracked BTC markets."""
        if abs(momentum) < MOMENTUM_THRESHOLD:
            # Clear stale signals when momentum subsides
            self._signal_buffer.clear()
            return

        direction = "YES" if momentum > 0 else "NO"
        btc_markets = [
            m for m in watcher.tracked_markets
            if any(kw in m.question.lower() for kw in BTC_KEYWORDS)
        ]

        if not btc_markets:
            log.debug("[momentum_alpha] No BTC markets currently tracked")
            return

        for market in btc_markets:
            sig = self.to_alpha_signal(market, direction, momentum)
            if sig:
                self._signal_buffer[market.condition_id] = sig
                log.info(
                    f"[momentum_alpha] {direction} signal: '{market.question[:50]}' "
                    f"momentum={momentum:+.2%} conf={sig.confidence:.2f}"
                )
