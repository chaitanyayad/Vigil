# VIGIL — AI-Assisted Infrastructure Monitoring with a Tamper-Evident Incident Ledger

> Project plan for Claude Code. Read this whole file before writing any code.
> Work phase by phase. Do not start a phase until the previous phase's "Done when" checklist passes.
> Ask before deviating from the stack or schema below.

---

## 0. Context

**Reference project:** https://github.com/tusharb05/sentinel (a friend's project, Go + Gin + SQLC + PostgreSQL + Docker).
Sentinel = lightweight observer agents push CPU/mem/disk/net metrics + heartbeats to a central orchestrator; orchestrator evaluates static threshold rules (e.g. `CPU > 85% for 5 min`), dedupes alerts (one active alert per observer+rule), auto-resolves when metrics recover.

**Goal:** Rebuild the same architecture from scratch (do NOT copy code), then extend it in three ways that Sentinel does not have:

1. **AI layer** — learned anomaly detection instead of only static thresholds, plus LLM-based incident triage (root-cause hypothesis + suggested runbook step).
2. **Blockchain layer** — tamper-evident incident/audit ledger: every alert lifecycle event is hashed and its Merkle root is periodically anchored on-chain, so the incident history can be independently verified.
3. **Better fundamentals** — time-series DB, WebSocket live dashboard, evaluation harness for the ML model, proper tests and CI.

**Owner:** Chaitanya (intermediate Python, backend + ML background, frontend is a weak area — keep frontend simple and component-driven). Dev machine: Windows laptop, RTX 4060 8 GB. Use Docker Desktop (WSL2 backend) for all services.

**Why this stack (and not Go like Sentinel):** owner's strength is Python; FastAPI + async gives comparable throughput at this scale, and keeps the ML layer in-process without a cross-language boundary. This is a deliberate choice, not a limitation.

---

## 1. Stack (fixed — do not substitute without asking)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | `uv` for deps, `ruff` + `mypy` |
| API | FastAPI + uvicorn | async everywhere |
| DB | PostgreSQL 16 + TimescaleDB extension | hypertable for metrics; plain tables for the rest |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic | raw SQL allowed for Timescale-specific queries |
| Queue / cache | Redis 7 | pub/sub for live dashboard, stream for ingestion buffer |
| Agent | Python + `psutil`, packaged as a Docker image | target < 80 MB (python:3.12-alpine base) |
| ML | scikit-learn (IsolationForest), numpy, pandas | CPU is fine; GPU not required |
| LLM triage | Anthropic API (`claude-sonnet-4-6`) | key via env var, never committed. Abstract behind an interface so a local model can be swapped in |
| Blockchain | Solidity 0.8.x + Foundry (Anvil local chain), `web3.py` on the Python side | Anvil for dev/tests; Sepolia testnet optional for demo |
| Frontend | React + Vite + TypeScript, Tailwind, shadcn/ui, Recharts | keep to ~6 screens; no state library beyond React Query |
| Infra | Docker Compose (dev), GitHub Actions (CI) | one `docker compose up` must bring up everything |
| Tests | pytest + pytest-asyncio + httpx, Foundry `forge test` for contracts | |

---

## 2. Repository layout

```
vigil/
├── PLAN.md                 # this file
├── CLAUDE.md               # short: how to run, test, lint (write in Phase 0)
├── docker-compose.yml
├── .env.example
├── agent/                  # observer agent
│   ├── vigil_agent/
│   │   ├── collector.py    # psutil sampling
│   │   ├── transport.py    # HTTP client, retry/backoff, local buffer on failure
│   │   └── main.py
│   ├── Dockerfile
│   └── tests/
├── orchestrator/
│   ├── vigil/
│   │   ├── api/            # FastAPI routers
│   │   ├── core/           # config, auth, logging
│   │   ├── db/             # models, session, migrations (alembic/)
│   │   ├── ingest/         # validation + Timescale insert + Redis publish
│   │   ├── rules/          # static threshold engine (Sentinel parity)
│   │   ├── ml/             # feature builder, IsolationForest train/infer, eval harness
│   │   ├── triage/         # LLM incident triage, runbook retrieval
│   │   ├── ledger/         # event hashing, Merkle batching, chain anchoring, verifier
│   │   └── ws/             # WebSocket broadcast
│   ├── tests/
│   └── Dockerfile
├── contracts/              # Foundry project
│   ├── src/IncidentAnchor.sol
│   ├── test/IncidentAnchor.t.sol
│   └── script/Deploy.s.sol
├── frontend/
├── runbooks/               # markdown runbooks used by triage RAG
├── scripts/                # seed data, load generator, chaos scripts
└── docs/                   # architecture.md, adr/ (architecture decision records)
```

