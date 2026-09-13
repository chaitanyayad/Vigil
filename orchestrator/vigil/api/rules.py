import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import require_admin
from vigil.db.models import AlertRule, RuleOp, Severity
from vigil.db.session import get_db

router = APIRouter(prefix="/v1/rules", tags=["rules"], dependencies=[Depends(require_admin)])

VALID_METRICS = {"cpu_pct", "mem_pct", "disk_pct", "net_rx_bps", "net_tx_bps", "load1"}


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    metric: str
    op: RuleOp
    threshold: float
    for_seconds: int = Field(0, ge=0, le=86400)
    severity: Severity
    enabled: bool = True
    observer_selector: dict[str, Any] | None = None


class RulePatch(BaseModel):
    name: str | None = None
    metric: str | None = None
    op: RuleOp | None = None
    threshold: float | None = None
    for_seconds: int | None = Field(None, ge=0, le=86400)
    severity: Severity | None = None
    enabled: bool | None = None
    observer_selector: dict[str, Any] | None = None


class RuleOut(RuleCreate):
    id: uuid.UUID
    model_config = {"from_attributes": True}


def _check_metric(metric: str) -> None:
    if metric not in VALID_METRICS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"metric must be one of {sorted(VALID_METRICS)}",
        )


@router.get("", response_model=list[RuleOut])
async def list_rules(db: AsyncSession = Depends(get_db)):
    return [
        RuleOut.model_validate(r)
        for r in (await db.execute(select(AlertRule).order_by(AlertRule.name))).scalars()
    ]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(body: RuleCreate, db: AsyncSession = Depends(get_db)):
    _check_metric(body.metric)
    rule = AlertRule(**body.model_dump())
    db.add(rule)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Rule '{body.name}' already exists") from e
    return RuleOut.model_validate(rule)


@router.patch("/{rule_id}", response_model=RuleOut)
async def patch_rule(rule_id: uuid.UUID, body: RulePatch, db: AsyncSession = Depends(get_db)):
    rule = await db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    updates = body.model_dump(exclude_unset=True)
    if "metric" in updates:
        _check_metric(updates["metric"])
    for k, v in updates.items():
        setattr(rule, k, v)
    await db.commit()
    return RuleOut.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    await db.delete(rule)
    await db.commit()
