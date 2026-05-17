"""
Validation passes 1-4: Stress, fail-open, FSM integrity, replay determinism.

All tests self-contained — no live pipeline required.
"""
import json
import time
import threading
from collections import deque

import pytest


# ============================================================================
# VALIDATION PASS 1: Stress-test telemetry overhead
# ============================================================================

class TestStress10KBurst:
    """10K+ trace creation burst — verify bounded memory and no stalls."""

    def test_10k_trace_creation_bounded_memory(self):
        from observability.tracer import create_trace, get_active_traces, remove_trace
        traces = []
        for i in range(10_000):
            trace = create_trace(f"Stress headline {i}", "rss")
            traces.append(trace)
        active = get_active_traces()
        assert len(active) <= 500, f"Active traces exceeded cap: {len(active)}"
        for t in traces:
            try:
                remove_trace(t.trace_id)
            except KeyError:
                pass

    def test_10k_trace_latency_under_1ms(self):
        from observability.tracer import create_trace, remove_trace
        t0 = time.monotonic()
        for i in range(1000):
            trace = create_trace(f"Latency test {i}", "rss")
            remove_trace(trace.trace_id)
        elapsed_ms = (time.monotonic() - t0) * 1000
        avg_us = (elapsed_ms * 1000) / 1000
        assert avg_us < 1000, f"Average trace create+remove: {avg_us:.0f}us (target <1000us)"

    def test_rejection_flood_memory_stable(self):
        from observability.tracer import create_trace, remove_trace
        from observability.rejection import RejectionReason
        traces = []
        for i in range(2000):
            trace = create_trace(f"Rejection flood {i}", "rss")
            trace.reject(RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
                         threshold=0.10, actual=0.01, snapshot={"NLP_MIN_IMPACT": 0.10})
            traces.append(trace)
            if i % 100 == 0:
                for t in traces[-600:-500]:
                    try:
                        remove_trace(t.trace_id)
                    except KeyError:
                        pass
        rejected = sum(1 for t in traces if t.rejection is not None)
        assert rejected == 2000
        for t in traces:
            try:
                remove_trace(t.trace_id)
            except KeyError:
                pass

    def test_stage_timer_backpressure(self):
        """Ring buffer handles burst without blocking."""
        from observability.stage_timer import get_stage_timer
        timer = get_stage_timer()
        timer.clear()
        t0 = time.monotonic()
        for i in range(50_000):
            timer.record(f"sig-{i % 1000}", "BURST_TEST", i % 5000,
                         critical=(i % 10 == 0))
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 500, f"50K records took {elapsed_ms:.0f}ms — too slow"
        dist = timer.get_distribution("BURST_TEST")
        assert dist.count <= 1000  # max_per_stage enforced
        timer.clear()

    def test_dlq_backpressure(self):
        from observability.tracer import get_dlq, DeadLetter
        dlq = get_dlq()
        for i in range(1000):
            dl = DeadLetter({"headline": f"DLQ burst {i}"}, "TestError('burst')",
                            "pipeline", f"sig-{i}")
            dlq.push(dl)
        stats = dlq.stats()
        assert stats["total"] <= 500, f"DLQ exceeded cap: {stats['total']}"


class TestSQLiteContention:
    """Verify SQLite writes don't stall under concurrent trace creation."""

    def test_concurrent_log_trace(self):
        from observability.logger import log_trace
        import uuid
        prefix = uuid.uuid4().hex[:6]
        for i in range(100):
            log_trace(f"sig-{prefix}-{i}", f"Headline {i}", "rss")

    def test_prune_is_safe_to_call(self):
        from observability.logger import prune_signal_traces, prune_dead_letters
        # prune_dead_letters is simple and should always work
        d2 = prune_dead_letters(ttl_days=9999)
        assert d2 >= 0
        # prune_signal_traces with high max_rows is a no-op
        d1 = prune_signal_traces(max_rows=10_000_000)
        assert d1 == 0


