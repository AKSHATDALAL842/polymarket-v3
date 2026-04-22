"""
Kalshi Execution Engine — places orders on Kalshi's REST API v2.

Routing: executor.py calls execute_kalshi() when signal.market.source == "kalshi".

Key differences from Polymarket:
  - Prices in cents (1–99), not floats
  - Order unit is "contracts" (each contract = $0.01–$1.00 notional)
  - Auth: JWT bearer token (email/password) or RSA key signing
  - No blockchain signing required
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import httpx

import config
import logger as lg
from edge_model import Signal
from kalshi_markets import _get_auth_headers, get_kalshi_ticker

log = logging.getLogger(__name__)


# ── Order sizing ───────────────────────────────────────────────────────────────

def _compute_kalshi_order(signal: Signal) -> tuple[int, int, str]:
    """
    Returns (yes_price_cents, count, side).

    Kalshi limit price:
      YES buy → limit at just-above yes_bid  (inside spread)
      NO  buy → equivalent YES price just-below yes_ask

    count = floor(bet_amount / price_per_contract_usd)
    """
    offset_cents = round(config.LIMIT_ORDER_OFFSET * 100)   # e.g. 1 cent

    yes_bid_cents = round(signal.p_market * 100)
    yes_ask_cents = round((signal.p_market + signal.spread) * 100)

    if signal.side == "YES":
        side = "yes"
        limit_cents = min(99, yes_bid_cents + offset_cents)
        price_per_contract = limit_cents / 100.0
    else:
        # Buying NO: we pay (100 - yes_ask) cents per contract
        side = "no"
        no_price_cents = 100 - yes_ask_cents
        limit_cents = max(1, no_price_cents + offset_cents)
        price_per_contract = limit_cents / 100.0

    if price_per_contract <= 0:
        price_per_contract = 0.5

    count = max(1, int(signal.bet_amount / price_per_contract))
    return limit_cents, count, side


# ── Dry run ────────────────────────────────────────────────────────────────────

def _dry_run(signal: Signal, exec_start: float):
    """Import ExecutionResult lazily to avoid circular imports."""
    from executor import ExecutionResult, _log_trade
    latency = int((time.monotonic() - exec_start) * 1000)
    total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency
    trade_id = _log_trade(
        signal, status="dry_run", order_id=None,
        fill_price=signal.p_market, filled_size=signal.bet_amount,
        slippage=0.0, latency_ms=total_latency,
    )
    log.info(
        f"[kalshi-executor] DRY_RUN {signal.side} ${signal.bet_amount:.2f} "
        f"'{signal.market.question[:50]}' ev={signal.ev:.3f}"
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


# ── Live execution ─────────────────────────────────────────────────────────────

def _execute_live(signal: Signal, exec_start: float):
    from executor import ExecutionResult, _log_trade

    headers = _get_auth_headers()
    if not headers:
        log.error("[kalshi-executor] No auth credentials — cannot place order")
        return _err_result("error_no_auth", signal, exec_start)

    ticker = get_kalshi_ticker(signal.market)
    limit_cents, count, side = _compute_kalshi_order(signal)
    client_order_id = str(uuid.uuid4())

    body = {
        "ticker": ticker,
        "client_order_id": client_order_id,
        "type": config.ORDER_TYPE,          # "limit" or "market"
        "action": "buy",
        "side": side,
        "yes_price": limit_cents,           # Kalshi always uses yes_price field
        "count": count,
    }

    last_err = ""
    for attempt in range(config.ORDER_RETRY_ATTEMPTS):
        try:
            resp = httpx.post(
                f"{config.KALSHI_HOST}/portfolio/orders",
                json=body,
                headers={**headers, "Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            order = data.get("order", data)

            order_id      = order.get("order_id", client_order_id)
            filled_count  = float(order.get("filled_count", count))
            fill_cents    = float(order.get("yes_price", limit_cents))
            fill_price    = fill_cents / 100.0
            filled_size   = filled_count * fill_price
            slippage      = fill_price - signal.p_market

            latency       = int((time.monotonic() - exec_start) * 1000)
            total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency

            trade_id = _log_trade(
                signal, status="executed", order_id=order_id,
                fill_price=fill_price, filled_size=filled_size,
                slippage=slippage, latency_ms=total_latency,
            )
            log.info(
                f"[kalshi-executor] EXECUTED {side.upper()} {count} contracts "
                f"@{fill_cents}¢ ticker={ticker} order={order_id}"
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

        except httpx.HTTPStatusError as e:
            last_err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            log.warning(f"[kalshi-executor] Attempt {attempt+1} failed: {last_err}")
        except Exception as e:
            last_err = str(e)
            log.warning(f"[kalshi-executor] Attempt {attempt+1} error: {e}")

        if attempt < config.ORDER_RETRY_ATTEMPTS - 1:
            time.sleep(config.ORDER_RETRY_DELAY_SECONDS)

    return _err_result("error_order_failed", signal, exec_start)


def _err_result(status: str, signal: Signal, exec_start: float):
    from executor import ExecutionResult, _log_trade
    latency = int((time.monotonic() - exec_start) * 1000)
    total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency
    _log_trade(signal, status=status, order_id=None, fill_price=0.0,
               filled_size=0.0, slippage=0.0, latency_ms=total_latency)
    return ExecutionResult(
        trade_id=None, status=status, order_id=None,
        filled_size=0.0, fill_price=0.0, slippage=0.0, latency_ms=total_latency,
    )


# ── Public entry point ─────────────────────────────────────────────────────────

def execute_kalshi(signal: Signal):
    """Called by executor.py when signal.market.source == 'kalshi'."""
    exec_start = time.monotonic()
    if config.DRY_RUN:
        return _dry_run(signal, exec_start)
    return _execute_live(signal, exec_start)
