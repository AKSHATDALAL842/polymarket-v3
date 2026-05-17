from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline import Pipeline

log = logging.getLogger(__name__)


class Watchdog:
    def __init__(self, name: str, max_idle_seconds: float):
        self.name = name
        self.max_idle_seconds = max_idle_seconds
        self.last_activity: float = time.monotonic()
        self.alert_fired: bool = False
        self.alert_count: int = 0

    def feed(self) -> None:
        self.last_activity = time.monotonic()
        self.alert_fired = False

    def check(self) -> dict | None:
        idle = time.monotonic() - self.last_activity
        if idle > self.max_idle_seconds and not self.alert_fired:
            self.alert_fired = True
            self.alert_count += 1
            return {
                "watchdog": self.name,
                "idle_seconds": round(idle, 1),
                "max_idle_seconds": self.max_idle_seconds,
                "alert_count": self.alert_count,
            }
        return None


class FrozenWSWatchdog(Watchdog):
    def __init__(self):
        super().__init__("ws_frozen", max_idle_seconds=60)

    def check_ws(self, ws_connected: bool, last_msg_time: float | None) -> dict | None:
        if not ws_connected:
            self.feed()
            return None
        if last_msg_time is not None:
            self.last_activity = last_msg_time
        return self.check()


class ZeroSignalWatchdog:
    def __init__(self, max_zero_window: float = 900.0):
        self.name = "zero_signal"
        self.max_zero_window = max_zero_window
        self.last_signal_time: float = time.monotonic()
        self.alert_fired: bool = False
        self.alert_count: int = 0

    def feed(self) -> None:
        self.last_signal_time = time.monotonic()
        self.alert_fired = False

    def check(self) -> dict | None:
        idle = time.monotonic() - self.last_signal_time
        if idle > self.max_zero_window and not self.alert_fired:
            self.alert_fired = True
            self.alert_count += 1
            return {
                "watchdog": self.name,
                "idle_seconds": round(idle, 1),
                "max_zero_window": self.max_zero_window,
                "alert_count": self.alert_count,
            }
        return None


class IngestionOutageWatchdog:
    def __init__(self, max_idle_seconds: float = 600.0):
        self.name = "ingestion_outage"
        self.max_idle_seconds = max_idle_seconds
        self.last_event_time: float = time.monotonic()
        self.alert_fired: bool = False
        self.alert_count: int = 0

    def feed(self) -> None:
        self.last_event_time = time.monotonic()
        self.alert_fired = False

    def check(self) -> dict | None:
        idle = time.monotonic() - self.last_event_time
        if idle > self.max_idle_seconds and not self.alert_fired:
            self.alert_fired = True
            self.alert_count += 1
            return {
                "watchdog": self.name,
                "idle_seconds": round(idle, 1),
                "max_idle_seconds": self.max_idle_seconds,
                "alert_count": self.alert_count,
            }
        return None


class HealthMonitor:
    def __init__(self, pipeline, check_interval: float = 30.0):
        self._pipeline = pipeline
        self._check_interval = check_interval
        self._watchdogs: list[Watchdog] = [
            Watchdog("news_queue", max_idle_seconds=120),
            Watchdog("cold_path", max_idle_seconds=300),
            Watchdog("settlement", max_idle_seconds=600),
        ]
        self._frozen_ws = FrozenWSWatchdog()
        self._zero_signal = ZeroSignalWatchdog(max_zero_window=900)
        self._ingestion_outage = IngestionOutageWatchdog(max_idle_seconds=600)
        self._alerts: list[dict] = []

    def feed(self, watchdog_name: str) -> None:
        for wd in self._watchdogs:
            if wd.name == watchdog_name:
                wd.feed()
                return

    def feed_signal(self) -> None:
        self._zero_signal.feed()

    def feed_ingestion(self) -> None:
        self._ingestion_outage.feed()

    async def run(self) -> None:
        log.info("[health_monitor] Starting (interval=%ss)", self._check_interval)
        from observability import broadcaster
        while True:
            try:
                alerts = []
                for wd in self._watchdogs:
                    alert = wd.check()
                    if alert:
                        alerts.append(alert)

                ws_alert = self._frozen_ws.check_ws(
                    ws_connected=getattr(self._pipeline.watcher, '_ws_connected', False),
                    last_msg_time=None,
                )
                if ws_alert:
                    alerts.append(ws_alert)

                zs_alert = self._zero_signal.check()
                if zs_alert:
                    alerts.append(zs_alert)

                io_alert = self._ingestion_outage.check()
                if io_alert:
                    alerts.append(io_alert)

                for alert in alerts:
                    alert["severity"] = "WARNING"
                    alert["timestamp"] = time.time()
                    self._alerts.append(alert)
                    if len(self._alerts) > 100:
                        self._alerts = self._alerts[-100:]

                    log.warning(
                        "[health_monitor] ALERT: %s idle=%.0fs (limit=%.0fs)",
                        alert["watchdog"], alert.get("idle_seconds", 0),
                        alert.get("max_idle_seconds", alert.get("max_zero_window", 0)),
                    )
                    try:
                        broadcaster.broadcast({
                            "type": "health_alert",
                            "watchdog": alert["watchdog"],
                            "severity": alert["severity"],
                            "detail": alert,
                            "timestamp": alert["timestamp"],
                        })
                    except Exception:
                        pass

            except Exception as e:
                log.warning("[health_monitor] Check cycle error: %s", e)

            await asyncio.sleep(self._check_interval)

    def status(self) -> dict:
        return {
            "watchdogs": [
                {
                    "name": wd.name,
                    "last_activity_seconds_ago": round(time.monotonic() - wd.last_activity, 1),
                    "alert_fired": wd.alert_fired,
                    "alert_count": wd.alert_count,
                }
                for wd in self._watchdogs
            ],
            "frozen_ws": {
                "last_activity_seconds_ago": round(time.monotonic() - self._frozen_ws.last_activity, 1),
                "alert_fired": self._frozen_ws.alert_fired,
            },
            "zero_signal": {
                "last_signal_seconds_ago": round(time.monotonic() - self._zero_signal.last_signal_time, 1),
                "alert_fired": self._zero_signal.alert_fired,
            },
            "ingestion_outage": {
                "last_event_seconds_ago": round(time.monotonic() - self._ingestion_outage.last_event_time, 1),
                "alert_fired": self._ingestion_outage.alert_fired,
            },
            "recent_alerts": self._alerts[-10:],
        }
