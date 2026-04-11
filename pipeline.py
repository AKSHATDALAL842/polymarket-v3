"""
Event-Driven Pipeline Orchestrator — V3

Architecture:
  news_stream → matcher (semantic) → classifier (multi-pass) → edge_model
             → microstructure check → risk check → executor → metrics

Design principles:
  - Sub-5s reaction time from news ingestion to order submission
  - Non-blocking: market watcher and news stream run as concurrent tasks
  - Adversarial: skip markets already moving (momentum gate)
  - Measured: every trade has full latency accounting
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
from executor import execute_trade_async
from risk import RiskManager
from metrics import get_tracker
import nlp_processor
import broadcaster

log = logging.getLogger(__name__)


class Pipeline:
    """
    V3 event-driven trading pipeline.

    Component lifecycle:
      1. MarketWatcher starts in background — maintains live snapshots
      2. NewsStream connects to Twitter/Telegram/RSS
      3. On each NewsEvent: run the full signal chain
      4. All I/O is async; classification and matching run concurrently where possible
    """

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
        # Per-market cooldown: condition_id → monotonic time of last signal
        self._last_signal_time: dict[str, float] = {}

    # ── Main entry point ───────────────────────────────────────────────────────

    async def run(self):
        """Start all background tasks and begin processing news events."""
        self._start_time = time.monotonic()
        log.info(
            f"[pipeline] Starting V3 pipeline "
            f"{'(DRY RUN)' if self.dry_run else '(LIVE)'}"
        )

        # Wait for initial market list before starting news
        await self.watcher.refresh_markets()
        update_market_embeddings(self.watcher.tracked_markets)
        log.info(f"[pipeline] Loaded {len(self.watcher.tracked_markets)} niche markets")

        # NewsAggregator writes into a shared queue
        self._news_aggregator = NewsStream(self._news_queue)

        # Run watcher + news aggregator + event consumer concurrently
        results = await asyncio.gather(
            self.watcher.run(),
            self._news_aggregator.run(),
            self._consume_news_queue(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.error(f"[pipeline] Top-level task failed: {r}")

    async def _consume_news_queue(self):
        """Drain the news queue and dispatch each event as a concurrent task."""
        while True:
            event: NewsEvent = await self._news_queue.get()
            qsize = self._news_queue.qsize()
            if qsize > 50:
                log.warning(f"[pipeline] Queue depth={qsize} — events may lag behind news ingestion")
            asyncio.create_task(
                self._handle_event(event),
                name=f"event-{event.source}-{self._event_count}",
            )

    # ── Event handler ──────────────────────────────────────────────────────────

    async def _handle_event(self, event: NewsEvent):
        """
        Full signal chain for one news event.
        Runs concurrently with other events (via create_task).
        """
        t0 = time.monotonic()
        self._event_count += 1

        # Risk pre-check: abort early if we can't trade at all
        if not self.risk.can_trade_daily():
            log.warning("[pipeline] Daily loss limit hit — skipping event")
            return
        if self.risk.in_cooldown():
            log.debug("[pipeline] In cooldown — skipping event")
            return

        headline = event.headline
        source = event.source
        news_latency_ms = getattr(event, "receive_latency_ms", 0)

        # Step 0: NLP enrichment — NER, sentiment, impact score, temporal decay
        if config.NLP_ENABLED:
            age_seconds = event.age_seconds()
            nlp = nlp_processor.process(
                headline=headline,
                source=source,
                age_seconds=age_seconds,
                novelty_score=0.5,   # will be refined by classifier pass
            )
            if nlp.relevance < config.NLP_MIN_IMPACT:
                log.debug(
                    f"[pipeline] NLP gate: relevance={nlp.relevance:.3f} < {config.NLP_MIN_IMPACT} "
                    f"— skipping '{headline[:50]}'"
                )
                return
            log.debug(
                f"[pipeline] NLP: cat={nlp.category} sent={nlp.sentiment_polarity:+.2f} "
                f"impact={nlp.impact_score:.2f} relevance={nlp.relevance:.2f} "
                f"entities={[e.text for e in nlp.entities[:3]]}"
            )

        # Step 1: Find candidate markets (semantic search)
        markets = self.watcher.tracked_markets
        if not markets:
            return

        matches = match_news_to_markets(headline, markets)
        if not matches:
            log.debug(f"[pipeline] No market matches for: {headline[:60]}")
            return

        log.info(
            f"[pipeline] Event: '{headline[:60]}' → "
            f"{len(matches)} candidate markets (source={source})"
        )

        # Step 2: For each matched market, run classification + edge in parallel
        tasks = [
            self._process_market(
                event=event,
                market=match.market,
                similarity=match.similarity,
                news_latency_ms=news_latency_ms,
                t0=t0,
            )
            for match in matches
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error(f"[pipeline] Market processing error: {r}")

        elapsed = int((time.monotonic() - t0) * 1000)
        log.debug(f"[pipeline] Event processed in {elapsed}ms")

    async def _process_market(
        self,
        event: NewsEvent,
        market,
        similarity: float,
        news_latency_ms: int,
        t0: float,
    ):
        """Process one (event, market) pair: classify → edge → microstructure → execute."""

        # Per-market cooldown: skip if we already signalled this market recently
        last = self._last_signal_time.get(market.condition_id, 0.0)
        if time.monotonic() - last < config.MARKET_SIGNAL_COOLDOWN_SECONDS:
            log.debug(f"[pipeline] Market cooldown active, skipping: {market.question[:50]}")
            return

        # Step 2a: Classification (3-pass LLM voting)
        cls_start = time.monotonic()
        classification = await classify_async(
            headline=event.headline,
            market=market,
            source=event.source,
        )
        cls_latency_ms = int((time.monotonic() - cls_start) * 1000)

        if not classification.is_actionable:
            log.debug(
                f"[pipeline] Not actionable: {market.question[:50]} "
                f"dir={classification.direction} conf={classification.confidence:.2f}"
            )
            return

        # Step 2b: Fetch live order book for microstructure data
        ob = await self.watcher.fetch_order_book(market)
        snap = self.watcher.get_snapshot(market.condition_id)

        # Microstructure gates
        if snap and snap.is_moving:
            log.info(
                f"[pipeline] Market already moving (momentum={snap.momentum:.3f}), skipping: "
                f"{market.question[:50]}"
            )
            return

        spread = ob.spread if ob.spread > 0.001 else (snap.spread if snap else 0.05)
        liquidity_score = ob.liquidity_score

        if ob.bid_depth_usd < config.MIN_ORDERBOOK_DEPTH_USD and ob.bid_depth_usd > 0:
            log.debug(f"[pipeline] Insufficient depth (${ob.bid_depth_usd:.0f}), skipping")
            return

        # Step 2c: Edge calculation
        signal = compute_edge(
            market=market,
            classification=classification,
            liquidity_score=liquidity_score,
            spread=spread,
            estimated_slippage=snap.estimated_slippage(classification.direction, 25.0) if snap else 0.0,
        )

        if signal is None:
            return

        # Record signal time for cooldown
        self._last_signal_time[market.condition_id] = time.monotonic()

        # Attach latency accounting
        total_elapsed_ms = int((time.monotonic() - t0) * 1000)
        signal.news_latency_ms = news_latency_ms
        signal.classification_latency_ms = cls_latency_ms
        signal.total_latency_ms = total_elapsed_ms
        signal.news_source = event.source
        signal.headlines = event.headline

        if total_elapsed_ms > config.SPEED_TARGET_SECONDS * 1000:
            log.warning(
                f"[pipeline] Speed target missed: {total_elapsed_ms}ms "
                f"(target={int(config.SPEED_TARGET_SECONDS * 1000)}ms)"
            )

        self._signal_count += 1

        # Step 2d: Execute
        result = await execute_trade_async(signal)

        # Step 2e: Update risk state and metrics
        if result.success and result.filled_size > 0:
            self.risk.on_trade_opened(
                condition_id=market.condition_id,
                category=market.category,
                amount_usd=result.filled_size,
            )
            self.metrics.record_trade(
                pnl=0.0,         # PnL unknown until resolution
                ev=signal.ev,
                latency_ms=result.latency_ms,
            )

        log.info(
            f"[pipeline] ✓ {result.status} {signal.side} ${result.filled_size:.2f} "
            f"'{market.question[:45]}' ev={signal.ev:.3f} "
            f"latency={result.latency_ms}ms"
        )

        # Broadcast to WebSocket subscribers
        broadcaster.broadcast({
            "type": "signal",
            "side": signal.side,
            "market": market.question,
            "market_id": market.condition_id,
            "p_market": round(signal.p_market, 4),
            "p_true": round(signal.p_true, 4),
            "ev": round(signal.ev, 4),
            "bet_usd": result.filled_size,
            "status": result.status,
            "source": signal.news_source,
            "headline": signal.headlines[:120],
            "latency_ms": result.latency_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ── Status ─────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        elapsed = time.monotonic() - (self._start_time or time.monotonic())
        return {
            "uptime_seconds": int(elapsed),
            "events_processed": self._event_count,
            "signals_generated": self._signal_count,
            "tracked_markets": len(self.watcher.tracked_markets),
            "ws_connected": self.watcher._ws_connected,
            "risk": self.risk.status(),
            "metrics": self.metrics.snapshot().__dict__,
        }


def run_pipeline_v2(dry_run: bool | None = None):
    """Synchronous entry point called by cli.py watch command."""
    pipeline = Pipeline(dry_run=dry_run)
    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        log.info("[pipeline] Stopped by user")
