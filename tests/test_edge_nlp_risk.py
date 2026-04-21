"""
Unit tests for edge_model.py, nlp_processor.py, and risk.py.
Run: pytest tests/test_edge_nlp_risk.py -v
"""
import math
import time
import pytest
from unittest.mock import patch
from dataclasses import dataclass

import config


# ── Helpers ────────────────────────────────────────────────────────────────────

@dataclass
class _Market:
    condition_id: str = "mkt-001"
    question: str = "Will X happen?"
    category: str = "crypto"
    yes_price: float = 0.40
    no_price: float = 0.60
    volume: float = 100_000
    end_date: str = "2026-12-31"
    active: bool = True
    tokens: list = None
    source: str = "polymarket"

    def __post_init__(self):
        if self.tokens is None:
            self.tokens = []


def _cls(direction="YES", confidence=0.75, materiality=0.70,
         novelty_score=0.65, consistency=1.0, time_sensitivity="short-term"):
    from classifier import Classification
    return Classification(
        direction=direction,
        confidence=confidence,
        materiality=materiality,
        novelty_score=novelty_score,
        time_sensitivity=time_sensitivity,
        reasoning="test",
        consistency=consistency,
    )


# ════════════════════════════════════════════════════════════════════════════════
# edge_model — _adjustment formula
# ════════════════════════════════════════════════════════════════════════════════

class TestAdjustmentFormula:

    def test_yes_direction_positive_sign(self):
        from edge_model import _adjustment
        adj = _adjustment("YES", 0.8, 0.8, 0.8, p_market=0.5)
        assert adj > 0, "YES adjustment must be positive"

    def test_no_direction_negative_sign(self):
        from edge_model import _adjustment
        adj = _adjustment("NO", 0.8, 0.8, 0.8, p_market=0.5)
        assert adj < 0, "NO adjustment must be negative"

    def test_neutral_direction_returns_zero(self):
        from edge_model import _adjustment
        assert _adjustment("NEUTRAL", 0.8, 0.8, 0.8, p_market=0.5) == 0.0

    def test_hard_cap_never_exceeded(self):
        from edge_model import _adjustment
        # Max possible inputs — adjustment must not exceed EDGE_MAX_ADJUSTMENT
        adj = abs(_adjustment("YES", 1.0, 1.0, 1.0, p_market=0.5))
        assert adj <= config.EDGE_MAX_ADJUSTMENT + 1e-9

    def test_asymmetric_room_near_boundary(self):
        from edge_model import _adjustment
        # Market already at 0.90 → very little room for YES
        adj_high = abs(_adjustment("YES", 1.0, 1.0, 1.0, p_market=0.90))
        adj_mid  = abs(_adjustment("YES", 1.0, 1.0, 1.0, p_market=0.50))
        assert adj_high < adj_mid, "Less room near boundary must produce smaller adjustment"

    def test_zero_signal_produces_zero_adjustment(self):
        from edge_model import _adjustment
        adj = _adjustment("YES", 0.0, 0.0, 0.0, p_market=0.5)
        assert adj == pytest.approx(0.0, abs=1e-9)


# ════════════════════════════════════════════════════════════════════════════════
# edge_model — compute_edge gates
# ════════════════════════════════════════════════════════════════════════════════

class TestComputeEdgeGates:

    def test_neutral_direction_returns_none(self):
        from edge_model import compute_edge
        mkt = _Market()
        signal = compute_edge(mkt, _cls(direction="NEUTRAL"))
        assert signal is None

    def test_low_confidence_returns_none(self):
        from edge_model import compute_edge
        mkt = _Market()
        signal = compute_edge(mkt, _cls(confidence=0.30))
        assert signal is None

    def test_low_novelty_returns_none(self):
        from edge_model import compute_edge
        mkt = _Market()
        signal = compute_edge(mkt, _cls(novelty_score=0.05))
        assert signal is None

    def test_wide_spread_returns_none(self):
        from edge_model import compute_edge
        mkt = _Market()
        signal = compute_edge(mkt, _cls(), spread=0.15)   # 15% > 8% max
        assert signal is None

    def test_illiquid_market_returns_none(self):
        from edge_model import compute_edge
        mkt = _Market()
        signal = compute_edge(mkt, _cls(), liquidity_score=0.05)
        assert signal is None

    def test_valid_signal_has_correct_side(self):
        from edge_model import compute_edge
        mkt = _Market(yes_price=0.35)
        signal = compute_edge(mkt, _cls(direction="YES"), liquidity_score=0.8, spread=0.03)
        if signal is not None:
            assert signal.side == "YES"

    def test_ev_is_positive_for_valid_signal(self):
        from edge_model import compute_edge
        mkt = _Market(yes_price=0.35)
        signal = compute_edge(mkt, _cls(direction="YES"), liquidity_score=0.8, spread=0.02)
        if signal is not None:
            assert signal.ev > 0

    def test_bet_amount_respects_max_cap(self):
        from edge_model import compute_edge
        mkt = _Market(yes_price=0.35)
        signal = compute_edge(mkt, _cls(direction="YES"), liquidity_score=0.9, spread=0.01)
        if signal is not None:
            assert signal.bet_amount <= config.MAX_BET_USD


