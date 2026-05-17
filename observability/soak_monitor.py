"""
Automated soak test monitor — collects pipeline health, system health,
market health, and queue health every N minutes. Persists to SQLite.

Usage: python -m observability.soak_monitor [--interval 300] [--duration 86400]
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SOAK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS soak_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    uptime_seconds REAL,
    signals_total INTEGER,
    signals_per_hour REAL,
    matches_total INTEGER,
    rejection_rate REAL,
    nlp_impact_rejections INTEGER,
    no_match_rejections INTEGER,
    classifier_rejections INTEGER,
    edge_rejections INTEGER,
    nlp_p50_ms REAL,
    matcher_p50_ms REAL,
    classifier_p50_ms REAL,
    edge_p50_ms REAL,
    nlp_p95_ms REAL,
    classifier_p95_ms REAL,
    news_queue_depth INTEGER,
    cold_path_queue_depth INTEGER,
    dlq_total INTEGER,
    dlq_growth INTEGER,
    health_alerts INTEGER,
    tracked_markets INTEGER,
    stale_markets INTEGER,
    ws_connected INTEGER,
    memory_mb REAL,
    sqlite_size_mb REAL,
    signal_reviews_pending INTEGER,
    signal_reviews_labeled INTEGER,
    match_rate REAL
)
"""


@dataclass
class SoakSnapshot:
    timestamp: str
    uptime_seconds: float = 0
    signals_total: int = 0
    signals_per_hour: float = 0
    matches_total: int = 0
    rejection_rate: float = 0
    nlp_impact_rejections: int = 0
    no_match_rejections: int = 0
    classifier_rejections: int = 0
    edge_rejections: int = 0
    nlp_p50_ms: float = 0
    matcher_p50_ms: float = 0
    classifier_p50_ms: float = 0
    edge_p50_ms: float = 0
    nlp_p95_ms: float = 0
    classifier_p95_ms: float = 0
    news_queue_depth: int = 0
    cold_path_queue_depth: int = 0
    dlq_total: int = 0
    dlq_growth: int = 0
    health_alerts: int = 0
    tracked_markets: int = 0
    stale_markets: int = 0
    ws_connected: bool = False
    memory_mb: float = 0
    sqlite_size_mb: float = 0
    signal_reviews_pending: int = 0
    signal_reviews_labeled: int = 0
    match_rate: float = 0