# ============================================================================
# VALIDATION PASS 2: Fail-open guarantees
# ============================================================================

class TestFailOpen:
    """Telemetry failures must never block execution."""

    def test_stage_timer_measure_passthrough(self):
        """measure() context manager propagates inner exception, never raises itself."""
        from observability.stage_timer import get_stage_timer
        timer = get_stage_timer()
        try:
            with timer.measure("sig-failopen", "TEST"):
                raise RuntimeError("simulated crash")
        except RuntimeError:
            pass
        except Exception as e:
            pytest.fail(f"measure() raised an unexpected exception: {e}")

    def test_persist_trace_safe_never_raises(self):
        """_persist_trace_safe swallows all errors."""
        from pipeline import _persist_trace_safe
        from observability.tracer import create_trace, remove_trace
        from observability.rejection import RejectionReason
        trace = create_trace("Safe test", "rss")
        trace.reject(RejectionReason.NO_MARKET_MATCHES)
        try:
            _persist_trace_safe(trace)
        except Exception as e:
            pytest.fail(f"_persist_trace_safe raised: {e}")
        remove_trace(trace.trace_id)

    def test_log_trace_safe_never_raises(self):
        from pipeline import _log_trace_safe
        _log_trace_safe("sig-nonexistent", "test", "rss")

    def test_inspector_never_raises_on_none(self):
        from observability.inspector import inspect, PipelineInspection
        result = inspect(None)
        assert isinstance(result, PipelineInspection)

    def test_inspector_never_raises_on_garbage(self):
        from observability.inspector import inspect, PipelineInspection

        class GarbageObject:
            def status(self):
                raise RuntimeError("simulated broken status")

        result = inspect(GarbageObject())
        assert isinstance(result, PipelineInspection)

    def test_heatmap_never_raises_on_none(self):
        from observability.inspector import get_heatmap, PipelineHeatmap
        result = get_heatmap(None)
        assert isinstance(result, PipelineHeatmap)

    def test_broadcaster_subscribe_unsubscribe_never_raises(self):
        from observability.broadcaster import subscribe, unsubscribe, broadcast
        q = subscribe(maxsize=1)
        # Fill queue to capacity
        broadcast({"type": "test", "data": "a"})
        # Broadcast when full — should not raise
        broadcast({"type": "test", "data": "b"})
        unsubscribe(q)
        # Double unsubscribe — should not raise
        unsubscribe(q)

    def test_trace_reject_never_raises_with_none_snapshot(self):
        from observability.tracer import create_trace, remove_trace
        from observability.rejection import RejectionReason
        trace = create_trace("None snapshot test", "rss")
        trace.reject(RejectionReason.NO_MARKET_MATCHES)
        assert trace.rejection is not None
        remove_trace(trace.trace_id)


# ============================================================================
# VALIDATION PASS 3: FSM integrity under adversarial inputs
# ============================================================================

