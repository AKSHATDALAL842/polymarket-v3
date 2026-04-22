from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import config
import logger
from edge_model import Signal

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    trade_id: int | None
    status: str
    order_id: str | None
    filled_size: float
    fill_price: float
    slippage: float
    latency_ms: int
    retries: int = 0

    @property
    def success(self) -> bool:
        return self.status in ("executed", "dry_run", "paper")


def _check_risk_gates(signal: Signal) -> str | None:
    from risk import RiskManager
    rm = RiskManager.instance()

    if not rm.can_trade_daily():
        return "rejected_daily_limit"

    if not rm.can_open_position():
        return "rejected_max_positions"

    category = signal.market.category
    if not rm.can_trade_category(category, signal.bet_amount):
        return f"rejected_category_exposure_{category}"

    if rm.in_cooldown():
        return "rejected_cooldown"

    if signal.estimated_slippage > config.MAX_SLIPPAGE_FRACTION:
        return "rejected_slippage"

    return None


def _compute_limit_price(signal: Signal) -> float:
    offset = config.LIMIT_ORDER_OFFSET
    mid = signal.p_market
    spread = signal.spread

    if signal.side == "YES":
        price = max(0.01, mid - spread / 2 + offset)
    else:
        price = min(0.99, mid + spread / 2 - offset)

    return round(price, 4)


def _dry_run_execution(signal: Signal, exec_start: float) -> ExecutionResult:
    latency = int((time.monotonic() - exec_start) * 1000)
    total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency

    trade_id = _log_trade(signal, status="dry_run", order_id=None,
                          fill_price=signal.p_market, filled_size=signal.bet_amount,
                          slippage=0.0, latency_ms=total_latency)
    log.info(
        f"[executor] DRY_RUN {signal.side} ${signal.bet_amount:.2f} "
        f"'{signal.market.question[:50]}' ev={signal.ev:.3f} "
        f"latency={total_latency}ms"
    )
    return ExecutionResult(
        trade_id=trade_id,
        status="dry_run",
        order_id=None,
        filled_size=signal.bet_amount,
        fill_price=signal.p_market,
        slippage=0.0,
        latency_ms=total_latency,
    )


