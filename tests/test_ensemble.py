# tests/test_ensemble.py
import pytest
from alpha.signal import AlphaSignal
from alpha.ensemble import combine

MKT = "0xabc"
Q   = "Will BTC go up?"


def make(strategy, direction, confidence=0.75, edge=0.05):
    return AlphaSignal(
        market_id=MKT, market_question=Q,
        direction=direction, confidence=confidence,
        expected_edge=edge, horizon="1h", strategy=strategy,
    )


def test_combine_agreement_yes():
    sigs = [make("news", "YES", 0.8, 0.06), make("momentum", "YES", 0.7, 0.05)]
    agg = combine(sigs)
    assert agg.direction == "YES"
    assert agg.size_multiplier == 1.0
    assert agg.is_strong is True
    assert set(agg.strategies) == {"news", "momentum"}


def test_combine_agreement_no():
    sigs = [make("news", "NO", 0.8, 0.06), make("momentum", "NO", 0.65, 0.04)]
    agg = combine(sigs)
    assert agg.direction == "NO"
    assert agg.size_multiplier == 1.0


def test_combine_conflict():
    sigs = [make("news", "YES", 0.75, 0.05), make("momentum", "NO", 0.60, 0.04)]
    agg = combine(sigs)
    # News has higher weight (0.6) so YES wins, but multiplier reduced
    assert agg.direction == "YES"
    assert agg.size_multiplier == 0.4
    assert agg.has_conflict is True


def test_combine_news_only():
    sigs = [make("news", "YES", 0.80, 0.06)]
    agg = combine(sigs)
    assert agg.direction == "YES"
    assert agg.size_multiplier == 0.6
    assert agg.strategies == ["news"]


def test_combine_momentum_only():
    sigs = [make("momentum", "NO", 0.70, 0.04)]
    agg = combine(sigs)
    assert agg.direction == "NO"
    assert agg.size_multiplier == 0.6
    assert agg.strategies == ["momentum"]


def test_combine_weighted_confidence():
    # news weight=0.6, momentum weight=0.4
    # news conf=1.0, momentum conf=0.5
    # weighted = (0.6*1.0 + 0.4*0.5) / (0.6+0.4) = 0.80
    sigs = [make("news", "YES", 1.0, 0.10), make("momentum", "YES", 0.5, 0.03)]
    agg = combine(sigs)
    assert abs(agg.confidence - 0.80) < 0.001


def test_combine_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        combine([])


def test_combine_market_preserved():
    class FakeMarket:
        condition_id = MKT
    sig = make("news", "YES")
    sig.market = FakeMarket()
    agg = combine([sig])
    assert agg.market is sig.market
