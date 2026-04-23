import pytest
import config
from control.trading_mode import TradingMode
from control.safety_guard import SafetyGuard, SafetyCheckResult


def test_default_mode_is_paper():
    tm = TradingMode()
    assert tm.mode == "DRY_RUN"
    assert tm.is_live is False
    assert tm.is_paper is True


def test_enable_live_requires_confirm():
    tm = TradingMode()
    result = tm.set_mode("LIVE", confirm=False)
    assert result["success"] is False
    assert "confirm" in result["error"].lower()
    assert tm.mode == "DRY_RUN"


def test_enable_live_safe_conditions(monkeypatch):
    # Patch safety guard to always pass
    monkeypatch.setattr(
        "control.trading_mode.SafetyGuard.check",
        lambda self: SafetyCheckResult(safe=True, reason="ok"),
    )
    tm = TradingMode()
    result = tm.set_mode("LIVE", confirm=True)
    assert result["success"] is True
    assert tm.mode == "LIVE"
    assert config.DRY_RUN is False


def test_enable_live_unsafe_conditions(monkeypatch):
    monkeypatch.setattr(
        "control.trading_mode.SafetyGuard.check",
        lambda self: SafetyCheckResult(safe=False, reason="drawdown too high: 25.00%"),
    )
    tm = TradingMode()
    result = tm.set_mode("LIVE", confirm=True)
    assert result["success"] is False
    assert "drawdown" in result["error"]
    assert tm.mode == "DRY_RUN"


def test_disable_live_always_works(monkeypatch):
    monkeypatch.setattr(
        "control.trading_mode.SafetyGuard.check",
        lambda self: SafetyCheckResult(safe=True, reason="ok"),
    )
    tm = TradingMode()
    tm.set_mode("LIVE", confirm=True)
    result = tm.set_mode("DRY_RUN", confirm=False)
    assert result["success"] is True
    assert tm.is_paper is True
    assert config.DRY_RUN is True


def test_switch_history_logged(monkeypatch):
    monkeypatch.setattr(
        "control.trading_mode.SafetyGuard.check",
        lambda self: SafetyCheckResult(safe=True, reason="ok"),
    )
    tm = TradingMode()
    tm.set_mode("LIVE", confirm=True)
    tm.set_mode("DRY_RUN", confirm=False)
    history = tm.get_history()
    assert len(history) == 2
    assert history[0]["to"] == "LIVE"
    assert history[1]["to"] == "DRY_RUN"
