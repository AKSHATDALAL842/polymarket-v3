"""Tests for fast_classifier: watchlist path and is_trained() (A-2 fix)."""
from __future__ import annotations

import pytest

import signal.fast_classifier as fc


# ---------------------------------------------------------------------------
# is_trained()
# ---------------------------------------------------------------------------

def test_is_trained_false_when_no_model(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "_lgbm_model", None)
    monkeypatch.setattr(fc, "_MODEL_PATH", tmp_path / "nonexistent.lgbm")
    assert fc.is_trained() is False


def test_is_trained_true_when_model_file_exists(tmp_path, monkeypatch):
    model_file = tmp_path / "fast_classifier.lgbm"
    model_file.touch()
    monkeypatch.setattr(fc, "_lgbm_model", None)
    monkeypatch.setattr(fc, "_MODEL_PATH", model_file)
    assert fc.is_trained() is True


def test_is_trained_true_when_model_loaded(monkeypatch):
    monkeypatch.setattr(fc, "_lgbm_model", object())  # any truthy sentinel
    assert fc.is_trained() is True


# ---------------------------------------------------------------------------
# build_classification: watchlist hit → time_sensitivity="immediate"
# ---------------------------------------------------------------------------

def test_build_classification_watchlist_immediate(monkeypatch):
    """A watchlist-method result must produce time_sensitivity='immediate'."""
    result = fc.ClassifierResult(
        direction="YES",
        confidence=0.80,
        materiality=0.70,
        method="watchlist",
        latency_ms=1,
    )
    cls = fc.build_classification(result)
    assert cls.time_sensitivity == "immediate"


def test_build_classification_non_watchlist_short_term(monkeypatch):
    """Rule-based / lgbm results must produce time_sensitivity='short-term'."""
    for method in ("rule_based", "lgbm"):
        result = fc.ClassifierResult(
            direction="YES",
            confidence=0.75,
            materiality=0.60,
            method=method,
            latency_ms=1,
        )
        cls = fc.build_classification(result)
        assert cls.time_sensitivity == "short-term", f"failed for method={method!r}"


# ---------------------------------------------------------------------------
# predict(): watchlist short-circuit path
# ---------------------------------------------------------------------------

def test_predict_watchlist_path_direction(monkeypatch):
    """
    A watchlist hit from a credible source must take the short-circuit path
    and return the correct direction without touching LightGBM.
    """
    monkeypatch.setattr(fc, "_lgbm_model", None)

    result = fc.predict(
        headline="Ceasefire collapses as fighting resumes across the border",
        source="Reuters",
        market_yes_price=0.50,
    )

    assert result.direction == "NO"
    assert result.method == "watchlist"
    assert result.confidence > 0.0


def test_predict_watchlist_path_yes(monkeypatch):
    monkeypatch.setattr(fc, "_lgbm_model", None)

    result = fc.predict(
        headline="Trade deal reached between US and China",
        source="Bloomberg",
        market_yes_price=0.45,
    )

    assert result.direction == "YES"
    assert result.method == "watchlist"


def test_predict_low_credibility_source_skips_watchlist_shortcircuit(monkeypatch):
    """
    Watchlist short-circuit requires source credibility >= 0.65.
    A low-credibility source should fall through to rule_based.
    """
    monkeypatch.setattr(fc, "_lgbm_model", None)

    result = fc.predict(
        headline="Ceasefire collapses according to some blog",
        source="randomtrumoredblog.net",
        market_yes_price=0.50,
    )
    # Method must NOT be "watchlist" for a low-cred source.
    assert result.method != "watchlist"
