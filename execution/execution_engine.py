from __future__ import annotations

import copy
import logging
from threading import Lock
from typing import Optional

log = logging.getLogger(__name__)


class ExecutionEngine:
    """Singleton. Get the shared instance via ExecutionEngine.instance()."""
    _singleton: Optional["ExecutionEngine"] = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "ExecutionEngine":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
        return cls._singleton

    def __init__(self):
        self._watcher = None  # set via set_watcher() from Pipeline after startup

    def set_watcher(self, watcher) -> None:
        self._watcher = watcher

    def execute(self, order: dict):
        """
        Execute an order from PortfolioManager.
        order: { "signal": AggregatedSignal, "size_usd": float }
        """
        from execution.smart_router import get_routing_strategy

        agg_signal = order["signal"]
        size_usd   = order["size_usd"]

        spread, momentum = self._get_microstructure(agg_signal.market_id)
        if get_routing_strategy(spread, momentum) == "reject":
            return self._rejected_result("rejected_spread")

        exec_signal = self._build_signal(agg_signal, size_usd)
        if exec_signal is None:
            return self._rejected_result("rejected_no_market")

        from execution.executor import execute_trade
        return execute_trade(exec_signal)

    def _build_signal(self, agg, size_usd: float):
        """
        Convert AggregatedSignal → edge_model.Signal.
        Reuses the raw news Signal when available; otherwise builds a momentum stub.
        """
        from signal.edge_model import Signal
        from signal.classifier import Classification

        if agg.market is None:
            log.warning(f"[execution_engine] No market object in signal {agg.market_id[:12]}")
            return None

        for alpha_sig in agg.signals:
            if alpha_sig.strategy == "news" and alpha_sig.raw_signal is not None:
                raw = copy.copy(alpha_sig.raw_signal)
                raw.bet_amount = size_usd
                return raw

        market = agg.market
        p_market = getattr(market, 'yes_price', 0.5)
        cls = Classification(
            direction=agg.direction,
            confidence=agg.confidence,
            materiality=min(agg.expected_edge * 2, 1.0),
            novelty_score=0.5,
            time_sensitivity="short-term",
            reasoning=f"Momentum ensemble: {', '.join(agg.strategies)}",
            consistency=1.0,
        )
        adj = agg.expected_edge if agg.direction == "YES" else -agg.expected_edge
        return Signal(
            market=market, side=agg.direction,
            p_market=p_market, p_true=max(0.02, min(0.98, p_market + adj)),
            ev=agg.expected_edge, bet_amount=size_usd,
            reasoning=cls.reasoning, classification=cls,
            news_source="momentum", headlines=f"Momentum: {agg.market_question[:80]}",
        )

    def _get_microstructure(self, market_id: str) -> tuple[float, float]:
        if self._watcher is not None:
            snap = self._watcher.get_snapshot(market_id)
            if snap is not None:
                return snap.spread, 0.0  # live spread; momentum tracking is future work
        return 0.04, 0.0  # fallback when watcher not yet connected

    def _rejected_result(self, reason: str):
        from execution.executor import ExecutionResult
        return ExecutionResult(
            trade_id=None, status=reason, order_id=None,
            filled_size=0.0, fill_price=0.0, slippage=0.0, latency_ms=0,
        )
