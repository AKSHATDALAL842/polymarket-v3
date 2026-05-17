"""
Tests for operational durability: Market Sync, Task Supervisor.
"""
import asyncio
import time
import pytest
from execution.market_sync import (
    MarketStateSynchronizer, MarketSyncState, SyncHealth,
    get_market_synchronizer,
)
from execution.task_supervisor import (
    TaskSupervisor, SupervisedTask, TaskState,
    get_task_supervisor,
)


class TestMarketSync:
    def test_initial_state_disconnected(self):
        sync = MarketStateSynchronizer()
        assert sync.check_health() == SyncHealth.DISCONNECTED

    def test_register_and_update_market(self):
        sync = MarketStateSynchronizer(stale_ws_threshold=99999)
        sync.register_market("mkt-1")
        sync.record_ws_update("mkt-1", 0.65, sequence=1)
        assert sync.check_health() == SyncHealth.HEALTHY
        state = sync._markets["mkt-1"]
        assert state.price == 0.65
        assert state.ws_message_count == 1

    def test_stale_detection(self):
        sync = MarketStateSynchronizer(stale_ws_threshold=0.0)
        sync.register_market("mkt-1")
        sync.record_ws_update("mkt-1", 0.65)
        # stale_ws_threshold=0 means immediately stale
        health = sync.check_health()
        assert health in (SyncHealth.STALE, SyncHealth.DEGRADED)

    def test_sequence_gap_detection(self):
        sync = MarketStateSynchronizer()
        sync.register_market("mkt-1")
        sync.record_ws_update("mkt-1", 0.60, sequence=1)
        sync.record_ws_update("mkt-1", 0.65, sequence=5)  # gap: 2,3,4 missing
        state = sync._markets["mkt-1"]
        assert state.sequence_gaps == 1
        assert sync._sequence_gaps_total == 1

    def test_no_sequence_gap_on_first_message(self):
        sync = MarketStateSynchronizer()
        sync.register_market("mkt-1")
        sync.record_ws_update("mkt-1", 0.60, sequence=100)
        state = sync._markets["mkt-1"]
        assert state.sequence_gaps == 0

    def test_snapshot_recording(self):
        sync = MarketStateSynchronizer()
        sync.record_snapshot("mkt-1", 0.45, spread=0.03, liquidity=200.0)
        state = sync._markets["mkt-1"]
        assert state.price == 0.45
        assert state.spread == 0.03
        assert state.liquidity == 200.0
        assert state.snapshot_count == 1

    def test_closed_market_detection(self):
        sync = MarketStateSynchronizer()
        sync.record_snapshot("mkt-1", 0.99, spread=0.01, liquidity=0.0, is_closed=True)
        state = sync._markets["mkt-1"]
        assert state.is_closed

    def test_get_stale_markets(self):
        sync = MarketStateSynchronizer(stale_ws_threshold=0.0)
        sync.register_market("mkt-1")
        sync.record_ws_update("mkt-1", 0.65)
        sync.check_health()
        stale = sync.get_stale_markets()
        assert "mkt-1" in stale

    def test_status_report(self):
        sync = MarketStateSynchronizer()
        status = sync.status()
        assert status["health"] == "disconnected"
        assert "markets_tracked" in status
        assert "stale_markets" in status
        assert "sequence_gaps" in status


class TestTaskSupervisor:
    def test_register_and_status(self):
        async def _test():
            sup = TaskSupervisor()
            async def dummy_task():
                await asyncio.sleep(0.01)
            sup.register("test-task", dummy_task)
            sup._tasks["test-task"].state = TaskState.RUNNING
            status = sup.status()
            assert status["test-task"]["state"] == "running"
        asyncio.run(_test())

    def test_heartbeat_updates(self):
        async def _test():
            sup = TaskSupervisor()
            async def dummy_task():
                await asyncio.sleep(0.01)
            sup.register("beat-test", dummy_task)
            sup._tasks["beat-test"].state = TaskState.RUNNING
            before = sup._tasks["beat-test"].last_heartbeat
            await asyncio.sleep(0.01)
            sup.heartbeat("beat-test")
            after = sup._tasks["beat-test"].last_heartbeat
            assert after > before
        asyncio.run(_test())

    def test_stall_detection(self):
        sup = TaskSupervisor()
        async def _noop():
            pass
        sup.register("stall-test", _noop, stall_threshold=0.0)
        sup._tasks["stall-test"].state = TaskState.RUNNING
        stalled = sup.check_stalls()
        assert "stall-test" in stalled

    def test_task_crash_and_restart(self):
        async def _test():
            sup = TaskSupervisor()
            crash_count = [0]
            async def crashing_task():
                crash_count[0] += 1
                if crash_count[0] <= 2:
                    raise RuntimeError("simulated crash")
                await asyncio.sleep(999)
            sup.register("crash-test", crashing_task, max_restarts=3)
            sup._tasks["crash-test"].cooldown_seconds = 0.01
            await sup._launch_task(sup._tasks["crash-test"])
            await asyncio.sleep(0.1)
            st = sup._tasks["crash-test"]
            assert st.exception_count >= 2
            assert st.restart_count >= 2
        asyncio.run(_test())

    def test_max_restarts_fails_permanently(self):
        async def _test():
            sup = TaskSupervisor()
            async def always_crash():
                raise RuntimeError("always crash")
            sup.register("fail-task", always_crash, max_restarts=1)
            sup._tasks["fail-task"].cooldown_seconds = 0.01
            await sup._launch_task(sup._tasks["fail-task"])
            await asyncio.sleep(0.1)
            st = sup._tasks["fail-task"]
            assert st.state == TaskState.FAILED
        asyncio.run(_test())

    def test_supervisor_initial_state(self):
        sup = TaskSupervisor()
        assert sup._running is True
        status = sup.status()
        assert status == {}
