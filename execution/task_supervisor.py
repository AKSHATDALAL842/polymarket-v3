"""
Task Supervisor — centralized background task lifecycle management.

Tracks: task state, restart count, exception count, stall detection,
heartbeat freshness, recovery duration.

Background tasks must NEVER silently die.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class TaskState(Enum):
    STARTING = "starting"
    RUNNING = "running"
    STALLED = "stalled"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class SupervisedTask:
    name: str
    coroutine_fn: callable
    state: TaskState = TaskState.STARTING
    task: asyncio.Task | None = None
    restart_count: int = 0
    max_restarts: int = 5
    exception_count: int = 0
    last_heartbeat: float = field(default_factory=time.monotonic)
    last_started: float = field(default_factory=time.monotonic)
    last_error: str | None = None
    stall_threshold_seconds: float = 300.0
    cooldown_seconds: float = 5.0


class TaskSupervisor:
    """Centralized supervision for all background async tasks."""

    def __init__(self):
        self._tasks: dict[str, SupervisedTask] = {}
        self._running = True

    def register(self, name: str, coroutine_fn, stall_threshold: float = 300.0,
                 max_restarts: int = 5) -> SupervisedTask:
        if name in self._tasks:
            log.warning("[supervisor] Task %s already registered — replacing", name)

        st = SupervisedTask(
            name=name,
            coroutine_fn=coroutine_fn,
            stall_threshold_seconds=stall_threshold,
            max_restarts=max_restarts,
        )
        self._tasks[name] = st
        return st

    async def start_all(self, *args, **kwargs) -> None:
        """Start all registered tasks. Returns when all are running."""
        self._running = True
        for name, st in self._tasks.items():
            await self._launch_task(st, *args, **kwargs)
        log.info("[supervisor] All %d tasks started", len(self._tasks))

    async def _launch_task(self, st: SupervisedTask, *args, **kwargs) -> None:
        """Launch a single supervised task with restart-on-failure."""
        async def _wrapper():
            st.state = TaskState.RUNNING
            st.last_started = time.monotonic()
            st.last_heartbeat = time.monotonic()
            try:
                await st.coroutine_fn(*args, **kwargs)
            except asyncio.CancelledError:
                st.state = TaskState.STOPPED
                log.info("[supervisor] Task %s cancelled cleanly", st.name)
            except Exception as e:
                st.exception_count += 1
                st.last_error = str(e)
                log.error("[supervisor] Task %s crashed: %s (restart %d/%d)",
                          st.name, e, st.restart_count, st.max_restarts)

                if st.restart_count < st.max_restarts:
                    st.state = TaskState.RECOVERING
                    st.restart_count += 1
                    await asyncio.sleep(st.cooldown_seconds)
                    log.info("[supervisor] Restarting task %s", st.name)
                    await self._launch_task(st, *args, **kwargs)
                else:
                    st.state = TaskState.FAILED
                    log.error("[supervisor] Task %s FAILED permanently after %d restarts",
                              st.name, st.restart_count)
                    from observability import broadcaster
                    try:
                        broadcaster.broadcast({
                            "type": "health_alert",
                            "watchdog": f"task_{st.name}_failed",
                            "severity": "CRITICAL",
                            "detail": f"Task {st.name} failed after {st.restart_count} restarts: {e}",
                            "timestamp": time.time(),
                        })
                    except Exception:
                        pass

        st.task = asyncio.create_task(_wrapper(), name=f"supervised-{st.name}")

    def heartbeat(self, name: str) -> None:
        """Call from within a task to signal it's alive."""
        st = self._tasks.get(name)
        if st:
            st.last_heartbeat = time.monotonic()
            if st.state == TaskState.STALLED:
                st.state = TaskState.RUNNING

    async def stop_all(self) -> None:
        """Gracefully cancel all supervised tasks."""
        self._running = False
        for name, st in self._tasks.items():
            if st.task and not st.task.done():
                st.task.cancel()
                st.state = TaskState.STOPPING
        # Wait for all to finish
        tasks = [st.task for st in self._tasks.values() if st.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log.info("[supervisor] All tasks stopped")

    def check_stalls(self) -> list[str]:
        """Return names of stalled tasks (no heartbeat within threshold)."""
        stalled = []
        now = time.monotonic()
        for name, st in self._tasks.items():
            if st.state == TaskState.RUNNING:
                idle = now - st.last_heartbeat
                if idle > st.stall_threshold_seconds:
                    st.state = TaskState.STALLED
                    stalled.append(name)
                    log.warning("[supervisor] Task %s STALLED: no heartbeat for %.0fs",
                                name, idle)
        return stalled

    async def monitor_loop(self, interval: float = 30.0) -> None:
        """Background coroutine: periodic stall checking."""
        log.info("[supervisor] Monitor started (interval=%ss)", interval)
        while self._running:
            try:
                stalled = self.check_stalls()
                if stalled:
                    log.warning("[supervisor] Stalled tasks: %s", stalled)
            except Exception as e:
                log.error("[supervisor] Monitor error: %s", e)
            await asyncio.sleep(interval)

    def status(self) -> dict:
        return {
            name: {
                "state": st.state.value,
                "restarts": st.restart_count,
                "exceptions": st.exception_count,
                "seconds_since_heartbeat": round(time.monotonic() - st.last_heartbeat, 1),
                "last_error": st.last_error,
            }
            for name, st in self._tasks.items()
        }


_supervisor = TaskSupervisor()


def get_task_supervisor() -> TaskSupervisor:
    return _supervisor
