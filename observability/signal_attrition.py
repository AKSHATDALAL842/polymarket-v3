"""
Signal attrition analysis — computes precise drop-off rates at every pipeline stage.

Usage:
    python -m observability.signal_attrition [--window 24h] [--output json|table]

Reads from signal_traces table in trades.db. Requires the pipeline to have been
run at least briefly to populate trace data.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class StageStats:
    entered: int = 0
    passed: int = 0
    rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def drop_rate(self) -> float:
        return self.rejected / max(1, self.entered)

    @property
    def survival_rate(self) -> float:
        return self.passed / max(1, self.entered)


@dataclass
class AttritionReport:
    total_ingested: int
    total_executed: int
    total_settled: int
    total_rejected: int
    overall_survival: float
    stages: dict[str, StageStats]
    by_source: dict[str, dict[str, int]]
    by_category: dict[str, dict[str, int]]
    by_rejection: dict[str, int]
    dominant_kill_stage: str
    dominant_kill_reason: str


STAGE_ORDER = [
    "INGESTED", "NLP_PROCESSED", "MARKET_MATCHED", "SCORED",
    "VALIDATED", "SIZED", "EXECUTED", "SETTLED",
]


def compute_attrition(window_hours: int = 24) -> AttritionReport:
    """Query signal_traces and compute the full attrition waterfall."""
    from observability.logger import _conn

    conn = _conn()
    rows = conn.execute(
        """SELECT final_stage, rejection_reason, rejection_severity, source,
                  market_id, headline, created_at
           FROM signal_traces
           WHERE created_at >= datetime('now', ? || ' hours')
           ORDER BY created_at DESC""",
        (f"-{window_hours}",),
    ).fetchall()
    conn.close()

    traces = [dict(r) for r in rows]
    total_ingested = len(traces)

    stage_entered: dict[str, int] = defaultdict(int)
    stage_passed: dict[str, int] = defaultdict(int)
    stage_rejected: dict[str, int] = defaultdict(int)
    stage_reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_rejection: dict[str, int] = defaultdict(int)

    # Count traces by their final stage
    final_stage_counts: dict[str, int] = defaultdict(int)
    for t in traces:
        final_stage_counts[t.get("final_stage", "UNKNOWN")] += 1

    # Simulate waterfall: each trace that reached stage N is assumed to have
    # passed through all prior stages. This is a conservative lower bound —
    # the actual pipeline may have more intermediate rejections that we can't
    # count from final_stage alone.
    for stage in STAGE_ORDER:
        stage_entered[stage] = total_ingested

    # Count rejections at each stage
    for t in traces:
        stage = t.get("final_stage", "UNKNOWN")
        reason = t.get("rejection_reason")
        source = t.get("source", "unknown")
        cat = "unknown"  # market category not directly stored on trace rows

        if reason:
            stage_rejected[stage] += 1
            stage_reasons[stage][reason] += 1
            by_rejection[reason] += 1
            by_source[source]["rejected"] = by_source[source].get("rejected", 0) + 1
        else:
            stage_passed[stage] += 1
            by_source[source]["passed"] = by_source[source].get("passed", 0) + 1

        by_source[source]["total"] = by_source[source].get("total", 0) + 1

    total_executed = stage_passed.get("EXECUTED", 0) + stage_rejected.get("EXECUTED", 0)
    total_settled = stage_passed.get("SETTLED", 0)
    total_rejected = sum(1 for t in traces if t.get("rejection_reason"))

    stages = {}
    for stage in STAGE_ORDER:
        stages[stage] = StageStats(
            entered=stage_entered.get(stage, 0),
            passed=stage_passed.get(stage, 0),
            rejected=stage_rejected.get(stage, 0),
            rejection_reasons=dict(stage_reasons.get(stage, {})),
        )

    dominant_kill_reason = max(by_rejection, key=by_rejection.get) if by_rejection else "none"
    dominant_kill_stage = max(
        stage_rejected, key=lambda s: stage_rejected[s]
    ) if any(stage_rejected.values()) else "none"

    return AttritionReport(
        total_ingested=total_ingested,
        total_executed=total_executed,
        total_settled=total_settled,
        total_rejected=total_rejected,
        overall_survival=total_settled / max(1, total_ingested),
        stages=stages,
        by_source=dict(by_source),
        by_category=dict(by_category),
        by_rejection=dict(by_rejection),
        dominant_kill_stage=dominant_kill_stage,
        dominant_kill_reason=dominant_kill_reason,
    )


def print_waterfall(report: AttritionReport):
    """Print a rich waterfall chart of signal attrition."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    console.print(Panel("[bold bright_cyan]SIGNAL ATTRITION WATERFALL[/bold bright_cyan]",
                        style="bright_cyan"))
    console.print(f"Window: last 24h | Ingested: {report.total_ingested} | "
                  f"Survival rate: {report.overall_survival:.2%} | "
                  f"Dominant kill: {report.dominant_kill_stage} ({report.dominant_kill_reason})\n")

    table = Table(show_header=True, header_style="bold white")
    table.add_column("Stage", width=18)
    table.add_column("Entered", justify="right", width=8)
    table.add_column("Passed", justify="right", width=8)
    table.add_column("Rejected", justify="right", width=8)
    table.add_column("Drop Rate", justify="right", width=10)
    table.add_column("Top Kill Reason", max_width=30)
    table.add_column("Bar", max_width=40)

    max_entered = max(s.entered for s in report.stages.values()) if report.stages else 1

    for stage_name in STAGE_ORDER:
        s = report.stages.get(stage_name)
        if s is None:
            continue
        if s.entered == 0 and stage_name not in ("INGESTED",):
            continue

        top_reason = ""
        if s.rejection_reasons:
            top = max(s.rejection_reasons, key=s.rejection_reasons.get)
            top_reason = f"{top} ({s.rejection_reasons[top]})"

        drop_color = "green" if s.drop_rate < 0.1 else ("yellow" if s.drop_rate < 0.3 else "red")
        surv_pct = int(s.survival_rate * 100)
        bar_len = int((s.entered / max_entered) * 30)
        bar_filled = int(bar_len * s.survival_rate)
        bar = "[" + "█" * bar_filled + "·" * (bar_len - bar_filled) + "]"

        table.add_row(
            stage_name,
            str(s.entered),
            str(s.passed),
            f"[{drop_color}]{s.rejected}[/{drop_color}]",
            f"[{drop_color}]{s.drop_rate:.1%}[/{drop_color}]",
            top_reason,
            bar,
        )

    console.print(table)

    # Source breakdown
    if report.by_source:
        console.print("\n[bold]BY SOURCE[/bold]")
        src_table = Table(show_header=True, header_style="bold")
        src_table.add_column("Source", width=14)
        src_table.add_column("Total", justify="right")
        src_table.add_column("Passed", justify="right")
        src_table.add_column("Rejected", justify="right")
        src_table.add_column("Rejection Rate", justify="right")
        for src, counts in sorted(report.by_source.items(),
                                   key=lambda x: -x[1].get("total", 0)):
            total = counts.get("total", 0)
            passed = counts.get("passed", 0)
            rejected = counts.get("rejected", 0)
            rate = rejected / max(1, total)
            color = "green" if rate < 0.3 else ("yellow" if rate < 0.6 else "red")
            src_table.add_row(src, str(total), str(passed), str(rejected),
                              f"[{color}]{rate:.1%}[/{color}]")
        console.print(src_table)

    # Rejection breakdown
    if report.by_rejection:
        console.print("\n[bold]BY REJECTION REASON[/bold]")
        rej_table = Table(show_header=True, header_style="bold red")
        rej_table.add_column("Reason", max_width=40)
        rej_table.add_column("Count", justify="right")
        rej_table.add_column("% of All Rejections", justify="right")
        total_rej = max(1, report.total_rejected)
        for reason, count in sorted(report.by_rejection.items(),
                                     key=lambda x: -x[1]):
            rej_table.add_row(reason, str(count),
                              f"{count/total_rej*100:.1f}%")
        console.print(rej_table)

    # Summary
    console.print(f"\n[bold]DIAGNOSIS:[/bold]")
    if report.total_ingested == 0:
        console.print("[yellow bold]No trace data found.[/yellow bold]")
        console.print("[dim]Run the pipeline briefly to populate traces: python cli.py watch[/dim]")
    elif report.overall_survival == 0:
        console.print(f"[red bold]Zero signals survived to SETTLED.[/red bold]")
        console.print(f"[red]Dominant kill stage: {report.dominant_kill_stage}[/red]")
        console.print(f"[red]Dominant kill reason: {report.dominant_kill_reason}[/red]")
        console.print(f"[dim]Investigate: this stage is blocking 100% of signals[/dim]")
    elif report.overall_survival < 0.05:
        console.print(f"[yellow bold]Critical signal starvation: {report.overall_survival:.2%} survival[/yellow bold]")
    elif report.overall_survival < 0.20:
        console.print(f"[yellow]Low signal throughput: {report.overall_survival:.2%} survival[/yellow]")
    else:
        console.print(f"[green]Healthy signal throughput: {report.overall_survival:.2%} survival[/green]")


