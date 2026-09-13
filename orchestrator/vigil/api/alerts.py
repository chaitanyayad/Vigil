import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import require_admin
from vigil.db.models import (
    Alert,
    AlertEvent,
    AlertSource,
    AlertState,
    Severity,
    TriageResult,
)
from vigil.db.session import get_db, get_sessionmaker
from vigil.rules.lifecycle import ack_alert
from vigil.triage.service import TriageSkipped, run_triage

router = APIRouter(prefix="/v1/alerts", tags=["alerts"], dependencies=[Depends(require_admin)])


class AlertOut(BaseModel):
    id: uuid.UUID
    observer_id: uuid.UUID
    rule_id: uuid.UUID | None
    source: AlertSource
    severity: Severity
    state: AlertState
    fired_at: datetime
    acked_at: datetime | None
    resolved_at: datetime | None
    summary: str
    anomaly_score: float | None

    model_config = {"from_attributes": True}


class AlertEventOut(BaseModel):
    id: int
    event_type: str
    payload: dict
    created_at: datetime
    event_hash: str
    prev_hash: str | None
    batch_id: int | None


class TriageOut(BaseModel):
    id: uuid.UUID
    alert_id: uuid.UUID
    model: str
    hypothesis: str
    suggested_runbook: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    state: AlertState | None = None,
    severity: Severity | None = None,
    observer_id: uuid.UUID | None = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    q = select(Alert).order_by(Alert.fired_at.desc()).limit(min(limit, 1000))
    if state is not None:
        q = q.where(Alert.state == state)
    if severity is not None:
        q = q.where(Alert.severity == severity)
    if observer_id is not None:
        q = q.where(Alert.observer_id == observer_id)
    return [AlertOut.model_validate(a) for a in (await db.execute(q)).scalars()]


@router.post("/{alert_id}/ack", response_model=AlertOut)
async def ack(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if alert.state == AlertState.resolved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alert already resolved")
    alert = await ack_alert(db, alert)
    await db.commit()
    return AlertOut.model_validate(alert)


@router.get("/{alert_id}/events", response_model=list[AlertEventOut])
async def alert_events(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if await db.get(Alert, alert_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    rows = (
        await db.execute(
            select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.id)
        )
    ).scalars()
    return [
        AlertEventOut(
            id=e.id,
            event_type=e.event_type.value,
            payload=e.payload,
            created_at=e.created_at,
            event_hash="0x" + e.event_hash.hex(),
            prev_hash="0x" + e.prev_hash.hex() if e.prev_hash else None,
            batch_id=e.batch_id,
        )
        for e in rows
    ]


@router.get("/{alert_id}/triage", response_model=list[TriageOut])
async def get_triage(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(TriageResult)
            .where(TriageResult.alert_id == alert_id)
            .order_by(TriageResult.created_at.desc())
        )
    ).scalars()
    return [TriageOut.model_validate(t) for t in rows]


async def _triage_job(alert_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as db:
        try:
            await run_triage(db, alert_id, force=True)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("manual triage failed for %s", alert_id)


@router.post("/{alert_id}/triage", status_code=status.HTTP_202_ACCEPTED)
async def trigger_triage(
    alert_id: uuid.UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Kick LLM triage in the background; results land in GET .../triage and on the WS bus."""
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    from vigil.triage.provider import get_provider

    if not get_provider().enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Triage disabled: set GEMINI_API_KEY (free key: https://aistudio.google.com/apikey)",
        )
    background.add_task(_triage_job, alert_id)
    return {"status": "triage_started", "alert_id": str(alert_id)}


# Convenience for tests/scripts that need synchronous triage
@router.post("/{alert_id}/triage/sync", response_model=TriageOut, include_in_schema=False)
async def trigger_triage_sync(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        result = await run_triage(db, alert_id, force=True)
    except TriageSkipped as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return TriageOut.model_validate(result)
