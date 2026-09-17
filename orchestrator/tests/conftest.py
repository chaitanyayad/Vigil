import asyncio
import socket

import pytest

from vigil.core.config import get_settings


def _tcp_up(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def infra_available() -> bool:
    return _tcp_up("localhost", 5433) and _tcp_up("localhost", 6379)


requires_infra = pytest.mark.skipif(
    not infra_available(),
    reason="needs TimescaleDB+Redis: docker compose up -d timescaledb redis",
)


@pytest.fixture(scope="session")
def migrated_db():
    """Run alembic migrations once against the compose database."""
    if not infra_available():
        pytest.skip("infra not available")
    from alembic.config import Config

    from alembic import command

    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_db(migrated_db):
    """Fresh engine/redis per test (per event loop) + truncated tables."""
    from sqlalchemy import text

    from vigil.db.session import dispose_engine, get_sessionmaker
    from vigil.ws.bus import close_redis, get_redis

    async with get_sessionmaker()() as db:
        await db.execute(
            text(
                "TRUNCATE alert_events, triage_results, alerts, alert_rules, metrics, "
                "ml_models, ledger_batches, observers, runbook_chunks RESTART IDENTITY CASCADE"
            )
        )
        await db.commit()
    redis = get_redis()
    await redis.flushdb()
    yield
    await close_redis()
    await dispose_engine()


@pytest.fixture
async def client(clean_db):
    """ASGI test client over the real app (workers disabled)."""
    import httpx

    from vigil.main import create_app

    app = create_app(enable_workers=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_headers(client):
    s = get_settings()
    r = await client.post(
        "/v1/auth/login", json={"username": s.admin_username, "password": s.admin_password}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def observer(client, admin_headers):
    r = await client.post(
        "/v1/observers",
        json={"name": "test-host", "labels": {"env": "test"}},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()  # includes api_key


def agent_headers(observer: dict) -> dict:
    return {"Authorization": f"Bearer {observer['api_key']}"}


async def wait_until(predicate, timeout=5.0, interval=0.1):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False
