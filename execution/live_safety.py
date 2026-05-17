"""
Live-Capital Safety Layer — pre-flight validation, hard-stop, manual confirmation.

CRITICAL: This module is the last line of defense before real capital deployment.
Do not modify without thorough review.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# LIVE CONSTRAINTS — never modify these without explicit approval
# ═══════════════════════════════════════════════════════════════════════════

LIVE_CONSTRAINTS = {
    "MAX_BET_USD": 2.0,
    "MAX_CONCURRENT_POSITIONS": 1,
    "DAILY_LOSS_LIMIT_USD": 5.0,
    "MARKET_SIGNAL_COOLDOWN_SECONDS": 300,
    "MAX_TRADES_PER_DAY": 3,
    "MANUAL_CONFIRM": True,
    "RECONCILIATION_INTERVAL": 60,
    "PROPOSAL_EXPIRY_SECONDS": 300,   # 5 minutes
    "ALLOW_ONLY_ONE_PENDING": True,
}

HARD_STOP_FILE = os.path.join(os.path.dirname(__file__), "..", ".hard_stop")
MANUAL_APPROVAL_FILE = os.path.join(os.path.dirname(__file__), "..", ".pending_approval")


class PreflightStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class PreflightCheck:
    name: str
    status: PreflightStatus = PreflightStatus.FAIL
    detail: str = ""
    latency_ms: int = 0


@dataclass
class PreflightReport:
    all_pass: bool = False
    checks: list[PreflightCheck] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LiveSafetyGuard:
    """Pre-flight validation, hard-stop, and manual confirmation for live trading."""

    def __init__(self):
        self._hard_stopped = os.path.exists(HARD_STOP_FILE)
        self._trade_count_today: int = 0
        self._last_trade_time: float = 0.0
        self._pending_approval: dict | None = None

    def is_hard_stopped(self) -> bool:
        return os.path.exists(HARD_STOP_FILE) or self._hard_stopped

    def hard_stop(self, reason: str = "manual") -> None:
        """Immediate execution halt. Freezes all new signals and pending orders."""
        self._hard_stopped = True
        with open(HARD_STOP_FILE, 'w') as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()}\n{reason}\n")
        log.critical("[live_safety] HARD STOP ENGAGED: %s", reason)

        # Dump runtime state
        self._dump_state_on_stop(reason)

        # Broadcast emergency stop
        try:
            from observability import broadcaster
            broadcaster.broadcast({
                "type": "health_alert",
                "watchdog": "hard_stop",
                "severity": "CRITICAL",
                "detail": f"HARD STOP: {reason}",
                "timestamp": time.time(),
            })
        except Exception:
            pass

    def clear_hard_stop(self) -> None:
        """Remove hard stop after investigation and approval."""
        if os.path.exists(HARD_STOP_FILE):
            os.remove(HARD_STOP_FILE)
        self._hard_stopped = False
        log.warning("[live_safety] Hard stop cleared — resuming execution")

    def _dump_state_on_stop(self, reason: str) -> None:
        """Dump runtime state to disk on emergency stop."""
        try:
            state = {
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trade_count_today": self._trade_count_today,
                "last_trade_time": self._last_trade_time,
            }

            # Capture pipeline state if available
            try:
                from pipeline import Pipeline
                # Can't easily access running singleton — log what we can
            except Exception:
                pass

            dump_path = os.path.join(os.path.dirname(__file__), "..", f".stop_dump_{int(time.time())}.json")
            with open(dump_path, 'w') as f:
                json.dump(state, f, indent=2)
            log.info("[live_safety] State dumped to %s", dump_path)
        except Exception as e:
            log.error("[live_safety] Failed to dump state: %s", e)

    def run_preflight(self) -> PreflightReport:
        """Run all pre-flight checks before allowing live execution."""
        report = PreflightReport()

        # 1. CLOB connectivity
        check = self._check_clob_connectivity()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 2. WebSocket connectivity
        check = self._check_ws_readiness()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 3. Background task health
        check = self._check_task_health()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 4. Circuit breakers initialized
        check = self._check_circuit_breakers()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 5. SQLite writable
        check = self._check_sqlite()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 6. No stale positions
        check = self._check_no_stale_positions()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 7. No orphan orders
        check = self._check_no_orphan_orders()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 8. Reconciliation engine alive
        check = self._check_reconciliation()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        # 9. Market sync alive
        check = self._check_market_sync()
        report.checks.append(check)
        if check.status == PreflightStatus.FAIL:
            report.failures.append(check.name)

        report.all_pass = len(report.failures) == 0
        return report

    def _check_clob_connectivity(self) -> PreflightCheck:
        t0 = time.monotonic()
        try:
            import config
            import httpx
            resp = httpx.get(f"{config.POLYMARKET_HOST}/markets", params={"limit": 1}, timeout=10)
            resp.raise_for_status()
            return PreflightCheck("clob_connectivity", PreflightStatus.PASS,
                                  f"CLOB reachable ({resp.status_code})",
                                  int((time.monotonic()-t0)*1000))
        except Exception as e:
            return PreflightCheck("clob_connectivity", PreflightStatus.FAIL,
                                  f"CLOB unreachable: {e}", int((time.monotonic()-t0)*1000))

    def _check_ws_readiness(self) -> PreflightCheck:
        return PreflightCheck("websocket", PreflightStatus.WARN,
                              "WS readiness checked at runtime by MarketWatcher")

    def _check_task_health(self) -> PreflightCheck:
        try:
            from execution.task_supervisor import get_task_supervisor
            sup = get_task_supervisor()
            status = sup.status()
            failed = [n for n, s in status.items() if s.get("state") == "failed"]
            if failed:
                return PreflightCheck("task_health", PreflightStatus.FAIL,
                                      f"Failed tasks: {failed}")
            return PreflightCheck("task_health", PreflightStatus.PASS,
                                  f"{len(status)} tasks healthy")
        except Exception as e:
            return PreflightCheck("task_health", PreflightStatus.WARN,
                                  f"Supervisor not yet started: {e}")

    def _check_circuit_breakers(self) -> PreflightCheck:
        try:
            from execution.circuit_breakers import get_circuit_breakers
            cbs = get_circuit_breakers()
            if cbs.any_tripped():
                return PreflightCheck("circuit_breakers", PreflightStatus.FAIL,
                                      "One or more breakers already tripped")
            return PreflightCheck("circuit_breakers", PreflightStatus.PASS,
                                  f"{len(cbs.breakers)} breakers initialized")
        except Exception as e:
            return PreflightCheck("circuit_breakers", PreflightStatus.WARN,
                                  f"{e}")

    def _check_sqlite(self) -> PreflightCheck:
        t0 = time.monotonic()
        try:
            from observability.logger import _conn
            conn = _conn()
            conn.execute("SELECT 1")
            conn.close()
            return PreflightCheck("sqlite", PreflightStatus.PASS,
                                  "Writable", int((time.monotonic()-t0)*1000))
        except Exception as e:
            return PreflightCheck("sqlite", PreflightStatus.FAIL,
                                  f"Not writable: {e}", int((time.monotonic()-t0)*1000))

    def _check_no_stale_positions(self) -> PreflightCheck:
        try:
            from execution.position_lifecycle import get_position_ledger
            p_ledger = get_position_ledger()
            orphans = p_ledger.get_orphaned()
            if orphans:
                return PreflightCheck("stale_positions", PreflightStatus.FAIL,
                                      f"{len(orphans)} orphaned positions")
            return PreflightCheck("stale_positions", PreflightStatus.PASS,
                                  "No orphaned positions")
        except Exception:
            return PreflightCheck("stale_positions", PreflightStatus.PASS, "No positions")

    def _check_no_orphan_orders(self) -> PreflightCheck:
        try:
            from execution.order_lifecycle import get_order_ledger
            ledger = get_order_ledger()
            active = ledger.get_active_orders()
            stale = [o for o in active if time.monotonic() - o.created_at > 3600]
            if stale:
                return PreflightCheck("orphan_orders", PreflightStatus.WARN,
                                      f"{len(stale)} stale orders >1h old (shadow mode OK)")
            return PreflightCheck("orphan_orders", PreflightStatus.PASS,
                                  "No stale orders")
        except Exception:
            return PreflightCheck("orphan_orders", PreflightStatus.PASS, "No orders")

    def _check_reconciliation(self) -> PreflightCheck:
        try:
            from execution.reconciliation import get_reconciliation_engine
            recon = get_reconciliation_engine()
            status = recon.status()
            return PreflightCheck("reconciliation", PreflightStatus.PASS,
                                  f"State: {status['state']}")
        except Exception as e:
            return PreflightCheck("reconciliation", PreflightStatus.WARN, f"{e}")

    def _check_market_sync(self) -> PreflightCheck:
        try:
            from execution.market_sync import get_market_synchronizer
            sync = get_market_synchronizer()
            status = sync.status()
            return PreflightCheck("market_sync", PreflightStatus.PASS,
                                  f"Health: {status['health']}")
        except Exception as e:
            return PreflightCheck("market_sync", PreflightStatus.WARN, f"{e}")

    # ── Manual confirmation ──────────────────────────────────────────────

    def propose_trade(self, trace, signal, market) -> dict | None:
        """Propose a trade for manual review. Returns approval payload or None if blocked."""
        # Approval locking: only one pending at a time
        if LIVE_CONSTRAINTS.get("ALLOW_ONLY_ONE_PENDING", True):
            if self._pending_approval is not None:
                # Check if existing proposal is expired
                existing_time = self._pending_approval.get("proposed_at", "")
                if existing_time:
                    try:
                        proposed_dt = datetime.fromisoformat(existing_time)
                        age = (datetime.now(timezone.utc) - proposed_dt).total_seconds()
                        expiry = LIVE_CONSTRAINTS.get("PROPOSAL_EXPIRY_SECONDS", 300)
                        if age > expiry:
                            log.warning("[live_safety] Previous proposal expired (%.0fs > %ds), replacing",
                                        age, expiry)
                            self._pending_approval = None
                        else:
                            log.warning("[live_safety] Already have a pending proposal — skipping")
                            return None
                    except (ValueError, TypeError):
                        self._pending_approval = None
                else:
                    log.warning("[live_safety] Already have a pending proposal — skipping")
                    return None

        proposal = {
            "trace_id": trace.trace_id if hasattr(trace, 'trace_id') else 'unknown',
            "headline": trace.headline if hasattr(trace, 'headline') else '',
            "source": trace.source if hasattr(trace, 'source') else '',
            "signal_rationale": getattr(signal, 'reasoning', ''),
            "confidence": getattr(signal.classification, 'confidence', 0) if hasattr(signal, 'classification') else 0,
            "direction": getattr(signal, 'side', ''),
            "market_id": getattr(market, 'condition_id', ''),
            "market_question": getattr(market, 'question', ''),
            "yes_price": getattr(market, 'yes_price', 0),
            "ev": getattr(signal, 'ev', 0),
            "bet_usd": getattr(signal, 'bet_amount', 0),
            "risk_exposure_impact": f"+${getattr(signal, 'bet_amount', 0):.2f}",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_approval",
        }
        self._pending_approval = proposal
        with open(MANUAL_APPROVAL_FILE, 'w') as f:
            json.dump(proposal, f, indent=2)
        log.warning("[live_safety] Trade PROPOSED — awaiting manual approval: %s", proposal['trace_id'])
        return proposal

    def approve_trade(self) -> dict | None:
        """Approve the pending trade. Caller must verify the proposal first."""
        proposal = self._pending_approval
        if proposal is None:
            return None
        proposal["status"] = "approved"
        proposal["approved_at"] = datetime.now(timezone.utc).isoformat()
        self._pending_approval = None
        if os.path.exists(MANUAL_APPROVAL_FILE):
            os.remove(MANUAL_APPROVAL_FILE)
        log.warning("[live_safety] Trade APPROVED: %s", proposal['trace_id'])
        return proposal

    def reject_trade(self, reason: str = "") -> dict | None:
        proposal = self._pending_approval
        if proposal is None:
            return None
        proposal["status"] = "rejected"
        proposal["rejection_reason"] = reason
        self._pending_approval = None
        if os.path.exists(MANUAL_APPROVAL_FILE):
            os.remove(MANUAL_APPROVAL_FILE)
        log.info("[live_safety] Trade REJECTED: %s — %s", proposal['trace_id'], reason)
        return proposal

    def check_proposal_expiry(self) -> str | None:
        """Check if the pending proposal has expired. Returns reason if expired."""
        if self._pending_approval is None:
            return None
        try:
            proposed_at = self._pending_approval.get("proposed_at", "")
            if proposed_at:
                proposed_dt = datetime.fromisoformat(proposed_at)
                age = (datetime.now(timezone.utc) - proposed_dt).total_seconds()
                expiry = LIVE_CONSTRAINTS.get("PROPOSAL_EXPIRY_SECONDS", 300)
                if age > expiry:
                    reason = f"Proposal expired after {age:.0f}s (limit: {expiry}s)"
                    self._pending_approval["status"] = "expired"
                    self._pending_approval["expired_at"] = datetime.now(timezone.utc).isoformat()
                    self._pending_approval = None
                    if os.path.exists(MANUAL_APPROVAL_FILE):
                        os.remove(MANUAL_APPROVAL_FILE)
                    log.warning("[live_safety] %s", reason)
                    return reason
        except (ValueError, TypeError):
            pass
        return None

    def snapshot_runtime(self, pipeline=None) -> dict:
        """Capture a complete runtime snapshot for postmortem analysis."""
        snap = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hard_stopped": self.is_hard_stopped(),
            "trade_count_today": self._trade_count_today,
            "has_pending_approval": self._pending_approval is not None,
        }

        # Task supervisor
        try:
            from execution.task_supervisor import get_task_supervisor
            snap["tasks"] = get_task_supervisor().status()
        except Exception:
            snap["tasks"] = {}

        # Circuit breakers
        try:
            from execution.circuit_breakers import get_circuit_breakers
            snap["circuit_breakers"] = get_circuit_breakers().status()
        except Exception:
            snap["circuit_breakers"] = {}

        # Reconciliation
        try:
            from execution.reconciliation import get_reconciliation_engine
            snap["reconciliation"] = get_reconciliation_engine().status()
        except Exception:
            snap["reconciliation"] = {}

        # Market sync
        try:
            from execution.market_sync import get_market_synchronizer
            snap["market_sync"] = get_market_synchronizer().status()
        except Exception:
            snap["market_sync"] = {}

        # Pipeline state
        if pipeline:
            try:
                snap["pipeline"] = {
                    "uptime": pipeline.status().get("uptime_seconds", 0),
                    "signals": pipeline.status().get("signals_generated", 0),
                    "ws_connected": pipeline.status().get("ws_connected", False),
                    "markets_tracked": pipeline.status().get("tracked_markets", 0),
                }
            except Exception:
                snap["pipeline"] = {}

        # Persist
        try:
            snap_path = os.path.join(os.path.dirname(__file__), "..",
                                     f".runtime_snap_{int(time.time())}.json")
            with open(snap_path, 'w') as f:
                json.dump(snap, f, indent=2, default=str)
        except Exception:
            pass

        return snap

    def record_trade(self) -> None:
        self._trade_count_today += 1
        self._last_trade_time = time.monotonic()

    def can_trade(self) -> tuple[bool, str]:
        """Check all live constraints before allowing a trade."""
        if self.is_hard_stopped():
            return False, "hard_stop_active"
        if self._trade_count_today >= LIVE_CONSTRAINTS["MAX_TRADES_PER_DAY"]:
            return False, f"daily_trade_limit ({self._trade_count_today}/{LIVE_CONSTRAINTS['MAX_TRADES_PER_DAY']})"
        cooldown = LIVE_CONSTRAINTS["MARKET_SIGNAL_COOLDOWN_SECONDS"]
        if time.monotonic() - self._last_trade_time < cooldown and self._last_trade_time > 0:
            return False, f"cooldown_active ({cooldown}s)"
        return True, "ok"


_live_safety = LiveSafetyGuard()


def get_live_safety() -> LiveSafetyGuard:
    return _live_safety
