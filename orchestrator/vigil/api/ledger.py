import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import require_admin
from vigil.db.models import BatchStatus, LedgerBatch
from vigil.db.session import get_db
from vigil.ledger.anchor import get_chain_client
from vigil.ledger.batcher import ledger_tick
from vigil.ledger.verify import verify_alert

router = APIRouter(prefix="/v1/ledger", tags=["ledger"])


class BatchOut(BaseModel):
    id: int
    merkle_root: str
    first_event_id: int
    last_event_id: int
    tx_hash: str | None
    chain_id: int
    chain_batch_id: int | None
    block_number: int | None
    anchored_at: datetime | None
    status: BatchStatus


@router.get("/batches", response_model=list[BatchOut], dependencies=[Depends(require_admin)])
async def list_batches(limit: int = 100, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(LedgerBatch).order_by(LedgerBatch.id.desc()).limit(min(limit, 500)))
    ).scalars()
    return [
        BatchOut(
            id=b.id,
            merkle_root="0x" + b.merkle_root.hex(),
            first_event_id=b.first_event_id,
            last_event_id=b.last_event_id,
            tx_hash=b.tx_hash,
            chain_id=b.chain_id,
            chain_batch_id=b.chain_batch_id,
            block_number=b.block_number,
            anchored_at=b.anchored_at,
            status=b.status,
        )
        for b in rows
    ]


@router.get("/verify/{alert_id}")
async def verify(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Public endpoint: anyone can check that an alert's history matches the
    on-chain Merkle roots — no auth on purpose."""
    return await verify_alert(db, alert_id, get_chain_client())


@router.post("/anchor", dependencies=[Depends(require_admin)])
async def force_anchor() -> dict:
    """Batch all pending events and anchor now."""
    await ledger_tick(force=True)
    return {"status": "ok"}
