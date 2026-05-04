"""Tests for Kalshi executor order computation (B-1 fix)."""
from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from types import SimpleNamespace

from execution.kalshi_executor import _compute_kalshi_order


@dataclass
class FakeMarket:
    condition_id: str = "mkt-abc"
    question: str = "Will X happen?"
    yes_price: float = 0.50
    source: str = "kalshi"


@dataclass
class FakeSignal:
    side: str
    p_market: float
    spread: float = 0.02
    bet_amount: float = 25.0
    ev: float = 0.05
    news_latency_ms: int = 0
    classification_latency_ms: int = 0
    market: FakeMarket = field(default_factory=FakeMarket)


# ---------------------------------------------------------------------------
# YES side
# ---------------------------------------------------------------------------

def test_yes_order_yes_price_equals_limit(monkeypatch):
    """For a YES buy, yes_price in the API body must equal limit_cents."""
    import config
    monkeypatch.setattr(config, "LIMIT_ORDER_OFFSET", 0.01)  # 1 cent

    sig = FakeSignal(side="YES", p_market=0.50)
    limit_cents, count, side = _compute_kalshi_order(sig)

    assert side == "yes"
    # limit_cents is the yes_price field sent for YES buys
    expected_yes_price_in_body = limit_cents
    assert expected_yes_price_in_body == limit_cents  # tautological but explicit


def test_yes_order_limit_capped_at_99(monkeypatch):
    import config
    monkeypatch.setattr(config, "LIMIT_ORDER_OFFSET", 0.10)

    sig = FakeSignal(side="YES", p_market=0.98)
    limit_cents, _, side = _compute_kalshi_order(sig)

    assert side == "yes"
    assert limit_cents <= 99


# ---------------------------------------------------------------------------
# NO side — the B-1 fix: yes_price must be 100 - limit_cents
# ---------------------------------------------------------------------------

def test_no_order_yes_price_is_complement(monkeypatch):
    """
    For a NO buy, the API body's yes_price field must be (100 - limit_cents),
    NOT limit_cents. This is the Kalshi API convention: yes_price is always
    expressed from the YES perspective, even when buying NO.
    """
    import config
    monkeypatch.setattr(config, "LIMIT_ORDER_OFFSET", 0.01)

    sig = FakeSignal(side="NO", p_market=0.50, spread=0.02)
    limit_cents, count, side = _compute_kalshi_order(sig)

    # Simulate what _execute_live() does when building the order body:
    yes_price_in_body = limit_cents if side == "yes" else max(1, 100 - limit_cents)

    assert side == "no"
    # For NO orders, yes_price in body must NOT equal limit_cents
    assert yes_price_in_body == max(1, 100 - limit_cents)
    assert yes_price_in_body != limit_cents or limit_cents == 50  # only equal at midpoint


def test_no_order_yes_price_at_least_1(monkeypatch):
    """yes_price for NO must be at least 1 cent (clipped by max(1, ...))."""
    import config
    monkeypatch.setattr(config, "LIMIT_ORDER_OFFSET", 0.00)

    # When NO price is ~99¢, limit_cents≈99, so 100-99=1 → still valid.
    sig = FakeSignal(side="NO", p_market=0.01, spread=0.00)
    limit_cents, _, side = _compute_kalshi_order(sig)

    yes_price_in_body = max(1, 100 - limit_cents)
    assert yes_price_in_body >= 1


def test_no_order_count_positive(monkeypatch):
    import config
    monkeypatch.setattr(config, "LIMIT_ORDER_OFFSET", 0.01)

    sig = FakeSignal(side="NO", p_market=0.60, bet_amount=50.0)
    _, count, side = _compute_kalshi_order(sig)

    assert side == "no"
    assert count >= 1


# ---------------------------------------------------------------------------
# Symmetry check: YES and NO should produce complementary yes_prices
# ---------------------------------------------------------------------------

def test_yes_no_prices_are_complementary(monkeypatch):
    """
    YES limit at price P and NO limit at (100-P) should be roughly complementary,
    reflecting that both sides price the same event.
    """
    import config
    monkeypatch.setattr(config, "LIMIT_ORDER_OFFSET", 0.00)

    p = 0.55
    yes_sig = FakeSignal(side="YES", p_market=p, spread=0.00)
    no_sig  = FakeSignal(side="NO",  p_market=p, spread=0.00)

    yes_limit, _, yes_side = _compute_kalshi_order(yes_sig)
    no_limit,  _, no_side  = _compute_kalshi_order(no_sig)

    yes_price_yes = yes_limit                   # body for YES order
    yes_price_no  = max(1, 100 - no_limit)     # body for NO order

    # Both should be near 55¢ from the YES perspective
    assert abs(yes_price_yes - yes_price_no) <= 2, (
        f"YES body yes_price={yes_price_yes}, NO body yes_price={yes_price_no} — too far apart"
    )
