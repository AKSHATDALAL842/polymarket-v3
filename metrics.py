"""
Performance Metrics — live tracking of key trading statistics.

Tracks:
  - Sharpe ratio (rolling)
  - Win rate
  - Average EV per trade
  - Latency distribution (p50, p95, p99)
  - Drawdown (current + max)
  - Trade frequency
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class LatencyStats:
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    n: int


@dataclass
class PerformanceSnapshot:
    n_trades: int
    win_rate: float
    avg_ev: float
    total_pnl: float
    sharpe: float
    current_drawdown: float
    max_drawdown: float
    latency: LatencyStats
    trades_per_hour: float
    uptime_seconds: float


class MetricsTracker:
    """
    Rolling metrics tracker. Call record_trade() after each execution.
    All windows are in-memory; no persistence (use logger for that).
    """

    WINDOW = 100   # rolling window size for Sharpe

    def __init__(self):
        self._pnl_window: Deque[float] = deque(maxlen=self.WINDOW)
        self._latency_window: Deque[int] = deque(maxlen=500)
        self._ev_window: Deque[float] = deque(maxlen=self.WINDOW)
        self._all_pnl: list[float] = []
        self._start_time: float = time.monotonic()
        self._n_wins: int = 0
        self._n_total: int = 0
        self._peak_cumulative: float = 0.0
        self._cumulative_pnl: float = 0.0
        self._max_drawdown: float = 0.0

    def record_trade(
        self,
        pnl: float,
        ev: float,
        latency_ms: int,
    ):
        self._n_total += 1
        if pnl > 0:
            self._n_wins += 1

        self._pnl_window.append(pnl)
        self._all_pnl.append(pnl)
        self._ev_window.append(ev)
        self._latency_window.append(latency_ms)

        self._cumulative_pnl += pnl
        if self._cumulative_pnl > self._peak_cumulative:
            self._peak_cumulative = self._cumulative_pnl
        drawdown = self._peak_cumulative - self._cumulative_pnl
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown

    def snapshot(self) -> PerformanceSnapshot:
        return PerformanceSnapshot(
            n_trades=self._n_total,
            win_rate=self._n_wins / self._n_total if self._n_total else 0.0,
            avg_ev=statistics.mean(self._ev_window) if self._ev_window else 0.0,
            total_pnl=self._cumulative_pnl,
            sharpe=self._rolling_sharpe(),
            current_drawdown=max(0.0, self._peak_cumulative - self._cumulative_pnl),
            max_drawdown=self._max_drawdown,
            latency=self._latency_stats(),
            trades_per_hour=self._trades_per_hour(),
            uptime_seconds=time.monotonic() - self._start_time,
        )

    def _rolling_sharpe(self) -> float:
        if len(self._pnl_window) < 5:
            return 0.0
        try:
            mean = statistics.mean(self._pnl_window)
            std = statistics.stdev(self._pnl_window)
            if std == 0:
                return 0.0
            return mean / std * (252 ** 0.5)   # annualized
        except Exception:
            return 0.0

    def _latency_stats(self) -> LatencyStats:
        if not self._latency_window:
            return LatencyStats(0, 0, 0, 0, 0)
        sorted_lat = sorted(self._latency_window)
        n = len(sorted_lat)
        return LatencyStats(
            p50_ms=sorted_lat[int(n * 0.50)],
            p95_ms=sorted_lat[int(n * 0.95)],
            p99_ms=sorted_lat[min(n - 1, int(n * 0.99))],
            mean_ms=int(statistics.mean(sorted_lat)),
            n=n,
        )

    def _trades_per_hour(self) -> float:
        elapsed_hours = (time.monotonic() - self._start_time) / 3600
        return self._n_total / elapsed_hours if elapsed_hours > 0 else 0.0

    def print_snapshot(self):
        from rich.console import Console
        from rich.table import Table
        console = Console()
        snap = self.snapshot()

        table = Table(title="Live Performance", header_style="bold cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        pnl_color = "bright_green" if snap.total_pnl >= 0 else "red"
        wr_color = "bright_green" if snap.win_rate >= 0.55 else ("yellow" if snap.win_rate >= 0.45 else "red")
        sharpe_color = "bright_green" if snap.sharpe >= 1 else ("yellow" if snap.sharpe >= 0 else "red")

        rows = [
            ("Trades", str(snap.n_trades)),
            ("Win Rate", f"[{wr_color}]{snap.win_rate:.1%}[/{wr_color}]"),
            ("Total PnL", f"[{pnl_color}]${snap.total_pnl:+.2f}[/{pnl_color}]"),
            ("Avg EV", f"{snap.avg_ev:.4f}"),
            ("Sharpe (rolling)", f"[{sharpe_color}]{snap.sharpe:.2f}[/{sharpe_color}]"),
            ("Current Drawdown", f"${snap.current_drawdown:.2f}"),
            ("Max Drawdown", f"${snap.max_drawdown:.2f}"),
            ("Latency p50/p95/p99", f"{snap.latency.p50_ms}/{snap.latency.p95_ms}/{snap.latency.p99_ms}ms"),
            ("Trades/Hour", f"{snap.trades_per_hour:.1f}"),
        ]
        for label, val in rows:
            table.add_row(label, val)
        console.print(table)


# Module-level singleton
_tracker = MetricsTracker()


def get_tracker() -> MetricsTracker:
    return _tracker