class SoakMonitor:
    def __init__(self, interval: int = 300):
        self.interval = interval
        self._snapshots: list[SoakSnapshot] = []
        self._prev_dlq_total = 0
        self._prev_signals_total = 0
        self._start_time = time.monotonic()
        self._init_db()

    def _init_db(self):
        from observability.logger import _conn
        conn = _conn()
        conn.execute(SOAK_TABLE_SQL)
        conn.commit()
        conn.close()

    def capture(self, pipeline) -> SoakSnapshot:
        """Capture a full snapshot from the running pipeline."""
        now = datetime.now(timezone.utc).isoformat()

        # Pipeline health
        status = {}
        try:
            status = pipeline.status()
        except Exception:
            pass

        uptime = time.monotonic() - self._start_time
        signals_total = status.get("signals_generated", 0)
        signals_ph = (signals_total / (uptime / 3600)) if uptime > 0 else 0
        match_rate = 0.0

        # Rejection analytics
        from observability.logger import get_rejection_analytics, get_recent_traces
        try:
            analytics = get_rejection_analytics(window_seconds=86400)
            by_reason = {r["reason"]: r["count"] for r in analytics.get("by_reason", [])}
            nlp_impact_rej = by_reason.get("NLP_IMPACT_BELOW_THRESHOLD", 0)
            no_match_rej = by_reason.get("NO_MARKET_MATCHES", 0)
            classifier_rej = by_reason.get("CLASSIFIER_NOT_ACTIONABLE", 0) + by_reason.get("CLASSIFIER_HOT_PATH_FILTERED", 0)
            edge_rej = by_reason.get("EDGE_EV_BELOW_THRESHOLD", 0)
            total_sigs = max(1, analytics.get("total_signals", 0))
            rejection_rate = sum(by_reason.values()) / total_sigs
        except Exception:
            nlp_impact_rej = no_match_rej = classifier_rej = edge_rej = 0
            rejection_rate = 0.0

        # Match rate from traces
        try:
            traces = get_recent_traces(limit=200)
            matched = sum(1 for t in traces if t.get("market_id"))
            match_rate = matched / max(1, len(traces))
            matches_total = matched
        except Exception:
            matches_total = 0

        # Stage latency
        from observability.stage_timer import get_stage_timer
        timer = get_stage_timer()
        nlp_p50 = nlp_p95 = matcher_p50 = classifier_p50 = classifier_p95 = edge_p50 = 0.0
        try:
            dists = timer.get_all_distributions()
            nlp_p50 = dists.get("NLP", type('', (), {'p50_us': 0})()).p50_us / 1000
            nlp_p95 = dists.get("NLP", type('', (), {'p95_us': 0})()).p95_us / 1000
            matcher_p50 = dists.get("MATCHER", type('', (), {'p50_us': 0})()).p50_us / 1000
            classifier_p50 = dists.get("CLASSIFIER", type('', (), {'p50_us': 0})()).p50_us / 1000
            classifier_p95 = dists.get("CLASSIFIER", type('', (), {'p95_us': 0})()).p95_us / 1000
            edge_p50 = dists.get("EDGE", type('', (), {'p50_us': 0})()).p50_us / 1000
        except Exception:
            pass

        # Queue depths
        news_q = getattr(pipeline, '_news_queue', None)
        news_depth = news_q.qsize() if news_q else 0
        cold_q = 0

        # DLQ
        from observability.tracer import get_dlq
        dlq = get_dlq()
        dlq_total = dlq.stats().get("total", 0)
        dlq_growth = dlq_total - self._prev_dlq_total
        self._prev_dlq_total = dlq_total

        # Health alerts
        try:
            hm_status = pipeline._health_monitor.status()
            alerts = sum(
                wd.get("alert_count", 0)
                for wd in hm_status.get("watchdogs", [])
            )
        except Exception:
            alerts = 0

        # Market health
        tracked = len(pipeline.watcher.tracked_markets) if hasattr(pipeline, 'watcher') else 0
        stale = 0
        ws_ok = getattr(pipeline.watcher, '_ws_connected', False) if hasattr(pipeline, 'watcher') else False

        # System health
        try:
            import psutil
            mem = psutil.Process().memory_info().rss / 1024 / 1024
        except ImportError:
            mem = 0

        try:
            db_size = os.path.getsize("trades.db") / 1024 / 1024 if os.path.exists("trades.db") else 0
        except Exception:
            db_size = 0

        # Review queue
        try:
            from observability.signal_review import get_review_queue
            rq = get_review_queue()
            rq_stats = rq.stats()
            reviews_pending = rq_stats.get("pending_review", 0)
            reviews_labeled = rq_stats.get("reviewed", 0)
        except Exception:
            reviews_pending = reviews_labeled = 0

        snap = SoakSnapshot(
            timestamp=now,
            uptime_seconds=round(uptime, 1),
            signals_total=signals_total,
            signals_per_hour=round(signals_ph, 1),
            matches_total=matches_total,
            rejection_rate=round(rejection_rate, 4),
            nlp_impact_rejections=nlp_impact_rej,
            no_match_rejections=no_match_rej,
            classifier_rejections=classifier_rej,
            edge_rejections=edge_rej,
            nlp_p50_ms=round(nlp_p50, 2),
            matcher_p50_ms=round(matcher_p50, 2),
            classifier_p50_ms=round(classifier_p50, 2),
            edge_p50_ms=round(edge_p50, 2),
            nlp_p95_ms=round(nlp_p95, 2),
            classifier_p95_ms=round(classifier_p95, 2),
            news_queue_depth=news_depth,
            cold_path_queue_depth=cold_q,
            dlq_total=dlq_total,
            dlq_growth=dlq_growth,
            health_alerts=alerts,
            tracked_markets=tracked,
            stale_markets=stale,
            ws_connected=ws_ok,
            memory_mb=round(mem, 1),
            sqlite_size_mb=round(db_size, 2),
            signal_reviews_pending=reviews_pending,
            signal_reviews_labeled=reviews_labeled,
            match_rate=round(match_rate, 4),
        )

        self._snapshots.append(snap)
        if len(self._snapshots) > 300:
            self._snapshots = self._snapshots[-300:]

        self._persist(snap)
        return snap

    def _persist(self, snap: SoakSnapshot):
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT INTO soak_metrics
                   (timestamp, uptime_seconds, signals_total, signals_per_hour,
                    matches_total, rejection_rate, nlp_impact_rejections,
                    no_match_rejections, classifier_rejections, edge_rejections,
                    nlp_p50_ms, matcher_p50_ms, classifier_p50_ms, edge_p50_ms,
                    nlp_p95_ms, classifier_p95_ms, news_queue_depth,
                    cold_path_queue_depth, dlq_total, dlq_growth, health_alerts,
                    tracked_markets, stale_markets, ws_connected, memory_mb,
                    sqlite_size_mb, signal_reviews_pending, signal_reviews_labeled,
                    match_rate)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snap.timestamp, snap.uptime_seconds, snap.signals_total,
                 snap.signals_per_hour, snap.matches_total, snap.rejection_rate,
                 snap.nlp_impact_rejections, snap.no_match_rejections,
                 snap.classifier_rejections, snap.edge_rejections,
                 snap.nlp_p50_ms, snap.matcher_p50_ms, snap.classifier_p50_ms,
                 snap.edge_p50_ms, snap.nlp_p95_ms, snap.classifier_p95_ms,
                 snap.news_queue_depth, snap.cold_path_queue_depth,
                 snap.dlq_total, snap.dlq_growth, snap.health_alerts,
                 snap.tracked_markets, snap.stale_markets,
                 1 if snap.ws_connected else 0,
                 snap.memory_mb, snap.sqlite_size_mb,
                 snap.signal_reviews_pending, snap.signal_reviews_labeled,
                 snap.match_rate),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_report(self) -> dict:
        if not self._snapshots:
            return {"status": "no_data"}
        latest = self._snapshots[-1]
        first = self._snapshots[0]

        # Memory trend
        mem_trend = "stable"
        if len(self._snapshots) >= 3:
            first_mem = self._snapshots[0].memory_mb
            last_mem = self._snapshots[-1].memory_mb
            if last_mem > first_mem * 1.5:
                mem_trend = f"GROWING (+{last_mem - first_mem:.1f}MB)"
            elif last_mem < first_mem * 0.9:
                mem_trend = "shrinking"

        # Signal trend
        sig_trend = "stable"
        if len(self._snapshots) >= 3:
            first_sph = self._snapshots[0].signals_per_hour
            last_sph = self._snapshots[-1].signals_per_hour
            if last_sph < first_sph * 0.5:
                sig_trend = "DECLINING"
            elif last_sph > first_sph * 1.5:
                sig_trend = "increasing"

        # DLQ trend
        dlq_trend = "clean" if latest.dlq_total == 0 else (
            "GROWING" if latest.dlq_growth > 0 else "stable"
        )

        return {
            "runtime_hours": round(latest.uptime_seconds / 3600, 1),
            "signals_total": latest.signals_total,
            "signals_per_hour": latest.signals_per_hour,
            "signal_trend": sig_trend,
            "match_rate": latest.match_rate,
            "rejection_rate": latest.rejection_rate,
            "memory_mb": latest.memory_mb,
            "memory_trend": mem_trend,
            "sqlite_mb": latest.sqlite_size_mb,
            "dlq_total": latest.dlq_total,
            "dlq_trend": dlq_trend,
            "health_alerts": latest.health_alerts,
            "tracked_markets": latest.tracked_markets,
            "ws_connected": latest.ws_connected,
            "snapshots_collected": len(self._snapshots),
            "stage_latency": {
                "nlp_p50": latest.nlp_p50_ms,
                "matcher_p50": latest.matcher_p50_ms,
                "classifier_p50": latest.classifier_p50_ms,
                "edge_p50": latest.edge_p50_ms,
            },
        }

    def print_report(self):
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()
        report = self.get_report()

        if report.get("status") == "no_data":
            console.print("[yellow]No soak data collected yet[/yellow]")
            return

        console.print(Panel(f"[bold bright_cyan]SOAK TEST REPORT[/bold bright_cyan] "
                            f"({report['runtime_hours']}h runtime)",
                            style="bright_cyan"))

        table = Table(show_header=False, padding=(0, 1))
        table.add_column("Metric", style="bold", width=25)
        table.add_column("Value")

        table.add_row("Runtime", f"{report['runtime_hours']}h")
        table.add_row("Signals total", str(report['signals_total']))
        table.add_row("Signals/hour", str(report['signals_per_hour']))
        table.add_row("Signal trend", f"[{'green' if report['signal_trend']=='stable' else 'red'}]{report['signal_trend']}[/]")
        table.add_row("Match rate", f"{report['match_rate']:.1%}")
        table.add_row("Rejection rate", f"{report['rejection_rate']:.1%}")
        table.add_row("Memory", f"{report['memory_mb']}MB [{report['memory_trend']}]")
        table.add_row("SQLite", f"{report['sqlite_mb']}MB")
        table.add_row("DLQ", f"{report['dlq_total']} [{report['dlq_trend']}]")
        table.add_row("Health alerts", str(report['health_alerts']))
        table.add_row("Markets tracked", str(report['tracked_markets']))
        table.add_row("WebSocket", "connected" if report['ws_connected'] else "disconnected")
        table.add_row("Snapshots", str(report['snapshots_collected']))
        console.print(table)

        # Stage latency
        lat = report['stage_latency']
        console.print(f"\n[bold]Stage latency (p50):[/bold] NLP={lat['nlp_p50']}ms "
                      f"Matcher={lat['matcher_p50']}ms "
                      f"Classifier={lat['classifier_p50']}ms "
                      f"Edge={lat['edge_p50']}ms")

        # Alerts
        if report['dlq_total'] > 0:
            console.print(f"\n[red]DLQ has {report['dlq_total']} entries — investigate[/red]")
        if report['health_alerts'] > 0:
            console.print(f"\n[yellow]{report['health_alerts']} health alerts — investigate[/yellow]")
        if report['memory_trend'] == 'GROWING':
            console.print(f"\n[red]Memory is growing — possible leak[/red]")
        if report['signal_trend'] == 'DECLINING':
            console.print(f"\n[red]Signal throughput declining — possible degradation[/red]")
        if not report['ws_connected']:
            console.print(f"\n[yellow]WebSocket disconnected — price feed offline[/yellow]")


_soak_monitor = None


def get_soak_monitor(interval: int = 300) -> SoakMonitor:
    global _soak_monitor
    if _soak_monitor is None:
        _soak_monitor = SoakMonitor(interval=interval)
    return _soak_monitor
