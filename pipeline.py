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
from observability.tracer import (
    create_trace, remove_trace, generate_news_id,
    MarketMatchTrace, get_dlq, DeadLetter, SignalStage,
)
from observability.rejection import RejectionReason
from observability.stage_timer import get_stage_timer
from observability.health_monitor import HealthMonitor
from execution.live_safety import get_live_safety, LIVE_CONSTRAINTS
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
        self._health_monitor = HealthMonitor(self)
        self._shutdown = asyncio.Event()
        self._child_tasks: set[asyncio.Task] = set()

    async def run(self):
        self._start_time = time.monotonic()
        log.info(f"[pipeline] Starting V3 pipeline {'(DRY RUN)' if config.DRY_RUN else '(LIVE)'}")

        await self.watcher.refresh_markets()
        update_market_embeddings(self.watcher.tracked_markets)
        log.info(f"[pipeline] Loaded {len(self.watcher.tracked_markets)} niche markets")

        from portfolio._paper import get_portfolio
        get_portfolio().set_watcher(self.watcher)
        from execution.execution_engine import ExecutionEngine
        ExecutionEngine.instance().set_watcher(self.watcher)

        self._news_aggregator = NewsStream(self._news_queue)

        from observability.broadcaster import start_heartbeat
        start_heartbeat(self)

        from execution.task_supervisor import get_task_supervisor
        from execution.reconciliation import get_reconciliation_engine
        from execution.settlement import get_settlement_engine
        from execution.market_sync import get_market_synchronizer

        supervisor = get_task_supervisor()
        supervisor.register("reconciliation", get_reconciliation_engine().run, stall_threshold=600)
        supervisor.register("settlement", get_settlement_engine().run, stall_threshold=600)
        supervisor.register("market_sync", get_market_synchronizer().run, stall_threshold=600)

        bg_tasks = [
            asyncio.create_task(self.watcher.run(), name="watcher"),
            asyncio.create_task(self._news_aggregator.run(), name="news_aggregator"),
            asyncio.create_task(self._consume_news_queue(), name="news_consumer"),
            asyncio.create_task(self._momentum_alpha.run(self.watcher), name="momentum_alpha"),
            asyncio.create_task(self._cold_path.run(), name="cold_path"),
            asyncio.create_task(self._health_monitor.run(), name="health_monitor"),
            asyncio.create_task(
                get_reconciliation_engine().run(self), name="reconciliation",
            ),
            asyncio.create_task(
                get_settlement_engine().run(self), name="settlement",
            ),
            asyncio.create_task(
                get_market_synchronizer().run(self), name="market_sync",
            ),
            asyncio.create_task(supervisor.monitor_loop(), name="task_monitor"),
        ]
        shutdown_waiter = asyncio.create_task(self._shutdown.wait(), name="shutdown_waiter")

        try:
            done, _ = await asyncio.wait(
                bg_tasks + [shutdown_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                if t is not shutdown_waiter and not t.cancelled():
                    exc = t.exception()
                    if exc is not None:
                        log.error("[pipeline] Background task %s failed: %s", t.get_name(), exc)
        finally:
            from observability.broadcaster import stop_heartbeat
            stop_heartbeat()
            self._shutdown.set()
            shutdown_waiter.cancel()
            for t in bg_tasks:
                t.cancel()
            await asyncio.gather(*bg_tasks, return_exceptions=True)
            for t in list(self._child_tasks):
                t.cancel()
            if self._child_tasks:
                await asyncio.gather(*self._child_tasks, return_exceptions=True)
            log.info("[pipeline] Shutdown complete")

    def signal_shutdown(self):
        self._shutdown.set()

    async def _consume_news_queue(self):
        _queue_high = False
        while not self._shutdown.is_set():
            try:
                event: NewsEvent = await asyncio.wait_for(self._news_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            qsize = self._news_queue.qsize()
            if qsize > 50 and not _queue_high:
                log.warning(f"[pipeline] Queue depth={qsize} — events lagging behind ingestion")
                _queue_high = True
            elif qsize <= 10 and _queue_high:
                log.info(f"[pipeline] Queue depth recovered ({qsize})")
                _queue_high = False
            task = asyncio.create_task(
                self._handle_event(event),
                name=f"event-{event.source}-{self._event_count}",
            )
            self._child_tasks.add(task)
            task.add_done_callback(self._child_tasks.discard)

    async def _handle_event(self, event: NewsEvent):
        if self._shutdown.is_set():
            return

        # Live safety gate — hard stop check
        safety = get_live_safety()
        if safety.is_hard_stopped():
            return

        t0 = time.monotonic()
        self._event_count += 1

        news_id = generate_news_id()
        trace = create_trace(
            headline=event.headline,
            source=event.source,
            news_id=news_id,
            source_id=event.source,
        )
        _log_trace_safe(trace.trace_id, event.headline, event.source,
                        news_id=news_id, source_id=event.source)
        self._health_monitor.feed_ingestion()

        timer = get_stage_timer()

        try:
            if not self.risk.can_trade_daily():
                trace.reject(
                    RejectionReason.DAILY_LOSS_CAP_HIT,
                    detail="Daily loss limit hit before event processing",
                    snapshot=config.get_effective_config(),
                )
                _persist_trace_safe(trace)
                broadcaster.broadcast({
                    "type": "signal_rejected", "trace_id": trace.trace_id,
                    "reason": "DAILY_LOSS_CAP_HIT", "severity": "SOFT_REJECT",
                    "subsystem": "risk", "timestamp": time.time(),
                })
                remove_trace(trace.trace_id)
                return
            if self.risk.in_cooldown():
                trace.reject(
                    RejectionReason.COOLDOWN_ACTIVE,
                    detail="RiskManager cooldown active",
                    snapshot=config.get_effective_config(),
                )
                _persist_trace_safe(trace)
                broadcaster.broadcast({
                    "type": "signal_rejected", "trace_id": trace.trace_id,
                    "reason": "COOLDOWN_ACTIVE", "severity": "SOFT_REJECT",
                    "subsystem": "risk", "timestamp": time.time(),
                })
                remove_trace(trace.trace_id)
                return

            headline = event.headline
            source = event.source
            news_latency_ms = getattr(event, "receive_latency_ms", 0)

            from ingestion.categories import is_relevant_event
            if not is_relevant_event(event, config.SELECTED_CATEGORIES):
                trace.reject(
                    RejectionReason.CATEGORY_NOT_SELECTED,
                    detail="Event headline not in selected categories",
                    snapshot=config.get_effective_config(),
                )
                _persist_trace_safe(trace)
                remove_trace(trace.trace_id)
                return

            if config.NLP_ENABLED:
                age_seconds = event.age_seconds()
                with timer.measure(trace.trace_id, "NLP", critical=False):
                    nlp = nlp_processor.process(
                        headline=headline,
                        source=source,
                        age_seconds=age_seconds,
                        novelty_score=0.5,
                    )
                trace.transition(SignalStage.NLP_PROCESSED)
                # Gate on raw IMPACT score, not time-decayed relevance.
                # Temporal decay reduces sizing/urgency, not signal eligibility.
                # Without this, RSS feeds (1-6h old) are all killed by exp(-0.05*age).
                impact_gate_value = nlp.impact_score
                if impact_gate_value < config.NLP_MIN_IMPACT:
                    trace.reject(
                        RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
                        threshold=config.NLP_MIN_IMPACT,
                        actual=round(impact_gate_value, 4),
                        snapshot=config.get_effective_config(),
                        detail=f"NLP impact {impact_gate_value:.3f} < {config.NLP_MIN_IMPACT}",
                    )
                    _persist_trace_safe(trace)
                    broadcaster.broadcast({
                        "type": "signal_rejected", "trace_id": trace.trace_id,
                        "reason": "NLP_IMPACT_BELOW_THRESHOLD", "severity": "HARD_REJECT",
                        "subsystem": "nlp", "threshold": config.NLP_MIN_IMPACT,
                        "actual": round(nlp.relevance, 4), "timestamp": time.time(),
                    })
                    remove_trace(trace.trace_id)
                    return

            markets = self.watcher.tracked_markets
            if not markets:
                remove_trace(trace.trace_id)
                return

            try:
                with timer.measure(trace.trace_id, "MATCHER", critical=False):
                    matches = match_news_to_markets(headline, markets)
            except Exception as e:
                log.warning(f"[pipeline] Matcher failed for '{headline[:60]}': {e}")
                trace.reject(
                    RejectionReason.PIPELINE_EXCEPTION,
                    detail=f"Matcher exception: {e}",
                    snapshot=config.get_effective_config(),
                )
                _persist_trace_safe(trace)
                remove_trace(trace.trace_id)
                return

            trace.transition(SignalStage.MARKET_MATCHED)

            if matches:
                top_match = matches[0]
                mt = MarketMatchTrace(
                    trace_id=trace.trace_id,
                    market_id=top_match.market.condition_id,
                    market_question=top_match.market.question,
                    similarity_score=top_match.similarity,
                    match_method=top_match.match_method,
                    rank_position=1,
                    embedding_distance=1.0 - top_match.similarity,
                    rejected_alternatives=[
                        {"market_id": m.market.condition_id, "score": m.similarity,
                         "reason": "below_top_k" if i >= config.MATCHER_TOP_K else "lower_score"}
                        for i, m in enumerate(matches[config.MATCHER_TOP_K:])
                    ],
                )
                trace.set_match_trace(mt)
                trace.context.market_id = top_match.market.condition_id
            else:
                trace.reject(
                    RejectionReason.NO_MARKET_MATCHES,
                    threshold=config.MATCHER_MIN_SIMILARITY,
                    snapshot=config.get_effective_config(),
                    detail=f"No market matches for headline",
                )
                _persist_trace_safe(trace)
                broadcaster.broadcast({
                    "type": "signal_rejected", "trace_id": trace.trace_id,
                    "reason": "NO_MARKET_MATCHES", "severity": "HARD_REJECT",
                    "subsystem": "matcher", "threshold": config.MATCHER_MIN_SIMILARITY,
                    "timestamp": time.time(),
                })
                remove_trace(trace.trace_id)
                return

            log.info(f"[pipeline] Event: '{headline[:60]}' -> {len(matches)} candidate markets (source={source})")

            tasks = [
                self._process_market(
                    event=event, market=match.market,
                    similarity=match.similarity,
                    news_latency_ms=news_latency_ms, t0=t0,
                    parent_trace_id=trace.trace_id,
                )
                for match in matches
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    log.error(f"[pipeline] Market processing error: {r}")

            self._health_monitor.feed_signal()

            elapsed = int((time.monotonic() - t0) * 1000)
            log.debug(f"[pipeline] Event processed in {elapsed}ms")

            _persist_trace_safe(trace)
            remove_trace(trace.trace_id)

        except Exception as e:
            dl = DeadLetter(
                payload={"headline": event.headline, "source": event.source},
                exception=repr(e),
                subsystem="pipeline._handle_event",
                trace_id=trace.trace_id if 'trace' in locals() else None,
            )
            get_dlq().push(dl)
            try:
                from observability.logger import log_dead_letter
                log_dead_letter(dl.dlq_id, dl.trace_id, dl.subsystem, dl.exception, dl.payload)
            except Exception:
                pass
            log.error("[pipeline] Event processing exception (dlq=%s): %s", dl.dlq_id, e)

    async def _process_market(
        self,
        event: NewsEvent,
        market,
        similarity: float,
        news_latency_ms: int,
        t0: float,
        parent_trace_id: str | None = None,
    ):
        if self._shutdown.is_set():
            return
        child_trace = create_trace(
            headline=event.headline,
            source=event.source,
            parent_trace_id=parent_trace_id,
        )
        child_trace.context.market_id = market.condition_id
        timer = get_stage_timer()

        try:
            last = self._last_signal_time.get(market.condition_id, 0.0)
            if time.monotonic() - last < config.MARKET_SIGNAL_COOLDOWN_SECONDS:
                child_trace.reject(
                    RejectionReason.MARKET_COOLDOWN_ACTIVE,
                    detail=f"Market cooldown active: {market.question[:50]}",
                    snapshot=config.get_effective_config(),
                )
                _persist_trace_safe(child_trace)
                remove_trace(child_trace.trace_id)
                return

            cls_start = time.monotonic()

            if config.HOT_PATH_ENABLED and fast_classifier.is_trained():
                with timer.measure(child_trace.trace_id, "CLASSIFIER", critical=False):
                    fast_result = fast_classifier.predict(
                        headline=event.headline,
                        source=event.source,
                        market_yes_price=market.yes_price,
                        age_seconds=event.age_seconds(),
                    )
                if fast_result.confidence < config.FAST_CLASSIFIER_MIN_CONFIDENCE:
                    child_trace.reject(
                        RejectionReason.CLASSIFIER_HOT_PATH_FILTERED,
                        threshold=config.FAST_CLASSIFIER_MIN_CONFIDENCE,
                        actual=round(fast_result.confidence, 4),
                        snapshot=config.get_effective_config(),
                        detail=f"Hot path filtered: conf={fast_result.confidence:.2f}",
                    )
                    _persist_trace_safe(child_trace)
                    broadcaster.broadcast({
                        "type": "signal_rejected", "trace_id": child_trace.trace_id,
                        "reason": "CLASSIFIER_HOT_PATH_FILTERED", "severity": "HARD_REJECT",
                        "subsystem": "classifier", "threshold": config.FAST_CLASSIFIER_MIN_CONFIDENCE,
                        "actual": round(fast_result.confidence, 4), "timestamp": time.time(),
                    })
                    remove_trace(child_trace.trace_id)
                    return
                classification = fast_classifier.build_classification(fast_result)
                ob = await self.watcher.fetch_order_book(market)
            else:
                with timer.measure(child_trace.trace_id, "CLASSIFIER", critical=False):
                    classification, ob = await asyncio.gather(
                        classify_async(headline=event.headline, market=market, source=event.source),
                        self.watcher.fetch_order_book(market),
                    )

            child_trace.transition(SignalStage.SCORED)

            cls_latency_ms = int((time.monotonic() - cls_start) * 1000)

            log.debug(
                f"[pipeline] classify done in {cls_latency_ms}ms: "
                f"dir={classification.direction} actionable={classification.is_actionable} "
                f"'{market.question[:40]}'"
            )

            if not classification.is_actionable:
                child_trace.reject(
                    RejectionReason.CLASSIFIER_NOT_ACTIONABLE,
                    threshold=config.MIN_CONFIDENCE,
                    actual=round(classification.confidence, 4),
                    snapshot=config.get_effective_config(),
                    detail=f"Not actionable: conf={classification.confidence:.2f} mat={classification.materiality:.2f}",
                )
                _persist_trace_safe(child_trace)
                remove_trace(child_trace.trace_id)
                return

            snap = self.watcher.get_snapshot(market.condition_id)

            if snap and snap.is_moving:
                child_trace.reject(
                    RejectionReason.MOMENTUM_ALREADY_MOVING,
                    threshold=config.MOMENTUM_THRESHOLD,
                    actual=round(abs(snap.momentum), 4),
                    snapshot=config.get_effective_config(),
                    detail=f"Market already moving: momentum={snap.momentum:.4f}",
                )
                _persist_trace_safe(child_trace)
                remove_trace(child_trace.trace_id)
                return

            spread = ob.spread if ob.spread > 0.001 else (snap.spread if snap else 0.05)
            liquidity_score = ob.liquidity_score

            if ob.bid_depth_usd < config.MIN_ORDERBOOK_DEPTH_USD and ob.bid_depth_usd > 0:
                child_trace.reject(
                    RejectionReason.INSUFFICIENT_DEPTH,
                    threshold=config.MIN_ORDERBOOK_DEPTH_USD,
                    actual=round(ob.bid_depth_usd, 2),
                    snapshot=config.get_effective_config(),
                    detail=f"Insufficient depth: ${ob.bid_depth_usd:.0f}",
                )
                _persist_trace_safe(child_trace)
                remove_trace(child_trace.trace_id)
                return

            with timer.measure(child_trace.trace_id, "EDGE", critical=False):
                signal = compute_edge(
                    market=market, classification=classification,
                    liquidity_score=liquidity_score, spread=spread,
                    estimated_slippage=snap.estimated_slippage(classification.direction, 25.0) if snap else 0.0,
                )

            child_trace.transition(SignalStage.VALIDATED)

            if signal is None:
                child_trace.reject(
                    RejectionReason.EDGE_EV_BELOW_THRESHOLD,
                    threshold=config.EDGE_THRESHOLD,
                    snapshot=config.get_effective_config(),
                    detail="Edge model returned None (EV below threshold or gate failed)",
                )
                _persist_trace_safe(child_trace)
                remove_trace(child_trace.trace_id)
                return

            if snap and config.HOT_PATH_ENABLED and hasattr(snap, "yes_price"):
                predicted_move = abs(signal.p_true - market.yes_price)
                actual_move = abs(snap.yes_price - market.yes_price)
                if predicted_move > 0 and actual_move >= predicted_move * config.STALENESS_THRESHOLD:
                    child_trace.reject(
                        RejectionReason.STALENESS_ABORT,
                        threshold=config.STALENESS_THRESHOLD,
                        actual=round(actual_move / max(predicted_move, 0.0001), 4),
                        snapshot=config.get_effective_config(),
                        detail=f"Staleness abort: market moved {actual_move:.3f} of predicted {predicted_move:.3f}",
                    )
                    _persist_trace_safe(child_trace)
                    remove_trace(child_trace.trace_id)
                    return

            self._last_signal_time[market.condition_id] = time.monotonic()

            child_trace.transition(SignalStage.SIZED)

            total_elapsed_ms = int((time.monotonic() - t0) * 1000)
            signal.news_latency_ms = news_latency_ms
            signal.classification_latency_ms = cls_latency_ms
            signal.total_latency_ms = total_elapsed_ms
            signal.news_source = event.source
            signal.headlines = event.headline

            if total_elapsed_ms > config.SPEED_TARGET_SECONDS * 1000:
                log.warning(f"[pipeline] Speed target missed: {total_elapsed_ms}ms")

            self._signal_count += 1
            self._health_monitor.feed_signal()

            news_alpha_sig = self._news_alpha.to_alpha_signal(signal)
            if news_alpha_sig is None:
                broadcaster.broadcast({
                    "type":       "signal",
                    "trace_id":   child_trace.trace_id,
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
                child_trace.transition(SignalStage.REJECTED)
                _persist_trace_safe(child_trace)
                remove_trace(child_trace.trace_id)
                return

            momentum_sig = self._momentum_alpha.get_signal(market.condition_id)
            all_alpha_sigs = [news_alpha_sig]
            if momentum_sig is not None:
                all_alpha_sigs.append(momentum_sig)

            aggregated = combine(all_alpha_sigs)

            # Live safety gate: check constraints before execution
            if not config.DRY_RUN:
                safety = get_live_safety()
                can_trade, reason = safety.can_trade()
                if not can_trade:
                    log.warning("[pipeline] Live safety blocked: %s", reason)
                    child_trace.reject(
                        RejectionReason.COOLDOWN_ACTIVE,
                        detail=f"Live safety: {reason}",
                        snapshot=config.get_effective_config(),
                    )
                    _persist_trace_safe(child_trace)
                    remove_trace(child_trace.trace_id)
                    return

                # Manual confirmation mode
                if LIVE_CONSTRAINTS.get("MANUAL_CONFIRM", True):
                    safety.propose_trade(child_trace, signal, market)
                    log.warning("[pipeline] Trade proposed for manual review: %s", child_trace.trace_id)
                    # Trade is NOT executed until approved via API or CLI
                    remove_trace(child_trace.trace_id)
                    return

            result = await PortfolioManager.instance().process_signal_async(aggregated)

            if result.success and result.filled_size > 0:
                self.metrics.record_trade(pnl=0.0, ev=signal.ev, latency_ms=result.latency_ms)
                child_trace.transition(SignalStage.EXECUTED)
                child_trace.context.execution_id = str(result.trade_id) if result.trade_id else None
                child_trace.context.position_id = result.trade_id

            if config.HOT_PATH_ENABLED:
                is_loss = result.status in ("error_order_failed", "rejected", "error_no_clob_client",
                                             "error_no_token", "error_client_init", "error_no_auth")
                self._cold_path.submit(ColdPathJob(
                    headline=event.headline,
                    source=event.source,
                    market_id=market.condition_id,
                    market_question=market.question,
                    yes_price=market.yes_price,
                    fast_confidence=classification.confidence,
                    is_loss_trade=is_loss,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))

            elif not config.HOT_PATH_ENABLED and classification.is_actionable:
                self._cold_path.submit(ColdPathJob(
                    headline=event.headline,
                    source=event.source,
                    market_id=market.condition_id,
                    market_question=market.question,
                    yes_price=market.yes_price,
                    fast_confidence=classification.confidence,
                    is_loss_trade=result.filled_size == 0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))

            log.info(
                f"[pipeline] ok {result.status} {signal.side} ${result.filled_size:.2f} "
                f"'{market.question[:45]}' ev={signal.ev:.3f} "
                f"strategies={aggregated.strategies} latency={result.latency_ms}ms"
            )

            broadcaster.broadcast({
                "type":       "signal",
                "trace_id":   child_trace.trace_id,
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

            _persist_trace_safe(child_trace)
            remove_trace(child_trace.trace_id)

        except Exception as e:
            dl = DeadLetter(
                payload={"headline": event.headline, "market_id": market.condition_id},
                exception=repr(e),
                subsystem="pipeline._process_market",
                trace_id=child_trace.trace_id if 'child_trace' in locals() else None,
            )
            get_dlq().push(dl)
            try:
                from observability.logger import log_dead_letter
                log_dead_letter(dl.dlq_id, dl.trace_id, dl.subsystem, dl.exception, dl.payload)
            except Exception:
                pass
            log.error("[pipeline] Market processing exception (dlq=%s): %s", dl.dlq_id, e)

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

    def get_source_stats(self) -> dict:
        if self._news_aggregator is None:
            return {"error": "news aggregator not started yet"}
        return dict(self._news_aggregator.stats)


def _persist_trace_safe(trace):
    """Flush trace to SQLite. Never raises."""
    try:
        from observability.logger import update_trace
        import json as _json
        row = trace.finalize()
        rejection = trace.rejection
        update_trace(
            trace.trace_id,
            final_stage=row["final_stage"],
            final_status=row["final_status"],
            rejection_reason=row["rejection_reason"],
            rejection_severity=row["rejection_severity"],
            rejection_detail=_json.dumps({
                "threshold": rejection.threshold_value if rejection else None,
                "actual": rejection.actual_value if rejection else None,
                "subsystem": rejection.subsystem if rejection else None,
                "detail": rejection.detail if rejection else None,
                "snapshot": rejection.threshold_snapshot if rejection else {},
            }) if rejection else None,
            match_trace=_json.dumps({
                "trace_id": trace.match_trace.trace_id,
                "market_id": trace.match_trace.market_id,
                "market_question": trace.match_trace.market_question,
                "similarity_score": trace.match_trace.similarity_score,
                "matched_entities": trace.match_trace.matched_entities,
                "keywords_hit": trace.match_trace.keywords_hit,
                "embedding_distance": trace.match_trace.embedding_distance,
                "rank_position": trace.match_trace.rank_position,
                "match_method": trace.match_trace.match_method,
                "rejected_alternatives": trace.match_trace.rejected_alternatives,
            }) if trace.match_trace else None,
            stage_timings=_json.dumps(trace.stage_timings) if trace.stage_timings else None,
            total_latency_ms=trace.total_latency_ms,
            market_id=trace.context.market_id,
            execution_id=trace.context.execution_id,
            position_id=trace.context.position_id,
        )
    except Exception:
        pass


def _log_trace_safe(trace_id, headline, source, **kwargs):
    """Fire-and-forget trace persistence. Never raises."""
    try:
        from observability.logger import log_trace
        log_trace(trace_id, headline, source, **kwargs)
    except Exception:
        pass


def run_pipeline_v2(dry_run: bool | None = None):
    import signal as _signal

    pipeline = Pipeline(dry_run=dry_run)

    def _handle_sigterm(signum, frame):
        log.info("[pipeline] SIGTERM received — initiating shutdown")
        pipeline.signal_shutdown()

    _signal.signal(_signal.SIGTERM, _handle_sigterm)

    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        log.info("[pipeline] Stopped by user")
        pipeline.signal_shutdown()