def _execute_live(signal: Signal, exec_start: float) -> ExecutionResult:
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType
    except ImportError:
        log.error("[executor] py_clob_client not installed — cannot execute live")
        return ExecutionResult(
            trade_id=None,
            status="error_no_clob_client",
            order_id=None,
            filled_size=0.0,
            fill_price=0.0,
            slippage=0.0,
            latency_ms=0,
        )

    from markets import get_token_id

    token_id = get_token_id(signal.market, signal.side)
    if not token_id:
        return ExecutionResult(
            trade_id=None,
            status="error_no_token",
            order_id=None,
            filled_size=0.0,
            fill_price=0.0,
            slippage=0.0,
            latency_ms=0,
        )

    limit_price = _compute_limit_price(signal)

    try:
        client = ClobClient(
            host=config.POLYMARKET_HOST,
            key=config.POLYMARKET_API_KEY,
            chain_id=137,
            funder=config.POLYMARKET_PRIVATE_KEY,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
    except Exception as e:
        log.error(f"[executor] CLOB client init failed: {e}")
        return ExecutionResult(
            trade_id=None,
            status=f"error_client_init",
            order_id=None,
            filled_size=0.0,
            fill_price=0.0,
            slippage=0.0,
            latency_ms=0,
        )

    last_error = ""
    for attempt in range(config.ORDER_RETRY_ATTEMPTS):
        try:
            order_args = OrderArgs(
                price=limit_price,
                size=signal.bet_amount,
                side="BUY",
                token_id=token_id,
            )
            signed_order = client.create_order(order_args)
            resp = client.post_order(signed_order, OrderType.GTC)

            order_id = resp.get("orderID", resp.get("id", "unknown"))
            fill_price = float(resp.get("price", limit_price))
            filled_size = float(resp.get("sizeMatched", signal.bet_amount))
            slippage = fill_price - signal.p_market

            latency = int((time.monotonic() - exec_start) * 1000)
            total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency

            trade_id = _log_trade(
                signal, status="executed", order_id=order_id,
                fill_price=fill_price, filled_size=filled_size,
                slippage=slippage, latency_ms=total_latency
            )

            log.info(
                f"[executor] EXECUTED {signal.side} ${filled_size:.2f} "
                f"@{fill_price:.4f} slippage={slippage:+.4f} "
                f"order={order_id} latency={total_latency}ms"
            )
            return ExecutionResult(
                trade_id=trade_id,
                status="executed",
                order_id=order_id,
                filled_size=filled_size,
                fill_price=fill_price,
                slippage=slippage,
                latency_ms=total_latency,
                retries=attempt,
            )

        except Exception as e:
            last_error = str(e)
            log.warning(f"[executor] Order attempt {attempt+1} failed: {e}")
            if attempt < config.ORDER_RETRY_ATTEMPTS - 1:
                time.sleep(config.ORDER_RETRY_DELAY_SECONDS)

    latency = int((time.monotonic() - exec_start) * 1000)
    total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency
    trade_id = _log_trade(
        signal, status="error_order_failed", order_id=None,
        fill_price=0.0, filled_size=0.0, slippage=0.0, latency_ms=total_latency
    )
    return ExecutionResult(
        trade_id=trade_id,
        status="error_order_failed",
        order_id=None,
        filled_size=0.0,
        fill_price=0.0,
        slippage=0.0,
        latency_ms=total_latency,
        retries=config.ORDER_RETRY_ATTEMPTS,
    )


def _log_trade(
    signal: Signal,
    status: str,
    order_id: Optional[str],
    fill_price: float,
    filled_size: float,
    slippage: float,
    latency_ms: int,
) -> int | None:
    try:
        cls = signal.classification
        return logger.log_trade(
            market_id=signal.market.condition_id,
            market_question=signal.market.question,
            claude_score=cls.confidence,
            market_price=signal.p_market,
            edge=signal.ev,
            side=signal.side,
            amount_usd=filled_size,
            order_id=order_id,
            status=status,
            reasoning=signal.reasoning,
            headlines=signal.headlines,
            news_source=signal.news_source,
            classification=cls.direction,
            materiality=cls.materiality,
            news_latency_ms=signal.news_latency_ms,
            classification_latency_ms=cls.total_latency_ms,
            total_latency_ms=latency_ms,
            category=getattr(signal.market, "category", None),
            platform=getattr(signal.market, "source", "polymarket"),
        )
    except Exception as e:
        log.warning(f"[executor] Log failed: {e}")
        return None


def execute_trade(signal: Signal) -> ExecutionResult:
    exec_start = time.monotonic()

    rejection = _check_risk_gates(signal)
    if rejection:
        latency = int((time.monotonic() - exec_start) * 1000)
        trade_id = _log_trade(signal, status=rejection, order_id=None,
                              fill_price=0.0, filled_size=0.0, slippage=0.0,
                              latency_ms=latency)
        log.info(f"[executor] Rejected: {rejection}")
        return ExecutionResult(
            trade_id=trade_id,
            status=rejection,
            order_id=None,
            filled_size=0.0,
            fill_price=0.0,
            slippage=0.0,
            latency_ms=latency,
        )

    if config.DRY_RUN:
        try:
            from portfolio import get_portfolio
            return get_portfolio().simulate_trade(signal)
        except Exception as e:
            log.warning(f"[executor] Portfolio unavailable, falling back to dry_run: {e}")
            if getattr(signal.market, "source", "polymarket") == "kalshi":
                from kalshi_executor import execute_kalshi
                return execute_kalshi(signal)
            return _dry_run_execution(signal, exec_start)

    if getattr(signal.market, "source", "polymarket") == "kalshi":
        from kalshi_executor import execute_kalshi
        return execute_kalshi(signal)

    return _execute_live(signal, exec_start)


async def execute_trade_async(signal: Signal) -> ExecutionResult:
    return await asyncio.get_running_loop().run_in_executor(None, execute_trade, signal)
