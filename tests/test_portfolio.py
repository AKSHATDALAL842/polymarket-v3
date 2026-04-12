import pytest
import sys, os
import tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import portfolio as pm
import logger as lg


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a fresh temp DB for each test — no cross-test contamination."""
    db_file = tmp_path / "test_trades.db"
    monkeypatch.setattr(lg, "DB_PATH", db_file)
    # Re-init the schema in the temp DB
    lg.init_db()
    # Reset portfolio singleton
    pm._portfolio = None
    yield
    pm._portfolio = None


def _fresh_portfolio():
    """Return a fresh Portfolio instance, bypassing DB restore."""
    pm._portfolio = None
    return pm.Portfolio(balance=1_000_000.0, initial_balance=1_000_000.0)


def test_initial_balance():
    p = _fresh_portfolio()
    assert p.balance == 1_000_000.0


def test_simulate_trade_deducts_balance():
    from dataclasses import dataclass, field

    p = _fresh_portfolio()

    @dataclass
    class FakeMarket:
        condition_id: str = "mkt_001"
        question: str = "Will X happen?"
        category: str = "crypto"
        yes_price: float = 0.60
        source: str = "polymarket"

    @dataclass
    class FakeClassification:
        direction: str = "YES"
        confidence: float = 0.8
        materiality: float = 0.5
        novelty_score: float = 0.6
        reasoning: str = "test"
        total_latency_ms: int = 100
        is_actionable: bool = True

    @dataclass
    class FakeSignal:
        market: FakeMarket = field(default_factory=FakeMarket)
        classification: FakeClassification = field(default_factory=FakeClassification)
        side: str = "YES"
        bet_amount: float = 100.0
        p_market: float = 0.60
        ev: float = 0.05
        spread: float = 0.02
        news_source: str = "rss"
        headlines: str = "BTC hits ATH"
        reasoning: str = "test"
        news_latency_ms: int = 50
        classification_latency_ms: int = 200
        estimated_slippage: float = 0.01

    signal = FakeSignal()
    result = p.simulate_trade(signal)

    assert result.status == "paper"
    assert p.balance == pytest.approx(999_900.0)
    assert "mkt_001" in p.positions


def test_mark_to_market_yes():
    from portfolio import Position
    from datetime import datetime, timezone

    p = _fresh_portfolio()
    pos = Position(
        position_id=1,
        market_id="mkt_001",
        market_question="Will X?",
        platform="polymarket",
        category="crypto",
        side="YES",
        entry_price=0.50,
        size_usd=100.0,
        contracts=200.0,
        opened_at=datetime.now(timezone.utc),
    )
    p.positions["mkt_001"] = pos
    pnl = p.mark_to_market("mkt_001", 0.60)
    assert pnl == pytest.approx(200.0 * (0.60 - 0.50))  # 20.0


def test_mark_to_market_no():
    from portfolio import Position
    from datetime import datetime, timezone

    p = _fresh_portfolio()
    pos = Position(
        position_id=2,
        market_id="mkt_002",
        market_question="Will Y?",
        platform="kalshi",
        category="politics",
        side="NO",
        entry_price=0.40,
        size_usd=100.0,
        contracts=166.67,
        opened_at=datetime.now(timezone.utc),
    )
    p.positions["mkt_002"] = pos
    pnl = p.mark_to_market("mkt_002", 0.30)
    expected = 166.67 * (0.40 - 0.30)
    assert pnl == pytest.approx(expected, rel=1e-3)


def test_get_portfolio_state_keys():
    p = _fresh_portfolio()
    state = p.get_portfolio_state()
    required_keys = {
        "balance", "initial_balance", "total_value", "unrealized_pnl",
        "realized_pnl", "open_positions", "closed_positions",
        "win_rate", "sharpe_ratio", "max_drawdown", "total_return_pct", "by_category"
    }
    assert required_keys.issubset(set(state.keys()))


def test_close_position_restores_balance():
    from portfolio import Position
    from datetime import datetime, timezone

    p = _fresh_portfolio()
    pos = Position(
        position_id=1,
        market_id="mkt_close",
        market_question="Will Z?",
        platform="polymarket",
        category="crypto",
        side="YES",
        entry_price=0.50,
        size_usd=200.0,
        contracts=400.0,  # 200 / 0.50
        opened_at=datetime.now(timezone.utc),
    )
    # Manually insert into DB so update_position_closed finds it
    pos.position_id = lg.log_position(
        market_id=pos.market_id,
        market_question=pos.market_question,
        platform=pos.platform,
        category=pos.category,
        side=pos.side,
        entry_price=pos.entry_price,
        size_usd=pos.size_usd,
        contracts=pos.contracts,
        opened_at=pos.opened_at.isoformat(),
    )
    p.positions["mkt_close"] = pos
    p.balance -= pos.size_usd  # simulate balance already deducted

    realized = p.close_position("mkt_close", exit_price=0.60)
    # YES P&L: 400 contracts * (0.60 - 0.50) = 40.0
    assert realized == pytest.approx(40.0)
    # balance should be restored: (1M - 200) + 200 + 40 = 1_000_040
    assert p.balance == pytest.approx(1_000_040.0)


def test_get_sharpe_ratio_known_sequence():
    p = _fresh_portfolio()
    # Add 3 daily returns: 0.01, 0.02, 0.03
    p.daily_returns = [0.01, 0.02, 0.03]
    sharpe = p.get_sharpe_ratio()
    import math
    mean = 0.02
    std = math.sqrt(((0.01-0.02)**2 + (0.02-0.02)**2 + (0.03-0.02)**2) / 2)
    expected = round(mean / std * math.sqrt(252), 4)
    assert sharpe == pytest.approx(expected)
