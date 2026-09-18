# ADR 0001 — Python/FastAPI instead of Go

**Status:** accepted

## Context
The reference architecture (Sentinel) is Go + Gin. VIGIL adds an ML layer (feature building,
IsolationForest train/infer, eval harness) and an LLM triage layer on top of the same
ingest/rules core.

## Decision
Build the orchestrator in Python 3.12 with FastAPI + async SQLAlchemy.

## Rationale
- The ML layer lives in-process: pandas/scikit-learn feature parity in Go would mean either a
  second service and a cross-language boundary, or reimplementing the ecosystem.
- At this scale (hundreds of observers, batched ingest every 30 s) async FastAPI throughput is
  nowhere near the bottleneck — TimescaleDB inserts are.
- Owner's strength is Python; a portfolio project should demonstrate depth, not language tourism.

## Consequences
- CPU-bound work (training, scoring) must be pushed off the event loop (`asyncio.to_thread`);
  request handlers stay non-blocking. Enforced as a project convention.
- Single process hosts API + schedulers; see ADR 0005 for why that's acceptable.
