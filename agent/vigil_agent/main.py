"""VIGIL agent: sample every 10 s, batch-send every 30 s, heartbeat every 15 s.

Dev bootstrap: when no VIGIL_AGENT_API_KEY is provided but admin credentials
are, the agent self-registers (rotating the key if the observer already
exists) and caches the key on disk. In production, provision the key instead.
"""

import logging
import os
import threading
import time
from pathlib import Path

import httpx

from vigil_agent.collector import Collector
from vigil_agent.transport import Transport

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s agent: %(message)s")
log = logging.getLogger(__name__)

SAMPLE_INTERVAL = float(os.environ.get("VIGIL_SAMPLE_INTERVAL", "10"))
BATCH_INTERVAL = float(os.environ.get("VIGIL_BATCH_INTERVAL", "30"))
HEARTBEAT_INTERVAL = float(os.environ.get("VIGIL_HEARTBEAT_INTERVAL", "15"))
STATE_DIR = Path(os.environ.get("VIGIL_STATE_DIR", "/var/lib/vigil-agent"))


def bootstrap_api_key(base_url: str, name: str) -> str:
    key = os.environ.get("VIGIL_AGENT_API_KEY", "")
    if key:
        return key
    key_file = STATE_DIR / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()

    admin_user = os.environ.get("VIGIL_BOOTSTRAP_ADMIN_USERNAME")
    admin_pass = os.environ.get("VIGIL_BOOTSTRAP_ADMIN_PASSWORD")
    if not (admin_user and admin_pass):
        raise SystemExit("Set VIGIL_AGENT_API_KEY, or admin bootstrap credentials for dev")

    with httpx.Client(timeout=10.0) as client:
        for attempt in range(30):
            try:
                token = client.post(
                    f"{base_url}/v1/auth/login",
                    json={"username": admin_user, "password": admin_pass},
                ).raise_for_status().json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                resp = client.post(
                    f"{base_url}/v1/observers",
                    json={"name": name, "labels": {"env": "dev", "bootstrap": "auto"}},
                    headers=headers,
                )
                if resp.status_code == 409:
                    observers = client.get(
                        f"{base_url}/v1/observers", headers=headers
                    ).raise_for_status().json()
                    observer_id = next(o["id"] for o in observers if o["name"] == name)
                    resp = client.post(
                        f"{base_url}/v1/observers/{observer_id}/rotate_key", headers=headers
                    )
                resp.raise_for_status()
                key = resp.json()["api_key"]
                try:
                    STATE_DIR.mkdir(parents=True, exist_ok=True)
                    key_file.write_text(key)
                except OSError:
                    pass
                log.info("bootstrap: registered observer %r", name)
                return key
            except (httpx.HTTPError, StopIteration) as e:
                log.warning("bootstrap attempt %d failed: %s", attempt + 1, e)
                time.sleep(min(30, 2**attempt))
    raise SystemExit("bootstrap failed: orchestrator unreachable")


def heartbeat_loop(transport: Transport, stop: threading.Event) -> None:
    while not stop.is_set():
        transport.send_heartbeat()
        stop.wait(HEARTBEAT_INTERVAL)


def main() -> None:
    base_url = os.environ.get("VIGIL_ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
    import socket

    name = os.environ.get("VIGIL_AGENT_NAME") or socket.gethostname()
    api_key = bootstrap_api_key(base_url, name)
    transport = Transport(base_url, api_key, STATE_DIR / "buffer.json")
    collector = Collector()
    stop = threading.Event()
    hb = threading.Thread(target=heartbeat_loop, args=(transport, stop), daemon=True)
    hb.start()
    log.info("agent %r started (sample %.0fs, batch %.0fs)", name, SAMPLE_INTERVAL, BATCH_INTERVAL)

    pending = []
    last_batch = time.monotonic()
    try:
        while True:
            pending.append(collector.sample())
            now = time.monotonic()
            if now - last_batch >= BATCH_INTERVAL:
                transport.send_metrics(pending)
                pending = []
                last_batch = now
                delay = transport.backoff_seconds()
                if delay:
                    time.sleep(delay)
            time.sleep(SAMPLE_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if pending:
            transport.send_metrics(pending)
        transport.close()


if __name__ == "__main__":
    main()
