"""Seed a sensible default ruleset via the API.

    python scripts/seed_rules.py [--base-url http://localhost:8000]
"""

import argparse

import httpx

RULES = [
    {"name": "cpu-high", "metric": "cpu_pct", "op": "gt", "threshold": 85, "for_seconds": 300,
     "severity": "critical"},
    {"name": "cpu-warn", "metric": "cpu_pct", "op": "gt", "threshold": 70, "for_seconds": 600,
     "severity": "warning"},
    {"name": "mem-high", "metric": "mem_pct", "op": "gt", "threshold": 90, "for_seconds": 300,
     "severity": "critical"},
    {"name": "disk-high", "metric": "disk_pct", "op": "gt", "threshold": 90, "for_seconds": 60,
     "severity": "critical"},
    {"name": "net-rx-flood", "metric": "net_rx_bps", "op": "gt", "threshold": 100_000_000,
     "for_seconds": 120, "severity": "warning"},
    {"name": "load-high", "metric": "load1", "op": "gt", "threshold": 8, "for_seconds": 300,
     "severity": "warning"},
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--admin-user", default="admin")
    p.add_argument("--admin-pass", default="change-me")
    args = p.parse_args()

    with httpx.Client(timeout=10.0) as client:
        token = client.post(
            f"{args.base_url}/v1/auth/login",
            json={"username": args.admin_user, "password": args.admin_pass},
        ).raise_for_status().json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for rule in RULES:
            r = client.post(f"{args.base_url}/v1/rules", json=rule, headers=headers)
            if r.status_code == 201:
                print(f"created {rule['name']}")
            elif r.status_code == 409:
                print(f"exists  {rule['name']}")
            else:
                print(f"error   {rule['name']}: {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    main()