---

## 3. Data model

### 3.1 Tables

**observers**
- `id UUID PK`, `name TEXT UNIQUE`, `api_key_hash TEXT` (argon2), `labels JSONB`, `created_at`, `last_heartbeat TIMESTAMPTZ`, `status ENUM(online, offline, unknown)`

**metrics** — TimescaleDB hypertable, partitioned on `ts`
- `ts TIMESTAMPTZ`, `observer_id UUID`, `cpu_pct REAL`, `mem_pct REAL`, `disk_pct REAL`, `net_rx_bps BIGINT`, `net_tx_bps BIGINT`, `load1 REAL`, `extra JSONB`
- Continuous aggregate: `metrics_1m` (avg/max per minute per observer). Retention policy: raw 7 days, 1m aggregate 90 days.

**alert_rules**
- `id`, `name`, `metric TEXT`, `op ENUM(gt, lt, gte, lte)`, `threshold REAL`, `for_seconds INT`, `severity ENUM(info, warning, critical)`, `enabled BOOL`, `observer_selector JSONB` (label match, null = all)

**alerts**
- `id`, `observer_id`, `rule_id NULLABLE` (null when raised by ML), `source ENUM(rule, anomaly)`, `severity`, `state ENUM(firing, acknowledged, resolved)`, `fired_at`, `acked_at`, `resolved_at`, `summary TEXT`, `anomaly_score REAL NULLABLE`
- **Invariant (Sentinel parity):** partial unique index on `(observer_id, rule_id) WHERE state != 'resolved'` — one active alert per observer+rule. For anomaly alerts use `(observer_id, source) WHERE source='anomaly' AND state != 'resolved'`.

**alert_events** — append-only lifecycle log, the thing the ledger protects
- `id BIGSERIAL`, `alert_id`, `event_type ENUM(fired, acked, resolved, triaged, escalated)`, `payload JSONB`, `created_at`, `event_hash BYTEA` (sha256 of canonical JSON of the row minus hash), `prev_hash BYTEA` (hash chain within the table), `batch_id NULLABLE`

**ledger_batches**
- `id`, `merkle_root BYTEA`, `first_event_id`, `last_event_id`, `tx_hash TEXT NULLABLE`, `chain_id INT`, `block_number BIGINT NULLABLE`, `anchored_at TIMESTAMPTZ NULLABLE`, `status ENUM(pending, anchored, failed)`

**triage_results**
- `id`, `alert_id`, `model TEXT`, `hypothesis TEXT`, `suggested_runbook TEXT`, `confidence REAL`, `raw_response JSONB`, `created_at`

**ml_models**
- `id`, `observer_id NULLABLE` (null = global), `algo TEXT`, `trained_at`, `window_hours INT`, `artifact_path TEXT`, `metrics JSONB` (precision/recall on labelled eval set)

### 3.2 Auth
- Agents: `Authorization: Bearer <api_key>` → argon2 verify against `observers.api_key_hash`. Key shown once at observer creation.
- Dashboard/admin: single admin JWT (username/password from env). No user management needed for v1.

---

## 4. API surface (orchestrator)

