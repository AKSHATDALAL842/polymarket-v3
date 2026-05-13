#!/usr/bin/env python3
from __future__ import annotations

import time
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

import config
from observability import logger
from ingestion.scraper import scrape_all
from ingestion.markets import fetch_active_markets, filter_by_categories

console = Console()

ACCENT = "bright_green"
DIM = "bright_black"
WARN = "yellow"
LOSS = "red"
WIN = "bright_green"
MUTED = "dim white"


class PipelineState:
    def __init__(self):
        self.run_number = 0
        self.markets_scanned = 0
        self.headlines_found = 0
        self.latest_headlines = []
        self.latest_markets = []
        self.scanning = False
        self.scan_status = "Initializing..."


state = PipelineState()


def run_scan_cycle():
    state.run_number += 1
    state.scanning = True
    state.scan_status = "Scraping news..."

    news = scrape_all()
    state.headlines_found = len(news)
    state.latest_headlines = [
        {"headline": n.headline, "source": n.source, "age": f"{n.age_hours():.1f}h"}
        for n in news[:8]
    ]

    state.scan_status = "Fetching markets..."
    all_markets = fetch_active_markets(limit=100)
    markets = filter_by_categories(all_markets)[:12]
    state.markets_scanned = len(markets)
    state.latest_markets = markets

    state.scanning = False
    state.scan_status = "Idle — waiting for next cycle"


def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )
    layout["left"].split_column(
        Layout(name="status", ratio=1),
        Layout(name="performance", ratio=1),
    )
    layout["right"].split_column(
        Layout(name="scanner", ratio=2),
        Layout(name="trades", ratio=3),
    )
    return layout


def render_header() -> Panel:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="center", ratio=2)
    grid.add_column(justify="right", ratio=1)
    grid.add_row(
        Text(" POLYMARKET PIPELINE", style="bold bright_green"),
        Text("NEWS MONITOR + MARKET DISPLAY", style=DIM),
        Text(f"{now} ", style=MUTED),
    )
    return Panel(grid, style="bright_green", box=box.HEAVY)


def render_status() -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
    table.add_column("label", style=MUTED, width=18)
    table.add_column("value", style=ACCENT)

    if state.scanning:
        status_dot = "[yellow]◌[/yellow]"
        status_text = f"{status_dot} SCANNING"
    elif state.run_number > 0:
        status_dot = "[bright_green]●[/bright_green]"
        status_text = f"{status_dot} ACTIVE"
    else:
        status_dot = "[yellow]○[/yellow]"
        status_text = f"{status_dot} STARTING"

    table.add_row("Pipeline", status_text)
    table.add_row("Scan Cycle", f"#{state.run_number}" if state.run_number > 0 else "—")
    table.add_row("Activity", f"[{DIM}]{state.scan_status[:30]}[/{DIM}]")
    table.add_row("Markets Scanned", str(state.markets_scanned) if state.run_number > 0 else "—")
    table.add_row("Headlines Found", str(state.headlines_found) if state.run_number > 0 else "—")
    table.add_row("", "")
    table.add_row("Edge Threshold", f">= {config.EDGE_THRESHOLD:.0%}")
    table.add_row("Max Bet", f"${config.MAX_BET_USD:.2f}")
    table.add_row("Daily Limit", f"${config.DAILY_LOSS_LIMIT_USD:.2f}")
    mode = "[bright_green]LIVE[/bright_green]" if not config.DRY_RUN else f"[{WARN}]DRY RUN[/{WARN}]"
    table.add_row("Mode", mode)

    return Panel(table, title="[bold]PIPELINE STATUS[/bold]", border_style="bright_green", box=box.ROUNDED)


def render_performance() -> Panel:
    stats = logger.get_trade_stats()
    trades = logger.get_recent_trades(limit=100)
    daily_spent = abs(logger.get_daily_pnl())

    total = stats["total_trades"]
    by_status = stats["by_status"]
    dry_runs = by_status.get("dry_run", 0)
    executed = by_status.get("executed", 0)
    paper = by_status.get("paper", 0)
    errors = sum(v for k, v in by_status.items() if k.startswith("error") or "rejected" in k)

    total_wagered = sum(t.get("amount_usd", 0) for t in trades)
    avg_edge = sum(t.get("edge", 0) for t in trades) / max(len(trades), 1) * 100

    table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
    table.add_column("label", style=MUTED, width=18)
    table.add_column("value")

    table.add_row("Total Signals", f"[{ACCENT}]{total}[/{ACCENT}]")
    table.add_row("Paper Trades", f"[{WARN}]{paper}[/{WARN}]")
    table.add_row("Executed", f"[{WIN}]{executed}[/{WIN}]")
    if dry_runs:
        table.add_row("Dry Runs", f"[{WARN}]{dry_runs}[/{WARN}]")
    if errors:
        table.add_row("Errors", f"[{LOSS}]{errors}[/{LOSS}]")
    table.add_row("", "")
    table.add_row("Daily Exposure", f"[{ACCENT}]${daily_spent:.2f}[/{ACCENT}]")
    table.add_row("Total Wagered", f"[{ACCENT}]${total_wagered:.2f}[/{ACCENT}]")
    table.add_row("Avg Edge", f"[{ACCENT}]{avg_edge:.1f}%[/{ACCENT}]")
    table.add_row("", "")

    if trades:
        best = max(t.get("edge", 0) for t in trades)
        table.add_row("Best Edge", f"[{WIN}]{best:.1%}[/{WIN}]")

    return Panel(table, title="[bold]PERFORMANCE[/bold]", border_style="bright_cyan", box=box.ROUNDED)


