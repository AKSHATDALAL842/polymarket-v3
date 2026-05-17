from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline import Pipeline

log = logging.getLogger(__name__)


@dataclass
class QueueDepths:
    news_pending: int = 0
    nlp_backlog: int = 0
    matcher_backlog: int = 0
    execution_backlog: int = 0
    cold_path_backlog: int = 0
    ws_broadcast_lag: int = 0
    ws_subscriber_count: int = 0


@dataclass
class PipelineInspection:
    uptime_seconds: float = 0.0
    events_total: int = 0
    signals_total: int = 0
    signals_active: int = 0
    signals_completed: int = 0
    signals_rejected: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    stage_latency_p50: dict[str, float] = field(default_factory=dict)
    stage_latency_p95: dict[str, float] = field(default_factory=dict)
    queue_depths: QueueDepths = field(default_factory=QueueDepths)
    recent_rejections: list[dict] = field(default_factory=list)
    recent_signals: list[dict] = field(default_factory=list)
    throughput_per_minute: float = 0.0
    risk_state: dict = field(default_factory=dict)
    ws_connected: bool = False
    source_stats: dict = field(default_factory=dict)


@dataclass
class PipelineHeatmap:
    rejection_hotspots: dict[str, int] = field(default_factory=dict)
    latency_bottlenecks: dict[str, float] = field(default_factory=dict)
    dead_stages: list[str] = field(default_factory=list)
    threshold_overfiltering: dict[str, float] = field(default_factory=dict)
    signal_survival_rate: float = 0.0
    stage_transition_counts: dict[str, int] = field(default_factory=dict)


def inspect(pipeline) -> PipelineInspection:
    """Build a live PipelineInspection snapshot. Never raises - returns empty snapshot on failure."""
    try:
        from observability.tracer import get_active_traces
        from observability.stage_timer import get_stage_timer
        from observability import broadcaster

        status = pipeline.status()
        timer = get_stage_timer()
        dists = timer.get_all_distributions()

        active = get_active_traces()
        rejected = [t for t in active if t.rejection is not None]

        rejection_counts: dict[str, int] = {}
        for t in rejected:
            if t.rejection:
                reason = t.rejection.reason.name
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        stage_p50: dict[str, float] = {}
        stage_p95: dict[str, float] = {}
        for stage, d in dists.items():
            stage_p50[stage] = d.p50_us / 1000.0
            stage_p95[stage] = d.p95_us / 1000.0

        uptime = status.get("uptime_seconds", 0)
        signals_total = status.get("signals_generated", 0)
        tpm = (signals_total / (uptime / 60.0)) if uptime > 0 else 0.0

        source_stats = {}
        try:
            source_stats = pipeline.get_source_stats()
        except Exception:
            pass

        recent_rej = [
            {
                "trace_id": t.trace_id,
                "reason": t.rejection.reason.name,
                "severity": t.rejection.severity.name,
                "subsystem": t.rejection.subsystem,
                "threshold": t.rejection.threshold_value,
                "actual": t.rejection.actual_value,
                "headline": t.headline[:100],
            }
            for t in rejected[-20:]
        ]

        recent_sigs = [
            {
                "trace_id": t.trace_id,
                "stage": t.current_stage.name,
                "status": t.final_status,
                "headline": t.headline[:80],
                "source": t.source,
            }
            for t in active[-20:]
        ]

        return PipelineInspection(
            uptime_seconds=uptime,
            events_total=status.get("events_processed", 0),
            signals_total=signals_total,
            signals_active=len(active),
            signals_completed=sum(1 for t in active if t.final_status == "completed"),
            signals_rejected=len(rejected),
            rejection_counts=rejection_counts,
            stage_latency_p50=stage_p50,
            stage_latency_p95=stage_p95,
            queue_depths=_get_queue_depths(pipeline),
            recent_rejections=recent_rej,
            recent_signals=recent_sigs,
            throughput_per_minute=round(tpm, 2),
            risk_state=status.get("risk", {}),
            ws_connected=status.get("ws_connected", False),
            source_stats=source_stats,
        )
    except Exception as e:
        log.warning("[inspector] inspect() failed: %s - returning empty snapshot", e)
        return PipelineInspection()


def get_heatmap(pipeline, window_seconds: int = 3600) -> PipelineHeatmap:
    """Compute pipeline heatmap from signal_traces table. Never raises."""
    try:
        from observability.logger import get_recent_traces_for_heatmap
        rows = get_recent_traces_for_heatmap(window_seconds)

        rejection_hotspots: dict[str, int] = {}
        threshold_overfiltering: dict[str, float] = {}
        stage_transitions: dict[str, int] = {}
        total_created = len(rows)
        total_executed = 0

        for row in rows:
            stage = row.get("final_stage", "UNKNOWN")
            reason = row.get("rejection_reason")
            transition_key = f"{stage}"

            if reason:
                rejection_hotspots[stage] = rejection_hotspots.get(stage, 0) + 1
                threshold_overfiltering[reason] = threshold_overfiltering.get(reason, 0) + 1

            stage_transitions[transition_key] = stage_transitions.get(transition_key, 0) + 1

            if stage == "EXECUTED" or stage == "SETTLED":
                total_executed += 1

        for key in threshold_overfiltering:
            threshold_overfiltering[key] = round(
                threshold_overfiltering[key] / max(1, total_created), 4
            )

        from observability.stage_timer import get_stage_timer
        timer = get_stage_timer()
        dists = timer.get_all_distributions()
        latency_bottlenecks = {
            stage: d.p95_us / 1000.0 for stage, d in dists.items()
        }

        all_stages = {"INGESTED", "NLP_PROCESSED", "MARKET_MATCHED", "SCORED",
                       "VALIDATED", "SIZED", "EXECUTED", "SETTLED"}
        dead_stages = [
            stage for stage in all_stages
            if stage not in stage_transitions
        ]

        survival_rate = total_executed / max(1, total_created)

        return PipelineHeatmap(
            rejection_hotspots=rejection_hotspots,
            latency_bottlenecks=latency_bottlenecks,
            dead_stages=dead_stages,
            threshold_overfiltering=threshold_overfiltering,
            signal_survival_rate=round(survival_rate, 4),
            stage_transition_counts=stage_transitions,
        )
    except Exception as e:
        log.warning("[inspector] get_heatmap() failed: %s", e)
        return PipelineHeatmap()


def _get_queue_depths(pipeline) -> QueueDepths:
    """Sample queue depths from pipeline internals. Never raises."""
    try:
        from observability import broadcaster

        ws_max_lag = 0
        ws_count = 0
        try:
            subs = broadcaster._subscribers
            ws_count = len(subs)
            for q in subs:
                ws_max_lag = max(ws_max_lag, q.qsize())
        except Exception:
            pass

        return QueueDepths(
            news_pending=getattr(pipeline, '_news_queue', None).qsize() if hasattr(pipeline, '_news_queue') else 0,
            cold_path_backlog=0,
            ws_broadcast_lag=ws_max_lag,
            ws_subscriber_count=ws_count,
        )
    except Exception:
        return QueueDepths()
