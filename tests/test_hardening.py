"""
Tests for final hardening: Reconciliation, Settlement, Risk Accounting.
"""
import time
from execution.reconciliation import (
    ReconciliationEngine, ReconciliationState, ReconciliationAnomaly,
    AnomalySeverity, get_reconciliation_engine,
)
from execution.settlement import (
    SettlementEngine, SettlementRecord, SettlementStage,
    get_settlement_engine,
)
from execution.risk_accounting import (
    RiskAccountant, ExposureLimits, RiskExposure,
)


class TestReconciliation:
    def test_engine_starts_clean(self):
        engine = ReconciliationEngine(check_interval=9999)
        assert engine.state == ReconciliationState.CLEAN
        assert engine._cycle_count == 0

    def test_anomaly_creation(self):
        a = ReconciliationAnomaly(
            anomaly_id="anom-test-1",
            anomaly_type="stale_order",
            severity=AnomalySeverity.WARNING,
            local_state={"order_id": "ord-1", "stage": "SUBMITTED"},
            exchange_state=None,
            description="Order stale for 3600s",
            repair_action="mark_expired",
        )
        assert a.severity == AnomalySeverity.WARNING
        assert a.repair_action == "mark_expired"
        assert a.repair_success is None

    def test_severity_ordering(self):
        assert AnomalySeverity.INFO.value < AnomalySeverity.WARNING.value
        assert AnomalySeverity.WARNING.value < AnomalySeverity.ERROR.value
        assert AnomalySeverity.ERROR.value < AnomalySeverity.CRITICAL.value

    def test_recon_engine_status(self):
        engine = ReconciliationEngine(check_interval=9999)
        status = engine.status()
        assert status["state"] == "clean"
        assert status["cycles_completed"] == 0
        assert status["total_escalations"] == 0


class TestSettlement:
    def test_settlement_record_lifecycle(self):
        record = SettlementRecord(
            settlement_id="settle-test-1",
            market_id="mkt-1",
            market_question="Will BTC hit 100K?",
            position_id="pos-1",
            signal_trace_id="sig-1",
            resolved_yes=True,
            exit_price=1.0,
            realized_pnl=13.46,
            entry_price=0.65,
            side="YES",
            size_usd=25.0,
            contracts=38.46,
        )
        assert record.current_stage == SettlementStage.RESOLUTION_PENDING
        record.confirm(source="gamma_api")
        assert record.current_stage == SettlementStage.RESOLUTION_CONFIRMED
        record.finalize()
        assert record.current_stage == SettlementStage.SETTLED
        assert record.is_terminal()

    def test_settlement_dispute(self):
        record = SettlementRecord(
            settlement_id="settle-dispute-1",
            market_id="mkt-2",
            market_question="Test market",
            resolved_yes=False,
            exit_price=0.0,
            realized_pnl=-10.0,
            entry_price=0.50,
            side="YES",
            size_usd=25.0,
            contracts=50.0,
        )
        record.dispute("Resolution data inconsistent with exchange")
        assert record.current_stage == SettlementStage.DISPUTED
        assert record.is_terminal()

    def test_settlement_engine_registration(self):
        engine = SettlementEngine(check_interval=9999)

        class StubPosition:
            position_id = "pos-test"
            market_id = "mkt-test"
            market_question = "Test Q"
            category = "crypto"
            platform = "polymarket"
            signal_trace_id = "sig-test"
            side = "YES"
            entry_price = 0.60
            size_usd = 25.0
            contracts = 41.67

        record = engine.register_position(StubPosition(), signal_trace_id="sig-test")
        assert record.market_id == "mkt-test"
        assert record.entry_price == 0.60

    def test_settlement_engine_status(self):
        engine = SettlementEngine(check_interval=9999)
        status = engine.status()
        assert status["settled"] == 0
        assert status["disputed"] == 0


class TestRiskAccounting:
    def test_clean_portfolio_no_violations(self):
        accountant = RiskAccountant(ExposureLimits(
            total_max=200, per_market_max=50, per_category_max=80, max_concurrent=10,
            concentration_warning=0.90,  # High enough to not trigger on diverse portfolio
        ))

        class Pos:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        positions = [
            Pos("mkt-1", "crypto", "polymarket", 25.0),
            Pos("mkt-2", "politics", "polymarket", 15.0),
            Pos("mkt-3", "ai", "kalshi", 10.0),
        ]
        exp, violations = accountant.assess(positions, drawdown=0.05)
        assert exp.total_exposure == 50.0
        assert exp.position_count == 3
        assert len(violations) == 0

    def test_total_exposure_violation(self):
        accountant = RiskAccountant(ExposureLimits(total_max=30.0))

        class Pos:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        positions = [Pos("mkt-1", "crypto", "polymarket", 25.0),
                     Pos("mkt-2", "politics", "polymarket", 15.0)]
        exp, violations = accountant.assess(positions)
        assert exp.total_exposure == 40.0
        assert len(violations) > 0
        assert any("Total exposure" in v for v in violations)

    def test_category_exposure_violation(self):
        accountant = RiskAccountant(ExposureLimits(per_category_max=30.0))

        class Pos:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        positions = [Pos("mkt-1", "crypto", "polymarket", 25.0),
                     Pos("mkt-2", "crypto", "polymarket", 20.0)]
        exp, violations = accountant.assess(positions)
        assert exp.by_category["crypto"] == 45.0
        assert len(violations) > 0

    def test_concentration_warning(self):
        accountant = RiskAccountant(ExposureLimits(
            total_max=200, concentration_warning=0.30,
        ))

        class Pos:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        positions = [
            Pos("mkt-big", "crypto", "polymarket", 80.0),
            Pos("mkt-2", "politics", "polymarket", 10.0),
            Pos("mkt-3", "ai", "kalshi", 10.0),
        ]
        exp, violations = accountant.assess(positions)
        assert exp.concentration_risk > 0.50
        assert any("Concentration" in v for v in violations)

    def test_pre_trade_check_approves_safe_trade(self):
        accountant = RiskAccountant(ExposureLimits(
            total_max=200, per_category_max=80, concentration_warning=0.90,
        ))

        class Pos:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        positions = [Pos("mkt-1", "crypto", "polymarket", 25.0)]
        approved, reason = accountant.pre_trade_check(
            "mkt-2", "politics", "polymarket", 15.0, positions,
        )
        assert approved
        assert reason == "ok"

    def test_pre_trade_check_rejects_over_limit(self):
        accountant = RiskAccountant(ExposureLimits(total_max=30.0))

        class Pos:
            def __init__(self, m, c, p, s):
                self.market_id = m
                self.category = c
                self.platform = p
                self.size_usd = s
            def is_active(self):
                return True

        positions = [Pos("mkt-1", "crypto", "polymarket", 25.0)]
        approved, reason = accountant.pre_trade_check(
            "mkt-2", "politics", "polymarket", 15.0, positions,
        )
        assert not approved
        assert "Total exposure" in reason