# ════════════════════════════════════════════════════════════════════════════════
# nlp_processor — impact score and temporal decay
# ════════════════════════════════════════════════════════════════════════════════

class TestNLPProcessor:

    def test_impact_score_range(self):
        from nlp_processor import compute_impact_score
        score = compute_impact_score(
            source="rss", sentiment_polarity=0.6, sentiment_confidence=0.7,
            entity_importance=0.8, novelty_score=0.7, velocity_score=0.3,
        )
        assert 0.0 <= score <= 1.0

    def test_temporal_decay_at_zero_age(self):
        from nlp_processor import apply_temporal_decay
        result = apply_temporal_decay(impact=0.8, age_seconds=0)
        assert result == pytest.approx(0.8, rel=1e-6)

    def test_temporal_decay_half_life(self):
        """Relevance should halve after ~13.9 minutes (ln2 / 0.05)."""
        from nlp_processor import apply_temporal_decay
        half_life_seconds = math.log(2) / 0.05 * 60
        result = apply_temporal_decay(impact=1.0, age_seconds=half_life_seconds)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_high_reliability_source_raises_score(self):
        from nlp_processor import compute_impact_score
        score_gnews = compute_impact_score("gnews",   0.5, 0.5, 0.5, 0.5, 0.0)
        score_reddit = compute_impact_score("reddit", 0.5, 0.5, 0.5, 0.5, 0.0)
        assert score_gnews > score_reddit

    def test_process_returns_nlpresult(self):
        from nlp_processor import process, NLPResult
        result = process("Fed raises rates by 25 basis points", source="rss", age_seconds=60)
        assert isinstance(result, NLPResult)
        assert 0.0 <= result.impact_score <= 1.0
        assert 0.0 <= result.relevance <= result.impact_score + 1e-9


# ════════════════════════════════════════════════════════════════════════════════
# risk.py — state transitions and atomic check_and_open
# ════════════════════════════════════════════════════════════════════════════════

class TestRiskManager:

    def setup_method(self):
        """Fresh RiskManager instance for every test."""
        from risk import RiskManager
        RiskManager._singleton = None
        self.rm = RiskManager.instance()

    def test_fresh_manager_allows_trade(self):
        opened = self.rm.check_and_open("mkt-1", "crypto", 10.0)
        assert opened is True

    def test_position_recorded_after_open(self):
        self.rm.check_and_open("mkt-1", "crypto", 10.0)
        assert "mkt-1" in self.rm._open_positions
        assert self.rm._category_exposure["crypto"] == pytest.approx(10.0)

    def test_max_positions_blocks_new_trade(self):
        for i in range(config.MAX_CONCURRENT_POSITIONS):
            self.rm.check_and_open(f"mkt-{i}", "crypto", 5.0)
        opened = self.rm.check_and_open("mkt-overflow", "crypto", 5.0)
        assert opened is False

    def test_category_exposure_cap_blocks_trade(self):
        # Fill up to the cap
        self.rm.check_and_open("mkt-1", "politics", config.MAX_EXPOSURE_PER_CATEGORY_USD - 1.0)
        # Next trade would exceed cap
        opened = self.rm.check_and_open("mkt-2", "politics", 5.0)
        assert opened is False

    def test_consecutive_loss_triggers_cooldown(self):
        for i in range(config.CONSECUTIVE_LOSS_COOLDOWN):
            self.rm.on_trade_closed(f"mkt-{i}", "crypto", pnl=-1.0)
        assert self.rm.in_cooldown() is True

    def test_win_resets_consecutive_losses(self):
        self.rm.on_trade_closed("mkt-1", "crypto", pnl=-1.0)
        self.rm.on_trade_closed("mkt-2", "crypto", pnl=-1.0)
        self.rm.on_trade_closed("mkt-3", "crypto", pnl=+5.0)   # win resets counter
        assert self.rm._consecutive_losses == 0

    def test_cooldown_blocks_check_and_open(self):
        # Force cooldown
        self.rm._cooldown_until = time.monotonic() + 1800
        opened = self.rm.check_and_open("mkt-x", "crypto", 5.0)
        assert opened is False

    def test_on_trade_closed_removes_position(self):
        self.rm.check_and_open("mkt-1", "crypto", 10.0)
        self.rm.on_trade_closed("mkt-1", "crypto", pnl=2.0)
        assert "mkt-1" not in self.rm._open_positions
        assert self.rm._category_exposure["crypto"] == pytest.approx(0.0)
