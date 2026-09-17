"""Integrity verification for an alert's event history.

For each event of the alert:
  1. recompute its hash from the raw DB row (a tampered row recomputes differently),
  2. build the Merkle proof from the *stored* hashes of its batch siblings,
  3. compare against the on-chain root for that batch.

valid=True  → row content matches what was anchored on-chain.
valid=False → the row was edited after anchoring (or the chain disagrees).
valid=None  → event not yet anchored (pending batch) or chain unreachable.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.db.models import AlertEvent, BatchStatus, LedgerBatch
from vigil.ledger.anchor import ChainClient
from vigil.ledger.hashing import compute_event_hash
from vigil.ledger.merkle import merkle_proof, verify_proof

log = logging.getLogger(__name__)


async def verify_alert(
    db: AsyncSession,
    alert_id: uuid.UUID,
    chain: ChainClient | None,
) -> dict[str, Any]:
    events = list(
        (
            await db.execute(
                select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.id)
            )
        ).scalars()
    )
    results: list[dict[str, Any]] = []
    roots_cache: dict[int, bytes | None] = {}
    batch_cache: dict[int, tuple[LedgerBatch, list[AlertEvent]]] = {}

    for ev in events:
        recomputed = compute_event_hash(
            ev.alert_id, ev.event_type.value, ev.payload, ev.created_at, ev.prev_hash
        )
        entry: dict[str, Any] = {
            "event_id": ev.id,
            "event_type": ev.event_type.value,
            "created_at": ev.created_at.isoformat(),
            "local_hash": "0x" + recomputed.hex(),
            "stored_hash": "0x" + ev.event_hash.hex(),
            "hash_matches_stored": recomputed == ev.event_hash,
            "batch_id": ev.batch_id,
            "proof": [],
            "on_chain_root": None,
            "valid": None,
        }
        if ev.batch_id is None:
            entry["status"] = "unbatched"
            results.append(entry)
            continue

        if ev.batch_id not in batch_cache:
            batch = await db.get(LedgerBatch, ev.batch_id)
            assert batch is not None  # FK guarantees the batch row exists
            siblings = list(
                (
                    await db.execute(
                        select(AlertEvent)
                        .where(AlertEvent.batch_id == ev.batch_id)
                        .order_by(AlertEvent.id)
                    )
                ).scalars()
            )
            batch_cache[ev.batch_id] = (batch, siblings)
        batch, siblings = batch_cache[ev.batch_id]

        leaves = [s.event_hash for s in siblings]
        index = next(i for i, s in enumerate(siblings) if s.id == ev.id)
        proof = merkle_proof(leaves, index)
        entry["proof"] = ["0x" + p.hex() for p in proof]

        if batch.status != BatchStatus.anchored or batch.chain_batch_id is None:
            entry["status"] = "pending_anchor"
            results.append(entry)
            continue

        if ev.batch_id not in roots_cache:
            if chain is None:
                roots_cache[ev.batch_id] = None
            else:
                try:
                    roots_cache[ev.batch_id] = await chain.get_root(batch.chain_batch_id)
                except Exception:
                    log.exception("failed to read on-chain root for batch %d", ev.batch_id)
                    roots_cache[ev.batch_id] = None
        on_chain_root = roots_cache[ev.batch_id]
        if on_chain_root is None:
            entry["status"] = "chain_unreachable"
            results.append(entry)
            continue

        entry["on_chain_root"] = "0x" + on_chain_root.hex()
        # The proof is built from stored sibling hashes but the target leaf is
        # RECOMPUTED from row content — an edited row fails right here.
        entry["valid"] = verify_proof(recomputed, proof, on_chain_root)
        entry["status"] = "verified" if entry["valid"] else "TAMPERED"
        results.append(entry)

    overall = all(e["valid"] for e in results if e["valid"] is not None) if results else True
    return {
        "alert_id": str(alert_id),
        "events": results,
        "all_verified": overall and any(e["valid"] is not None for e in results),
        "tampered_event_ids": [e["event_id"] for e in results if e["valid"] is False],
    }
