import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import require_admin
from vigil.db.models import MLModel
from vigil.db.session import get_db
from vigil.ml.service import train_and_store

router = APIRouter(prefix="/v1/ml", tags=["ml"], dependencies=[Depends(require_admin)])


class MLModelOut(BaseModel):
    id: uuid.UUID
    observer_id: uuid.UUID | None
    algo: str
    trained_at: datetime
    window_hours: int
    artifact_path: str
    metrics: dict | None

    model_config = {"from_attributes": True}


@router.get("/models", response_model=list[MLModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(MLModel).order_by(MLModel.trained_at.desc()))).scalars()
    return [MLModelOut.model_validate(m) for m in rows]


@router.post("/train", status_code=status.HTTP_202_ACCEPTED)
async def train(
    background: BackgroundTasks,
    observer_id: uuid.UUID | None = None,
) -> dict:
    """Async training job for one observer (or the global model)."""
    background.add_task(train_and_store, observer_id)
    return {"status": "training_started", "observer_id": str(observer_id) if observer_id else None}


@router.get("/eval")
async def latest_eval(db: AsyncSession = Depends(get_db)) -> dict:
    """Latest stored eval report (rules-vs-ML comparison from the synthetic set)."""
    row = (
        await db.execute(select(MLModel).order_by(MLModel.trained_at.desc()).limit(1))
    ).scalar_one_or_none()
    if row is None or not row.metrics:
        return {"available": False, "hint": "POST /v1/ml/train first (or run python -m vigil.ml.eval)"}
    return {"available": True, "model_id": str(row.id), "trained_at": row.trained_at.isoformat(),
            "report": row.metrics}
