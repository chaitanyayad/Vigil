"""Verify the alert_events hash chain straight from the database.

Standalone on purpose: recomputes every hash from raw rows without importing
orchestrator code, so it double-checks the implementation too.

    python scripts/verify_chain.py [--db postgresql://vigil:vigil@localhost:5433/vigil]
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC

import asyncpg


def compute_hash(alert_id, event_type, payload: dict, created_at, prev_hash: bytes | None) -> bytes:
    doc = {
        "alert_id": str(alert_id),
        "event_type": event_type,
        "payload": payload,
        "created_at": created_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    h = hashlib.sha256()
    h.update(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
    h.update(prev_hash or b"\x00" * 32)
    return h.digest()


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="postgresql://vigil:vigil@localhost:5433/vigil")
    args = p.parse_args()

    conn = await asyncpg.connect(args.db)
    rows = await conn.fetch(
        "SELECT id, alert_id, event_type, payload, created_at, event_hash, prev_hash "
        "FROM alert_events ORDER BY id"
    )
    await conn.close()

    if not rows:
        print("no alert events yet — chain trivially valid")
        return 0

    bad = []
    prev = None
    for r in rows:
        payload = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
        expected = compute_hash(r["alert_id"], r["event_type"], payload, r["created_at"], prev)
        if expected != bytes(r["event_hash"]):
            bad.append((r["id"], "event_hash mismatch (row content edited?)"))
        if (r["prev_hash"] and bytes(r["prev_hash"]) or None) != prev:
            bad.append((r["id"], "prev_hash link broken"))
        prev = bytes(r["event_hash"])

    print(f"checked {len(rows)} events (ids {rows[0]['id']}..{rows[-1]['id']})")
    if bad:
        for event_id, reason in bad:
            print(f"  TAMPERED event {event_id}: {reason}")
        print("CHAIN INVALID")
        return 1
    print("CHAIN VALID — every hash and link verifies")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
