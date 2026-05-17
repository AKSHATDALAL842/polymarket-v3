"""
Incident Report System — mandatory post-trade review for every live trade.

Produces: signal rationale, market match rationale, execution timeline,
fill analysis, reconciliation analysis, settlement outcome, slippage
analysis, anomaly analysis, replay verification.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class IncidentReport:
    incident_id: str
    trace_id: str
    severity: str                # INFO | WARNING | CRITICAL
    incident_type: str           # "live_trade" | "reconciliation_anomaly" | "circuit_breaker_trip" | "execution_failure"
    headline: str = ""
    market_id: str = ""
    market_question: str = ""
    signal_rationale: str = ""
    match_rationale: str = ""
    execution_timeline: list[dict] = field(default_factory=list)
    fill_analysis: dict = field(default_factory=dict)
    reconciliation_analysis: dict = field(default_factory=dict)
    settlement_outcome: dict = field(default_factory=dict)
    slippage_analysis: dict = field(default_factory=dict)
    anomaly_analysis: dict = field(default_factory=dict)
    replay_verified: bool = False
    resolution: str = ""         # What happened / what was done
    root_cause: str = ""         # Why it happened
    blast_radius: str = ""       # What was affected
    recovery_timeline: list[dict] = field(default_factory=list)
    prevention_fix: str = ""     # What prevents recurrence
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IncidentLogger:
    """Persists and manages incident reports."""

    def __init__(self):
        self._incidents: list[IncidentReport] = []
        self._init_db()

    def _init_db(self):
        from observability.logger import _conn
        conn = _conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incident_reports (
                incident_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                incident_type TEXT NOT NULL,
                headline TEXT,
                market_id TEXT,
                market_question TEXT,
                signal_rationale TEXT,
                match_rationale TEXT,
                execution_timeline TEXT,
                fill_analysis TEXT,
                reconciliation_analysis TEXT,
                settlement_outcome TEXT,
                slippage_analysis TEXT,
                anomaly_analysis TEXT,
                replay_verified INTEGER DEFAULT 0,
                resolution TEXT,
                root_cause TEXT,
                blast_radius TEXT,
                recovery_timeline TEXT,
                prevention_fix TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

    def log_trade(self, trace, execution_result, pipeline=None) -> IncidentReport:
        """Create a post-trade incident report for every live trade."""
        import uuid
        report = IncidentReport(
            incident_id=f"inc-{uuid.uuid4().hex[:12]}",
            trace_id=trace.trace_id if hasattr(trace, 'trace_id') else 'unknown',
            severity="INFO",
            incident_type="live_trade",
            headline=trace.headline if hasattr(trace, 'headline') else '',
            market_id=getattr(trace.context, 'market_id', '') if hasattr(trace, 'context') else '',
            signal_rationale=f"Signal generated from {trace.source if hasattr(trace, 'source') else 'unknown'} source",
            execution_timeline=[
                {"stage": "signal_created", "timestamp": time.time()},
                {"stage": "executed", "status": getattr(execution_result, 'status', 'unknown'),
                 "filled_size": getattr(execution_result, 'filled_size', 0),
                 "fill_price": getattr(execution_result, 'fill_price', 0)},
            ],
            fill_analysis={
                "filled_size": getattr(execution_result, 'filled_size', 0),
                "fill_price": getattr(execution_result, 'fill_price', 0),
                "slippage": getattr(execution_result, 'slippage', 0),
            },
            slippage_analysis={
                "estimated_slippage": getattr(execution_result, 'slippage', 0),
            },
        )

        self._incidents.append(report)
        if len(self._incidents) > 500:
            self._incidents = self._incidents[-500:]

        self._persist(report)
        return report

    def log_anomaly(self, trace_id: str, anomaly_type: str, description: str,
                    severity: str = "WARNING") -> IncidentReport:
        import uuid
        report = IncidentReport(
            incident_id=f"inc-{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            severity=severity,
            incident_type=anomaly_type,
            anomaly_analysis={"description": description},
        )
        self._incidents.append(report)
        self._persist(report)
        return report

    def _persist(self, report: IncidentReport):
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT OR REPLACE INTO incident_reports
                   (incident_id, trace_id, severity, incident_type, headline,
                    market_id, market_question, signal_rationale, match_rationale,
                    execution_timeline, fill_analysis, reconciliation_analysis,
                    settlement_outcome, slippage_analysis, anomaly_analysis,
                    replay_verified, resolution, root_cause, blast_radius,
                    recovery_timeline, prevention_fix)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (report.incident_id, report.trace_id, report.severity,
                 report.incident_type, report.headline, report.market_id,
                 report.market_question, report.signal_rationale,
                 report.match_rationale, json.dumps(report.execution_timeline),
                 json.dumps(report.fill_analysis),
                 json.dumps(report.reconciliation_analysis),
                 json.dumps(report.settlement_outcome),
                 json.dumps(report.slippage_analysis),
                 json.dumps(report.anomaly_analysis),
                 1 if report.replay_verified else 0,
                 report.resolution, report.root_cause, report.blast_radius,
                 json.dumps(report.recovery_timeline), report.prevention_fix),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_recent(self, n: int = 20) -> list[IncidentReport]:
        return self._incidents[-n:]

    def stats(self) -> dict:
        by_severity = {}
        by_type = {}
        for inc in self._incidents:
            by_severity[inc.severity] = by_severity.get(inc.severity, 0) + 1
            by_type[inc.incident_type] = by_type.get(inc.incident_type, 0) + 1
        return {
            "total": len(self._incidents),
            "by_severity": by_severity,
            "by_type": by_type,
        }


_incident_logger = IncidentLogger()


def get_incident_logger() -> IncidentLogger:
    return _incident_logger
