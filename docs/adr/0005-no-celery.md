# ADR 0005 — In-process scheduling (APScheduler), no Celery

**Status:** accepted

## Context
Background work: heartbeat watchdog (10 s), ML inference (60 s), ledger batching/anchoring
(60 s), auto-triage (30 s), nightly retrain. Celery (or arq/dramatiq) is the reflexive answer.

## Decision
Run everything with AsyncIOScheduler inside the orchestrator process.

## Rationale
- Every job is either I/O-bound (fits the event loop) or short CPU-bound work pushed through
  `asyncio.to_thread`. Nothing needs distribution, routing, or per-task retry queues.
- Celery adds a broker contract, worker deployment, serialization boundaries, and a second
  failure domain — for a system whose jobs are all idempotent ticks that re-derive state from
  the database ("find unbatched events", "find untriaged criticals"). A missed tick costs
  nothing; the next tick catches up. That idempotence is the actual reliability mechanism.
- One process = `docker compose up` stays one orchestrator container.

## Consequences
- Horizontal scaling of the API would double the schedulers; if that day comes, the workers
  split into a separate entrypoint (same code, `create_app(enable_workers=...)` already
  supports it) — not a rewrite.
- Long ML training runs share the process; acceptable because training is seconds, and
  `to_thread` keeps the loop responsive.
