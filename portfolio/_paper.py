"""
Paper trading engine — $1M virtual portfolio.
Singleton via get_portfolio(). Persists open positions to SQLite on every trade.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import config
from observability import logger as lg

log = logging.getLogger(__name__)

_portfolio: Optional["Portfolio"] = None


@dataclass
class Position:
    position_id: int
    market_id: str
    market_question: str
    platform: str           # "polymarket" | "kalshi"
    category: str
    side: str               # "YES" | "NO"
    entry_price: float
    size_usd: float
    contracts: float
    opened_at: datetime
    closed_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    status: str = "open"    # "open" | "closed"


class Portfolio:
    def __init__(self, balance: float, initial_balance: float):
        self.balance = balance
        self.initial_balance = initial_balance
        self.positions: dict[str, Position] = {}
        self.daily_returns: list[float] = []
        self._peak_value: float = initial_balance
        self._realized_pnl: float = 0.0

    # ── Trade simulation ─────────────────────────────────────────────────────

    def simulate_trade(self, signal) -> "ExecutionResult":
        from execution.executor import ExecutionResult, _log_trade
        import time

        exec_start = time.monotonic()

        market = signal.market
        market_id = market.condition_id
        platform = getattr(market, "source", "polymarket")
        category = getattr(market, "category", "unknown")

        entry_price = signal.p_market
        bet_amount = signal.bet_amount

        if signal.side == "YES":
            contracts = bet_amount / entry_price if entry_price > 0 else 0.0
        else:
            no_price = 1.0 - entry_price
            contracts = bet_amount / no_price if no_price > 0 else 0.0

        # Guard: if position already open for this market, skip (don't double-open)
        if market_id in self.positions and self.positions[market_id].status == "open":
            log.warning(
                f"[portfolio] Skipping duplicate open position for market {market_id}: "
                f"already have {self.positions[market_id].side} position"
            )
            from execution.executor import ExecutionResult
            return ExecutionResult(
                trade_id=None,
                status="rejected_duplicate_position",
                order_id=None,
                filled_size=0.0,
                fill_price=signal.p_market,
                slippage=0.0,
                latency_ms=0,
            )

        self.balance -= bet_amount
        now = datetime.now(timezone.utc)

        position_id = lg.log_position(
            market_id=market_id,
            market_question=market.question,
            platform=platform,
            category=category,
            side=signal.side,
            entry_price=entry_price,
            size_usd=bet_amount,
            contracts=contracts,
            opened_at=now.isoformat(),
        )

        pos = Position(
            position_id=position_id,
            market_id=market_id,
            market_question=market.question,
            platform=platform,
            category=category,
            side=signal.side,
            entry_price=entry_price,
            size_usd=bet_amount,
            contracts=contracts,
            opened_at=now,
        )
        self.positions[market_id] = pos

        latency = int((time.monotonic() - exec_start) * 1000)
        total_latency = signal.news_latency_ms + signal.classification_latency_ms + latency

        trade_id = _log_trade(
            signal,
            status="paper",
            order_id=None,
            fill_price=entry_price,
            filled_size=bet_amount,
            slippage=0.0,
            latency_ms=total_latency,
        )

        log.info(
            f"[portfolio][PAPER][{category}][{platform}] {signal.side} ${bet_amount:.2f} "
            f"'{market.question[:40]}' ev={signal.ev:.3f}"
        )

        return ExecutionResult(
            trade_id=trade_id,
            status="paper",
            order_id=None,
            filled_size=bet_amount,
            fill_price=entry_price,
            slippage=0.0,
            latency_ms=total_latency,
        )

    # ── P&L ──────────────────────────────────────────────────────────────────

    def mark_to_market(self, market_id: str, current_price: float) -> float:
        """Return unrealized P&L for an open position using current YES price."""
        pos = self.positions.get(market_id)
        if pos is None or pos.status != "open":
            return 0.0
        if pos.side == "YES":
            return pos.contracts * (current_price - pos.entry_price)
        else:
            return pos.contracts * (pos.entry_price - current_price)

    def close_position(self, market_id: str, exit_price: float) -> float:
        """Close an open position. Returns realized P&L."""
        pos = self.positions.get(market_id)
        if pos is None or pos.status != "open":
            return 0.0

        realized_pnl = self.mark_to_market(market_id, exit_price)
        self.balance += pos.size_usd + realized_pnl
        self._realized_pnl += realized_pnl

        now = datetime.now(timezone.utc)
        pos.status = "closed"
        pos.exit_price = exit_price
        pos.realized_pnl = realized_pnl
        pos.closed_at = now

        lg.update_position_closed(
            position_id=pos.position_id,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            closed_at=now.isoformat(),
        )

        daily_return = realized_pnl / pos.size_usd if pos.size_usd > 0 else 0.0
        self.daily_returns.append(daily_return)

        current_value = self._total_value()
        if current_value > self._peak_value:
            self._peak_value = current_value

        return realized_pnl

    def get_unrealized_pnl(self) -> float:
        """Sum mark_to_market across all open positions using watcher snapshots."""
        total = 0.0
        try:
            from ingestion.market_watcher import MarketWatcher
            watcher = MarketWatcher()
            for market_id, pos in list(self.positions.items()):
                if pos.status != "open":
                    continue
                snap = watcher.get_snapshot(market_id)
                if snap:
                    total += self.mark_to_market(market_id, snap.yes_price)
        except Exception:
            pass
        return total

    def _total_value(self) -> float:
        return self.balance + self.get_unrealized_pnl()

    def get_portfolio_state(self) -> dict:
        # Build open positions list with live unrealized P&L
        open_positions = []
        try:
            from ingestion.market_watcher import MarketWatcher
            watcher = MarketWatcher()
        except Exception:
            watcher = None

        for p in list(self.positions.values()):
            if p.status != "open":
                continue
            if watcher:
                snap = watcher.get_snapshot(p.market_id)
                current_price = snap.yes_price if snap else p.entry_price
            else:
                current_price = p.entry_price
            open_positions.append({
                "market_id": p.market_id,
                "question": p.market_question,
                "platform": p.platform,
                "category": p.category,
                "side": p.side,
                "entry_price": p.entry_price,
                "size_usd": p.size_usd,
                "contracts": p.contracts,
                "opened_at": p.opened_at.isoformat(),
                "unrealized_pnl": self.mark_to_market(p.market_id, current_price),
            })
        closed_db = lg.get_closed_positions(limit=100)

        closed_count = len(closed_db)
        wins = sum(1 for p in closed_db if (p.get("realized_pnl") or 0) > 0)
        win_rate = wins / closed_count if closed_count > 0 else 0.0

        unrealized = self.get_unrealized_pnl()
        total_value = self.balance + unrealized

        by_category = lg.get_category_stats()

        return {
            "balance": round(self.balance, 2),
            "initial_balance": round(self.initial_balance, 2),
            "total_value": round(total_value, 2),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(self._realized_pnl, 2),
            "open_positions": open_positions,
            "closed_positions": closed_db,
            "win_rate": round(win_rate, 3),
            "sharpe_ratio": self.get_sharpe_ratio(),
            "max_drawdown": round(self.get_max_drawdown(), 4),
            "total_return_pct": round((total_value - self.initial_balance) / self.initial_balance * 100, 3),
            "by_category": by_category,
        }

    def get_sharpe_ratio(self) -> Optional[float]:
        """Annualized Sharpe from daily returns. None if fewer than 2 data points."""
        if len(self.daily_returns) < 2:
            return None
        mean = sum(self.daily_returns) / len(self.daily_returns)
        variance = sum((r - mean) ** 2 for r in self.daily_returns) / (len(self.daily_returns) - 1)
        std = math.sqrt(variance)
        if std == 0:
            return None
        return round(mean / std * math.sqrt(252), 4)

    def get_max_drawdown(self) -> float:
        """Peak-to-trough as fraction of peak portfolio value. Range [0, 1]."""
        if self._peak_value <= 0:
            return 0.0
        current = self._total_value()
        drawdown = (self._peak_value - current) / self._peak_value
        return max(0.0, drawdown)


def get_portfolio() -> Portfolio:
    """Module-level singleton. Lazily initialized on first call."""
    global _portfolio
    if _portfolio is None:
        _portfolio = Portfolio(
            balance=config.PAPER_BALANCE,
            initial_balance=config.PAPER_BALANCE,
        )
        _restore_open_positions(_portfolio)
    return _portfolio


def _restore_open_positions(portfolio: Portfolio):
    """Load open positions from SQLite into the in-memory portfolio on startup."""
    try:
        rows = lg.get_open_positions()
        for row in rows:
            pos = Position(
                position_id=row["id"],
                market_id=row["market_id"],
                market_question=row["market_question"],
                platform=row["platform"],
                category=row["category"],
                side=row["side"],
                entry_price=row["entry_price"],
                size_usd=row["size_usd"],
                contracts=row["contracts"] or 0.0,
                opened_at=datetime.fromisoformat(row["opened_at"]),
            )
            portfolio.positions[pos.market_id] = pos
            portfolio.balance -= pos.size_usd
        if rows:
            log.info(f"[portfolio] Restored {len(rows)} open positions from SQLite")
    except Exception as e:
        log.warning(f"[portfolio] Could not restore positions: {e}")
