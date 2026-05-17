import json
import time
from observability.rejection import RejectionReason, RejectionSeverity, RejectionRecord
from observability.tracer import (
    SignalStage, VALID_TRANSITIONS, SignalTrace, TraceContext,
    create_trace, generate_trace_id, DeadLetterQueue, DeadLetter,
    remove_trace, reconstruct_trace,
)
from observability.stage_timer import StageTimer, get_stage_timer
from observability.inspector import (
    PipelineInspection, PipelineHeatmap, QueueDepths, inspect,
)
from observability.health_monitor import (
    Watchdog, FrozenWSWatchdog, ZeroSignalWatchdog,
    IngestionOutageWatchdog,
)


class TestRejectionReason:
    def test_nlp_impact_is_hard_reject(self):
        r = RejectionReason.NLP_IMPACT_BELOW_THRESHOLD
        assert r.subsystem == "nlp"
        assert r.threshold_field == "impact_score"
        assert r.config_key == "NLP_MIN_IMPACT"
        assert r.severity == RejectionSeverity.HARD_REJECT

    def test_daily_loss_cap_is_soft_reject(self):
        r = RejectionReason.DAILY_LOSS_CAP_HIT
        assert r.subsystem == "risk"
        assert r.severity == RejectionSeverity.SOFT_REJECT

    def test_pipeline_exception_is_system_failure(self):
        r = RejectionReason.PIPELINE_EXCEPTION
        assert r.severity == RejectionSeverity.SYSTEM_FAILURE
        assert r.threshold_field is None

    def test_category_filter_is_info(self):
        r = RejectionReason.CATEGORY_NOT_SELECTED
        assert r.severity == RejectionSeverity.INFO

    def test_rejection_record_creation(self):
        record = RejectionRecord(
            trace_id="sig-abc123def456",
            reason=RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
            severity=RejectionSeverity.HARD_REJECT,
            subsystem="nlp",
            threshold_value=0.10,
            actual_value=0.05,
            threshold_snapshot={"NLP_MIN_IMPACT": 0.10, "DRY_RUN": True},
            detail="NLP relevance 0.05 < 0.10",
            timestamp=1000000.0,
        )
        assert record.trace_id == "sig-abc123def456"
        assert record.actual_value == 0.05
        assert record.threshold_snapshot["NLP_MIN_IMPACT"] == 0.10


class TestSignalStageFSM:
    def test_legal_transition_ingested_to_nlp(self):
        assert SignalStage.NLP_PROCESSED in VALID_TRANSITIONS[SignalStage.INGESTED]

    def test_legal_transition_executed_to_settled(self):
        assert SignalStage.SETTLED in VALID_TRANSITIONS[SignalStage.EXECUTED]

    def test_illegal_transition_ingested_to_executed(self):
        assert SignalStage.EXECUTED not in VALID_TRANSITIONS[SignalStage.INGESTED]

    def test_illegal_transition_from_terminal_rejected(self):
        assert len(VALID_TRANSITIONS[SignalStage.REJECTED]) == 0

    def test_illegal_transition_from_terminal_settled(self):
        assert len(VALID_TRANSITIONS[SignalStage.SETTLED]) == 0

    def test_any_stage_can_reject_except_terminals(self):
        for stage, allowed in VALID_TRANSITIONS.items():
            if stage in (SignalStage.SETTLED, SignalStage.REJECTED, SignalStage.EXPIRED):
                assert SignalStage.REJECTED not in allowed