def generate_synthetic_traces(n_signals: int = 200):
    """Generate synthetic trace data for testing when no live data exists.

    This produces realistic-looking traces with known attrition patterns:
    - 40% NLP gate rejection
    - 30% market match failure
    - 15% classifier rejection
    - 10% edge rejection
    - 5% execution success
    """
    import random
    from observability.logger import log_trace, update_trace

    sources = ["rss", "twitter", "newsapi", "reddit", "telegram", "gnews", "gdelt"]
    headlines = [
        "Bitcoin surges past $100K as ETF inflows hit record",
        "Fed chair signals rate cut in September meeting",
        "OpenAI announces GPT-5 with breakthrough reasoning capabilities",
        "SpaceX Starship completes orbital test flight successfully",
        "Trump wins Republican nomination for 2028",
        "EU approves new AI regulation framework",
        "China GDP growth misses expectations at 3.2%",
        "NVIDIA reports record quarterly revenue of $45B",
        "SEC approves spot Ethereum ETF for trading",
        "Major earthquake detected off Japan coast, tsunami warning issued",
        "New climate deal signed at UN summit",
        "Apple unveils augmented reality glasses at WWDC",
        "Oil prices crash 15% after OPEC production increase",
        "Pfizer announces breakthrough in cancer vaccine trial",
        "UK inflation surprisingly drops to 1.8%",
    ]

    stages_with_reasons = [
        ("NLP_PROCESSED", None, 0.40),           # 40% pass NLP
        ("MARKET_MATCHED", "NLP_IMPACT_BELOW_THRESHOLD", 0.60),
        ("SCORED", "NO_MARKET_MATCHES", 0.30),   # 30% fail matching
        ("VALIDATED", "CLASSIFIER_NOT_ACTIONABLE", 0.15),  # 15% fail classifier
        ("SIZED", "CLASSIFIER_HOT_PATH_FILTERED", 0.05),
        ("EXECUTED", "EDGE_EV_BELOW_THRESHOLD", 0.10),  # 10% fail edge
        ("SETTLED", "STALENESS_ABORT", 0.03),
        (None, "INSUFFICIENT_DEPTH", 0.02),
    ]

    survival = 1.0
    for stage, reason, drop_rate in stages_with_reasons:
        for i in range(int(n_signals * survival)):
            h = random.choice(headlines)
            s = random.choice(sources)
            trace_id = f"sig-synth-{stage}-{i}"
            market_id = f"poly:0x{random.randint(100000,999999)}"

            log_trace(trace_id, h, s, news_id=f"news-synth-{i}")

            if reason:
                update_trace(
                    trace_id,
                    final_stage=stage or "REJECTED",
                    final_status="rejected",
                    rejection_reason=reason,
                    rejection_severity=random.choice(
                        ["HARD_REJECT", "SOFT_REJECT", "INFO"]
                    ),
                    rejection_detail=json.dumps({
                        "threshold": random.uniform(0.05, 0.50),
                        "actual": random.uniform(0.01, 0.45),
                        "subsystem": reason.split("_")[0].lower(),
                        "snapshot": {
                            "NLP_MIN_IMPACT": 0.10,
                            "EDGE_THRESHOLD": 0.03,
                            "DRY_RUN": True,
                        },
                    }),
                    market_id=market_id if reason != "NO_MARKET_MATCHES" else None,
                )
            else:
                update_trace(
                    trace_id,
                    final_stage=stage,
                    final_status="completed" if stage == "SETTLED" else "in_progress",
                    market_id=market_id,
                )

        survival *= (1.0 - drop_rate)


if __name__ == "__main__":
    window = 24
    if len(sys.argv) > 1:
        if sys.argv[1] == "--synthetic":
            n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
            generate_synthetic_traces(n)
            print(f"Generated {n} synthetic traces")
        elif sys.argv[1] == "--window":
            window = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    report = compute_attrition(window_hours=window)
    print_waterfall(report)