```
POST   /v1/observers                  admin   create observer, returns api_key once
GET    /v1/observers                  admin
GET    /v1/observers/{id}             admin
DELETE /v1/observers/{id}             admin

POST   /v1/ingest/metrics             agent   batch of samples (array, max 100)
POST   /v1/ingest/heartbeat           agent

GET    /v1/metrics?observer_id&from&to&step   admin   reads from metrics_1m aggregate

GET    /v1/rules  POST /v1/rules  PATCH /v1/rules/{id}  DELETE /v1/rules/{id}

GET    /v1/alerts?state&severity&observer_id
POST   /v1/alerts/{id}/ack
GET    /v1/alerts/{id}/events
POST   /v1/alerts/{id}/triage         admin   trigger LLM triage (also auto-runs on critical)

GET    /v1/ledger/batches
GET    /v1/ledger/verify/{alert_id}   public  returns Merkle proof + on-chain root + verified: bool
POST   /v1/ledger/anchor              admin   force-anchor pending events now

GET    /v1/ml/models
POST   /v1/ml/train?observer_id       admin   (async job)
GET    /v1/ml/eval                    admin   latest eval report

WS     /v1/ws/live                    admin   stream: metric samples, alert state changes, ledger anchors
GET    /healthz  /readyz  /metrics (Prometheus format — bonus)
```

---

## 5. Phases

### Phase 0 — Skeleton (≈ 1 day)
- Init repo, `uv` project for `orchestrator/` and `agent/`, Foundry init for `contracts/`, Vite init for `frontend/`.
- `docker-compose.yml`: `timescaledb`, `redis`, `anvil`, `orchestrator`, `frontend`, and a sample `agent` service pointed at the orchestrator.
- Alembic baseline with all tables from §3. Enable Timescale extension + hypertable in migration.
- `CLAUDE.md` with run/test/lint commands. Pre-commit with ruff + mypy.
- GitHub Actions: lint + pytest + forge test on every PR.

**Done when:** `docker compose up` starts all containers healthy; `GET /healthz` returns 200; `pytest` runs (even if 1 test); `forge test` runs.

### Phase 1 — Sentinel parity (≈ 3 days)
Reproduce everything Sentinel does, cleanly.
- Agent: sample every 10 s via psutil, batch every 30 s, heartbeat every 15 s, exponential backoff, on-disk ring buffer (last 1000 samples) if orchestrator unreachable, flush on reconnect.
- Ingest: pydantic validation, bulk insert into hypertable, publish to Redis channel `metrics:{observer_id}`.
- Heartbeat watchdog: background task every 10 s marks observers `offline` if `now - last_heartbeat > 45 s`; raises a synthetic `observer_down` alert; resolves on next heartbeat.
- Rules engine: on each ingest, evaluate enabled rules matching the observer. Implement `for_seconds` correctly — a rule fires only if the condition has held continuously over that window (query `metrics_1m`, or keep a Redis-backed sliding state per observer+rule). Dedupe via the partial unique index; on conflict update `alerts.summary`, do not insert. Auto-resolve when condition clears.
- Every alert state change writes an `alert_events` row with `event_hash` and `prev_hash` (hash chain).
- WebSocket fan-out from Redis pub/sub.
- Tests: rules engine unit tests (boundary values, `for_seconds` edge cases, dedupe under concurrent ingest), ingest integration tests against a real Timescale container (testcontainers-python).

**Done when:** two agents in compose show as online; `scripts/load_gen.py` can push a CPU spike and an alert fires, then resolves; alert events form a valid hash chain (add `scripts/verify_chain.py`).

### Phase 2 — ML anomaly detection (≈ 3 days)
- Feature builder: per observer, from `metrics_1m`, features = [cpu, mem, disk, net_rx, net_tx, load1] + rolling mean/std (5m, 30m) + hour-of-day (sin/cos) + day-of-week.
- Model: `IsolationForest` per observer (fall back to global model when < 24 h of data). Train on last 7 days. Persist with joblib to `artifact_path`.
- Inference: run on each new 1-minute aggregate (background task on Redis stream). Score < threshold → raise `source='anomaly'` alert with `anomaly_score`; auto-resolve after N consecutive normal minutes.
- Threshold selection: pick contamination/score cutoff by evaluating on a labelled synthetic set — `scripts/synth_data.py` generates realistic baseline (diurnal pattern + noise) with injected incidents (CPU runaway, memory leak ramp, disk fill, network flood) and ground-truth labels.
- **Eval harness** (`vigil/ml/eval.py`): precision, recall, F1, mean detection delay in minutes, false alarms per day. Store in `ml_models.metrics`. Compare against static rules on the same synthetic set — this comparison table goes in the README.
- Nightly retrain job (APScheduler in-process; no Celery).

