from __future__ import annotations

import logging
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class StageTiming:
    trace_id: str
    stage: str
    latency_us: int
    metadata: dict | None = None


@dataclass
class LatencyDistribution:
    p50_us: int
    p95_us: int
    p99_us: int
    mean_us: int
    min_us: int
    max_us: int
    count: int


class StageTimer:
    def __init__(self, max_ring_entries: int = 10_000,
                 max_per_stage: int = 1_000):
        self._ring: deque[StageTiming] = deque(maxlen=max_ring_entries)
        self._by_stage: dict[str, deque[int]] = {}
        self._max_per_stage = max_per_stage
        self._critical_overflow: int = 0

    def record(self, trace_id: str, stage: str, latency_us: int,
               metadata: dict | None = None, critical: bool = False) -> None:
        entry = StageTiming(
            trace_id=trace_id,
            stage=stage,
            latency_us=latency_us,
            metadata=metadata,
        )
        if critical:
            self._ring.append(entry)
        else:
            try:
                self._ring.append(entry)
            except Exception:
                pass

        if stage not in self._by_stage:
            self._by_stage[stage] = deque(maxlen=self._max_per_stage)
        self._by_stage[stage].append(latency_us)

    def get_by_trace(self, trace_id: str) -> list[StageTiming]:
        return [t for t in self._ring if t.trace_id == trace_id]

    def get_distribution(self, stage: str, n: int = 1000) -> LatencyDistribution:
        latencies = list(self._by_stage.get(stage, deque()))[-n:]
        if not latencies:
            return LatencyDistribution(0, 0, 0, 0, 0, 0, 0)
        sorted_lat = sorted(latencies)
        count = len(sorted_lat)
        return LatencyDistribution(
            p50_us=sorted_lat[int(count * 0.50)],
            p95_us=sorted_lat[int(count * 0.95)],
            p99_us=sorted_lat[min(count - 1, int(count * 0.99))],
            mean_us=sum(sorted_lat) // count,
            min_us=sorted_lat[0],
            max_us=sorted_lat[-1],
            count=count,
        )

    def get_all_distributions(self) -> dict[str, LatencyDistribution]:
        return {stage: self.get_distribution(stage) for stage in self._by_stage}

    def get_recent(self, n: int = 100) -> list[dict]:
        recent = list(self._ring)[-n:]
        return [
            {"trace_id": t.trace_id, "stage": t.stage,
             "latency_us": t.latency_us, "metadata": t.metadata}
            for t in recent
        ]

    def clear(self) -> None:
        self._ring.clear()
        self._by_stage.clear()
        self._critical_overflow = 0

    @contextmanager
    def measure(self, trace_id: str, stage: str, critical: bool = False):
        """Context manager: records latency_us on exit. Never raises on telemetry failure."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            try:
                elapsed_us = int((time.monotonic() - t0) * 1_000_000)
                self.record(trace_id, stage, elapsed_us, critical=critical)
            except Exception:
                pass  # fail-open: telemetry error never propagates


_timer = StageTimer()


def get_stage_timer() -> StageTimer:
    return _timer
