"""Tamper demo: edit one alert_events.payload row directly in SQL, the way an
attacker with DB access would try to rewrite incident history.

After running this, GET /v1/ledger/verify/{alert_id} (and verify_offline.py)
must report valid=false for exactly the edited event.

    python scripts/tamper.py                # tampers the newest anchored event
    python scripts/tamper.py --event-id 42
    python scripts/tamper.py --restore      # put the original payload back
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

BACKUP = Path(__file__).parent / ".tamper_backup.json"


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="postgresql://vigil:vigil@localhost:5433/vigil")
    p.add_argument("--event-id", type=int, default=None)
    p.add_argument("--restore", action="store_true")
    args = p.parse_args()

    conn = await asyncpg.connect(args.db)
    try:
        if args.restore:
            if not BACKUP.exists():
                print("no backup found — nothing to restore")
                return 1
            saved = json.loads(BACKUP.read_text())
            await conn.execute(
                "UPDATE alert_events SET payload = $1::jsonb WHERE id = $2",
                json.dumps(saved["payload"]), saved["id"],
            )
            BACKUP.unlink()
            print(f"restored original payload of event {saved['id']}")
            return 0

        if args.event_id is not None:
            row = await conn.fetchrow(
                "SELECT id, alert_id, payload FROM alert_events WHERE id = $1", args.event_id
            )
        else:
            # newest event that's already in an anchored batch — the juicy target
            row = await conn.fetchrow("""
                SELECT e.id, e.alert_id, e.payload FROM alert_events e
                JOIN ledger_batches b ON b.id = e.batch_id
                WHERE b.status = 'anchored'
                ORDER BY e.id DESC LIMIT 1
            """)
        if row is None:
            print("no suitable event found (need at least one anchored event)")
            return 1

        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"])
        BACKUP.write_text(json.dumps({"id": row["id"], "payload": payload}))

        tampered = dict(payload)
        tampered["severity"] = "info"  # downgrade the incident after the fact
        tampered["summary"] = "(nothing happened here)"
        await conn.execute(
            "UPDATE alert_events SET payload = $1::jsonb WHERE id = $2",
            json.dumps(tampered), row["id"],
        )
        print(f"TAMPERED event {row['id']} of alert {row['alert_id']}")
        print("now run:  python scripts/verify_chain.py")
        print(f"     or:  GET /v1/ledger/verify/{row['alert_id']}")
        print("     undo: python scripts/tamper.py --restore")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
