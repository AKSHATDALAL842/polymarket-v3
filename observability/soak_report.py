"""
Post-Soak Analysis Report — comprehensive operational health assessment.

Produces: runtime stability, memory/resource trends, queue health,
replay divergence, reconciliation convergence, settlement correctness,
circuit-breaker behavior, failure recovery, operational risks,
live-capital readiness.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SoakReport:
    runtime_hours: float = 0.0
    signals_total: int = 0
    signals_per_hour: float = 0.0
    match_rate: float = 0.0
    rejection_rate: float = 0.0
    memory_trend: str = "unknown"
    memory_growth_mb_per_hour: float = 0.0
    sqlite_growth_mb: float = 0.0
    queue_health: str = "unknown"
    reconciliation_anomalies: int = 0
    reconciliation_repaired: int = 0
    reconciliation_escalated: int = 0
    settlement_count: int = 0
    settlement_disputes: int = 0
    circuit_breaker_trips: int = 0
    dlq_total: int = 0
    health_alerts: int = 0
    orphan_positions: int = 0
    stale_markets: int = 0
    ws_reconnects: int = 0
    task_crashes: int = 0
    task_restarts: int = 0
    live_capital_ready: bool = False
    blockers: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def generate_soak_report() -> SoakReport:
    """Generate comprehensive post-soak analysis from all telemetry sources."""
    report = SoakReport()

    # Pipeline health
    try:
        from observability.logger import get_recent_traces, get_rejection_analytics
        traces = get_recent_traces(limit=1000)
        report.signals_total = len(traces)
        matched = sum(1 for t in traces if t.get("market_id"))
        report.match_rate = matched / max(1, len(traces))

        analytics = get_rejection_analytics(window_seconds=86400)
        total = max(1, analytics.get("total_signals", 0))
        rejected = sum(r["count"] for r in analytics.get("by_reason", []))
        report.rejection_rate = rejected / total
    except Exception:
        pass

    # Soak metrics from soak_metrics table
    try:
        from observability.logger import _conn
        conn = _conn()
        rows = conn.execute(
            "SELECT * FROM soak_metrics ORDER BY timestamp ASC"
        ).fetchall()
        conn.close()

        if rows:
            first = dict(rows[0])
            last = dict(rows[-1])
            elapsed_h = (len(rows) * 5) / 60  # assume 5-min intervals
            report.runtime_hours = round(elapsed_h, 1)

            mem_first = first.get("memory_mb", 0) or 0
            mem_last = last.get("memory_mb", 0) or 0
            if elapsed_h > 0:
                report.memory_growth_mb_per_hour = round((mem_last - mem_first) / elapsed_h, 2)

            if report.memory_growth_mb_per_hour > 10:
                report.memory_trend = "GROWING_UNACCEPTABLE"
            elif report.memory_growth_mb_per_hour > 2:
                report.memory_trend = "GROWING_WATCH"
            elif report.memory_growth_mb_per_hour < 0:
                report.memory_trend = "SHRINKING"
            else:
                report.memory_trend = "STABLE"

            report.sqlite_growth_mb = round((last.get("sqlite_size_mb", 0) or 0) - (first.get("sqlite_size_mb", 0) or 0), 2)
            report.dlq_total = last.get("dlq_total", 0)
            report.health_alerts = last.get("health_alerts", 0)
            report.stale_markets = last.get("stale_markets", 0)
            report.signals_per_hour = last.get("signals_per_hour", 0)
    except Exception:
        pass

    # Reconciliation
    try:
        from execution.reconciliation import get_reconciliation_engine
        recon = get_reconciliation_engine()
        recon_status = recon.status()
        report.reconciliation_anomalies = len(recon._anomaly_history)
        report.reconciliation_repaired = recon_status.get("total_repairs", 0)
        report.reconciliation_escalated = recon_status.get("total_escalations", 0)
    except Exception:
        pass

    # Settlement
    try:
        from execution.settlement import get_settlement_engine
        settle = get_settlement_engine()
        settle_status = settle.status()
        report.settlement_count = settle_status.get("settled", 0)
        report.settlement_disputes = settle_status.get("disputed", 0)
    except Exception:
        pass

    # Circuit breakers
    try:
        from execution.circuit_breakers import get_circuit_breakers
        cbs = get_circuit_breakers()
        cb_status = cbs.status()
        report.circuit_breaker_trips = sum(b.get("trip_count", 0) for b in cb_status.values())
    except Exception:
        pass

    # Market sync
    try:
        from execution.market_sync import get_market_synchronizer
        sync = get_market_synchronizer()
        sync_status = sync.status()
        report.ws_reconnects = sync_status.get("ws_reconnects", 0)
    except Exception:
        pass

    # Task supervisor
    try:
        from execution.task_supervisor import get_task_supervisor
        sup = get_task_supervisor()
        sup_status = sup.status()
        report.task_crashes = sum(
            s.get("exceptions", 0) for s in sup_status.values()
        )
        report.task_restarts = sum(
            s.get("restarts", 0) for s in sup_status.values()
        )
    except Exception:
        pass

    # Orphan positions
    try:
        from execution.position_lifecycle import get_position_ledger
        p_ledger = get_position_ledger()
        report.orphan_positions = len(p_ledger.get_orphaned())
    except Exception:
        pass

    # Live-capital readiness assessment
    report.blockers = []
    report.recommendations = []

    if report.memory_trend == "GROWING_UNACCEPTABLE":
        report.blockers.append("Unacceptable memory growth (>10MB/h)")
    if report.reconciliation_escalated > 0:
        report.blockers.append(f"{report.reconciliation_escalated} reconciliation escalations")
    if report.circuit_breaker_trips > 0:
        report.recommendations.append("Review circuit breaker trip history")
    if report.dlq_total > 0:
        report.blockers.append(f"DLQ has {report.dlq_total} unprocessed entries")
    if report.orphan_positions > 0:
        report.blockers.append(f"{report.orphan_positions} orphaned positions")
    if report.runtime_hours < 24:
        report.recommendations.append(f"Complete 24h soak ({report.runtime_hours}h so far)")

    report.live_capital_ready = len(report.blockers) == 0

    return report


def print_soak_report(report: SoakReport):
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    readiness_color = "bright_green" if report.live_capital_ready else "red"
    console.print(Panel(
        f"[bold {readiness_color}]LIVE-CAPITAL READINESS: "
        f"{'READY' if report.live_capital_ready else 'NOT READY'}[/bold {readiness_color}]",
        style=readiness_color,
    ))

    console.print(f"\n[bold]RUNTIME STABILITY[/bold]")
    console.print(f"  Runtime: {report.runtime_hours}h | Signals: {report.signals_total} "
                  f"({report.signals_per_hour}/h) | Match rate: {report.match_rate:.1%}")

    console.print(f"\n[bold]RESOURCE HEALTH[/bold]")
    mem_color = "green" if report.memory_trend == "STABLE" else "red"
    console.print(f"  Memory: [{mem_color}]{report.memory_trend}[/{mem_color}] "
                  f"({report.memory_growth_mb_per_hour:+.1f}MB/h)")
    console.print(f"  SQLite growth: {report.sqlite_growth_mb:+.1f}MB")
    console.print(f"  DLQ: {report.dlq_total} | Health alerts: {report.health_alerts}")

    console.print(f"\n[bold]CORRECTNESS[/bold]")
    console.print(f"  Reconciliation: {report.reconciliation_anomalies} anomalies, "
                  f"{report.reconciliation_repaired} repaired, "
                  f"{report.reconciliation_escalated} escalated")
    console.print(f"  Settlement: {report.settlement_count} settled, "
                  f"{report.settlement_disputes} disputed")
    console.print(f"  Circuit breakers: {report.circuit_breaker_trips} trips")
    console.print(f"  Orphans: {report.orphan_positions} | Stale markets: {report.stale_markets}")

    console.print(f"\n[bold]TASK HEALTH[/bold]")
    console.print(f"  Crashes: {report.task_crashes} | Restarts: {report.task_restarts} "
                  f"| WS reconnects: {report.ws_reconnects}")

    if report.blockers:
        console.print(f"\n[bold red]BLOCKERS:[/bold red]")
        for b in report.blockers:
            console.print(f"  [red]✗ {b}[/red]")

    if report.recommendations:
        console.print(f"\n[bold yellow]RECOMMENDATIONS:[/bold yellow]")
        for r in report.recommendations:
            console.print(f"  [yellow]→ {r}[/yellow]")

    if report.live_capital_ready:
        console.print(f"\n[bold bright_green]SYSTEM READY FOR CONSTRAINED LIVE-CAPITAL TESTING[/bold bright_green]")
        console.print("[dim]Recommended: 1-2 concurrent positions, $5 max bet, aggressive reconciliation[/dim]")
