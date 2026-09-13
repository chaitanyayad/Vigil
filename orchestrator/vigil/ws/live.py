"""WS /v1/ws/live — fans Redis pub/sub out to dashboard clients.

Streams: metric samples (metrics:*), alert state changes, observer status
changes, and ledger anchor events.
"""

import asyncio
import contextlib
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from vigil.core.auth import require_admin_ws
from vigil.core.config import get_settings
from vigil.ws import bus

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/v1/ws/live")
async def live(websocket: WebSocket) -> None:
    await require_admin_ws(websocket)
    await websocket.accept()

    # Dedicated connection: pub/sub takes over the protocol
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.psubscribe("metrics:*")
    await pubsub.subscribe(bus.CH_ALERTS, bus.CH_LEDGER, bus.CH_OBSERVERS)

    async def forward() -> None:
        async for message in pubsub.listen():
            if message["type"] not in ("message", "pmessage"):
                continue
            try:
                payload = json.loads(message["data"])
                payload["channel"] = message["channel"]
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                return
            except Exception:
                log.exception("ws forward failed")

    task = asyncio.create_task(forward())
    try:
        while True:
            # Drain client pings / detect disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await pubsub.aclose()
        await r.aclose()