**Done when:** on synthetic set, anomaly model detects the memory-leak ramp ≥ 10 min earlier than any reasonable static threshold; eval report reproducible with one command.

### Phase 3 — LLM incident triage (≈ 2 days)
- `runbooks/` — 6–8 markdown runbooks (high CPU, memory leak, disk full, network saturation, host down, noisy neighbour, etc.). Chunk + embed with a small local model (`sentence-transformers/all-MiniLM-L6-v2`), store vectors in Postgres via `pgvector`.
- Triage flow on critical alert (or manual trigger): build context = alert summary + last 30 min of metrics for that observer (downsampled table) + other active alerts on same host + top-3 runbook chunks by similarity. Prompt Claude for structured JSON: `{hypothesis, confidence, suggested_runbook, next_steps[]}`. Validate with pydantic; store in `triage_results`; write a `triaged` alert_event.
- Guardrails: hard token cap, timeout 20 s, one triage per alert per 10 min, graceful degradation if API key missing (feature disabled, not crashed).
- `LLMProvider` interface with `AnthropicProvider` and `NullProvider`; leave a stub for `OllamaProvider`.

**Done when:** a synthetic memory-leak incident produces a triage result that names the memory-leak runbook with confidence > 0.7, fully covered by a test using a recorded/mocked LLM response.

### Phase 4 — Blockchain incident ledger (≈ 3 days)
Purpose: an auditor (or an SLA counterparty) can verify that the incident history was not edited after the fact. Keep it honest — the chain stores only 32-byte roots, never metrics.

- `contracts/src/IncidentAnchor.sol`:
  - `anchor(bytes32 root, uint64 firstEventId, uint64 lastEventId)` — `onlyOwner`, emits `Anchored(uint256 batchId, bytes32 root, uint64 first, uint64 last, uint256 timestamp)`.
  - `getBatch(uint256 id)` view; `batchCount()` view.
  - Ownable; no upgradeability for v1.
  - Foundry tests: anchoring, event emission, access control, sequential ids.
- Python side (`vigil/ledger/`):
  - Batcher: every 5 min (or every 500 events, whichever first) collect `alert_events` with `batch_id IS NULL`, build a Merkle tree over `event_hash` (sorted-pair sha256), store `ledger_batches` row as `pending`.
  - Anchorer: submit `anchor(...)` via web3.py to Anvil (dev) or Sepolia (demo, key from env). Retry with backoff; on receipt, set `tx_hash`, `block_number`, `status=anchored`.
  - Verifier: `GET /v1/ledger/verify/{alert_id}` → for each event of that alert, recompute hash from the DB row, compute Merkle proof, read the root from chain, return `{event_id, local_hash, proof[], on_chain_root, valid}`. Also expose a standalone CLI `scripts/verify_offline.py` that works with only a DB dump + RPC URL, to prove independence from the orchestrator.
  - Tamper demo: `scripts/tamper.py` edits one `alert_events.payload` row directly in SQL; verifier must then return `valid: false` for exactly that event. This is the demo moment — make it visible in the dashboard.
- Chain integration is optional at runtime: if `LEDGER_ENABLED=false`, hash chain still works, anchoring is skipped.

**Done when:** compose brings up Anvil with the contract auto-deployed (`script/Deploy.s.sol` run in an init container); anchors happen automatically; tamper script flips verification to invalid; `forge test` and Python ledger tests green.

