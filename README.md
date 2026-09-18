# VIGIL

**AI-assisted infrastructure monitoring with a tamper-evident incident ledger.**

Lightweight agents stream host metrics to an async FastAPI orchestrator. Alerts come from two
detectors — classic threshold rules *and* a per-host IsolationForest anomaly model — and every
alert lifecycle event is sha256-chained, Merkle-batched, and anchored on-chain, so the incident
history can be verified by anyone, even against a hostile database admin. Critical alerts get an
LLM triage pass (Google Gemini, free tier) grounded in your runbooks via pgvector retrieval.

```
 agents (psutil) ──HTTP──▶ ingest ──▶ TimescaleDB (hypertable + 1m continuous aggregate)
                              │
                              ├─▶ rules engine ──┐
                              │                  ├──▶ alerts ──▶ alert_events (hash chain)
 APScheduler ─▶ IsolationForest inference ───────┘                   │
                              │                                      ▼
 Redis pub/sub ◀──────────────┴── WebSocket live dashboard    Merkle batcher ─▶ IncidentAnchor.sol
                                                                     ▲              (Anvil/Sepolia)
 Gemini triage (runbook RAG, pgvector) ── writes `triaged` events ───┘
```

## Quick start

```bash
cp .env.example .env          # optional: add GEMINI_API_KEY for LLM triage
docker compose up -d --build
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:5173 (admin / change-me) |
| API + OpenAPI docs | http://localhost:8000/docs |
| Anvil dev chain | http://localhost:8545 |
| TimescaleDB | localhost:5433 (vigil/vigil) |

Compose brings up TimescaleDB, Redis, an Anvil chain with the `IncidentAnchor` contract
auto-deployed, the orchestrator, **two sample agents**, and the dashboard. Then:

```bash
cd orchestrator && uv sync                    # local venv for the demo scripts
.venv/Scripts/python ../scripts/seed_rules.py           # default ruleset
.venv/Scripts/python ../scripts/load_gen.py --observers 2 --minutes 3 --spike-after 30
```

Watch the CPU spike fire `cpu-high` in the dashboard, then auto-resolve when it clears.

## The tamper demo

The point of the ledger: **an edited incident history is detectable.**

```bash
python scripts/verify_chain.py     # CHAIN VALID — every hash and link verifies
python scripts/tamper.py           # edits one alert_events row via raw SQL (severity -> "info")
python scripts/verify_chain.py     # CHAIN INVALID — names the exact tampered event
python scripts/verify_offline.py   # independent audit: DB + RPC only, no orchestrator code
python scripts/tamper.py --restore
```

Same result in the browser: **Alerts → expand → Verify integrity** shows a red ✗ on exactly the
tampered event, because its recomputed hash no longer proves membership in the on-chain Merkle
root. The chain stores only 32-byte roots — never metrics, never alert content.

## Rules vs ML — why the anomaly detector earns its keep

Reproduce with `python -m vigil.ml.eval` (labelled synthetic set: diurnal baseline + injected
CPU runaway, memory-leak ramp, disk fill, network flood):

| Metric | IsolationForest | Static rules |
|---|---|---|
| Precision | 0.90 | 0.98 |
| Recall (point-wise) | 0.44 | 0.44 |
| Incidents detected | 4/4 | 3/4 |
| Mean detection delay | ~21 min | ~57 min |
| False alarms / day | ~4 | ~0.2 |

The headline: the **memory-leak ramp is flagged ≈ 170 minutes before** any sane static threshold
trips — the model learns the diurnal baseline, so "memory is 30 points above its usual 2 a.m.
value" is anomalous long before "memory > 90%". Static rules stay in the loop for the things
they're better at: precise, explainable, zero-training-data alarms. (Exact numbers vary a little
per training run; the eval stores each model's own report in `ml_models.metrics`.)

- Threshold is **calibrated per model** (0.5th percentile of training scores) — raw
  IsolationForest scores don't transfer between models.
- An alert needs **3 consecutive anomalous minutes** (mirrored in the eval), which is what keeps
  false alarms tolerable.
- Nightly retrain absorbs new legitimate baselines.

## How this differs from a threshold-only monitor

1. **Learned baselines** catch slow drifts (leaks, fills) while they're still slopes, not cliffs.
2. **Triage with context**: on a critical alert, Gemini gets the alert, 30 min of metrics,
   co-firing alerts, and the top-3 runbook chunks by embedding similarity — and must answer in
   validated JSON: hypothesis, confidence, one runbook, next steps. No key → feature disables
   itself, nothing breaks.
3. **Verifiable history**: threshold monitors trust their database. VIGIL's alert log is an
   append-only hash chain whose Merkle roots live on a chain the orchestrator can't rewrite;
   `scripts/verify_offline.py` audits it with zero trust in the orchestrator's code.

## Measured on the dev laptop

`scripts/load_gen.py --observers 50 --rate 10`: ingest latency **p50 86 ms / p95 93 ms /
p99 112 ms** (each request pays an argon2 API-key verification — the deliberate dominant cost;
batch size amortises it in real deployments). Agent image: **87 MB** (python:3.12-alpine base
is ~78 MB of that).

## Testing

```bash
cd orchestrator
.venv/Scripts/python -m pytest tests -q      # 66 tests; integration needs compose db+redis up
.venv/Scripts/python -m ruff check vigil tests && .venv/Scripts/python -m mypy vigil
cd ../agent && .venv/Scripts/python -m pytest tests -q
docker run --rm -v "$PWD/contracts:/c" -w /c --entrypoint sh ghcr.io/foundry-rs/foundry:stable \
  -c "forge install foundry-rs/forge-std --no-git 2>/dev/null; forge test"   # 9 tests
```

Covered end-to-end in tests: every REST endpoint, `for_seconds` hold semantics with resets,
dedupe under concurrent ingest (partial unique indexes), hash-chain integrity + tamper
detection, Merkle proofs for every leaf position, Gemini response parsing against recorded
fixtures, the agent's ring buffer, and contract access control/event emission.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 async · TimescaleDB (hypertable, continuous aggregates,
retention) · Redis pub/sub · scikit-learn · Google Gemini (free tier, REST) · pgvector ·
Solidity 0.8 + Foundry · web3.py · React + Vite + TS + Tailwind + Recharts · Docker Compose ·
GitHub Actions. Design decisions in [docs/adr/](docs/adr/).

## Repository map

See [PLAN.md](PLAN.md) for the full spec; `orchestrator/vigil/` is the core
(`rules/` engine + lifecycle, `ml/` features–train–eval, `triage/` providers + RAG,
`ledger/` hashing–merkle–anchor–verify, `ws/` live bus), `agent/` the observer,
`contracts/` the Foundry project, `scripts/` the demo tooling.
