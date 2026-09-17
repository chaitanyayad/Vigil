"""Merkle batcher + anchor worker.

Every LEDGER_BATCH_INTERVAL_SECONDS (or when LEDGER_BATCH_MAX_EVENTS unbatched
events pile up) the unbatched slice of alert_events becomes a ledger_batches
row holding its Merkle root. A second pass submits pending batches on-chain
with retry/backoff. If LEDGER_ENABLED=false the batches are still built — the
hash chain and Merkle roots work standalone; only the anchoring is skipped.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.config import get_settings
from vigil.db.models import AlertEvent, BatchStatus, LedgerBatch
from vigil.ledger.anchor import get_chain_client
from vigil.ledger.merkle import merkle_root
from vigil.ws import bus

log = logging.getLogger(__name__)


async def build_batch(db: AsyncSession) -> LedgerBatch | None:
    """Collect all unbatched events (ordered) into one pending batch."""
    events = list(
        (
            await db.execute(
                select(AlertEvent).where(AlertEvent.batch_id.is_(None)).order_by(AlertEvent.id)
            )
        ).scalars()
    )
    if not events:
        return None
    batch = LedgerBatch(
        merkle_root=merkle_root([e.event_hash for e in events]),
        first_event_id=events[0].id,
        last_event_id=events[-1].id,
        chain_id=get_settings().chain_id,
        status=BatchStatus.pending,
    )
    db.add(batch)
    await db.flush()
    await db.execute(
        update(AlertEvent)
        .where(AlertEvent.id >= batch.first_event_id, AlertEvent.id <= batch.last_event_id)
        .values(batch_id=batch.id)
    )
    await db.commit()
    log.info("built ledger batch %d (events %d..%d)", batch.id, batch.first_event_id, batch.last_event_id)
    return batch


async def anchor_pending(db: AsyncSession) -> int:
    """Submit pending/failed batches on-chain. Returns number anchored."""
    if not get_settings().ledger_enabled:
        return 0
    client = get_chain_client()
    if client is None:
        return 0
    batches = list(
        (
            await db.execute(
                select(LedgerBatch)
                .where(LedgerBatch.status != BatchStatus.anchored)
                .order_by(LedgerBatch.id)
            )
        ).scalars()
    )
    anchored = 0
    for batch in batches:
        try:
            result = await client.anchor(batch.merkle_root, batch.first_event_id, batch.last_event_id)
        except Exception:
            log.exception("anchoring batch %d failed — will retry", batch.id)
            batch.status = BatchStatus.failed
            await db.commit()
            continue
        batch.tx_hash = result["tx_hash"]
        batch.block_number = result["block_number"]
        batch.chain_batch_id = result["chain_batch_id"]
        batch.anchored_at = datetime.now(UTC)
        batch.status = BatchStatus.anchored
        await db.commit()
        anchored += 1
        await bus.publish(
            bus.CH_LEDGER, "batch_anchored",
            {"batch_id": batch.id, "tx_hash": batch.tx_hash,
             "block_number": batch.block_number,
             "merkle_root": "0x" + batch.merkle_root.hex(),
             "first_event_id": batch.first_event_id, "last_event_id": batch.last_event_id},
        )
        log.info("anchored batch %d in tx %s", batch.id, batch.tx_hash)
    return anchored


async def ledger_tick(force: bool = False) -> None:
    """Scheduler entrypoint: batch if due, then anchor."""
    from vigil.db.session import get_sessionmaker

    s = get_settings()
    async with get_sessionmaker()() as db:
        unbatched = (
            await db.execute(
                select(AlertEvent.id).where(AlertEvent.batch_id.is_(None)).limit(s.ledger_batch_max_events)
            )
        ).all()
        if unbatched and (force or len(unbatched) >= s.ledger_batch_max_events or await _interval_due(db)):
            await build_batch(db)
        await anchor_pending(db)


async def _interval_due(db: AsyncSession) -> bool:
    s = get_settings()
    last = (
        await db.execute(select(LedgerBatch).order_by(LedgerBatch.id.desc()).limit(1))
    ).scalar_one_or_none()
    if last is None:
        return True
    oldest_unbatched = (
        await db.execute(
            select(AlertEvent.created_at).where(AlertEvent.batch_id.is_(None)).order_by(AlertEvent.id).limit(1)
        )
    ).scalar_one_or_none()
    if oldest_unbatched is None:
        return False
    return (datetime.now(UTC) - oldest_unbatched).total_seconds() >= s.ledger_batch_interval_seconds
