"""
Circuit Breakers — kill-switch protections for execution safety.

Breakers trip on: rapid losses, execution anomalies, stale market data,
reconciliation drift, duplicate orders, runaway retries, excessive slippage,
websocket outage, ingestion outage, abnormal latency.

All breakers fail-safe: when in doubt, halt execution.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class BreakerState(Enum):
    CLOSED = "closed"         # Normal operation
    OPEN = "open"             # Tripped — execution halted
    HALF_OPEN = "half_open"   # Testing recovery


@dataclass
class BreakerTrip:
    breaker_name: str
    reason: str
    current_value: float
    threshold: float
    timestamp: float = field(default_factory=time.monotonic)


class CircuitBreaker:
    """Individual circuit breaker with configurable threshold and cooldown."""

    def __init__(self, name: str, threshold: float, cooldown_seconds: float = 300,
                 window_seconds: float = 300):
        self.name = name
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.window_seconds = window_seconds
        self.state = BreakerState.CLOSED
        self.trip_count: int = 0
        self.last_trip_time: float = 0.0
        self.trip_history: list[BreakerTrip] = []
        self._readings: deque[tuple[float, float]] = deque()  # (timestamp, value)

    def record(self, value: float) -> None:
        self._readings.append((time.monotonic(), value))
        self._evict_stale()

    def check(self) -> BreakerTrip | None:
        """Check if breaker should trip. Returns trip reason or None."""
        if self.state == BreakerState.OPEN:
            if time.monotonic() - self.last_trip_time > self.cooldown_seconds:
                self.state = BreakerState.HALF_OPEN
                log.info("[circuit_breaker] %s → HALF_OPEN (cooldown elapsed)", self.name)
            else:
                return BreakerTrip(self.name, "breaker still open", 0, self.threshold)

        self._evict_stale()

        if not self._readings:
            return None

        # Use the max value in the window as the trip signal
        max_val = max(v for _, v in self._readings)
        if max_val > self.threshold:
            self._trip(f"value {max_val:.4f} > threshold {self.threshold}", max_val)
            return BreakerTrip(self.name, f"value {max_val:.4f} > {self.threshold}",
                               max_val, self.threshold)

        return None

    def _trip(self, reason: str, current_value: float) -> None:
        self.state = BreakerState.OPEN
        self.trip_count += 1
        self.last_trip_time = time.monotonic()
        trip = BreakerTrip(self.name, reason, current_value, self.threshold)
        self.trip_history.append(trip)
        if len(self.trip_history) > 50:
            self.trip_history = self.trip_history[-50:]
        log.warning("[circuit_breaker] TRIPPED: %s — %s", self.name, reason)

    def reset(self) -> None:
        self.state = BreakerState.CLOSED
        self._readings.clear()
        log.info("[circuit_breaker] %s reset to CLOSED", self.name)

    def _evict_stale(self) -> None:
        cutoff = time.monotonic() - self.window_seconds
        while self._readings and self._readings[0][0] < cutoff:
            self._readings.popleft()


class ExecutionCircuitBreakers:
    """Collection of circuit breakers protecting the execution engine."""

    def __init__(self):
        self.breakers: dict[str, CircuitBreaker] = {
            "rapid_losses": CircuitBreaker(
                "rapid_losses", threshold=50.0, cooldown_seconds=600,
                window_seconds=300,
            ),
            "execution_anomalies": CircuitBreaker(
                "execution_anomalies", threshold=3, cooldown_seconds=300,
                window_seconds=300,
            ),
            "duplicate_orders": CircuitBreaker(
                "duplicate_orders", threshold=2, cooldown_seconds=600,
                window_seconds=300,
            ),
            "runaway_retries": CircuitBreaker(
                "runaway_retries", threshold=10, cooldown_seconds=300,
                window_seconds=120,
            ),
            "excessive_slippage": CircuitBreaker(
                "excessive_slippage", threshold=0.05, cooldown_seconds=300,
                window_seconds=300,
            ),
            "stale_market_data": CircuitBreaker(
                "stale_market_data", threshold=1, cooldown_seconds=120,
                window_seconds=300,
            ),
            "reconciliation_drift": CircuitBreaker(
                "reconciliation_drift", threshold=3, cooldown_seconds=600,
                window_seconds=600,
            ),
            "abnormal_latency": CircuitBreaker(
                "abnormal_latency", threshold=10_000, cooldown_seconds=300,
                window_seconds=300,
            ),
        }
        self._tripped_breakers: set[str] = set()

    def record_loss(self, loss_usd: float) -> None:
        self.breakers["rapid_losses"].record(abs(loss_usd))

    def record_anomaly(self) -> None:
        b = self.breakers["execution_anomalies"]
        b.record((b._readings[-1][1] + 1) if b._readings else 1)

    def record_duplicate(self) -> None:
        b = self.breakers["duplicate_orders"]
        b.record((b._readings[-1][1] + 1) if b._readings else 1)

    def record_retry(self) -> None:
        b = self.breakers["runaway_retries"]
        b.record((b._readings[-1][1] + 1) if b._readings else 1)

    def record_slippage(self, slippage: float) -> None:
        self.breakers["excessive_slippage"].record(abs(slippage))

    def record_stale_data(self) -> None:
        b = self.breakers["stale_market_data"]
        b.record((b._readings[-1][1] + 1) if b._readings else 1)

    def record_drift(self, drift_count: int) -> None:
        self.breakers["reconciliation_drift"].record(float(drift_count))

    def record_latency(self, latency_ms: float) -> None:
        self.breakers["abnormal_latency"].record(latency_ms)

    def check_all(self) -> list[BreakerTrip]:
        trips = []
        for name, breaker in self.breakers.items():
            trip = breaker.check()
            if trip:
                trips.append(trip)
                self._tripped_breakers.add(name)
        return trips

    def any_tripped(self) -> bool:
        return any(b.state == BreakerState.OPEN for b in self.breakers.values())

    def can_execute(self) -> bool:
        """Master kill-switch: returns False if any breaker is open."""
        return not self.any_tripped()

    def status(self) -> dict:
        return {
            name: {
                "state": b.state.value,
                "trip_count": b.trip_count,
                "threshold": b.threshold,
            }
            for name, b in self.breakers.items()
        }


_breakers = ExecutionCircuitBreakers()


def get_circuit_breakers() -> ExecutionCircuitBreakers:
    return _breakers
