from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import config
from ingestion.news_stream import NewsAggregator as NewsStream, NewsEvent
from ingestion.market_watcher import MarketWatcher
from signal.matcher import match_news_to_markets, update_market_embeddings
from signal.classifier import classify_async
from signal.edge_model import compute_edge
from signal import fast_classifier
from signal.cold_path import get_cold_path_worker, ColdPathJob
from portfolio.risk import RiskManager
from observability.metrics import get_tracker
from signal import nlp_processor
from observability import broadcaster
from alpha.momentum_alpha import MomentumAlpha
from alpha.news_alpha import NewsAlpha
from alpha.ensemble import combine
from portfolio.portfolio_manager import PortfolioManager

log = logging.getLogger(__name__)


class Pipeline:

    def __init__(self, dry_run: bool | None = None):
        if dry_run is not None:
            config.DRY_RUN = dry_run
        self.watcher = MarketWatcher()
        self._news_queue: asyncio.Queue = asyncio.Queue()
        self._news_aggregator: Optional[NewsStream] = None
        self.risk = RiskManager.instance()
        self.metrics = get_tracker()
        self._event_count = 0
        self._signal_count = 0
        self._start_time: Optional[float] = None
        self._last_signal_time: dict[str, float] = {}
        self._momentum_alpha = MomentumAlpha()
        self._news_alpha = NewsAlpha()
        self._cold_path = get_cold_path_worker()

    async def run(self):
        self._start_time = time.monotonic()
        log.info(f"[pipeline] Starting V3 pipeline {'(DRY RUN)' if config.DRY_RUN else '(LIVE)'}")

        await self.watcher.refresh_markets()
        update_market_embeddings(self.watcher.tracked_markets)
        log.info(f"[pipeline] Loaded {len(self.watcher.tracked_markets)} niche markets")

        # Inject the shared watcher so get_unrealized_pnl() reads live prices
        # instead of creating a fresh empty MarketWatcher that has no snapshots.
        from portfolio._paper import get_portfolio
        get_portfolio().set_watcher(self.watcher)
        from execution.execution_engine import ExecutionEngine
        ExecutionEngine.instance().set_watcher(self.watcher)

        self._news_aggregator = NewsStream(self._news_queue)

        results = await asyncio.gather(
            self.watcher.run(),
            self._news_aggregator.run(),
            self._consume_news_queue(),
            self._momentum_alpha.run(self.watcher),
            self._cold_path.run(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.error(f"[pipeline] Top-level task failed: {r}")

    async def _consume_news_queue(self):
        _queue_high = False  # hysteresis flag — warn once, reset when depth drops
        while True:
            event: NewsEvent = await self._news_queue.get()
            qsize = self._news_queue.qsize()
            if qsize > 50 and not _queue_high:
                log.warning(f"[pipeline] Queue depth={qsize} — events lagging behind ingestion")
                _queue_high = True
            elif qsize <= 10 and _queue_high:
                log.info(f"[pipeline] Queue depth recovered ({qsize})")
                _queue_high = False
            # fire-and-forget so one slow classification doesn't block the next event
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

        from ingestion.categories import is_relevant_event
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

    async def _process_market(
        self,
        event: NewsEvent,
        market,
        similarity: float,
        news_latency_ms: int,
        t0: float,
    ):
        last = self._last_signal_time.get(market.condition_id, 0.0)
        if time.monotonic() - last < config.MARKET_SIGNAL_COOLDOWN_SECONDS:
            log.debug(f"[pipeline] Market cooldown active: {market.question[:50]}")
            return

        cls_start = time.monotonic()

        if config.HOT_PATH_ENABLED and fast_classifier.is_trained():
            fast_result = fast_classifier.predict(
                headline=event.headline,
                source=event.source,
                market_yes_price=market.yes_price,
                age_seconds=event.age_seconds(),
            )
            if fast_result.confidence < config.FAST_CLASSIFIER_MIN_CONFIDENCE:
                log.debug(
                    f"[pipeline] hot path filtered: conf={fast_result.confidence:.2f} "
                    f"method={fast_result.method} '{market.question[:40]}'"
                )
                return
            classification = fast_classifier.build_classification(fast_result)
            ob = await self.watcher.fetch_order_book(market)
        else:
            # fetch order book while the LLM is classifying — saves ~200ms per market
            classification, ob = await asyncio.gather(
                classify_async(headline=event.headline, market=market, source=event.source),
                self.watcher.fetch_order_book(market),
            )

        cls_latency_ms = int((time.monotonic() - cls_start) * 1000)

        log.debug(
            f"[pipeline] classify done in {cls_latency_ms}ms: "
            f"dir={classification.direction} actionable={classification.is_actionable} "
            f"'{market.question[:40]}'"
        )

        if not classification.is_actionable:
            log.debug(f"[pipeline] Not actionable: {market.question[:50]}")
            return

        snap = self.watcher.get_snapshot(market.condition_id)

        if snap and snap.is_moving:
            # don't chase — price already ran, slippage will eat the edge
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

        if snap and config.HOT_PATH_ENABLED and hasattr(snap, "yes_price"):
            predicted_move = abs(signal.p_true - market.yes_price)
            actual_move = abs(snap.yes_price - market.yes_price)
            if predicted_move > 0 and actual_move >= predicted_move * config.STALENESS_THRESHOLD:
                log.info(
                    f"[pipeline] Staleness abort: market already moved "
                    f"{actual_move:.3f} of predicted {predicted_move:.3f} — '{market.question[:45]}'"
                )
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

        news_alpha_sig = self._news_alpha.to_alpha_signal(signal)
        if news_alpha_sig is None:
            # edge didn't clear NewsAlpha threshold, but still broadcast so the UI feed stays live
            broadcaster.broadcast({
                "type":       "signal",
                "side":       signal.side,
                "market":     market.question,
                "market_id":  market.condition_id,
                "p_market":   round(signal.p_market, 4),
                "p_true":     round(signal.p_true, 4),
                "ev":         round(signal.ev, 4),
                "bet_usd":    0.0,
                "status":     "filtered",
                "source":     signal.news_source,
                "headline":   signal.headlines[:120],
                "latency_ms": total_elapsed_ms,
                "strategies": ["news"],
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            })
            return

        momentum_sig = self._momentum_alpha.get_signal(market.condition_id)
        all_alpha_sigs = [news_alpha_sig]
        if momentum_sig is not None:
            all_alpha_sigs.append(momentum_sig)

        aggregated = combine(all_alpha_sigs)
        result = await PortfolioManager.instance().process_signal_async(aggregated)

        # Position slot was reserved atomically by risk_engine.validate() via
        # try_open_position(). Do NOT call on_trade_opened() here — that would
        # double-count the position and hit the limit after half the allowed trades.
        if result.success and result.filled_size > 0:
            self.metrics.record_trade(pnl=0.0, ev=signal.ev, latency_ms=result.latency_ms)

        if config.HOT_PATH_ENABLED:
            is_loss = result.filled_size == 0 or result.status in ("error", "rejected", "skipped")
            fast_conf = classification.confidence if config.HOT_PATH_ENABLED else 0.0
            self._cold_path.submit(ColdPathJob(
                headline=event.headline,
                source=event.source,
                market_id=market.condition_id,
                market_question=market.question,
                yes_price=market.yes_price,
                fast_confidence=fast_conf,
                is_loss_trade=is_loss,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

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
    import signal as _signal

    pipeline = Pipeline(dry_run=dry_run)

    def _handle_sigterm(signum, frame):
        log.info("[pipeline] SIGTERM received — shutting down")
        raise KeyboardInterrupt

    _signal.signal(_signal.SIGTERM, _handle_sigterm)

    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        log.info("[pipeline] Stopped by user")
