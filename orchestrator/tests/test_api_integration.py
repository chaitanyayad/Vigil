"""Endpoint integration tests against real TimescaleDB + Redis (compose).

Covers every REST endpoint plus the rules-engine and hash-chain flows.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import agent_headers, requires_infra
from vigil.db.models import AlertEvent
from vigil.ledger.hashing import verify_chain

pytestmark = requires_infra


def _sample(ts=None, **overrides):
    base = {
        "ts": (ts or datetime.now(UTC)).isoformat(),
        "cpu_pct": 25.0, "mem_pct": 40.0, "disk_pct": 55.0,
        "net_rx_bps": 1_000_000, "net_tx_bps": 500_000, "load1": 0.8,
    }
    base.update(overrides)
    return base


# ---- auth ----

async def test_login_ok_and_bad(client):
    r = await client.post("/v1/auth/login", json={"username": "admin", "password": "change-me"})
    assert r.status_code == 200 and r.json()["access_token"]
    r = await client.post("/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


async def test_admin_endpoints_reject_missing_token(client, clean_db):
    for path in ("/v1/observers", "/v1/rules", "/v1/alerts", "/v1/ledger/batches", "/v1/ml/models"):
        assert (await client.get(path)).status_code in (401, 403), path


# ---- health ----

async def test_healthz_readyz(client):
    assert (await client.get("/healthz")).status_code == 200
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json() == {"db": "ok", "redis": "ok"}


# ---- observers ----

async def test_observer_crud_and_key_rotation(client, admin_headers):
    r = await client.post("/v1/observers", json={"name": "web-1", "labels": {"env": "prod"}},
                          headers=admin_headers)
    assert r.status_code == 201
    created = r.json()
    assert created["api_key"].startswith("vg_")

    # duplicate name -> 409
    r = await client.post("/v1/observers", json={"name": "web-1"}, headers=admin_headers)
    assert r.status_code == 409

    r = await client.get("/v1/observers", headers=admin_headers)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.get(f"/v1/observers/{created['id']}", headers=admin_headers)
    assert r.status_code == 200 and "api_key" not in r.json()

    # old key works, rotated key replaces it
    hb = await client.post("/v1/ingest/heartbeat",
                           headers={"Authorization": f"Bearer {created['api_key']}"})
    assert hb.status_code == 200
    r = await client.post(f"/v1/observers/{created['id']}/rotate_key", headers=admin_headers)
    new_key = r.json()["api_key"]
    assert (await client.post("/v1/ingest/heartbeat",
                              headers={"Authorization": f"Bearer {created['api_key']}"})).status_code == 401
    assert (await client.post("/v1/ingest/heartbeat",
                              headers={"Authorization": f"Bearer {new_key}"})).status_code == 200

    assert (await client.delete(f"/v1/observers/{created['id']}", headers=admin_headers)).status_code == 204
    assert (await client.get(f"/v1/observers/{created['id']}", headers=admin_headers)).status_code == 404


# ---- ingest + metrics ----

async def test_ingest_and_query_metrics(client, admin_headers, observer):
    now = datetime.now(UTC)
    samples = [_sample(ts=now - timedelta(seconds=10 * i), cpu_pct=30 + i) for i in range(6)]
    r = await client.post("/v1/ingest/metrics", json={"samples": samples},
                          headers=agent_headers(observer))
    assert r.status_code == 200 and r.json()["accepted"] == 6

    # duplicate resend is idempotent, not an error
    r = await client.post("/v1/ingest/metrics", json={"samples": samples},
                          headers=agent_headers(observer))
    assert r.status_code == 200

    r = await client.get(
        "/v1/metrics",
        params={"observer_id": observer["id"], "step": 60},
        headers=admin_headers,
    )
    assert r.status_code == 200
    points = r.json()["points"]
    assert points and any(p["cpu_pct"] and p["cpu_pct"] > 0 for p in points)


async def test_ingest_validation(client, observer):
    bad = _sample(cpu_pct=150.0)  # out of range
    r = await client.post("/v1/ingest/metrics", json={"samples": [bad]},
                          headers=agent_headers(observer))
    assert r.status_code == 422
    r = await client.post("/v1/ingest/metrics",
                          json={"samples": [_sample()] * 101}, headers=agent_headers(observer))
    assert r.status_code == 422  # max 100 per batch
    r = await client.post("/v1/ingest/metrics", json={"samples": [_sample()]},
                          headers={"Authorization": "Bearer vg_nope_nope"})
    assert r.status_code == 401


async def test_heartbeat_marks_online(client, admin_headers, observer):
    await client.post("/v1/ingest/heartbeat", headers=agent_headers(observer))
    r = await client.get(f"/v1/observers/{observer['id']}", headers=admin_headers)
    body = r.json()
    assert body["status"] == "online" and body["last_heartbeat"] is not None


# ---- rules CRUD ----

async def test_rules_crud(client, admin_headers):
    rule = {"name": "cpu-crit", "metric": "cpu_pct", "op": "gt", "threshold": 85,
            "for_seconds": 0, "severity": "critical"}
    r = await client.post("/v1/rules", json=rule, headers=admin_headers)
    assert r.status_code == 201
    rule_id = r.json()["id"]
    assert (await client.post("/v1/rules", json=rule, headers=admin_headers)).status_code == 409
    r = await client.post("/v1/rules", json=rule | {"name": "x", "metric": "bogus"},
                          headers=admin_headers)
    assert r.status_code == 422

    r = await client.patch(f"/v1/rules/{rule_id}", json={"threshold": 90.0}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["threshold"] == 90.0
    r = await client.get("/v1/rules", headers=admin_headers)
    assert len(r.json()) == 1
    assert (await client.delete(f"/v1/rules/{rule_id}", headers=admin_headers)).status_code == 204
    assert (await client.patch(f"/v1/rules/{uuid.uuid4()}", json={}, headers=admin_headers)).status_code == 404


# ---- rules engine end-to-end ----

async def _make_rule(client, admin_headers, **overrides):
    rule = {"name": f"r-{uuid.uuid4().hex[:6]}", "metric": "cpu_pct", "op": "gt",
            "threshold": 85, "for_seconds": 0, "severity": "critical"}
    rule.update(overrides)
    r = await client.post("/v1/rules", json=rule, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_alert_fires_dedupes_and_resolves(client, admin_headers, observer, clean_db):
    await _make_rule(client, admin_headers)
    breach = [_sample(cpu_pct=95.0)]

    await client.post("/v1/ingest/metrics", json={"samples": breach}, headers=agent_headers(observer))
    r = await client.get("/v1/alerts", params={"state": "firing"}, headers=admin_headers)
    alerts = r.json()
    assert len(alerts) == 1 and alerts[0]["source"] == "rule"

    # second breach must dedupe (same alert, updated summary), not double-fire
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=97.0)]}, headers=agent_headers(observer))
    r = await client.get("/v1/alerts", headers=admin_headers)
    assert len(r.json()) == 1

    # recovery resolves it
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=20.0)]}, headers=agent_headers(observer))
    r = await client.get("/v1/alerts", params={"state": "resolved"}, headers=admin_headers)
    assert len(r.json()) == 1

    # lifecycle events: fired + resolved, forming a valid hash chain
    alert_id = alerts[0]["id"]
    r = await client.get(f"/v1/alerts/{alert_id}/events", headers=admin_headers)
    types = [e["event_type"] for e in r.json()]
    assert types == ["fired", "resolved"]

    from vigil.db.session import get_sessionmaker
    async with get_sessionmaker()() as db:
        events = list((await db.execute(select(AlertEvent).order_by(AlertEvent.id))).scalars())
        assert verify_chain(events) == []


async def test_for_seconds_requires_continuous_hold(client, admin_headers, observer, clean_db):
    await _make_rule(client, admin_headers, for_seconds=60)
    t0 = datetime.now(UTC) - timedelta(seconds=90)

    # first breaching sample starts the clock — no fire yet
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(ts=t0, cpu_pct=95)]}, headers=agent_headers(observer))
    r = await client.get("/v1/alerts", headers=admin_headers)
    assert r.json() == []

    # a dip resets the clock
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(ts=t0 + timedelta(seconds=30), cpu_pct=50)]},
                      headers=agent_headers(observer))
    # breach again 40s < 60s after reset — still no fire
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(ts=t0 + timedelta(seconds=40), cpu_pct=95)]},
                      headers=agent_headers(observer))
    r = await client.get("/v1/alerts", headers=admin_headers)
    assert r.json() == []

    # held past 60s since the reset breach — fires now
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(ts=t0 + timedelta(seconds=105), cpu_pct=95)]},
                      headers=agent_headers(observer))
    r = await client.get("/v1/alerts", params={"state": "firing"}, headers=admin_headers)
    assert len(r.json()) == 1


async def test_concurrent_ingest_dedupes_single_alert(client, admin_headers, observer, clean_db):
    await _make_rule(client, admin_headers)
    breach = {"samples": [_sample(cpu_pct=99.0)]}
    results = await asyncio.gather(
        *[client.post("/v1/ingest/metrics", json=breach, headers=agent_headers(observer))
          for _ in range(5)]
    )
    assert all(r.status_code == 200 for r in results)
    r = await client.get("/v1/alerts", headers=admin_headers)
    assert len(r.json()) == 1  # partial unique index holds under concurrency


async def test_ack_flow(client, admin_headers, observer, clean_db):
    await _make_rule(client, admin_headers)
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=95)]}, headers=agent_headers(observer))
    alert = (await client.get("/v1/alerts", headers=admin_headers)).json()[0]

    r = await client.post(f"/v1/alerts/{alert['id']}/ack", headers=admin_headers)
    assert r.status_code == 200 and r.json()["state"] == "acknowledged"
    # ack again is a no-op, resolved alerts can't be acked
    r = await client.post(f"/v1/alerts/{alert['id']}/ack", headers=admin_headers)
    assert r.status_code == 200
    assert (await client.post(f"/v1/alerts/{uuid.uuid4()}/ack", headers=admin_headers)).status_code == 404

    events = (await client.get(f"/v1/alerts/{alert['id']}/events", headers=admin_headers)).json()
    assert [e["event_type"] for e in events] == ["fired", "acked"]


# ---- selector matching ----

async def test_rule_selector_scopes_to_labels(client, admin_headers, clean_db):
    await _make_rule(client, admin_headers, observer_selector={"env": "prod"})
    r = await client.post("/v1/observers", json={"name": "dev-host", "labels": {"env": "dev"}},
                          headers=admin_headers)
    dev = r.json()
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=99)]}, headers=agent_headers(dev))
    assert (await client.get("/v1/alerts", headers=admin_headers)).json() == []

    r = await client.post("/v1/observers", json={"name": "prod-host", "labels": {"env": "prod"}},
                          headers=admin_headers)
    prod = r.json()
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=99)]}, headers=agent_headers(prod))
    alerts = (await client.get("/v1/alerts", headers=admin_headers)).json()
    assert len(alerts) == 1 and alerts[0]["observer_id"] == prod["id"]


# ---- ledger ----

async def test_ledger_batch_and_verify_without_chain(client, admin_headers, observer, clean_db, monkeypatch):
    from vigil.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ledger_enabled", False)
    await _make_rule(client, admin_headers)
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=95)]}, headers=agent_headers(observer))
    alert = (await client.get("/v1/alerts", headers=admin_headers)).json()[0]

    # force-batch (anchoring skipped because LEDGER_ENABLED=false)
    r = await client.post("/v1/ledger/anchor", headers=admin_headers)
    assert r.status_code == 200
    batches = (await client.get("/v1/ledger/batches", headers=admin_headers)).json()
    assert len(batches) == 1 and batches[0]["status"] == "pending"
    assert batches[0]["merkle_root"].startswith("0x")

    # verify is public (no auth) and reports pending state, hashes intact
    r = await client.get(f"/v1/ledger/verify/{alert['id']}")
    assert r.status_code == 200
    body = r.json()
    assert all(e["hash_matches_stored"] for e in body["events"])
    assert all(e["valid"] is None for e in body["events"])  # not anchored yet


async def test_tampered_event_detected_in_hash_chain(client, admin_headers, observer, clean_db):
    from sqlalchemy import text as sqltext

    from vigil.db.session import get_sessionmaker

    await _make_rule(client, admin_headers)
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=95)]}, headers=agent_headers(observer))
    alert = (await client.get("/v1/alerts", headers=admin_headers)).json()[0]

    async with get_sessionmaker()() as db:
        await db.execute(sqltext(
            "UPDATE alert_events SET payload = jsonb_set(payload, '{severity}', '\"info\"') "
            "WHERE event_type = 'fired'"
        ))
        await db.commit()

    r = await client.get(f"/v1/ledger/verify/{alert['id']}")
    flags = [e["hash_matches_stored"] for e in r.json()["events"]]
    assert False in flags  # exactly the tampered row fails
    assert flags.count(False) == 1

    async with get_sessionmaker()() as db:
        events = list((await db.execute(select(AlertEvent).order_by(AlertEvent.id))).scalars())
        assert verify_chain(events) != []


# ---- ml ----

async def test_ml_endpoints(client, admin_headers, clean_db):
    r = await client.get("/v1/ml/models", headers=admin_headers)
    assert r.status_code == 200 and r.json() == []
    r = await client.get("/v1/ml/eval", headers=admin_headers)
    assert r.status_code == 200 and r.json()["available"] is False
    r = await client.post("/v1/ml/train", headers=admin_headers)
    assert r.status_code == 202  # background job accepted (no data yet -> no-op)


# ---- triage (disabled without key) ----

async def test_triage_gracefully_disabled_without_key(client, admin_headers, observer, clean_db):
    await _make_rule(client, admin_headers)
    await client.post("/v1/ingest/metrics",
                      json={"samples": [_sample(cpu_pct=95)]}, headers=agent_headers(observer))
    alert = (await client.get("/v1/alerts", headers=admin_headers)).json()[0]
    r = await client.post(f"/v1/alerts/{alert['id']}/triage", headers=admin_headers)
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    r = await client.get(f"/v1/alerts/{alert['id']}/triage", headers=admin_headers)
    assert r.status_code == 200 and r.json() == []
