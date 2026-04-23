from __future__ import annotations

import asyncio
import logging
import time
from threading import Lock
from typing import Optional

import config
from alpha.signal import AggregatedSignal
from portfolio.allocator import Allocator
from portfolio.risk_engine import RiskEngine

log = logging.getLogger(__name__)


class PortfolioManager:
    """Central decision engine. Singleton via PortfolioManager.instance()."""
    _singleton: Optional["PortfolioManager"] = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "PortfolioManager":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
        return cls._singleton

    def __init__(self):
        self._allocator = Allocator(
            capital=getattr(config, 'PAPER_BALANCE', 1_000_000.0),
            max_bet=getattr(config, 'MAX_BET_USD', 25.0),
            sizing_k=getattr(config, 'SIZING_K', 0.25),
            bankroll=getattr(config, 'BANKROLL_USD', 1000.0),
        )
        self._risk_engine = RiskEngine()
        self._decisions: list[dict] = []

    async def process_signal_async(self, signal: AggregatedSignal):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.process_signal, signal
        )

    def process_signal(self, signal: AggregatedSignal):
        from execution.execution_engine import ExecutionEngine

        t0 = time.monotonic()
        size_usd = self._allocator.compute_size(signal, drawdown=self._get_current_drawdown())
        decision = self._risk_engine.validate(signal, size_usd)

        if not decision.approved:
            log.info(f"[portfolio_manager] Rejected: {decision.reason} — {signal.market_id[:12]}")
            self._log_decision(signal, size_usd, decision.reason, int((time.monotonic()-t0)*1000))
            return self._rejected_result(decision.reason)

        log.info(
            f"[portfolio_manager] Executing {signal.direction} ${size_usd:.2f} "
            f"'{signal.market_question[:45]}' strategies={signal.strategies} mult={signal.size_multiplier}"
        )

        result = ExecutionEngine.instance().execute({"signal": signal, "size_usd": size_usd})
        self._log_decision(signal, size_usd, result.status, int((time.monotonic()-t0)*1000))
        return result

    def _get_current_drawdown(self) -> float:
        try:
            from portfolio._paper import get_portfolio as get_paper_portfolio
            return get_paper_portfolio().get_max_drawdown()
        except Exception:
            return 0.0

    def _rejected_result(self, reason: str):
        from execution.executor import ExecutionResult
        return ExecutionResult(
            trade_id=None, status=reason, order_id=None,
            filled_size=0.0, fill_price=0.0, slippage=0.0, latency_ms=0,
        )

    def _log_decision(self, signal: AggregatedSignal, size: float, status: str, elapsed_ms: int):
        self._decisions.append({
            "market_id":  signal.market_id,
            "direction":  signal.direction,
            "strategies": signal.strategies,
            "size_usd":   size,
            "status":     status,
            "elapsed_ms": elapsed_ms,
            "timestamp":  time.time(),
        })
        if len(self._decisions) > 500:
            self._decisions = self._decisions[-500:]

    def get_recent_decisions(self, n: int = 20) -> list[dict]:
        return self._decisions[-n:]
