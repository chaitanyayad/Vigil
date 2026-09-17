"""Load generator + demo driver.

Registers N synthetic observers and pushes realistic metrics at a fixed rate.
Can inject a CPU spike on one observer to trip a rule, then let it recover.
Records ingest latency and prints p50/p95/p99 at the end.

Usage (from orchestrator/ venv):
    python ../scripts/load_gen.py --observers 5 --minutes 3
    python ../scripts/load_gen.py --observers 1 --minutes 3 --spike-after 30 --spike-seconds 90
    python ../scripts/load_gen.py --observers 200 --rate 10 --minutes 5   # load test
"""

import argparse
import math
import random
import statistics
import sys
import time
from datetime import UTC, datetime

import httpx


def admin_token(client: httpx.Client, base: str, user: str, password: str) -> str:
    r = client.post(f"{base}/v1/auth/login", json={"username": user, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def make_observers(client, base, token, n) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    out = []
    existing = {o["name"]: o for o in client.get(f"{base}/v1/observers", headers=headers).json()}
    for i in range(n):
        name = f"loadgen-{i:03d}"
        if name in existing:
            r = client.post(
                f"{base}/v1/observers/{existing[name]['id']}/rotate_key", headers=headers
            )
        else:
            r = client.post(
                f"{base}/v1/observers",
                json={"name": name, "labels": {"env": "loadtest"}},
                headers=headers,
            )
        r.raise_for_status()
        out.append(r.json())
    return out


def sample(t: float, spiking: bool) -> dict:
    hod = (t % 86400) / 86400
    diurnal = 0.5 - 0.5 * math.cos(2 * math.pi * hod)
    cpu = min(100, 20 + 30 * diurnal + random.gauss(0, 4))
    if spiking:
        cpu = min(100.0, 92 + random.gauss(0, 3))
    return {
        "ts": datetime.now(UTC).isoformat(),
        "cpu_pct": round(max(0, cpu), 2),
        "mem_pct": round(min(100, max(0, 45 + 8 * diurnal + random.gauss(0, 2))), 2),
        "disk_pct": round(min(100, 55 + random.gauss(0, 0.2)), 2),
        "net_rx_bps": max(0, int((2e6 + 5e6 * diurnal) * random.lognormvariate(0, 0.2))),
        "net_tx_bps": max(0, int((1e6 + 2e6 * diurnal) * random.lognormvariate(0, 0.2))),
        "load1": round(max(0, 0.7 + 2 * diurnal + random.gauss(0, 0.2)), 2),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--admin-user", default="admin")
    p.add_argument("--admin-pass", default="change-me")
    p.add_argument("--observers", type=int, default=2)
    p.add_argument("--rate", type=float, default=10.0, help="seconds between batches per observer")
    p.add_argument("--minutes", type=float, default=2.0)
    p.add_argument("--spike-after", type=float, default=None,
                   help="seconds until loadgen-000 starts a CPU spike")
    p.add_argument("--spike-seconds", type=float, default=90.0)
    args = p.parse_args()

    latencies: list[float] = []
    with httpx.Client(timeout=15.0) as client:
        token = admin_token(client, args.base_url, args.admin_user, args.admin_pass)
        observers = make_observers(client, args.base_url, token, args.observers)
        print(f"registered {len(observers)} observers")

        start = time.time()
        deadline = start + args.minutes * 60
        next_send = {o["name"]: start for o in observers}
        while time.time() < deadline:
            now = time.time()
            for obs in observers:
                if now < next_send[obs["name"]]:
                    continue
                next_send[obs["name"]] = now + args.rate
                spiking = (
                    args.spike_after is not None
                    and obs["name"] == "loadgen-000"
                    and args.spike_after <= (now - start) <= args.spike_after + args.spike_seconds
                )
                body = {"samples": [sample(now, spiking)]}
                t0 = time.perf_counter()
                r = client.post(
                    f"{args.base_url}/v1/ingest/metrics",
                    json=body,
                    headers={"Authorization": f"Bearer {obs['api_key']}"},
                )
                latencies.append(time.perf_counter() - t0)
                if r.status_code != 200:
                    print(f"ingest error {r.status_code}: {r.text[:200]}", file=sys.stderr)
                # keep the observer "online"
                client.post(
                    f"{args.base_url}/v1/ingest/heartbeat",
                    headers={"Authorization": f"Bearer {obs['api_key']}"},
                )
            time.sleep(0.05)

        headers = {"Authorization": f"Bearer {token}"}
        alerts = client.get(f"{args.base_url}/v1/alerts", headers=headers).json()

    lat_ms = sorted(x * 1000 for x in latencies)
    if lat_ms:
        q = statistics.quantiles(lat_ms, n=100)
        print(f"\ningest requests: {len(lat_ms)}")
        print(f"latency p50={q[49]:.1f}ms  p95={q[94]:.1f}ms  p99={q[98]:.1f}ms")
    print(f"alerts now in system: {len(alerts)}")
    for a in alerts[:10]:
        print(f"  [{a['state']:>12}] {a['severity']:<8} {a['summary'][:90]}")


if __name__ == "__main__":
    main()
