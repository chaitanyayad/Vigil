# VIGIL architecture

```mermaid
flowchart LR
    subgraph hosts [Monitored hosts]
        A1[agent-1<br/>psutil + ring buffer]
        A2[agent-2]
    end

    subgraph orch [Orchestrator - FastAPI, one process]
        ING[ingest<br/>validate + bulk insert]
        RUL[rules engine<br/>for_seconds hold, dedupe]
        WD[heartbeat watchdog]
        ML[IsolationForest<br/>train nightly / infer 60s]
        TRI[Gemini triage<br/>runbook RAG]
        LED[ledger<br/>hash chain -> Merkle -> anchor]
        WS[WebSocket fan-out]
    end

    subgraph store [State]
        TS[(TimescaleDB<br/>metrics hypertable<br/>metrics_1m cagg<br/>pgvector runbooks)]
        RD[(Redis<br/>pub/sub + rule state)]
    end

    CH[[IncidentAnchor.sol<br/>Anvil / Sepolia]]
    FE[React dashboard]
    AUD[verify_offline.py<br/>independent auditor]

    A1 -- "metrics 30s / heartbeat 15s" --> ING
    A2 --> ING
    ING --> TS
    ING --> RUL
    ING -- publish --> RD
    RUL -- "alert_events (sha256 chain)" --> TS
    WD --> RUL
    ML --> TS
    ML --> RUL
    TRI --> TS
    LED --> TS
    LED -- "anchor(root, first, last)" --> CH
    RD --> WS
    WS --> FE
    FE -- REST --> orch
    AUD -.-> TS
    AUD -.-> CH
```

## Data flow, in one paragraph

Agents sample psutil every 10 s, batch every 30 s (buffering the last 1000 samples on disk
across outages), and heartbeat every 15 s. Ingest validates, bulk-inserts into the `metrics`
hypertable, publishes to `metrics:{observer_id}`, and runs the rules engine, which tracks
first-breach timestamps in Redis to implement `for_seconds` and relies on partial unique
indexes for exactly-one-active-alert semantics. Every alert state change goes through one
lifecycle module that appends a hash-chained `alert_events` row and publishes to the WS bus.
A per-minute job scores the latest `metrics_1m` window with the observer's (or global)
IsolationForest; a 30 s job triages untriaged critical alerts through Gemini with runbook
chunks retrieved from pgvector; a 60 s job folds unbatched events into Merkle batches and
anchors their roots on-chain. The dashboard reads REST and listens to the WS relay of the
Redis bus.

## Trust model of the ledger

| Attacker capability | Detected by |
|---|---|
| Edit an `alert_events` row | its recomputed hash ≠ stored hash → chain + proof fail |
| Edit row *and* its stored hash | `prev_hash` link of the next event breaks |
| Rewrite the whole chain suffix | batch Merkle roots no longer match the on-chain roots |
| Rewrite chain + re-anchor | contract refuses overlapping event-id ranges; old `Anchored` events remain |
| Compromise the orchestrator | `verify_offline.py` needs only a DB dump + RPC URL |

Bootstrap secrets note: compose dev uses Anvil's public dev key and a default admin password —
both are placeholders and must be overridden outside local dev (`.env`).
