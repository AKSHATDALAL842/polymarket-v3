"""
Expected vs Actual (EVA) Analysis — the highest-value operational research dataset.

Measures: fill price, slippage, latency, liquidity, reconciliation timing,
settlement timing. Compares expectations against real exchange behavior.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class EVAMeasurement:
    eva_id: str
    trace_id: str
    metric: str                 # "fill_price" | "slippage" | "latency" | "liquidity" | "spread"
    expected_value: float
    actual_value: float
    deviation: float
    deviation_pct: float
    market_id: str = ""
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EVAAnalyzer:
    """Collects and analyzes expected vs actual measurements for every live trade."""

    def __init__(self):
        self._measurements: list[EVAMeasurement] = []
        self._init_db()

    def _init_db(self):
        from observability.logger import _conn
        conn = _conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eva_measurements (
                eva_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                expected_value REAL NOT NULL,
                actual_value REAL NOT NULL,
                deviation REAL NOT NULL,
                deviation_pct REAL NOT NULL,
                market_id TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eva_trace ON eva_measurements(trace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eva_metric ON eva_measurements(metric)")
        conn.commit()
        conn.close()

    def record_fill(self, trace_id: str, market_id: str,
                    expected_price: float, actual_price: float) -> EVAMeasurement:
        dev = actual_price - expected_price
        dev_pct = (dev / max(0.0001, expected_price)) * 100
        m = EVAMeasurement(
            eva_id=f"eva-{trace_id}-price",
            trace_id=trace_id,
            metric="fill_price",
            expected_value=expected_price,
            actual_value=actual_price,
            deviation=round(dev, 6),
            deviation_pct=round(dev_pct, 2),
            market_id=market_id,
        )
        self._store(m)
        return m

    def record_slippage(self, trace_id: str, market_id: str,
                        expected_slippage: float, actual_slippage: float) -> EVAMeasurement:
        dev = actual_slippage - expected_slippage
        dev_pct = (dev / max(0.0001, expected_slippage)) * 100 if expected_slippage > 0 else 0
        m = EVAMeasurement(
            eva_id=f"eva-{trace_id}-slippage",
            trace_id=trace_id,
            metric="slippage",
            expected_value=expected_slippage,
            actual_value=actual_slippage,
            deviation=round(dev, 6),
            deviation_pct=round(dev_pct, 2),
            market_id=market_id,
        )
        self._store(m)
        return m

    def record_latency(self, trace_id: str, market_id: str,
                       expected_ms: float, actual_ms: float) -> EVAMeasurement:
        dev = actual_ms - expected_ms
        dev_pct = (dev / max(1, expected_ms)) * 100
        m = EVAMeasurement(
            eva_id=f"eva-{trace_id}-latency",
            trace_id=trace_id,
            metric="latency",
            expected_value=expected_ms,
            actual_value=actual_ms,
            deviation=round(dev, 0),
            deviation_pct=round(dev_pct, 1),
            market_id=market_id,
        )
        self._store(m)
        return m

    def record_liquidity(self, trace_id: str, market_id: str,
                         expected_depth: float, actual_depth: float) -> EVAMeasurement:
        dev = actual_depth - expected_depth
        dev_pct = (dev / max(1, expected_depth)) * 100
        m = EVAMeasurement(
            eva_id=f"eva-{trace_id}-liquidity",
            trace_id=trace_id,
            metric="liquidity",
            expected_value=expected_depth,
            actual_value=actual_depth,
            deviation=round(dev, 0),
            deviation_pct=round(dev_pct, 1),
            market_id=market_id,
        )
        self._store(m)
        return m

    def _store(self, m: EVAMeasurement):
        self._measurements.append(m)
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute(
                """INSERT INTO eva_measurements
                   (eva_id, trace_id, metric, expected_value, actual_value,
                    deviation, deviation_pct, market_id, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (m.eva_id, m.trace_id, m.metric, m.expected_value, m.actual_value,
                 m.deviation, m.deviation_pct, m.market_id, m.notes),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def summary(self) -> dict:
        if not self._measurements:
            return {"status": "no_data"}
        by_metric = {}
        for m in self._measurements:
            if m.metric not in by_metric:
                by_metric[m.metric] = {"deviations": [], "count": 0}
            by_metric[m.metric]["deviations"].append(m.deviation_pct)
            by_metric[m.metric]["count"] += 1
        result = {}
        for metric, data in by_metric.items():
            devs = data["deviations"]
            result[metric] = {
                "count": data["count"],
                "mean_deviation_pct": round(sum(devs) / len(devs), 2),
                "max_deviation_pct": round(max(abs(d) for d in devs), 2),
                "samples": [round(d, 2) for d in devs[-10:]],
            }
        return result


_eva = EVAAnalyzer()


def get_eva_analyzer() -> EVAAnalyzer:
    return _eva
