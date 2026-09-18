# VIGIL — dev commands

AI-assisted infra monitoring with a tamper-evident incident ledger.
Stack: FastAPI + TimescaleDB + Redis + scikit-learn + Gemini (free tier) + Solidity/Anvil + React.
See PLAN.md for the full spec and phase log.

## Run everything

```bash
docker compose up -d --build       # db, redis, anvil, contract deploy, orchestrator, 2 agents, frontend
# API:      http://localhost:8000/docs
# Frontend: http://localhost:5173  (login admin / change-me)
```

Set `GEMINI_API_KEY` in `.env` (free key: https://aistudio.google.com/apikey) to enable LLM triage.

## Orchestrator (Python 3.12, uv)

```bash
cd orchestrator
uv sync                                      # or: python -m uv sync
.venv/Scripts/alembic upgrade head           # needs timescaledb+redis containers up
.venv/Scripts/uvicorn vigil.main:app --reload
```

## Tests

```bash
cd orchestrator
.venv/Scripts/python -m pytest tests -q --ignore=tests/test_api_integration.py   # unit, no infra
docker compose up -d timescaledb redis
.venv/Scripts/python -m pytest tests -q                                          # + endpoint integration
cd ../agent && .venv/Scripts/python -m pytest tests -q

# contracts (Foundry via docker; installs forge-std into contracts/lib once)
docker run --rm -v "$PWD/contracts:/c" -w /c --entrypoint sh ghcr.io/foundry-rs/foundry:stable \
  -c "forge install foundry-rs/forge-std --no-git 2>/dev/null; forge test -vv"
```

## Lint / typecheck

```bash
cd orchestrator
.venv/Scripts/python -m ruff check vigil tests
.venv/Scripts/python -m mypy vigil
```

## Demo scripts (run with orchestrator venv, stack up)

```bash
python scripts/seed_rules.py                                  # default ruleset
python scripts/load_gen.py --observers 2 --minutes 3 --spike-after 30   # CPU spike -> alert fires+resolves
python scripts/verify_chain.py                                # hash-chain audit
python scripts/tamper.py && python scripts/verify_chain.py    # tamper demo (then --restore)
python scripts/verify_offline.py                              # independent on-chain audit
python -m vigil.ml.eval                                       # rules-vs-ML eval table (from orchestrator/)
```

## Conventions
- Conventional commits (`feat(ledger): merkle batcher`).
- Async DB access only in request handlers; ML/LLM work goes to background tasks.
- Secrets only via env; every variable documented in `.env.example`.
- Every alert state change must go through `vigil/rules/lifecycle.py` (hash chain + WS bus).