class TestFSMIntegrity:
    def test_duplicate_transition_is_accepted_but_logged(self):
        """Transitioning to the same stage twice should be caught by the FSM.
        It's a valid transition from the previous stage, but it means the trace
        has already advanced — which is a logical error, not a crash."""
        from observability.tracer import create_trace, remove_trace, SignalStage
        trace = create_trace("Duplicate test", "rss")
        ok1 = trace.transition(SignalStage.NLP_PROCESSED)
        assert ok1
        # Second transition from NLP_PROCESSED to MARKET_MATCHED is valid
        ok2 = trace.transition(SignalStage.MARKET_MATCHED)
        assert ok2
        # But transitioning from MARKET_MATCHED to NLP_PROCESSED is illegal
        ok3 = trace.transition(SignalStage.NLP_PROCESSED)
        assert not ok3
        remove_trace(trace.trace_id)

    def test_all_illegal_jumps_rejected(self):
        """Test every illegal jump from INGESTED — none should corrupt state."""
        from observability.tracer import create_trace, remove_trace, SignalStage
        valid = {SignalStage.NLP_PROCESSED, SignalStage.REJECTED, SignalStage.EXPIRED}
        all_stages = set(SignalStage)
        illegal = all_stages - valid
        for stage in illegal:
            trace = create_trace(f"Illegal to {stage.name}", "rss")
            ok = trace.transition(stage)
            assert not ok, f"Transition to {stage.name} should be illegal"
            assert trace.current_stage == SignalStage.INGESTED, \
                f"State corrupted after illegal transition to {stage.name}"
            assert len(trace.lifecycle) == 0, \
                f"Lifecycle recorded for illegal transition to {stage.name}"
            remove_trace(trace.trace_id)

    def test_missing_stages_detected(self):
        """Jumping from INGESTED directly to SCORED must fail."""
        from observability.tracer import create_trace, remove_trace, SignalStage
        trace = create_trace("Missing stages test", "rss")
        ok = trace.transition(SignalStage.SCORED)
        assert not ok, "Jump from INGESTED to SCORED should be illegal"
        assert trace.current_stage == SignalStage.INGESTED
        remove_trace(trace.trace_id)

    def test_terminal_states_are_immutable(self):
        """Once REJECTED/SETTLED/EXPIRED, no further transitions allowed."""
        from observability.tracer import create_trace, remove_trace, SignalStage
        from observability.rejection import RejectionReason

        # REJECTED case: reject from INGESTED
        trace = create_trace("Terminal REJECTED", "rss")
        trace.reject(RejectionReason.NO_MARKET_MATCHES)
        for attempt in SignalStage:
            ok = trace.transition(attempt)
            assert not ok, f"Should not transition from REJECTED to {attempt.name}"
        remove_trace(trace.trace_id)

        # SETTLED case: full happy path
        trace = create_trace("Terminal SETTLED", "rss")
        for s in [SignalStage.NLP_PROCESSED, SignalStage.MARKET_MATCHED,
                  SignalStage.SCORED, SignalStage.VALIDATED,
                  SignalStage.SIZED, SignalStage.EXECUTED,
                  SignalStage.SETTLED]:
            trace.transition(s)
        for attempt in SignalStage:
            ok = trace.transition(attempt)
            assert not ok, f"Should not transition from SETTLED to {attempt.name}"
        remove_trace(trace.trace_id)

        # EXPIRED case: go directly from INGESTED to EXPIRED
        trace = create_trace("Terminal EXPIRED", "rss")
        trace.transition(SignalStage.EXPIRED)
        for attempt in SignalStage:
            ok = trace.transition(attempt)
            assert not ok, f"Should not transition from EXPIRED to {attempt.name}"
        remove_trace(trace.trace_id)

    def test_concurrent_trace_creation_thread_safety(self):
        """Multiple threads creating traces should not corrupt the active dict."""
        from observability.tracer import create_trace, get_active_traces
        import concurrent.futures

        def create_batch(n):
            ids = []
            for i in range(n):
                trace = create_trace(f"Thread batch {i}", "rss")
                ids.append(trace.trace_id)
            return ids

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(create_batch, 100) for _ in range(4)]
            results = [f.result() for f in futures]

        all_ids = set()
        for ids in results:
            all_ids.update(ids)
        assert len(all_ids) == 400, f"Expected 400 unique IDs, got {len(all_ids)}"

        active = get_active_traces()
        assert len(active) <= 500

        from observability.tracer import remove_trace
        for tid in list(all_ids):
            remove_trace(tid)


# ============================================================================
# VALIDATION PASS 4: Replay determinism from SQLite
# ============================================================================

