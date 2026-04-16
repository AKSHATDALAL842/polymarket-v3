import pytest
from unittest.mock import MagicMock
from alpha.news_alpha import NewsAlpha


def make_signal(direction="YES", confidence=0.75, ev=0.05,
                time_sensitivity="short-term", condition_id="0xabc",
                question="Will BTC go up?"):
    """Build a minimal mock of edge_model.Signal."""
    cls = MagicMock()
    cls.confidence = confidence
    cls.time_sensitivity = time_sensitivity

    market = MagicMock()
    market.condition_id = condition_id
    market.question = question

    sig = MagicMock()
    sig.side = direction
    sig.ev = ev
    sig.classification = cls
    sig.market = market
    return sig


def test_none_signal_returns_none():
    na = NewsAlpha()
    assert na.to_alpha_signal(None) is None


def test_valid_signal_converts():
    na = NewsAlpha()
    sig = make_signal(direction="YES", confidence=0.8, ev=0.06)
    result = na.to_alpha_signal(sig)
    assert result is not None
    assert result.direction == "YES"
    assert result.confidence == 0.8
    assert result.expected_edge == 0.06
    assert result.strategy == "news"
    assert result.market_id == "0xabc"
    assert result.raw_signal is sig


def test_horizon_immediate():
    na = NewsAlpha()
    sig = make_signal(time_sensitivity="immediate")
    result = na.to_alpha_signal(sig)
    assert result.horizon == "5m"


def test_horizon_short_term():
    na = NewsAlpha()
    sig = make_signal(time_sensitivity="short-term")
    result = na.to_alpha_signal(sig)
    assert result.horizon == "1h"


def test_horizon_long_term():
    na = NewsAlpha()
    sig = make_signal(time_sensitivity="long-term")
    result = na.to_alpha_signal(sig)
    assert result.horizon == "1d"


def test_horizon_unknown_defaults_to_1h():
    na = NewsAlpha()
    sig = make_signal(time_sensitivity="very-long-term")
    result = na.to_alpha_signal(sig)
    assert result.horizon == "1h"


def test_attribute_error_returns_none():
    na = NewsAlpha()
    # Signal missing classification attribute entirely
    bad_signal = MagicMock(spec=[])  # spec=[] means no attributes
    result = na.to_alpha_signal(bad_signal)
    assert result is None


def test_invalid_direction_returns_none():
    na = NewsAlpha()
    sig = make_signal(direction="SIDEWAYS")  # invalid direction → ValueError in AlphaSignal
    result = na.to_alpha_signal(sig)
    assert result is None