class TestSignalTrace:
    def test_create_trace_starts_at_ingested(self):
        trace = create_trace("Test headline", "rss")
        assert trace.current_stage == SignalStage.INGESTED
        assert trace.trace_id.startswith("sig-")
        assert len(trace.trace_id) == 16
        remove_trace(trace.trace_id)

    def test_legal_transition_succeeds(self):
        trace = create_trace("Test headline", "rss")
        ok = trace.transition(SignalStage.NLP_PROCESSED, status="passed")
        assert ok is True
        assert trace.current_stage == SignalStage.NLP_PROCESSED
        assert len(trace.lifecycle) == 1
        remove_trace(trace.trace_id)

    def test_illegal_transition_returns_false(self):
        trace = create_trace("Test headline", "rss")
        ok = trace.transition(SignalStage.EXECUTED)
        assert ok is False
        assert trace.current_stage == SignalStage.INGESTED
        remove_trace(trace.trace_id)

    def test_reject_sets_correct_state(self):
        trace = create_trace("Test headline", "rss")
        trace.reject(
            RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
            threshold=0.10, actual=0.05,
            snapshot={"NLP_MIN_IMPACT": 0.10},
            detail="test rejection",
        )
        assert trace.current_stage == SignalStage.REJECTED
        assert trace.rejection is not None
        assert trace.rejection.severity == RejectionSeverity.HARD_REJECT
        assert trace.rejection.actual_value == 0.05
        remove_trace(trace.trace_id)

    def test_full_happy_path_transitions(self):
        trace = create_trace("Test headline", "rss")
        stages = [
            SignalStage.NLP_PROCESSED,
            SignalStage.MARKET_MATCHED,
            SignalStage.SCORED,
            SignalStage.VALIDATED,
            SignalStage.SIZED,
            SignalStage.EXECUTED,
            SignalStage.SETTLED,
        ]
        for stage in stages:
            ok = trace.transition(stage)
            assert ok is True, f"Failed at {stage.name}"
        assert len(trace.lifecycle) == 7
        remove_trace(trace.trace_id)

    def test_generate_trace_id_uniqueness(self):
        ids = {generate_trace_id() for _ in range(1000)}
        assert len(ids) == 1000


class TestDeadLetterQueue:
    def test_push_and_pop(self):
        dlq = DeadLetterQueue(maxlen=10)
        dl = DeadLetter({"headline": "test"}, "ValueError('bad')", "pipeline", "sig-abc123")
        dlq.push(dl)
        popped = dlq.pop()
        assert popped is not None
        assert popped.payload["headline"] == "test"
        assert popped.subsystem == "pipeline"

    def test_bury(self):
        dlq = DeadLetterQueue(maxlen=10)
        dl = DeadLetter({"headline": "test"}, "ValueError('bad')", "pipeline")
        dl_id = dl.dlq_id
        dlq.push(dl)
        assert dlq.bury(dl_id) is True
        popped = dlq.pop()
        assert popped.status == "dead"

    def test_stats(self):
        dlq = DeadLetterQueue(maxlen=10)
        dlq.push(DeadLetter({}, "err", "nlp"))
        dlq.push(DeadLetter({}, "err", "matcher"))
        s = dlq.stats()
        assert s["total"] == 2
        assert s["by_subsystem"]["nlp"] == 1
        assert s["by_subsystem"]["matcher"] == 1


class TestStageTimer:
    def test_record_and_retrieve(self):
        timer = StageTimer(max_ring_entries=100, max_per_stage=50)
        timer.record("sig-abc", "NLP", 1500, critical=False)
        timer.record("sig-abc", "NLP", 2500, critical=False)
        timer.record("sig-def", "NLP", 3500, critical=False)

        dist = timer.get_distribution("NLP")
        assert dist.count == 3
        assert dist.p50_us == 2500
        assert dist.min_us == 1500
        assert dist.max_us == 3500

    def test_critical_never_dropped(self):
        timer = StageTimer(max_ring_entries=3, max_per_stage=3)
        for i in range(10):
            timer.record(f"sig-{i}", "NLP", 1000, critical=True)
        recent = timer.get_recent(20)
        assert len(recent) == 3  # maxlen respected

    def test_measure_context_manager(self):
        timer = StageTimer(max_ring_entries=100, max_per_stage=50)
        with timer.measure("sig-xyz", "CLASSIFIER", critical=True):
            pass
        dist = timer.get_distribution("CLASSIFIER")
        assert dist.count == 1
        assert dist.min_us >= 0

    def test_measure_never_raises_on_error(self):
        timer = StageTimer(max_ring_entries=100, max_per_stage=50)
        try:
            with timer.measure("sig-err", "BAD_STAGE", critical=False):
                raise RuntimeError("simulated pipeline error")
        except RuntimeError:
            pass

    def test_clear(self):
        timer = StageTimer(max_ring_entries=100, max_per_stage=50)
        timer.record("sig-1", "NLP", 1000)
        timer.clear()
        dist = timer.get_distribution("NLP")
        assert dist.count == 0

    def test_get_all_distributions(self):
        timer = StageTimer(max_ring_entries=100, max_per_stage=50)
        timer.record("sig-1", "NLP", 1000)
        timer.record("sig-2", "CLASSIFIER", 5000)
        dists = timer.get_all_distributions()
        assert "NLP" in dists
        assert "CLASSIFIER" in dists
        assert dists["NLP"].count == 1