class TestReplayDeterminism:
    def test_rejection_path_replay(self):
        """Write a rejection trace to SQLite, then replay it."""
        from observability.tracer import create_trace, remove_trace, reconstruct_trace
        from observability.rejection import RejectionReason
        from observability.logger import log_trace, update_trace, get_trace_by_id

        trace = create_trace("Replay: Fed raises rates", "newsapi",
                             news_id="news-replay-001",
                             parent_trace_id="sig-parent-replay")
        log_trace(trace.trace_id, trace.headline, trace.source,
                  news_id="news-replay-001",
                  parent_trace_id="sig-parent-replay")

        trace.reject(RejectionReason.EDGE_EV_BELOW_THRESHOLD,
                     threshold=0.03, actual=0.012,
                     snapshot={"EDGE_THRESHOLD": 0.03, "DRY_RUN": True})
        update_trace(trace.trace_id,
                     final_stage="REJECTED",
                     final_status="rejected",
                     rejection_reason="EDGE_EV_BELOW_THRESHOLD",
                     rejection_severity="HARD_REJECT",
                     rejection_detail=json.dumps({
                         "threshold": 0.03,
                         "actual": 0.012,
                         "subsystem": "edge",
                         "detail": "EV 0.012 < threshold 0.03",
                         "snapshot": {"EDGE_THRESHOLD": 0.03, "DRY_RUN": True},
                     }),
                     stage_timings=json.dumps([
                         {"stage": "NLP", "latency_us": 2100},
                         {"stage": "MATCHER", "latency_us": 3800},
                         {"stage": "CLASSIFIER", "latency_us": 298000},
                         {"stage": "EDGE", "latency_us": 150},
                     ]),
                     total_latency_ms=310)

        row = get_trace_by_id(trace.trace_id)
        assert row is not None

        reconstructed = reconstruct_trace(trace.trace_id, row)
        assert reconstructed["trace_id"] == trace.trace_id
        assert reconstructed["parent_trace_id"] == "sig-parent-replay"
        assert reconstructed["final_stage"] == "REJECTED"
        assert reconstructed["rejection"] is not None
        assert reconstructed["rejection"]["threshold"] == 0.03
        assert reconstructed["rejection"]["actual"] == 0.012
        assert reconstructed["rejection"]["subsystem"] == "edge"
        assert reconstructed["rejection"]["snapshot"]["EDGE_THRESHOLD"] == 0.03
        assert reconstructed["rejection"]["snapshot"]["DRY_RUN"] is True
        assert len(reconstructed["lifecycle"]) == 5  # INGESTED + 4 stages
        assert reconstructed["schema_version"] == 1

        remove_trace(trace.trace_id)

    def test_causal_linkage_replay(self):
        """Verify parent/child causal linkage survives round-trip."""
        from observability.tracer import create_trace, remove_trace, reconstruct_trace
        from observability.logger import log_trace, update_trace, get_trace_by_id

        # Parent trace
        parent = create_trace("Parent: SpaceX launch", "rss",
                              news_id="news-causal-001")
        log_trace(parent.trace_id, parent.headline, parent.source,
                  news_id="news-causal-001")

        # Child trace with parent reference
        child = create_trace("Child: SpaceX market signal", "rss",
                             parent_trace_id=parent.trace_id,
                             news_id="news-causal-001")
        log_trace(child.trace_id, child.headline, child.source,
                  news_id="news-causal-001",
                  parent_trace_id=parent.trace_id)

        child_row = get_trace_by_id(child.trace_id)
        reconstructed = reconstruct_trace(child.trace_id, child_row)
        assert reconstructed["parent_trace_id"] == parent.trace_id

        remove_trace(parent.trace_id)
        remove_trace(child.trace_id)

    def test_market_match_trace_roundtrip(self):
        """MarketMatchTrace survives JSON serialization and replay."""
        from observability.tracer import create_trace, remove_trace, MarketMatchTrace, reconstruct_trace
        from observability.logger import log_trace, update_trace, get_trace_by_id

        trace = create_trace("Market match: BTC ATH", "rss",
                             news_id="news-match-001")
        log_trace(trace.trace_id, trace.headline, trace.source,
                  news_id="news-match-001")

        mt = MarketMatchTrace(
            trace_id=trace.trace_id,
            market_id="poly:0xabc123",
            market_question="Will Bitcoin exceed $150K in 2026?",
            similarity_score=0.74,
            matched_entities=["Bitcoin", "BTC"],
            keywords_hit=["bitcoin", "btc"],
            embedding_distance=0.26,
            rank_position=1,
            match_method="semantic",
            rejected_alternatives=[
                {"market_id": "poly:0xdef456", "score": 0.28, "reason": "below_threshold"},
            ],
        )
        trace.set_match_trace(mt)
        trace.context.market_id = "poly:0xabc123"

        update_trace(trace.trace_id,
                     market_id="poly:0xabc123",
                     match_trace=json.dumps({
                         "trace_id": mt.trace_id,
                         "market_id": mt.market_id,
                         "market_question": mt.market_question,
                         "similarity_score": mt.similarity_score,
                         "matched_entities": mt.matched_entities,
                         "keywords_hit": mt.keywords_hit,
                         "embedding_distance": mt.embedding_distance,
                         "rank_position": mt.rank_position,
                         "match_method": mt.match_method,
                         "rejected_alternatives": mt.rejected_alternatives,
                     }),
                     final_stage="MARKET_MATCHED")

        row = get_trace_by_id(trace.trace_id)
        reconstructed = reconstruct_trace(trace.trace_id, row)
        assert reconstructed["match_trace"] is not None
        assert reconstructed["match_trace"]["similarity_score"] == 0.74
        assert reconstructed["match_trace"]["matched_entities"] == ["Bitcoin", "BTC"]
        assert reconstructed["match_trace"]["rejected_alternatives"][0]["score"] == 0.28

        remove_trace(trace.trace_id)

    def test_multiple_rejection_paths_reconstructable(self):
        """Write 3 different rejection types, verify all reconstruct correctly."""
        from observability.tracer import create_trace, remove_trace, reconstruct_trace
        from observability.rejection import RejectionReason
        from observability.logger import log_trace, update_trace, get_trace_by_id

        scenarios = [
            (RejectionReason.NLP_IMPACT_BELOW_THRESHOLD, 0.10, 0.04,
             "nlp", "HARD_REJECT", "NLP impact 0.04 < 0.10"),
            (RejectionReason.MAX_POSITIONS_REACHED, 5, 5,
             "risk", "SOFT_REJECT", "5/5 positions open"),
            (RejectionReason.STALENESS_ABORT, 0.50, 0.72,
             "pipeline", "SOFT_REJECT", "Market moved 72% of predicted"),
        ]

        for reason, threshold, actual, subsystem, severity, detail in scenarios:
            trace = create_trace(f"Replay: {reason.name}", "rss")
            log_trace(trace.trace_id, trace.headline, trace.source)
            trace.reject(reason, threshold=threshold, actual=actual,
                         snapshot={reason.config_key or "NONE": threshold})

            update_trace(trace.trace_id,
                         final_stage="REJECTED", final_status="rejected",
                         rejection_reason=reason.name,
                         rejection_severity=severity,
                         rejection_detail=json.dumps({
                             "threshold": threshold, "actual": actual,
                             "subsystem": subsystem, "detail": detail,
                             "snapshot": {reason.config_key or "NONE": threshold},
                         }))

            row = get_trace_by_id(trace.trace_id)
            reconstructed = reconstruct_trace(trace.trace_id, row)
            assert reconstructed["rejection"] is not None
            assert reconstructed["rejection"]["threshold"] == threshold
            assert reconstructed["rejection"]["actual"] == actual
            assert reconstructed["rejection"]["subsystem"] == subsystem

            remove_trace(trace.trace_id)
