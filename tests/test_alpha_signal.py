import pytest
import time
from alpha.signal import AlphaSignal, AggregatedSignal


def test_alpha_signal_valid():
    s = AlphaSignal(
        market_id="0xabc",
        market_question="Will BTC go up?",
        direction="YES",
        confidence=0.75,
        expected_edge=0.05,
        horizon="5m",
        strategy="news",
    )
    assert s.direction == "YES"
    assert s.confidence == 0.75
    assert s.strategy == "news"
    assert isinstance(s.timestamp, float)


def test_alpha_signal_invalid_direction():
    with pytest.raises(ValueError, match="direction must be YES or NO"):
        AlphaSignal(
            market_id="0xabc",
            market_question="Will BTC go up?",
            direction="MAYBE",
            confidence=0.75,
            expected_edge=0.05,
            horizon="5m",
            strategy="news",
        )


def test_alpha_signal_invalid_confidence():
    with pytest.raises(ValueError, match="confidence must be in"):
        AlphaSignal(
            market_id="0xabc",
            market_question="Will BTC go up?",
            direction="YES",
            confidence=1.5,
            expected_edge=0.05,
            horizon="5m",
            strategy="news",
        )


def test_alpha_signal_invalid_confidence_lower():
    with pytest.raises(ValueError, match="confidence must be in"):
        AlphaSignal("0xabc", "Q", "YES", -0.1, 0.05, "5m", "news")


def test_alpha_signal_invalid_horizon():
    with pytest.raises(ValueError, match="horizon must be"):
        AlphaSignal("0xabc", "Q", "YES", 0.7, 0.05, "10m", "news")


def test_alpha_signal_invalid_strategy():
    with pytest.raises(ValueError, match="strategy must be"):
        AlphaSignal("0xabc", "Q", "YES", 0.7, 0.05, "5m", "volume")


def test_alpha_signal_empty_market_id():
    with pytest.raises(ValueError, match="market_id"):
        AlphaSignal("", "Q", "YES", 0.7, 0.05, "5m", "news")


def test_aggregated_signal_is_strong():
    s1 = AlphaSignal("0xabc", "Q", "YES", 0.8, 0.06, "1h", "news")
    s2 = AlphaSignal("0xabc", "Q", "YES", 0.7, 0.05, "5m", "momentum")
    agg = AggregatedSignal(
        market_id="0xabc",
        market_question="Q",
        direction="YES",
        confidence=0.75,
        expected_edge=0.055,
        size_multiplier=1.0,
        strategies=["news", "momentum"],
        signals=[s1, s2],
    )
    assert agg.is_strong is True
    assert agg.has_conflict is False


def test_aggregated_signal_conflict():
    s1 = AlphaSignal("0xabc", "Q", "YES", 0.7, 0.05, "1h", "news")
    s2 = AlphaSignal("0xabc", "Q", "NO",  0.6, 0.04, "5m", "momentum")
    agg = AggregatedSignal(
        market_id="0xabc",
        market_question="Q",
        direction="YES",
        confidence=0.42,
        expected_edge=0.03,
        size_multiplier=0.4,
        strategies=["news", "momentum"],
        signals=[s1, s2],
    )
    assert agg.has_conflict is True
    assert agg.is_strong is False


def test_aggregated_signal_single_strategy():
    s1 = AlphaSignal("0xabc", "Q", "YES", 0.8, 0.06, "1h", "news")
    agg = AggregatedSignal(
        market_id="0xabc",
        market_question="Q",
        direction="YES",
        confidence=0.8,
        expected_edge=0.06,
        size_multiplier=0.6,
        strategies=["news"],
        signals=[s1],
    )
    assert agg.is_strong is False
    assert agg.has_conflict is False


def test_aggregated_signal_invalid_direction():
    with pytest.raises(ValueError, match="direction must be YES or NO"):
        AggregatedSignal(
            market_id="0xabc", market_question="Q",
            direction="SIDEWAYS", confidence=0.7, expected_edge=0.05,
            size_multiplier=1.0, strategies=["news"], signals=[],
        )


def test_aggregated_signal_invalid_multiplier():
    with pytest.raises(ValueError, match="size_multiplier must be one of"):
        AggregatedSignal(
            market_id="0xabc", market_question="Q",
            direction="YES", confidence=0.7, expected_edge=0.05,
            size_multiplier=0.9, strategies=["news"], signals=[],
        )