def render_scanner() -> Panel:
    content = Table(show_header=True, box=box.SIMPLE_HEAD, expand=True, padding=(0, 1))
    content.add_column("Market", max_width=38)
    content.add_column("YES$", justify="right", width=5)
    content.add_column("NO$", justify="right", width=5)
    content.add_column("Volume", justify="right", width=10)
    content.add_column("Category", justify="center", width=10)

    if not state.latest_markets:
        content.add_row(f"[{DIM}]Waiting for first scan...[/{DIM}]", "", "", "", "")
        return Panel(content, title="[bold]MARKET WATCH[/bold]  ·  Active Markets", border_style="bright_green", box=box.ROUNDED)

    for m in state.latest_markets[:12]:
        content.add_row(
            m.question[:38],
            f"{m.yes_price:.2f}",
            f"{m.no_price:.2f}",
            f"${m.volume:,.0f}",
            m.category[:10],
        )

    return Panel(content, title="[bold]MARKET WATCH[/bold]  ·  Active Markets", border_style="bright_green", box=box.ROUNDED)


def render_trades() -> Panel:
    trades = logger.get_recent_trades(limit=10)

    table = Table(show_header=True, box=box.SIMPLE_HEAD, expand=True, padding=(0, 1))
    table.add_column("Time", width=16, style=MUTED)
    table.add_column("Market", max_width=38)
    table.add_column("Side", justify="center", width=5)
    table.add_column("Bet", justify="right", width=7)
    table.add_column("Edge", justify="right", width=6)
    table.add_column("Mkt$", justify="right", width=5)
    table.add_column("Status", justify="center", width=9)

    if not trades:
        table.add_row(f"[{DIM}]No trades yet — run the pipeline to generate signals[/{DIM}]", "", "", "", "", "", "")
    else:
        for t in trades:
            side_style = WIN if t["side"] == "YES" else "bright_magenta"
            status = t["status"]
            if status == "dry_run":
                status_str = f"[{WARN}]DRY_RUN[/{WARN}]"
            elif status == "executed":
                status_str = f"[{WIN}]FILLED[/{WIN}]"
            elif status == "paper":
                status_str = f"[{WARN}]PAPER[/{WARN}]"
            elif status.startswith("error"):
                status_str = f"[{LOSS}]ERROR[/{LOSS}]"
            elif "rejected" in status:
                status_str = f"[{LOSS}]REJECTED[/{LOSS}]"
            else:
                status_str = f"[{DIM}]{status[:9]}[/{DIM}]"

            table.add_row(
                t["created_at"][:16],
                t["market_question"][:38],
                f"[{side_style}]{t['side']}[/{side_style}]",
                f"${t['amount_usd']:.2f}",
                f"{t['edge']:.0%}",
                f"{t['market_price']:.2f}",
                status_str,
            )

    return Panel(table, title="[bold]TRADE LOG[/bold]  ·  Recent Trades", border_style="bright_cyan", box=box.ROUNDED)


def render_footer() -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=2)
    grid.add_column(justify="center", ratio=3)
    grid.add_column(justify="right", ratio=2)

    if state.latest_headlines:
        h = state.latest_headlines[0]
        headline_text = f"[{ACCENT}]>[/{ACCENT}] [{MUTED}]{h['source']}:[/{MUTED}] {h['headline'][:80]}"
    else:
        headline_text = f"[{DIM}]Waiting for news feed...[/{DIM}]"

    stats = logger.get_trade_stats()
    mode = "LIVE" if not config.DRY_RUN else "DRY"

    grid.add_row(
        headline_text,
        f"[{DIM}]Ctrl+C to exit[/{DIM}]",
        f"[{DIM}]{mode}[/{DIM}]  |  Signals: [{ACCENT}]{stats['total_trades']}[/{ACCENT}] ",
    )
    return Panel(grid, style="bright_green", box=box.HEAVY)


def run_dashboard(scan_interval: float = 60.0):
    layout = make_layout()

    layout["header"].update(render_header())
    layout["status"].update(render_status())
    layout["performance"].update(render_performance())
    layout["scanner"].update(render_scanner())
    layout["trades"].update(render_trades())
    layout["footer"].update(render_footer())

    try:
        with Live(layout, console=console, refresh_per_second=2, screen=True) as live:
            last_scan = 0.0

            while True:
                now = time.time()

                if now - last_scan >= scan_interval:
                    run_scan_cycle()
                    last_scan = now

                layout["header"].update(render_header())
                layout["status"].update(render_status())
                layout["performance"].update(render_performance())
                layout["scanner"].update(render_scanner())
                layout["trades"].update(render_trades())
                layout["footer"].update(render_footer())

                time.sleep(0.5)

    except KeyboardInterrupt:
        stats = logger.get_trade_stats()
        console.print(f"\n[{ACCENT}]Dashboard stopped. {stats['total_trades']} signals logged across {state.run_number} cycles.[/{ACCENT}]")


if __name__ == "__main__":
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    run_dashboard(scan_interval=interval)
