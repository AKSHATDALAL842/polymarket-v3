from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue] = []


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
