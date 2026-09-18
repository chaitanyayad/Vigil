# ADR 0003 — Merkle-root anchoring instead of writing events on-chain

**Status:** accepted

## Context
The ledger must let an external party verify that alert history wasn't edited after the fact.
A naive design writes every alert event to the chain.

## Decision
Events stay in Postgres as an append-only sha256 hash chain; every ~5 minutes (or 500 events)
the batch's Merkle root — 32 bytes — is anchored via `IncidentAnchor.anchor()`. Verification
recomputes an event's hash from the raw row and proves membership against the on-chain root.

## Rationale
- Cost & throughput: one small tx per batch vs one per event; works on a public testnet
  without drowning in gas.
- Privacy: metrics and alert text never leave the database; the chain sees only digests.
- The hash chain alone already detects tampering *if you trust the verifier's copy of the
  chain head*; the on-chain root removes that last trust assumption.
- `getBatch` enforces monotonically increasing event-id ranges, so history can't be
  re-anchored/rewritten even by the contract owner.

## Consequences
- Verification needs the sibling hashes from the DB (they're inputs to the proof, not secrets);
  `scripts/verify_offline.py` shows a DB dump + RPC URL is sufficient — no orchestrator trust.
- Events in a not-yet-anchored batch are only chain-protected, not chain-anchored; the UI and
  API surface this as `pending`, and `LEDGER_ENABLED=false` degrades to hash-chain-only mode.