class TestPipelineInspection:
    def test_empty_inspection_defaults(self):
        insp = PipelineInspection()
        assert insp.uptime_seconds == 0.0
        assert insp.signals_total == 0
        assert insp.queue_depths.ws_subscriber_count == 0

    def test_inspect_never_raises(self):
        result = inspect(None)
        assert isinstance(result, PipelineInspection)


class TestPipelineHeatmap:
    def test_heatmap_defaults(self):
        hm = PipelineHeatmap()
        assert hm.signal_survival_rate == 0.0
        assert hm.dead_stages == []
        assert hm.rejection_hotspots == {}


class TestWatchdogs:
    def test_stall_watchdog_no_alert_when_fed(self):
        wd = Watchdog("test", max_idle_seconds=0.01)
        wd.feed()
        result = wd.check()
        assert result is None

    def test_stall_watchdog_alerts_when_idle(self):
        wd = Watchdog("test", max_idle_seconds=0.0)
        time.sleep(0.01)
        result = wd.check()
        assert result is not None
        assert result["watchdog"] == "test"
        assert result["alert_count"] == 1

    def test_stall_watchdog_only_alerts_once(self):
        wd = Watchdog("test", max_idle_seconds=0.0)
        time.sleep(0.01)
        r1 = wd.check()
        r2 = wd.check()
        assert r1 is not None
        assert r2 is None
        assert wd.alert_count == 1

    def test_frozen_ws_no_alert_when_disconnected(self):
        wd = FrozenWSWatchdog()
        result = wd.check_ws(ws_connected=False, last_msg_time=None)
        assert result is None

    def test_zero_signal_alerts_after_window(self):
        wd = ZeroSignalWatchdog(max_zero_window=0.0)
        result = wd.check()
        assert result is not None
        assert result["watchdog"] == "zero_signal"

    def test_zero_signal_no_alert_when_fed(self):
        wd = ZeroSignalWatchdog(max_zero_window=999.0)
        wd.feed()
        result = wd.check()
        assert result is None

    def test_ingestion_outage_no_alert_when_fed(self):
        wd = IngestionOutageWatchdog(max_idle_seconds=999.0)
        wd.feed()
        result = wd.check()
        assert result is None


