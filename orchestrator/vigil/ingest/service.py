"""Metric ingestion: validate → bulk insert into the hypertable → publish to
Redis for the live dashboard → run the rules engine."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.db.models import Metric, Observer
from vigil.rules.engine import evaluate_samples
from vigil.ws import bus

MAX_BATCH = 100


class MetricSample(BaseModel):
    ts: datetime
    cpu_pct: float | None = Field(None, ge=0, le=100)
    mem_pct: float | None = Field(None, ge=0, le=100)
    disk_pct: float | None = Field(None, ge=0, le=100)
    net_rx_bps: int | None = Field(None, ge=0)
    net_tx_bps: int | None = Field(None, ge=0)
    load1: float | None = Field(None, ge=0)
    extra: dict[str, Any] | None = None


async def ingest_batch(db: AsyncSession, observer: Observer, samples: list[MetricSample]) -> int:
    rows: list[dict[str, Any]] = []
    for s in samples:
        ts = s.ts if s.ts.tzinfo else s.ts.replace(tzinfo=UTC)
        rows.append(
            dict(
                ts=ts,
                observer_id=observer.id,
                cpu_pct=s.cpu_pct,
                mem_pct=s.mem_pct,
                disk_pct=s.disk_pct,
                net_rx_bps=s.net_rx_bps,
                net_tx_bps=s.net_tx_bps,
                load1=s.load1,
                extra=s.extra,
            )
        )
    if not rows:
        return 0
    # Idempotent on (ts, observer_id): agents may re-send buffered samples after
    # a reconnect — duplicates are dropped, not errors.
    await db.execute(pg_insert(Metric).on_conflict_do_nothing(), rows)

    latest = max(rows, key=lambda r: r["ts"])
    await bus.publish(
        bus.metrics_channel(observer.id),
        "metric",
        {k: v for k, v in latest.items() if k != "extra"} | {"observer": observer.name},
    )
    await evaluate_samples(db, observer, rows)
    return len(rows)
