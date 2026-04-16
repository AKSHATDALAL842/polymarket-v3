# tests/test_allocator.py
import pytest
from alpha.signal import AlphaSignal, AggregatedSignal
from portfolio.allocator import Allocator


def make_agg(direction="YES", confidence=0.75, edge=0.06,
             multiplier=1.0, strategies=None):
    strategies = strategies or ["news"]
    return AggregatedSignal(
        market_id="0xabc",
        market_question="Will BTC go up?",
        direction=direction,
        confidence=confidence,
        expected_edge=edge,
        size_multiplier=multiplier,
        strategies=strategies,
        signals=[],
    )


def test_allocator_basic_size():
    a = Allocator(capital=1_000_000, max_bet=25.0, sizing_k=0.25, bankroll=1000.0)
    sig = make_agg(confidence=0.75, edge=0.06, multiplier=1.0, strategies=["news", "momentum"])
    size = a.compute_size(sig, drawdown=0.0)
    # base = 0.25 * 0.06 * 0.75 * 1000 = 11.25
    # * multiplier 1.0 = 11.25, capped at 25
    assert 10.0 < size <= 25.0


def test_allocator_respects_max_bet():
    a = Allocator(capital=1_000_000, max_bet=25.0, sizing_k=0.25, bankroll=1000.0)
    sig = make_agg(confidence=1.0, edge=1.0, multiplier=1.0)
    size = a.compute_size(sig, drawdown=0.0)
    assert size == 25.0


def test_allocator_conflict_reduces_size():
    a = Allocator(capital=1_000_000, max_bet=25.0, sizing_k=0.25, bankroll=1000.0)
    sig_agree    = make_agg(confidence=0.75, edge=0.06, multiplier=1.0, strategies=["news", "momentum"])
    sig_conflict = make_agg(confidence=0.75, edge=0.06, multiplier=0.4, strategies=["news", "momentum"])
    size_agree    = a.compute_size(sig_agree, drawdown=0.0)
    size_conflict = a.compute_size(sig_conflict, drawdown=0.0)
    assert size_conflict < size_agree


def test_allocator_drawdown_reduces_size():
    a = Allocator(capital=1_000_000, max_bet=25.0, sizing_k=0.25, bankroll=1000.0)
    sig = make_agg(confidence=0.75, edge=0.06, multiplier=1.0)
    size_no_dd   = a.compute_size(sig, drawdown=0.0)
    size_with_dd = a.compute_size(sig, drawdown=0.15)  # 15% drawdown
    assert size_with_dd < size_no_dd


def test_allocator_minimum_one_dollar():
    a = Allocator(capital=1_000_000, max_bet=25.0, sizing_k=0.001, bankroll=1.0)
    sig = make_agg(confidence=0.55, edge=0.03, multiplier=0.4)
    size = a.compute_size(sig, drawdown=0.0)
    assert size >= 1.0