### Phase 5 — Frontend (≈ 3 days, keep scope tight)
Screens, in priority order:
1. **Fleet overview** — observer cards (status, last heartbeat, sparkline), live via WS.
2. **Observer detail** — Recharts time-series for the 6 metrics, selectable range, anomaly score overlay, alert markers on the chart.
3. **Alerts** — table with state filter, ack button, expand → events timeline + triage card.
4. **Rules** — CRUD form.
5. **Ledger** — batches list with tx hash link (Etherscan for Sepolia / local explorer note for Anvil), per-alert "Verify integrity" button showing green/red per event.
6. **ML** — model list + eval report (precision/recall table, rules-vs-ML comparison).

Use shadcn/ui components as-is; do not hand-roll UI primitives. Dark theme default. Mobile layout not required.

**Done when:** every API endpoint above has a UI path; the tamper demo is visible end-to-end in the browser.

### Phase 6 — Polish for portfolio (≈ 2 days)
- README with: architecture diagram (Mermaid), the rules-vs-ML eval table, the ledger verification flow, a 2-minute demo GIF/video script, "how this differs from a threshold-only monitor" section.
- `docs/adr/` — 5 ADRs: why FastAPI over Go, why IsolationForest first, why Merkle-root anchoring instead of writing events on-chain, why pgvector over a separate vector DB, why no Celery.
- Load test: `scripts/load_gen.py --observers 200 --rate 10s`; record p95 ingest latency in README.
- Optional: deploy orchestrator + frontend to a small VPS, agents on 2 free-tier VMs, contract on Sepolia.

---

## 6. Non-goals (v1)
- Multi-tenant users/RBAC
- Log or trace collection (metrics only)
- Kubernetes operator
- Storing any metric data on-chain
- Training deep models (LSTM/transformer) — IsolationForest first; note as future work

---

## 7. Rules for Claude Code while implementing
- Never copy code from the reference repo. Architecture inspiration only.
- Every new module gets tests in the same PR. Rules engine and ledger require ≥ 90% coverage.
- Async DB access only; no blocking calls in request handlers (ML inference and LLM calls go to background tasks).
- Secrets only via env; `.env.example` lists every variable with a comment.
- Keep commits small and conventional (`feat(ledger): merkle batcher`).
- Update `CLAUDE.md` whenever a run/test command changes.
- When a phase is complete, append a short "Phase N status" entry at the bottom of this file with what was skipped and why.

---

## 8. Phase status log

### Phase 0 — Skeleton ✅ (2026-09-17)
Done: repo layout, uv projects, compose (timescaledb-ha/redis/anvil/deploy/orchestrator/2 agents/frontend), alembic baseline (extensions + hypertable + `metrics_1m` cagg + retention), CLAUDE.md, GitHub Actions CI (python lint+tests w/ services, forge, frontend build).
Deviations: **host port 5433** for TimescaleDB (5432 occupied by a host Postgres on the dev machine); DB image is `timescale/timescaledb-ha:pg16` because it ships pgvector too; no pre-commit hooks (CI runs ruff+mypy instead — add pre-commit if wanted).

### Phase 1 — Sentinel parity ✅ (2026-09-17)
Done: agent (10s sample / 30s batch / 15s heartbeat, exponential backoff, persistent 1000-sample ring buffer, dev self-registration via admin bootstrap), pydantic ingest → hypertable + Redis publish, watchdog (>45s → offline + synthetic alert, resolves on heartbeat), rules engine (`for_seconds` via Redis first-breach state incl. reset-on-dip, dedupe via partial unique indexes with xmax insert-detection, auto-resolve), hash-chained `alert_events` (pg advisory lock serialises appends), WS fan-out, `scripts/load_gen.py` + `scripts/verify_chain.py`. 17 endpoint integration tests + rules/hash unit tests.
Deviations: `alerts.source` enum gained a `watchdog` value (cleaner than NULL-rule_id dedupe games for observer_down); added `POST /v1/observers/{id}/rotate_key` (needed by agent bootstrap, useful anyway).

