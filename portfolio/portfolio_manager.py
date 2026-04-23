# portfolio/portfolio_manager.py
"""
PortfolioManager — central decision engine for the multi-strategy trading system.

Replaces direct execute_trade_async() calls from pipeline._process_market().
Receives AggregatedSignal objects, applies risk validation and dynamic sizing,
then delegates to execution_engine.execute_order().

Singleton via PortfolioManager.instance().
"""
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
    """
    Central decision engine. Get the shared instance via PortfolioManager.instance().
    """
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
        self._decisions: list[dict] = []   # audit log of all decisions

    # ── Main entry point ───────────────────────────────────────────────────────

    async def process_signal_async(self, signal: AggregatedSignal):
        """
        Async entry point called from pipeline._process_market().
        Runs synchronous logic in the event loop (no blocking I/O here).
        """
        return await asyncio.get_running_loop().run_in_executor(
            None, self.process_signal, signal
        )

    def process_signal(self, signal: AggregatedSignal):
        """
        Synchronous decision pipeline:
          1. Compute size via Allocator
          2. Validate via RiskEngine
          3. Build execution order
          4. Delegate to ExecutionEngine

        Returns ExecutionResult (from executor.py — unchanged).
        """
        from execution.execution_engine import ExecutionEngine

        t0 = time.monotonic()

        # Step 1: Compute position size
        current_drawdown = self._get_current_drawdown()
        size_usd = self._allocator.compute_size(signal, drawdown=current_drawdown)

        # Step 2: Risk validation
        decision = self._risk_engine.validate(signal, size_usd)
        if not decision.approved:
            log.info(f"[portfolio_manager] Rejected: {decision.reason} — {signal.market_id[:12]}")
            self._log_decision(signal, size_usd, decision.reason, elapsed_ms=int((time.monotonic()-t0)*1000))
            return self._rejected_result(decision.reason)

        # Step 3: Build order and execute
        order = {
            "signal": signal,
            "size_usd": size_usd,
        }

        log.info(
            f"[portfolio_manager] Executing {signal.direction} ${size_usd:.2f} "
            f"'{signal.market_question[:45]}' "
            f"strategies={signal.strategies} mult={signal.size_multiplier}"
        )

        result = ExecutionEngine.instance().execute(order)
        elapsed = int((time.monotonic() - t0) * 1000)
        self._log_decision(signal, size_usd, result.status, elapsed_ms=elapsed)
        return result

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_current_drawdown(self) -> float:
        """Get current max drawdown from paper portfolio. Returns 0.0 on error."""
        try:
            from portfolio._paper import get_portfolio as get_paper_portfolio
            return get_paper_portfolio().get_max_drawdown()
        except Exception:
            return 0.0

    def _rejected_result(self, reason: str):
        """Return a minimal ExecutionResult for rejected trades."""
        from execution.executor import ExecutionResult
        return ExecutionResult(
            trade_id=None,
            status=reason,
            order_id=None,
            filled_size=0.0,
            fill_price=0.0,
            slippage=0.0,
            latency_ms=0,
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
        # Keep last 500 decisions in memory
        if len(self._decisions) > 500:
            self._decisions = self._decisions[-500:]

    def get_recent_decisions(self, n: int = 20) -> list[dict]:
        return self._decisions[-n:]
