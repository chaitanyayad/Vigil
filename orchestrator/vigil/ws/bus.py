"""Redis pub/sub event bus feeding the live WebSocket dashboard."""

import json
from typing import Any

import redis.asyncio as aioredis

from vigil.core.config import get_settings

CH_ALERTS = "events:alerts"
CH_LEDGER = "events:ledger"
CH_OBSERVERS = "events:observers"


def metrics_channel(observer_id) -> str:
    return f"metrics:{observer_id}"


_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def publish(channel: str, kind: str, data: dict[str, Any]) -> None:
    try:
        await get_redis().publish(channel, json.dumps({"kind": kind, "data": data}, default=str))
    except Exception:
        # The bus is best-effort: a Redis hiccup must never fail ingest.
        pass
