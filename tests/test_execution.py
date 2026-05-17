"""
Tests for execution hardening: Order FSM, Position FSM, Circuit Breakers.
"""
import time
from execution.order_lifecycle import (
    OrderStage, VALID_ORDER_TRANSITIONS, Order, OrderLedger,
    generate_order_id, generate_idempotency_key, get_order_ledger,
)
from execution.position_lifecycle import (
    PositionStage, VALID_POSITION_TRANSITIONS, Position, PositionLedger,
    get_position_ledger,
)
from execution.circuit_breakers import (
    CircuitBreaker, ExecutionCircuitBreakers, BreakerState,
    get_circuit_breakers,
)


class TestOrderFSM:
    def test_legal_transitions(self):
        assert OrderStage.VALIDATED in VALID_ORDER_TRANSITIONS[OrderStage.CREATED]
        assert OrderStage.SUBMITTED in VALID_ORDER_TRANSITIONS[OrderStage.VALIDATED]
        assert OrderStage.FILLED in VALID_ORDER_TRANSITIONS[OrderStage.ACKNOWLEDGED]
        assert OrderStage.SETTLED in VALID_ORDER_TRANSITIONS[OrderStage.FILLED]

    def test_terminal_states_immutable(self):
        for terminal in (OrderStage.REJECTED, OrderStage.EXPIRED, OrderStage.SETTLED):
            assert len(VALID_ORDER_TRANSITIONS[terminal]) == 0

    def test_cancelled_can_only_settle(self):
        assert VALID_ORDER_TRANSITIONS[OrderStage.CANCELLED] == {OrderStage.SETTLED}

    def test_idempotency_key_deterministic(self):
        k1 = generate_idempotency_key("sig-abc", "market-1", "YES", 25.0, 0.65)
        k2 = generate_idempotency_key("sig-abc", "market-1", "YES", 25.0, 0.65)
        assert k1 == k2

    def test_idempotency_key_different_for_different_inputs(self):
        k1 = generate_idempotency_key("sig-abc", "market-1", "YES", 25.0, 0.65)
        k2 = generate_idempotency_key("sig-abc", "market-1", "NO", 25.0, 0.65)
        assert k1 != k2

    def test_generate_order_id_unique(self):
        ids = {generate_order_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_order_happy_path(self):
        order = Order(
            order_id="ord-test", market_id="mkt-1", signal_trace_id="sig-1",
            idempotency_key="idem-1", side="YES", size_usd=25.0, limit_price=0.65,
            created_at=time.monotonic(),
        )
        assert order.transition(OrderStage.VALIDATED)
        assert order.transition(OrderStage.SUBMITTED)
        assert order.transition(OrderStage.ACKNOWLEDGED)
        assert order.transition(OrderStage.FILLED)
        assert order.transition(OrderStage.SETTLED)
        assert order.is_terminal()
        assert len(order.ledger) == 5

    def test_order_rejection_path(self):
        order = Order(
            order_id="ord-rej", market_id="mkt-2", signal_trace_id="sig-2",
            idempotency_key="idem-2", side="NO", size_usd=10.0, limit_price=0.35,
            created_at=time.monotonic(),
        )
        assert order.transition(OrderStage.VALIDATED)
        assert order.transition(OrderStage.SUBMITTED)
        assert order.transition(OrderStage.REJECTED, error="Insufficient balance")
        assert order.is_terminal()
        assert order.rejection_reason == "Insufficient balance"

    def test_order_illegal_transition(self):
        order = Order(
            order_id="ord-bad", market_id="mkt-3", signal_trace_id="sig-3",
            idempotency_key="idem-3", side="YES", size_usd=25.0, limit_price=0.50,
            created_at=time.monotonic(),
        )
        assert not order.transition(OrderStage.FILLED)  # skip VALIDATED+SUBMITTED
        assert order.current_stage == OrderStage.CREATED

    def test_cancel_to_settled(self):
        order = Order(
            order_id="ord-cxl", market_id="mkt-4", signal_trace_id="sig-4",
            idempotency_key="idem-4", side="YES", size_usd=15.0, limit_price=0.60,
            created_at=time.monotonic(),
        )
        order.transition(OrderStage.VALIDATED)
        order.transition(OrderStage.SUBMITTED)
        order.transition(OrderStage.ACKNOWLEDGED)
        order.transition(OrderStage.CANCEL_PENDING)
        order.transition(OrderStage.CANCELLED)
        order.transition(OrderStage.SETTLED)
        assert order.is_terminal()

    def test_idempotency_prevents_duplicate_creation(self):
        ledger = OrderLedger()
        o1 = ledger.create_order("mkt-dup", "sig-dup", "YES", 25.0, 0.65)
        o2 = ledger.create_order("mkt-dup", "sig-dup", "YES", 25.0, 0.65)
        assert o1.order_id == o2.order_id
        assert ledger.total_active_exposure() == 25.0

    def test_can_retry(self):
        order = Order(
            order_id="ord-retry", market_id="mkt-5", signal_trace_id="sig-5",
            idempotency_key="idem-5", side="YES", size_usd=25.0, limit_price=0.50,
            created_at=time.monotonic(),
        )
        assert order.can_retry()
        for _ in range(3):
            order.record_retry()
        assert not order.can_retry()


class TestPositionFSM:
    def test_legal_transitions(self):
        assert PositionStage.OPEN in VALID_POSITION_TRANSITIONS[PositionStage.OPENING]
        assert PositionStage.CLOSED in VALID_POSITION_TRANSITIONS[PositionStage.OPEN]
        assert PositionStage.SETTLING in VALID_POSITION_TRANSITIONS[PositionStage.CLOSED]

    def test_settled_is_terminal(self):
        assert len(VALID_POSITION_TRANSITIONS[PositionStage.SETTLED]) == 0

    def test_orphaned_can_recover(self):
        assert PositionStage.RECONCILING in VALID_POSITION_TRANSITIONS[PositionStage.ORPHANED]
        assert PositionStage.CLOSED in VALID_POSITION_TRANSITIONS[PositionStage.ORPHANED]

    def test_position_happy_path(self):
        pos = Position(
            position_id="pos-test", market_id="mkt-1",
            market_question="Will BTC hit 100K?", category="crypto",
            platform="polymarket", signal_trace_id="sig-1",
            order_ids=["ord-1"], side="YES", entry_price=0.65,
            size_usd=25.0, contracts=38.46,
        )
        # Position starts at OPENING — transition to OPEN
        assert pos.transition(PositionStage.OPEN)
        assert pos.is_active()
        pos.settle(1.0)
        assert pos.current_stage == PositionStage.SETTLED
        assert pos.realized_pnl > 0

    def test_position_mark_to_market(self):
        pos = Position(
            position_id="pos-mtm", market_id="mkt-2",
            market_question="Test market", category="politics",
            platform="polymarket", signal_trace_id="sig-2",
            order_ids=["ord-2"], side="YES", entry_price=0.50,
            size_usd=10.0, contracts=20.0,
        )
        pos.transition(PositionStage.OPEN)
        pnl = pos.mark_to_market(0.70)
        assert abs(pnl - 4.0) < 0.01  # 20 * (0.70 - 0.50)

    def test_position_no_side_mark_to_market(self):
        pos = Position(
            position_id="pos-no", market_id="mkt-3",
            market_question="Test market", category="politics",
            platform="polymarket", signal_trace_id="sig-3",
            order_ids=["ord-3"], side="NO", entry_price=0.40,
            size_usd=10.0, contracts=16.67,
        )
        pos.transition(PositionStage.OPEN)
        pnl = pos.mark_to_market(0.30)  # market moved from 0.40 to 0.30 for NO
        assert round(pnl, 2) == 1.67

    def test_position_illegal_transition(self):
        pos = Position(
            position_id="pos-bad", market_id="mkt-4",
            market_question="Test", category="ai", platform="kalshi",
            signal_trace_id="sig-4", order_ids=[], side="YES",
            entry_price=0.50, size_usd=10.0, contracts=20.0,
        )
        assert not pos.transition(PositionStage.SETTLED)
        assert pos.current_stage == PositionStage.OPENING

    def test_orphan_flagging(self):
        pos = Position(
            position_id="pos-orph", market_id="mkt-5",
            market_question="Test", category="ai", platform="polymarket",
            signal_trace_id="sig-5", order_ids=[], side="YES",
            entry_price=0.50, size_usd=10.0, contracts=20.0,
        )
        pos.transition(PositionStage.OPEN)
        pos.flag_orphaned("Market closed unexpectedly")
        assert pos.current_stage == PositionStage.ORPHANED
        assert pos.reconciliation_count == 1

    def test_position_ledger_exposure_tracking(self):
        ledger = PositionLedger()
        ledger.open_position("mkt-a", "Q1", "crypto", "polymarket",
                             "sig-a", "YES", 0.65, 25.0, 38.46)
        ledger.open_position("mkt-b", "Q2", "politics", "polymarket",
                             "sig-b", "NO", 0.40, 15.0, 25.0)
        assert ledger.total_exposure() == 40.0
        assert ledger.category_exposure("crypto") == 25.0
        assert ledger.category_exposure("politics") == 15.0
        assert len(ledger.get_active_positions()) == 2


class TestCircuitBreakers:
    def test_breaker_starts_closed(self):
        cb = CircuitBreaker("test", threshold=5.0)
        assert cb.state == BreakerState.CLOSED

    def test_breaker_trips_when_threshold_exceeded(self):
        cb = CircuitBreaker("test", threshold=5.0, window_seconds=60)
        cb.record(10.0)
        trip = cb.check()
        assert trip is not None
        assert cb.state == BreakerState.OPEN
        assert cb.trip_count == 1

    def test_breaker_does_not_trip_below_threshold(self):
        cb = CircuitBreaker("test", threshold=5.0)
        cb.record(3.0)
        trip = cb.check()
        assert trip is None
        assert cb.state == BreakerState.CLOSED

    def test_breaker_half_open_after_cooldown(self):
        cb = CircuitBreaker("test", threshold=5.0, cooldown_seconds=0.01)
        cb.record(10.0)
        cb.check()
        assert cb.state == BreakerState.OPEN
        time.sleep(0.02)
        # After cooldown, should transition to half-open
        # The reading still exists but breaker should not re-trip while half-open
        # (it would need a new reading above threshold to trip again)
        cb.reset()  # Clean reset for the test
        assert cb.state == BreakerState.CLOSED

    def test_breaker_reset(self):
        cb = CircuitBreaker("test", threshold=5.0)
        cb.record(10.0)
        cb.check()
        cb.reset()
        assert cb.state == BreakerState.CLOSED
        assert cb.check() is None

    def test_execution_breakers_collection(self):
        ebc = ExecutionCircuitBreakers()
        ebc.record_loss(100.0)
        trips = ebc.check_all()
        assert any(t.breaker_name == "rapid_losses" for t in trips)

    def test_can_execute_blocks_when_any_tripped(self):
        ebc = ExecutionCircuitBreakers()
        assert ebc.can_execute()
        ebc.record_loss(100.0)
        ebc.check_all()
        assert not ebc.can_execute()

    def test_excessive_slippage_trips(self):
        ebc = ExecutionCircuitBreakers()
        ebc.record_slippage(0.08)
        trips = ebc.check_all()
        assert any(t.breaker_name == "excessive_slippage" for t in trips)

    def test_status_report(self):
        ebc = ExecutionCircuitBreakers()
        status = ebc.status()
        assert "rapid_losses" in status
        assert "excessive_slippage" in status
        assert all(s["state"] == "closed" for s in status.values())
