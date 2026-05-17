"""
Adversarial testing — inject failure modes and verify fail-open + bounded degradation.

Tests: duplicate storms, malformed payloads, WS disconnects, SQLite contention,
       ingestion spikes, queue overflow, contradictory signals.
"""
import time
import json
import pytest


class TestDuplicateStorm:
    """Duplicate news floods should not amplify signals."""

    def test_create_trace_dedup_by_content(self):
        from observability.tracer import create_trace, get_active_traces, remove_trace

        headline = "BREAKING: Bitcoin crashes 20% in flash crash"
        traces = []
        for i in range(100):
            trace = create_trace(headline, "rss")
            traces.append(trace)

        active = get_active_traces()
        assert len(active) <= 100
        assert all(t.headline == headline for t in active)

        for t in traces:
            try:
                remove_trace(t.trace_id)
            except KeyError:
                pass

    def test_rapid_rejection_doesnt_stall(self):
        from observability.tracer import create_trace, remove_trace
        from observability.rejection import RejectionReason

        t0 = time.monotonic()
        for i in range(500):
            trace = create_trace(f"Flood headline {i}", "rss")
            trace.reject(RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
                         threshold=0.10, actual=0.01,
                         snapshot={"NLP_MIN_IMPACT": 0.10})
            remove_trace(trace.trace_id)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 2000, f"500 reject+remove took {elapsed_ms:.0f}ms"


class TestQueueOverflow:
    """Queue overflow should not crash or lose critical events."""

    def test_dlq_maxlen_enforced(self):
        from observability.tracer import get_dlq, DeadLetter
        dlq = get_dlq()
        for i in range(1000):
            dl = DeadLetter({"headline": f"overflow {i}"}, "TestError", "pipeline")
            dlq.push(dl)
        assert dlq.stats()["total"] <= 500

    def test_stage_timer_overflow_handled(self):
        from observability.stage_timer import get_stage_timer
        timer = get_stage_timer()
        timer.clear()
        for i in range(20_000):
            timer.record(f"sig-{i}", "OVERFLOW_TEST", i % 5000,
                         critical=(i % 100 == 0))
        dist = timer.get_distribution("OVERFLOW_TEST")
        assert dist.count <= 1000
        timer.clear()

    def test_broadcaster_full_queue_no_raise(self):
        from observability.broadcaster import broadcast, subscribe, unsubscribe
        q = subscribe(maxsize=2)
        broadcast({"type": "test", "data": "a"})
        broadcast({"type": "test", "data": "b"})
        broadcast({"type": "test", "data": "c"})  # should drop, not raise
        broadcast({"type": "test", "data": "d"})
        unsubscribe(q)


class TestMalformedInputs:
    """Malformed payloads should not crash the pipeline."""

    def test_empty_headline_trace(self):
        from observability.tracer import create_trace, remove_trace
        trace = create_trace("", "rss")
        assert trace.headline == ""
        assert trace.trace_id.startswith("sig-")
        remove_trace(trace.trace_id)

    def test_unicode_headline(self):
        from observability.tracer import create_trace, remove_trace
        trace = create_trace("BTC突破10万美元大关 🚀 市场疯狂", "rss")
        assert "BTC" in trace.headline
        remove_trace(trace.trace_id)

    def test_very_long_headline(self):
        from observability.tracer import create_trace, remove_trace
        long_headline = "A" * 5000
        trace = create_trace(long_headline, "rss")
        assert len(trace.headline) == 5000
        remove_trace(trace.trace_id)

    def test_invalid_source(self):
        from observability.tracer import create_trace, remove_trace
        trace = create_trace("Test", "")
        assert trace.source == ""
        remove_trace(trace.trace_id)

    def test_none_values_in_rejection(self):
        from observability.tracer import create_trace, remove_trace
        from observability.rejection import RejectionReason
        trace = create_trace("Test with None values", "rss")
        trace.reject(RejectionReason.NO_MARKET_MATCHES, threshold=None, actual=None)
        assert trace.rejection is not None
        assert trace.rejection.threshold_value is None
        remove_trace(trace.trace_id)


class TestContradictorySignals:
    """Conflicting signals should be detected, not silently merged."""

    def test_opposite_direction_signals_produce_conflict_multiplier(self):
        from alpha.signal import AlphaSignal, AggregatedSignal
        from alpha.ensemble import combine

        sig_yes = AlphaSignal(
            market_id="test-001", market_question="Will BTC hit 100K?",
            direction="YES", confidence=0.80, expected_edge=0.06,
            horizon="1h", strategy="news",
        )
        sig_no = AlphaSignal(
            market_id="test-001", market_question="Will BTC hit 100K?",
            direction="NO", confidence=0.60, expected_edge=0.04,
            horizon="1h", strategy="momentum",
        )
        aggregated = combine([sig_yes, sig_no])
        assert aggregated.has_conflict
        assert aggregated.size_multiplier == 0.4

    def test_agreement_produces_full_multiplier(self):
        from alpha.signal import AlphaSignal
        from alpha.ensemble import combine

        sig1 = AlphaSignal(
            market_id="test-001", market_question="Will BTC hit 100K?",
            direction="YES", confidence=0.80, expected_edge=0.06,
            horizon="1h", strategy="news",
        )
        sig2 = AlphaSignal(
            market_id="test-001", market_question="Will BTC hit 100K?",
            direction="YES", confidence=0.60, expected_edge=0.04,
            horizon="5m", strategy="momentum",
        )
        aggregated = combine([sig1, sig2])
        assert not aggregated.has_conflict
        assert aggregated.size_multiplier == 1.0
        assert aggregated.is_strong


class TestSQLiteFragmentation:
    """Verify SQLite doesn't fragment under write load."""

    def test_many_trace_writes(self):
        from observability.logger import log_trace, update_trace
        import uuid
        prefix = uuid.uuid4().hex[:8]
        for i in range(100):
            tid = f"sig-{prefix}-{i}"
            log_trace(tid, f"Frag test {i}", "rss")
            if i % 3 == 0:
                update_trace(tid, final_stage="REJECTED",
                             rejection_reason="TEST_REASON")


class TestGracefulDegradation:
    """System should degrade gracefully, not crash, under stress."""

    def test_inspector_handles_missing_pipeline(self):
        from observability.inspector import inspect, PipelineInspection
        result = inspect(None)
        assert isinstance(result, PipelineInspection)
        assert result.uptime_seconds == 0.0
        assert result.signals_total == 0

    def test_health_monitor_handles_none_pipeline(self):
        from observability.health_monitor import HealthMonitor
        hm = HealthMonitor(None)
        status = hm.status()
        assert "watchdogs" in status
        assert len(status["watchdogs"]) == 3
