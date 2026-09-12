from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import require_agent
from vigil.db.models import Observer
from vigil.db.session import get_db
from vigil.ingest.service import MAX_BATCH, MetricSample, ingest_batch
from vigil.workers.watchdog import on_heartbeat

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


class MetricsIn(BaseModel):
    samples: list[MetricSample] = Field(min_length=1, max_length=MAX_BATCH)


@router.post("/metrics")
async def post_metrics(
    body: MetricsIn,
    observer: Observer = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if len(body.samples) > MAX_BATCH:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Max {MAX_BATCH} samples")
    inserted = await ingest_batch(db, observer, body.samples)
    await db.commit()
    return {"accepted": inserted}


@router.post("/heartbeat")
async def post_heartbeat(
    observer: Observer = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await on_heartbeat(db, observer)
    await db.commit()
    return {"status": "ok", "observer": observer.name}
