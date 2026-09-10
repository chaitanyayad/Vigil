import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import generate_api_key, require_admin
from vigil.db.models import Observer, ObserverStatus
from vigil.db.session import get_db

router = APIRouter(prefix="/v1/observers", tags=["observers"], dependencies=[Depends(require_admin)])


class ObserverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    labels: dict[str, Any] = Field(default_factory=dict)


class ObserverOut(BaseModel):
    id: uuid.UUID
    name: str
    labels: dict[str, Any]
    created_at: datetime
    last_heartbeat: datetime | None
    status: ObserverStatus

    model_config = {"from_attributes": True}


class ObserverCreated(ObserverOut):
    api_key: str  # shown exactly once


@router.post("", response_model=ObserverCreated, status_code=status.HTTP_201_CREATED)
async def create_observer(body: ObserverCreate, db: AsyncSession = Depends(get_db)):
    observer_id = uuid.uuid4()
    api_key, key_hash = generate_api_key(observer_id)
    observer = Observer(id=observer_id, name=body.name, labels=body.labels, api_key_hash=key_hash)
    db.add(observer)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Observer '{body.name}' already exists") from e
    return ObserverCreated(**ObserverOut.model_validate(observer).model_dump(), api_key=api_key)


@router.get("", response_model=list[ObserverOut])
async def list_observers(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Observer).order_by(Observer.name))).scalars()
    return [ObserverOut.model_validate(o) for o in rows]


@router.get("/{observer_id}", response_model=ObserverOut)
async def get_observer(observer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    observer = await db.get(Observer, observer_id)
    if observer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Observer not found")
    return ObserverOut.model_validate(observer)


@router.post("/{observer_id}/rotate_key", response_model=ObserverCreated)
async def rotate_key(observer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    observer = await db.get(Observer, observer_id)
    if observer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Observer not found")
    api_key, key_hash = generate_api_key(observer.id)
    observer.api_key_hash = key_hash
    await db.commit()
    return ObserverCreated(**ObserverOut.model_validate(observer).model_dump(), api_key=api_key)


@router.delete("/{observer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_observer(observer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    observer = await db.get(Observer, observer_id)
    if observer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Observer not found")
    await db.delete(observer)
    await db.commit()