### Phase 2 — ML anomaly detection ✅ (2026-09-17)
Done: feature builder (raw + rolling means 5/30m + hod/dow sin-cos), per-observer IsolationForest w/ global fallback, joblib artifacts, per-minute inference on `metrics_1m` (real-time cagg), synth generator w/ 4 labelled incident types, eval harness (precision/recall/F1/delay/false-alarms + rules-vs-ML table), nightly APScheduler retrain, `POST /v1/ml/train` + `GET /v1/ml/eval`.
Deviations (evidence-driven, see ADR 0002): rolling **std** features dropped (measured ~2x worse detection delay); threshold is **calibrated per model** (p0.5 of train scores) instead of a fixed env value; firing requires 3 consecutive anomalous minutes. Result: 4/4 incidents, memory-leak ramp caught ≥10 min earlier than static rules (test-enforced; measured ≈170 min).

### Phase 3 — LLM triage ✅ (2026-09-17)
Done: 7 runbooks, heading-based chunking, pgvector storage, triage flow (alert + 30 min metrics + co-alerts + top-3 chunks → structured JSON w/ pydantic validation), `triaged` events, auto-triage worker for criticals, cooldown/timeout/token guardrails, graceful NullProvider when keyless, OllamaProvider stub. Provider tests use recorded Gemini fixtures.
Deviations (per owner): **LLM is Google Gemini free tier** (REST via httpx, `GEMINI_API_KEY` from AI Studio) instead of Anthropic; embeddings are Gemini `gemini-embedding-001` @768 dims with a deterministic local hashing embedder as offline fallback instead of sentence-transformers (avoids a ~2 GB torch dependency; chunks record their embedder so spaces never mix).

### Phase 4 — Blockchain ledger ✅ (2026-09-17)
Done: `IncidentAnchor.sol` (onlyOwner anchor, sequential ids, monotonic ranges, 9 forge tests), compose init-container deploy to Anvil (deterministic address), Merkle batcher (5 min/500 events), web3.py anchorer w/ retry + failed-status, per-event verifier endpoint (public), `verify_offline.py` (DB+RPC only), `tamper.py` (+ `--restore`), `LEDGER_ENABLED=false` degrades to hash-chain only.
Deviations: `ledger_batches.chain_batch_id` column added (maps DB batch → on-chain batch id from the `Anchored` event); Deploy script is forge-std-free so the init container needs no `forge install`.

### Phase 5 — Frontend ✅ (2026-09-17)
Done: all 6 screens (fleet cards w/ sparklines + live WS, observer detail w/ 6 small-multiple charts + range picker + alert markers + anomaly banner, alerts w/ filter/ack/timeline/triage card/per-event verify strip, rules CRUD, ledger table w/ tx links (Etherscan for Sepolia, Anvil-noted locally) + force-anchor, ML models + rules-vs-ML eval table). React Query + WS-driven cache invalidation; nginx serves + proxies in docker.
Deviations: **no shadcn/ui** — its CLI is interactive and heavy for this scope; small hand-rolled component set (Card/badges/buttons) with Tailwind v4 and the validated dataviz palette (dark-first). Recharts per plan.

### Phase 6 — Polish ✅ (2026-09-17)
Done: README (arch diagram, tamper demo, rules-vs-ML table, differentiation section), docs/architecture.md (mermaid + ledger trust model), 5 ADRs, seed/load/verify scripts. Load test run: 50 observers @ 10s → ingest p50 86ms / p95 93ms / p99 112ms (argon2 per-request verify dominates). Agent image 87 MB vs the 80 MB target — python:3.12-alpine alone is ~78 MB now; going lower means distroless surgery, skipped. VPS/Sepolia deploy left optional; demo GIF not recordable from this environment — the script for it is README's tamper-demo section.

### End-to-end verification (2026-09-17, full compose stack)
`docker compose up -d --build`: 8 services healthy; both agents self-registered and online; frontend 200. Spike demo: rule fired after hold, deduped, auto-resolved. Watchdog fired observer_down for a stale host and resolved on heartbeat. Ledger: 2 batches auto/force-anchored on Anvil; `verify_chain` + `verify_offline` VALID; `tamper.py` → both verifiers flag exactly the edited event → `--restore` → VALID. WS `/v1/ws/live` streams metric events. Test totals: orchestrator 66 (unit+integration), agent 5, forge 9 — all green; ruff+mypy clean.

