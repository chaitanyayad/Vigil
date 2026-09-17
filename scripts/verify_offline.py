"""Independent auditor tool: verify the incident ledger with ONLY a database
connection (or dump restored locally) and an RPC URL. Deliberately imports
nothing from the orchestrator — an auditor shouldn't have to trust its code.

    python scripts/verify_offline.py \
        --db postgresql://vigil:vigil@localhost:5433/vigil \
        --rpc http://localhost:8545 \
        --contract 0x5FbDB2315678afecb367f032d93F642f64180aa3
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC

import asyncpg
from web3 import Web3

ABI = [
    {
        "type": "function", "name": "getBatch", "stateMutability": "view",
        "inputs": [{"name": "id", "type": "uint256"}],
        "outputs": [
            {"name": "root", "type": "bytes32"},
            {"name": "firstEventId", "type": "uint64"},
            {"name": "lastEventId", "type": "uint64"},
            {"name": "timestamp", "type": "uint256"},
        ],
    },
    {
        "type": "function", "name": "batchCount", "stateMutability": "view",
        "inputs": [], "outputs": [{"name": "", "type": "uint256"}],
    },
]


def event_hash(alert_id, event_type, payload, created_at, prev_hash):
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


def merkle_root(leaves):
    level = list(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            a, b = level[i], level[i + 1]
            lo, hi = (a, b) if a <= b else (b, a)
            nxt.append(hashlib.sha256(lo + hi).digest())
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        level = nxt
    return level[0]


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="postgresql://vigil:vigil@localhost:5433/vigil")
    p.add_argument("--rpc", default="http://localhost:8545")
    p.add_argument("--contract", default="0x5FbDB2315678afecb367f032d93F642f64180aa3")
    args = p.parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc))
    contract = w3.eth.contract(address=Web3.to_checksum_address(args.contract), abi=ABI)
    conn = await asyncpg.connect(args.db)
    batches = await conn.fetch(
        "SELECT id, chain_batch_id, first_event_id, last_event_id FROM ledger_batches "
        "WHERE status = 'anchored' ORDER BY id"
    )

    failures = 0
    for batch in batches:
        rows = await conn.fetch(
            "SELECT id, alert_id, event_type, payload, created_at, prev_hash FROM alert_events "
            "WHERE id BETWEEN $1 AND $2 ORDER BY id",
            batch["first_event_id"], batch["last_event_id"],
        )
        # Recompute EVERY leaf from raw row content (using each row's stored
        # prev_hash link), then the root, then compare on-chain.
        leaves = []
        for r in rows:
            payload = json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"])
            prev = bytes(r["prev_hash"]) if r["prev_hash"] else None
            leaves.append(event_hash(r["alert_id"], r["event_type"], payload, r["created_at"], prev))
        local_root = merkle_root(leaves)
        chain_root, first, last, ts = contract.functions.getBatch(batch["chain_batch_id"]).call()
        ok = bytes(chain_root) == local_root and first == batch["first_event_id"] and last == batch["last_event_id"]
        status = "OK      " if ok else "TAMPERED"
        print(f"batch {batch['id']:>4} (chain #{batch['chain_batch_id']}) events "
              f"{batch['first_event_id']}..{batch['last_event_id']}  {status}")
        if not ok:
            failures += 1
            # narrow it down: recompute each event and flag the mismatching row(s)
            for r, leaf in zip(rows, leaves):
                stored = await conn.fetchval("SELECT event_hash FROM alert_events WHERE id=$1", r["id"])
                if bytes(stored) != leaf:
                    print(f"    event {r['id']}: row content no longer matches its hash")

    await conn.close()
    if not batches:
        print("no anchored batches yet")
    print("\nRESULT:", "LEDGER VERIFIED" if failures == 0 else f"{failures} TAMPERED BATCH(ES)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
