"""
Microstructure-aware market watcher.

Maintains live snapshots of tracked markets with:
  - Real-time price feed (WebSocket)
  - Order book depth analysis
  - Spread calculation
  - Price momentum detection
  - Liquidity scoring

Used by the pipeline to:
  - Filter out markets that are already moving (momentum gate)
  - Estimate slippage before submitting orders
  - Prioritize liquid markets
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque

import httpx

import config
from markets import Market, fetch_active_markets, filter_by_categories

log = logging.getLogger(__name__)


# ── Price tick for momentum tracking ──────────────────────────────────────────

@dataclass
class PriceTick:
    price: float
    timestamp: float    # monotonic seconds


# ── Order book snapshot ────────────────────────────────────────────────────────

@dataclass
class OrderBookSnapshot:
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_depth_usd: float = 0.0    # USD depth across top-3 bid levels
    ask_depth_usd: float = 0.0    # USD depth across top-3 ask levels
    spread: float = 1.0           # ask - bid
    mid: float = 0.5
    liquidity_score: float = 0.0  # 0=illiquid, 1=very liquid

    @classmethod
    def from_clob_response(cls, data: dict) -> "OrderBookSnapshot":
        """Parse a CLOB order book response."""
        try:
            bids = sorted(data.get("bids", []), key=lambda x: float(x.get("price", 0)), reverse=True)
            asks = sorted(data.get("asks", []), key=lambda x: float(x.get("price", 1)))

            if not bids or not asks:
                return cls()

            best_bid = float(bids[0]["price"])
            best_ask = float(asks[0]["price"])
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2

            # Depth: sum USD value of top 3 levels
            bid_depth = sum(
                float(b.get("price", 0)) * float(b.get("size", 0))
                for b in bids[:3]
            )
            ask_depth = sum(
                float(a.get("price", 0)) * float(a.get("size", 0))
                for a in asks[:3]
            )

            # Liquidity score: harmonic mean of bid/ask depth, normalized
            min_depth = min(bid_depth, ask_depth)
            liq = min(1.0, min_depth / 1000.0)    # $1000 depth → score=1.0

            return cls(
                best_bid=best_bid,
                best_ask=best_ask,
                bid_depth_usd=bid_depth,
                ask_depth_usd=ask_depth,
                spread=spread,
                mid=mid,
                liquidity_score=liq,
            )
        except Exception:
            return cls()


# ── Market snapshot ────────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    market: Market
    last_price: float
    prev_price: float
    last_update: datetime
    order_book: OrderBookSnapshot = field(default_factory=OrderBookSnapshot)
    # Rolling price history for momentum
    price_history: Deque[PriceTick] = field(default_factory=lambda: deque(maxlen=120))

    @property
    def price_change(self) -> float:
        return self.last_price - self.prev_price

    @property
    def momentum(self) -> float:
        """
        Price change over MOMENTUM_WINDOW_SECONDS.
        Positive = price moving up; negative = price moving down.
        """
        now = time.monotonic()
        cutoff = now - config.MOMENTUM_WINDOW_SECONDS
        history = [t for t in self.price_history if t.timestamp >= cutoff]
        if len(history) < 2:
            return 0.0
        return history[-1].price - history[0].price

    @property
    def is_moving(self) -> bool:
        """True if price has moved too much recently — avoid chasing."""
        return abs(self.momentum) > config.MOMENTUM_THRESHOLD

    @property
    def spread(self) -> float:
        if self.order_book.spread < 0.001:
            # Fallback to market bid/ask spread estimate from price
            p = self.last_price
            return max(0.01, min(0.1, 0.02 + 0.03 * (1 - abs(p - 0.5) * 2)))
        return self.order_book.spread

    @property
    def liquidity_score(self) -> float:
        return self.order_book.liquidity_score

    def estimated_slippage(self, side: str, size_usd: float) -> float:
        """
        Estimate slippage for a given order size.
        Larger orders on thin books = more slippage.
        """
        depth = self.order_book.bid_depth_usd if side == "NO" else self.order_book.ask_depth_usd
        if depth <= 0:
            return self.spread
        impact = size_usd / depth          # market impact fraction
        return min(self.spread + impact * 0.5, 0.15)


# ── Watcher ────────────────────────────────────────────────────────────────────

class MarketWatcher:
    """
    Maintains live microstructure snapshots for all tracked niche markets.
    Data sources:
      1. WebSocket — real-time price ticks (Polymarket CLOB)
      2. REST (CLOB) — order book depth (polled per-market on demand)
      3. Gamma API — market list refresh every 5 minutes
    """

    def __init__(self):
        self.snapshots: dict[str, MarketSnapshot] = {}
        self.tracked_markets: list[Market] = []
        self._refresh_interval = 300
        self._ws_connected = False
        self._ws = None   # live websocket handle, used to subscribe new markets
        self._http = httpx.AsyncClient(timeout=10)
        self.stats = {
            "ws_messages": 0,
            "price_updates": 0,
            "market_refreshes": 0,
            "orderbook_fetches": 0,
        }

    # ── Market list ────────────────────────────────────────────────────────────

    def get_niche_markets(self, markets: list[Market]) -> list[Market]:
        eligible = [
            m for m in markets
            if config.MIN_VOLUME_USD <= m.volume <= config.MAX_VOLUME_USD
            and m.active
        ]

        if not config.PREFER_SHORT_DURATION_DAYS:
            return eligible

        # Sort: markets resolving within PREFER_SHORT_DURATION_DAYS come first,
        # then remaining markets sorted by end_date ascending (soonest first).
        now = datetime.now(timezone.utc)
        cutoff_days = config.PREFER_SHORT_DURATION_DAYS

        def _days_to_expiry(m: Market) -> float:
            """Return days until market resolution, or inf if unparseable."""
            ed = m.end_date
            if not ed:
                return float("inf")
            try:
                # Handle ISO strings with or without timezone
                if ed.endswith("Z"):
                    ed = ed[:-1] + "+00:00"
                dt = datetime.fromisoformat(ed)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                delta = (dt - now).total_seconds() / 86400.0
                return max(0.0, delta)
            except (ValueError, TypeError):
                return float("inf")

        short = []
        long_ = []
        for m in eligible:
            days = _days_to_expiry(m)
            if days <= cutoff_days:
                short.append((days, m))
            else:
                long_.append((days, m))

        short.sort(key=lambda x: x[0])
        long_.sort(key=lambda x: x[0])

        sorted_markets = [m for _, m in short] + [m for _, m in long_]

        if short:
            log.info(
                f"[watcher] {len(short)} short-duration markets (≤{cutoff_days}d) "
                f"prioritized out of {len(eligible)} total"
            )

        return sorted_markets

    async def refresh_markets(self):
        try:
            # Fetch Polymarket markets
            all_markets = await asyncio.get_running_loop().run_in_executor(
                None, lambda: fetch_active_markets(limit=200)
            )

            # Merge Kalshi markets if enabled
            if config.KALSHI_ENABLED:
                try:
                    from kalshi_markets import fetch_kalshi_markets
                    kalshi = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: fetch_kalshi_markets(limit=200)
                    )
                    all_markets = all_markets + kalshi
                    log.info(f"[watcher] Merged {len(kalshi)} Kalshi markets")
                except Exception as e:
                    log.warning(f"[watcher] Kalshi fetch skipped: {e}")

            categorized = filter_by_categories(all_markets)
            self.tracked_markets = self.get_niche_markets(categorized)

            now = datetime.now(timezone.utc)
            existing_ids = set(self.snapshots)
            new_ids = {m.condition_id for m in self.tracked_markets}

            newly_added: list[Market] = []
            for m in self.tracked_markets:
                if m.condition_id not in self.snapshots:
                    self.snapshots[m.condition_id] = MarketSnapshot(
                        market=m,
                        last_price=m.yes_price,
                        prev_price=m.yes_price,
                        last_update=now,
                    )
                    newly_added.append(m)
                else:
                    snap = self.snapshots[m.condition_id]
                    snap.market = m

            for stale_id in existing_ids - new_ids:
                del self.snapshots[stale_id]

            # Subscribe new markets to live WebSocket if connected
            if newly_added and self._ws_connected and self._ws is not None:
                for m in newly_added:
                    for token in m.tokens:
                        tid = token.get("token_id")
                        if tid:
                            try:
                                await self._ws.send(json.dumps({
                                    "type": "subscribe",
                                    "channel": "price",
                                    "market": tid,
                                }))
                            except Exception as e:
                                log.debug(f"[watcher] WS re-subscribe failed for {tid}: {e}")

            self.stats["market_refreshes"] += 1
            log.info(f"[watcher] Tracking {len(self.tracked_markets)} niche markets")

            # Update embedding cache with new market list
            try:
                from matcher import update_market_embeddings
                update_market_embeddings(self.tracked_markets)
            except Exception as e:
                log.debug(f"[watcher] Embedding update skipped: {e}")

        except Exception as e:
            log.warning(f"[watcher] Market refresh error: {e}")

    # ── Order book depth (on-demand) ───────────────────────────────────────────

    async def fetch_order_book(self, market: Market) -> OrderBookSnapshot:
        """
        Fetch live order book for a specific market token from CLOB.
        Called before executing a trade to get accurate spread + depth.
        """
        if not market.tokens:
            return OrderBookSnapshot()

        token_id = market.tokens[0].get("token_id", "")
        if not token_id:
            return OrderBookSnapshot()

        try:
            resp = await self._http.get(
                f"{config.POLYMARKET_HOST}/book",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            data = resp.json()
            snap = OrderBookSnapshot.from_clob_response(data)
            self.stats["orderbook_fetches"] += 1

            # Update stored snapshot
            if market.condition_id in self.snapshots:
                self.snapshots[market.condition_id].order_book = snap

            return snap
        except Exception as e:
            log.debug(f"[watcher] Order book fetch failed for {market.condition_id}: {e}")
            return OrderBookSnapshot()

    # ── WebSocket ──────────────────────────────────────────────────────────────

    async def _connect_websocket(self):
        try:
            import websockets
        except ImportError:
            log.warning("[watcher] websockets not installed — price feed disabled")
            return

        import ssl, certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())

        while True:
            try:
                async with websockets.connect(
                    config.POLYMARKET_WS_HOST,
                    ping_interval=30,
                    ping_timeout=10,
                    ssl=ssl_ctx,
                ) as ws:
                    self._ws_connected = True
                    self._ws = ws
                    log.info("[watcher] WebSocket connected")

                    for market in self.tracked_markets:
                        for token in market.tokens:
                            tid = token.get("token_id")
                            if tid:
                                await ws.send(json.dumps({
                                    "type": "subscribe",
                                    "channel": "price",
                                    "market": tid,
                                }))

                    async for raw in ws:
                        self.stats["ws_messages"] += 1
                        try:
                            self._handle_ws_message(json.loads(raw))
                        except Exception:
                            pass

            except Exception as e:
                self._ws_connected = False
                self._ws = None
                log.warning(f"[watcher] WS error: {e}  — reconnecting in 5s")
                await asyncio.sleep(5)

    def _handle_ws_message(self, data: dict):
        msg_type = data.get("type", "")
        if msg_type not in ("price_change", "last_trade_price"):
            return

        market_id = data.get("market", data.get("condition_id", ""))
        price = data.get("price")
        if not market_id or price is None:
            return

        price = float(price)
        now_dt = datetime.now(timezone.utc)
        now_mono = time.monotonic()

        for cid, snap in self.snapshots.items():
            token_ids = [t.get("token_id", "") for t in snap.market.tokens]
            if market_id in token_ids or market_id == cid:
                snap.prev_price = snap.last_price
                snap.last_price = price
                snap.last_update = now_dt
                snap.price_history.append(PriceTick(price=price, timestamp=now_mono))
                self.stats["price_updates"] += 1
                break

    # ── Background tasks ───────────────────────────────────────────────────────

    async def _polling_fallback(self):
        """Re-poll market list when WebSocket is down."""
        while True:
            await asyncio.sleep(30)
            if not self._ws_connected:
                await self.refresh_markets()

    async def run(self):
        await self.refresh_markets()

        async def refresh_loop():
            while True:
                await asyncio.sleep(self._refresh_interval)
                await self.refresh_markets()

        await asyncio.gather(
            refresh_loop(),
            self._connect_websocket(),
            self._polling_fallback(),
            return_exceptions=True,
        )

    # ── Lookup helpers ─────────────────────────────────────────────────────────

    def get_snapshot(self, condition_id: str) -> MarketSnapshot | None:
        return self.snapshots.get(condition_id)

    def get_liquid_markets(self) -> list[Market]:
        """Return markets with sufficient depth and acceptable spread."""
        result = []
        for snap in self.snapshots.values():
            if (
                snap.order_book.liquidity_score >= 0.1
                and snap.spread <= config.MAX_SPREAD_FRACTION * 2
                and not snap.is_moving
            ):
                result.append(snap.market)
        return result

    def get_microstructure(self, condition_id: str) -> dict:
        """Return a dict of microstructure metrics for a market."""
        snap = self.snapshots.get(condition_id)
        if not snap:
            return {}
        return {
            "last_price": snap.last_price,
            "momentum": snap.momentum,
            "is_moving": snap.is_moving,
            "spread": snap.spread,
            "bid_depth_usd": snap.order_book.bid_depth_usd,
            "ask_depth_usd": snap.order_book.ask_depth_usd,
            "liquidity_score": snap.liquidity_score,
        }