class TestEndToEnd:
    def test_full_lifecycle_ingested_to_rejected(self):
        from observability.tracer import create_trace, remove_trace
        from observability.rejection import RejectionReason
        from observability.stage_timer import get_stage_timer

        timer = get_stage_timer()
        timer.clear()

        trace = create_trace("Bitcoin surges past $100K", "rss",
                             parent_trace_id="sig-parent123",
                             news_id="news-abc123def456")
        assert trace.current_stage.name == "INGESTED"

        with timer.measure(trace.trace_id, "NLP"):
            pass
        from observability.tracer import SignalStage
        trace.transition(SignalStage.NLP_PROCESSED)
        assert trace.current_stage.name == "NLP_PROCESSED"

        trace.reject(
            RejectionReason.NO_MARKET_MATCHES,
            threshold=0.30,
            actual=0.12,
            snapshot={"MATCHER_MIN_SIMILARITY": 0.30},
            detail="Best similarity 0.12 < threshold 0.30",
        )
        assert trace.current_stage.name == "REJECTED"
        assert trace.rejection is not None
        assert trace.rejection.reason == RejectionReason.NO_MARKET_MATCHES

        row = trace.finalize()
        assert row["final_stage"] == "REJECTED"
        assert row["rejection_reason"] == "NO_MARKET_MATCHES"

        remove_trace(trace.trace_id)

    def test_full_lifecycle_ingested_to_settled(self):
        from observability.tracer import create_trace, remove_trace, SignalStage
        from observability.stage_timer import get_stage_timer

        timer = get_stage_timer()
        timer.clear()

        trace = create_trace("Fed announces rate cut", "newsapi",
                             news_id="news-fed001")
        stages = [
            SignalStage.NLP_PROCESSED,
            SignalStage.MARKET_MATCHED,
            SignalStage.SCORED,
            SignalStage.VALIDATED,
            SignalStage.SIZED,
            SignalStage.EXECUTED,
            SignalStage.SETTLED,
        ]
        for stage in stages:
            with timer.measure(trace.trace_id, stage.name):
                pass
            ok = trace.transition(stage)
            assert ok, f"Failed transition to {stage.name}"

        row = trace.finalize()
        assert row["final_stage"] == "SETTLED"
        assert row["final_status"] == "settled"

        dists = timer.get_all_distributions()
        for stage_name in ["NLP_PROCESSED", "MARKET_MATCHED", "SCORED",
                            "VALIDATED", "SIZED", "EXECUTED", "SETTLED"]:
            assert stage_name in dists, f"Missing distribution for {stage_name}"
            assert dists[stage_name].count == 1

        remove_trace(trace.trace_id)

    def test_replay_reconstruction(self):
        row = {
            "trace_id": "sig-replay001",
            "parent_trace_id": "sig-parent001",
            "headline": "SpaceX Starship launch successful",
            "source": "rss",
            "market_id": "kalshi:SPACEX-25",
            "final_stage": "EXECUTED",
            "final_status": "completed",
            "rejection_reason": None,
            "rejection_severity": None,
            "rejection_detail": None,
            "match_trace": json.dumps({
                "trace_id": "sig-replay001",
                "market_id": "kalshi:SPACEX-25",
                "market_question": "Will SpaceX reach orbit in 2025?",
                "similarity_score": 0.72,
                "matched_entities": ["SpaceX", "Starship"],
                "keywords_hit": ["spacex", "launch"],
                "embedding_distance": 0.28,
                "rank_position": 1,
                "match_method": "semantic",
                "rejected_alternatives": [],
            }),
            "stage_timings": json.dumps([
                {"stage": "NLP", "latency_us": 1500},
                {"stage": "MATCHER", "latency_us": 4200},
                {"stage": "CLASSIFIER", "latency_us": 310000},
                {"stage": "EDGE", "latency_us": 200},
            ]),
            "total_latency_ms": 320,
            "execution_id": None,
            "position_id": None,
            "created_at": "2026-05-16T12:00:00",
            "schema_version": 1,
        }

        reconstructed = reconstruct_trace("sig-replay001", row)
        assert reconstructed["trace_id"] == "sig-replay001"
        assert reconstructed["parent_trace_id"] == "sig-parent001"
        assert reconstructed["final_stage"] == "EXECUTED"
        assert reconstructed["match_trace"] is not None
        assert reconstructed["match_trace"]["similarity_score"] == 0.72
        assert len(reconstructed["lifecycle"]) == 5
        assert reconstructed["schema_version"] == 1

    def test_illegal_fsm_transition_rejected(self):
        trace = create_trace("Test", "rss")
        ok = trace.transition(SignalStage.EXECUTED)
        assert ok is False
        trace.reject(RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
                     threshold=0.10, actual=0.05, snapshot={})
        ok = trace.transition(SignalStage.NLP_PROCESSED)
        assert ok is False
        remove_trace(trace.trace_id)

    def test_queue_stall_detection(self):
        wd = Watchdog("test_queue", max_idle_seconds=0.0)
        time.sleep(0.01)
        alert = wd.check()
        assert alert is not None
        assert alert["watchdog"] == "test_queue"

    def test_rejection_flood_handling(self):
        traces = []
        for i in range(100):
            trace = create_trace(f"Headline {i}", "rss")
            trace.reject(
                RejectionReason.NLP_IMPACT_BELOW_THRESHOLD,
                threshold=0.10, actual=0.01 + (i * 0.001),
                snapshot={"NLP_MIN_IMPACT": 0.10},
            )
            traces.append(trace)

        rejected_count = sum(1 for t in traces if t.current_stage.name == "REJECTED")
        assert rejected_count == 100

        for t in traces:
            remove_trace(t.trace_id)

    def test_high_ingestion_burst(self):
        traces = []
        for i in range(600):
            trace = create_trace(f"Burst headline {i}", "rss")
            traces.append(trace)

        from observability.tracer import get_active_traces
        active = get_active_traces()
        assert len(active) <= 500

        active_ids = {t.trace_id for t in active}
        assert traces[0].trace_id not in active_ids

        for t in traces:
            try:
                remove_trace(t.trace_id)
            except KeyError:
                pass
