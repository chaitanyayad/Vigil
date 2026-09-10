"""Canonical hashing for alert lifecycle events.

Every alert_events row carries:
  event_hash = sha256(canonical_json(alert_id, event_type, payload, created_at) || prev_hash)
  prev_hash  = event_hash of the previous row (global, ordered by id) — a hash chain.

The chain makes silent edits detectable even before a batch is anchored on-chain;
the Merkle root of each batch is what gets anchored.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.db.models import AlertEvent, AlertEventType

# Advisory lock key: serialises appends so prev_hash is race-free under
# concurrent ingest. Arbitrary constant, unique to this chain.
_CHAIN_LOCK_KEY = 0x71611  # "vigil"


def canonical_event_bytes(
    alert_id: uuid.UUID | str,
    event_type: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> bytes:
    """Deterministic byte serialisation of an event's protected fields."""
    doc = {
        "alert_id": str(alert_id),
        "event_type": event_type,
        "payload": payload,
        "created_at": created_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def compute_event_hash(
    alert_id: uuid.UUID | str,
    event_type: str,
    payload: dict[str, Any],
    created_at: datetime,
    prev_hash: bytes | None,
) -> bytes:
    h = hashlib.sha256()
    h.update(canonical_event_bytes(alert_id, event_type, payload, created_at))
    h.update(prev_hash or b"\x00" * 32)
    return h.digest()


async def record_alert_event(
    db: AsyncSession,
    alert_id: uuid.UUID,
    event_type: AlertEventType,
    payload: dict[str, Any] | None = None,
) -> AlertEvent:
    """Append an event to the hash chain. Must be called inside a transaction;
    takes a pg advisory xact lock so concurrent writers serialise."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    last = (
        await db.execute(select(AlertEvent).order_by(AlertEvent.id.desc()).limit(1))
    ).scalar_one_or_none()
    prev_hash = last.event_hash if last else None
    created_at = datetime.now(UTC)
    payload = payload or {}
    event = AlertEvent(
        alert_id=alert_id,
        event_type=event_type,
        payload=payload,
        created_at=created_at,
        prev_hash=prev_hash,
        event_hash=compute_event_hash(alert_id, event_type.value, payload, created_at, prev_hash),
    )
    db.add(event)
    await db.flush()
    return event


def verify_chain(events: list[AlertEvent]) -> list[int]:
    """Given ALL events ordered by id, return ids whose hash doesn't verify."""
    bad: list[int] = []
    prev: bytes | None = None
    for ev in events:
        expected = compute_event_hash(
            ev.alert_id, ev.event_type.value, ev.payload, ev.created_at, prev
        )
        if expected != ev.event_hash or ev.prev_hash != prev:
            bad.append(ev.id)
        prev = ev.event_hash
    return bad
