# execution/execution_engine.py
"""
ExecutionEngine — converts PortfolioManager orders into ExecutionResults.

Wraps the existing executor.py without modifying it.
In DRY_RUN mode → delegates to portfolio.simulate_trade() via a synthesized Signal.
In LIVE mode    → delegates to executor.execute_trade() via synthesized Signal.

The synthesized Signal is constructed from AggregatedSignal + size_usd.
For news signals, the original edge_model.Signal is reused (raw_signal in AlphaSignal).
For momentum-only signals, a minimal Signal stub is constructed.
"""
from __future__ import annotations

import copy
import logging
from threading import Lock
from typing import Optional

log = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Singleton execution engine.
    Get the shared instance via ExecutionEngine.instance().
    """
    _singleton: Optional["ExecutionEngine"] = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "ExecutionEngine":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
        return cls._singleton

    def execute(self, order: dict):
        """
        Execute an order dict from PortfolioManager.

        Args:
            order: { "signal": AggregatedSignal, "size_usd": float }

        Returns:
            executor.ExecutionResult
        """
        from execution.smart_router import get_routing_strategy

        agg_signal = order["signal"]
        size_usd   = order["size_usd"]

        # Get microstructure data for routing decision
        spread, momentum = self._get_microstructure(agg_signal.market_id)
        routing = get_routing_strategy(spread, momentum)

        if routing == "reject":
            return self._rejected_result("rejected_spread")

        # Build a Signal compatible with the existing executor/portfolio
        exec_signal = self._build_signal(agg_signal, size_usd)
        if exec_signal is None:
            return self._rejected_result("rejected_no_market")

        # Delegate to existing executor (handles DRY_RUN / LIVE routing)
        from executor import execute_trade
        return execute_trade(exec_signal)

    # ── Signal construction ────────────────────────────────────────────────────

    def _build_signal(self, agg, size_usd: float):
        """
        Convert AggregatedSignal + size_usd into an edge_model.Signal.

        Priority:
          1. If any news AlphaSignal has raw_signal → reuse it (update bet_amount).
          2. Otherwise build a momentum stub Signal.
        """
        from edge_model import Signal
        from classifier import Classification

        if agg.market is None:
            log.warning(f"[execution_engine] No market object in signal {agg.market_id[:12]}")
            return None

        # Try to reuse original news Signal
        for alpha_sig in agg.signals:
            if alpha_sig.strategy == "news" and alpha_sig.raw_signal is not None:
                raw = copy.copy(alpha_sig.raw_signal)
                raw.bet_amount = size_usd
                return raw

        # Build momentum stub Signal
        market = agg.market
        direction = agg.direction
        p_market = getattr(market, 'yes_price', 0.5)

        cls = Classification(
            direction=direction,
            confidence=agg.confidence,
            materiality=min(agg.expected_edge * 2, 1.0),
            novelty_score=0.5,
            time_sensitivity="short-term",
            reasoning=f"Momentum ensemble: {', '.join(agg.strategies)}",
            consistency=1.0,
        )

        adj = agg.expected_edge if direction == "YES" else -agg.expected_edge
        p_true = max(0.02, min(0.98, p_market + adj))

        return Signal(
            market=market,
            side=direction,
            p_market=p_market,
            p_true=p_true,
            ev=agg.expected_edge,
            bet_amount=size_usd,
            reasoning=cls.reasoning,
            classification=cls,
            news_source="momentum",
            headlines=f"Momentum: {agg.market_question[:80]}",
        )

    def _get_microstructure(self, market_id: str) -> tuple[float, float]:
        """
        Returns (spread, momentum) defaults. In a future iteration, this will
        integrate with MarketWatcher snapshots via dependency injection.
        Currently returns conservative defaults: spread=4%, momentum=0.0.
        """
        return 0.04, 0.0

    def _rejected_result(self, reason: str):
        from executor import ExecutionResult
        return ExecutionResult(
            trade_id=None, status=reason, order_id=None,
            filled_size=0.0, fill_price=0.0, slippage=0.0, latency_ms=0,
        )
