"""Heartbeat watchdog: marks observers offline when heartbeats stop, raises a
synthetic observer_down alert, resolves it on the next heartbeat."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vigil.core.config import get_settings
from vigil.db.models import AlertSource, Observer, ObserverStatus, Severity
from vigil.db.session import get_sessionmaker
from vigil.rules.lifecycle import find_active_alert, fire_alert, resolve_alert
from vigil.ws import bus

log = logging.getLogger(__name__)


async def watchdog_tick() -> None:
    s = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=s.heartbeat_offline_seconds)
    async with get_sessionmaker()() as db:
        observers = list((await db.execute(select(Observer))).scalars())
        for obs in observers:
            stale = obs.last_heartbeat is None or obs.last_heartbeat < cutoff
            if stale and obs.status == ObserverStatus.online:
                obs.status = ObserverStatus.offline
                await fire_alert(
                    db,
                    obs.id,
                    AlertSource.watchdog,
                    Severity.critical,
                    f"observer_down: no heartbeat from {obs.name} for "
                    f"> {s.heartbeat_offline_seconds}s",
                )
                await bus.publish(
                    bus.CH_OBSERVERS, "observer_status",
                    {"observer_id": str(obs.id), "name": obs.name, "status": "offline"},
                )
        await db.commit()


async def on_heartbeat(db, observer: Observer) -> None:
    """Called from the heartbeat endpoint: revive + resolve any down-alert."""
    was_offline = observer.status != ObserverStatus.online
    observer.last_heartbeat = datetime.now(UTC)
    observer.status = ObserverStatus.online
    if was_offline:
        active = await find_active_alert(db, observer.id, source=AlertSource.watchdog)
        if active is not None:
            await resolve_alert(db, active, reason="heartbeat_recovered")
        await bus.publish(
            bus.CH_OBSERVERS, "observer_status",
            {"observer_id": str(observer.id), "name": observer.name, "status": "online"},
        )


async def watchdog_loop(stop: asyncio.Event) -> None:
    interval = get_settings().watchdog_interval_seconds
    while not stop.is_set():
        try:
            await watchdog_tick()
        except Exception:
            log.exception("watchdog tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
