"""
Event-Driven Pipeline Orchestrator — V3
(Multi-strategy edition: news + momentum alpha, PortfolioManager routing)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import config
from news_stream import NewsAggregator as NewsStream, NewsEvent
from market_watcher import MarketWatcher
from matcher import match_news_to_markets, update_market_embeddings
from classifier import classify_async
from edge_model import compute_edge
from risk import RiskManager
from metrics import get_tracker
import nlp_processor
import broadcaster
from alpha.momentum_alpha import MomentumAlpha
from alpha.news_alpha import NewsAlpha

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, dry_run: bool | None = None):
        self.dry_run = dry_run if dry_run is not None else config.DRY_RUN
        self.watcher = MarketWatcher()
        self._news_queue: asyncio.Queue = asyncio.Queue()
        self._news_aggregator: Optional[NewsStream] = None
        self.risk = RiskManager.instance()
        self.metrics = get_tracker()
        self._event_count = 0
        self._signal_count = 0
        self._start_time: Optional[float] = None
        self._last_signal_time: dict[str, float] = {}
        # Alpha layer
        self._momentum_alpha = MomentumAlpha()
        self._news_alpha = NewsAlpha()

    async def run(self):
        self._start_time = time.monotonic()
        log.info(f"[pipeline] Starting V3 pipeline {'(DRY RUN)' if self.dry_run else '(LIVE)'}")

        await self.watcher.refresh_markets()
        update_market_embeddings(self.watcher.tracked_markets)
        log.info(f"[pipeline] Loaded {len(self.watcher.tracked_markets)} niche markets")

        self._news_aggregator = NewsStream(self._news_queue)

        results = await asyncio.gather(
            self.watcher.run(),
            self._news_aggregator.run(),
            self._consume_news_queue(),
            self._momentum_alpha.run(self.watcher),   # NEW: background momentum monitor
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.error(f"[pipeline] Top-level task failed: {r}")

    async def _consume_news_queue(self):
        while True:
            event: NewsEvent = await self._news_queue.get()
            qsize = self._news_queue.qsize()
            if qsize > 50:
                log.warning(f"[pipeline] Queue depth={qsize} — events may lag behind news ingestion")
            asyncio.create_task(
                self._handle_event(event),
                name=f"event-{event.source}-{self._event_count}",
            )

    async def _handle_event(self, event: NewsEvent):
        t0 = time.monotonic()
        self._event_count += 1

        if not self.risk.can_trade_daily():
            log.warning("[pipeline] Daily loss limit hit — skipping event")
            return
        if self.risk.in_cooldown():
            log.debug("[pipeline] In cooldown — skipping event")
            return

        headline = event.headline
        source = event.source
        news_latency_ms = getattr(event, "receive_latency_ms", 0)

        from categories import is_relevant_event
        if not is_relevant_event(event, config.SELECTED_CATEGORIES):
            log.debug(f"[pipeline] Skipping (not in categories): {headline[:60]}")
            return

        if config.NLP_ENABLED:
            age_seconds = event.age_seconds()
            nlp = nlp_processor.process(
                headline=headline,
                source=source,
                age_seconds=age_seconds,
                novelty_score=0.5,
            )
            if nlp.relevance < config.NLP_MIN_IMPACT:
                log.debug(f"[pipeline] NLP gate: relevance={nlp.relevance:.3f} < {config.NLP_MIN_IMPACT} — skipping")
                return

        markets = self.watcher.tracked_markets
        if not markets:
            return

        matches = match_news_to_markets(headline, markets)
        if not matches:
            log.debug(f"[pipeline] No market matches for: {headline[:60]}")
            return

        log.info(f"[pipeline] Event: '{headline[:60]}' → {len(matches)} candidate markets (source={source})")

        tasks = [
            self._process_market(
                event=event, market=match.market,
                similarity=match.similarity,
                news_latency_ms=news_latency_ms, t0=t0,
            )
            for match in matches
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error(f"[pipeline] Market processing error: {r}")

        elapsed = int((time.monotonic() - t0) * 1000)
        log.debug(f"[pipeline] Event processed in {elapsed}ms")

    async def _process_market(self, event, market, similarity, news_latency_ms, t0):
        last = self._last_signal_time.get(market.condition_id, 0.0)
        if time.monotonic() - last < config.MARKET_SIGNAL_COOLDOWN_SECONDS:
            log.debug(f"[pipeline] Market cooldown active: {market.question[:50]}")
            return

        cls_start = time.monotonic()
        classification = await classify_async(
            headline=event.headline, market=market, source=event.source,
        )
        cls_latency_ms = int((time.monotonic() - cls_start) * 1000)

        if not classification.is_actionable:
            log.debug(f"[pipeline] Not actionable: {market.question[:50]}")
            return

        ob = await self.watcher.fetch_order_book(market)
        snap = self.watcher.get_snapshot(market.condition_id)

        if snap and snap.is_moving:
            log.info(f"[pipeline] Market already moving, skipping: {market.question[:50]}")
            return

        spread = ob.spread if ob.spread > 0.001 else (snap.spread if snap else 0.05)
        liquidity_score = ob.liquidity_score

        if ob.bid_depth_usd < config.MIN_ORDERBOOK_DEPTH_USD and ob.bid_depth_usd > 0:
            log.debug(f"[pipeline] Insufficient depth (${ob.bid_depth_usd:.0f}), skipping")
            return

        signal = compute_edge(
            market=market, classification=classification,
            liquidity_score=liquidity_score, spread=spread,
            estimated_slippage=snap.estimated_slippage(classification.direction, 25.0) if snap else 0.0,
        )
        if signal is None:
            return

        self._last_signal_time[market.condition_id] = time.monotonic()

        total_elapsed_ms = int((time.monotonic() - t0) * 1000)
        signal.news_latency_ms = news_latency_ms
        signal.classification_latency_ms = cls_latency_ms
        signal.total_latency_ms = total_elapsed_ms
        signal.news_source = event.source
        signal.headlines = event.headline

        if total_elapsed_ms > config.SPEED_TARGET_SECONDS * 1000:
            log.warning(f"[pipeline] Speed target missed: {total_elapsed_ms}ms")

        self._signal_count += 1

        # ── Alpha layer routing ──────────────────────────────────────────────
        from alpha.ensemble import combine
        from portfolio.portfolio_manager import PortfolioManager

        news_alpha_sig = self._news_alpha.to_alpha_signal(signal)
        if news_alpha_sig is None:
            return

        momentum_sig = self._momentum_alpha.get_signal(market.condition_id)
        all_alpha_sigs = [news_alpha_sig]
        if momentum_sig is not None:
            all_alpha_sigs.append(momentum_sig)

        aggregated = combine(all_alpha_sigs)
        result = await PortfolioManager.instance().process_signal_async(aggregated)
        # ── End alpha layer routing ──────────────────────────────────────────

        if result.success and result.filled_size > 0:
            self.risk.on_trade_opened(
                condition_id=market.condition_id,
                category=market.category,
                amount_usd=result.filled_size,
            )
            self.metrics.record_trade(pnl=0.0, ev=signal.ev, latency_ms=result.latency_ms)

        log.info(
            f"[pipeline] ✓ {result.status} {signal.side} ${result.filled_size:.2f} "
            f"'{market.question[:45]}' ev={signal.ev:.3f} "
            f"strategies={aggregated.strategies} latency={result.latency_ms}ms"
        )

        broadcaster.broadcast({
            "type":       "signal",
            "side":       signal.side,
            "market":     market.question,
            "market_id":  market.condition_id,
            "p_market":   round(signal.p_market, 4),
            "p_true":     round(signal.p_true, 4),
            "ev":         round(signal.ev, 4),
            "bet_usd":    result.filled_size,
            "status":     result.status,
            "source":     signal.news_source,
            "headline":   signal.headlines[:120],
            "latency_ms": result.latency_ms,
            "strategies": aggregated.strategies,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })

    def status(self) -> dict:
        elapsed = time.monotonic() - (self._start_time or time.monotonic())
        return {
            "uptime_seconds":    int(elapsed),
            "events_processed":  self._event_count,
            "signals_generated": self._signal_count,
            "tracked_markets":   len(self.watcher.tracked_markets),
            "ws_connected":      self.watcher._ws_connected,
            "risk":              self.risk.status(),
            "metrics":           self.metrics.snapshot().__dict__,
        }


def run_pipeline_v2(dry_run: bool | None = None):
    pipeline = Pipeline(dry_run=dry_run)
    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        log.info("[pipeline] Stopped by user")
