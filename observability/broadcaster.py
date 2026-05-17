from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue] = []

# Event type constants for structured event typing
EVENT_SIGNAL_CREATED   = "signal_created"
EVENT_SIGNAL_STAGE     = "signal_stage"
EVENT_SIGNAL_REJECTED  = "signal_rejected"
EVENT_SIGNAL_EXECUTED  = "signal_executed"
EVENT_SIGNAL_SETTLED   = "signal_settled"
EVENT_HEALTH_ALERT     = "health_alert"
EVENT_HEARTBEAT        = "pipeline_heartbeat"

_heartbeat_task: asyncio.Task | None = None


def subscribe(maxsize: int = 50) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def broadcast(data: dict) -> None:
    """Non-blocking fan-out to all current subscribers. Drops if queue full."""
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass
        except Exception as e:
            log.debug(f"[broadcaster] subscriber error: {e}")
            dead.append(q)
    for q in dead:
        unsubscribe(q)


def start_heartbeat(pipeline, interval: float = 10.0):
    """Start periodic pipeline heartbeat broadcast. Safe to call multiple times."""
    global _heartbeat_task
    if _heartbeat_task is not None and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(_heartbeat_loop(pipeline, interval))


async def _heartbeat_loop(pipeline, interval: float):
    while True:
        try:
            uptime = time.monotonic() - (getattr(pipeline, '_start_time', time.monotonic()) or time.monotonic())
            status = pipeline.status() if hasattr(pipeline, 'status') else {}
            broadcast({
                "type": EVENT_HEARTBEAT,
                "uptime": round(uptime, 1),
                "signals_total": status.get("signals_generated", 0),
                "signals_active": 0,
                "rejection_rate_1m": 0.0,
                "queue_depths": {},
                "timestamp": time.time(),
            })
        except Exception:
            pass
        await asyncio.sleep(interval)


def stop_heartbeat():
    global _heartbeat_task
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        _heartbeat_task = None
