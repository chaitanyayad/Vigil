"""Synthetic labelled dataset for threshold selection and the eval harness.

Baseline: diurnal CPU/net pattern + gaussian noise + slow disk growth.
Injected incidents (with ground-truth label windows):
  cpu_runaway  — CPU pinned near 100%
  memory_leak  — slow memory ramp toward 100% (the classic "static thresholds
                 catch it late" case)
  disk_fill    — disk usage jumps then keeps climbing
  net_flood    — rx/tx explode by 2 orders of magnitude
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd


@dataclass
class Incident:
    kind: str
    start_min: int
    duration_min: int
    meta: dict = field(default_factory=dict)


DEFAULT_INCIDENTS = [
    Incident("cpu_runaway", start_min=1500, duration_min=45),
    Incident("memory_leak", start_min=3200, duration_min=240),
    Incident("disk_fill", start_min=5200, duration_min=120),
    Incident("net_flood", start_min=6800, duration_min=30),
]


def generate(
    days: int = 6,
    seed: int = 42,
    incidents: list[Incident] | None = None,
    start: datetime | None = None,
) -> tuple[pd.DataFrame, np.ndarray, list[Incident]]:
    """Returns (df with 1-min samples, labels[0/1], incidents)."""
    rng = np.random.default_rng(seed)
    n = days * 24 * 60
    start = start or (datetime.now(UTC) - timedelta(minutes=n))
    ts = pd.date_range(start, periods=n, freq="1min", tz=UTC)
    minutes = np.arange(n)
    hod = (minutes % 1440) / 1440.0

    # Diurnal load: busy days, quiet nights
    diurnal = 0.5 - 0.5 * np.cos(2 * np.pi * hod)
    cpu = 18 + 30 * diurnal + rng.normal(0, 4, n)
    mem = 42 + 8 * diurnal + rng.normal(0, 2, n)
    disk = 55 + minutes * (2.0 / n) + rng.normal(0, 0.15, n)  # slow organic growth
    net_rx = (1.5e6 + 6e6 * diurnal) * rng.lognormal(0, 0.25, n)
    net_tx = (0.8e6 + 3e6 * diurnal) * rng.lognormal(0, 0.25, n)
    load1 = 0.6 + 2.2 * diurnal + rng.normal(0, 0.25, n)

    labels = np.zeros(n, dtype=int)
    incidents = incidents if incidents is not None else list(DEFAULT_INCIDENTS)
    for inc in incidents:
        s, e = inc.start_min, min(inc.start_min + inc.duration_min, n)
        length = e - s
        if length <= 0:
            continue
        labels[s:e] = 1
        if inc.kind == "cpu_runaway":
            cpu[s:e] = np.clip(92 + rng.normal(0, 3, length), 0, 100)
            load1[s:e] += 6
        elif inc.kind == "memory_leak":
            # Ramp from baseline to ~97% over the incident — anomalous long
            # before it crosses any sane static threshold.
            ramp = np.linspace(0, 50, length)
            mem[s:e] = np.clip(mem[s:e] + ramp, 0, 99)
        elif inc.kind == "disk_fill":
            ramp = np.linspace(8, 35, length)
            disk[s:e] = np.clip(disk[s:e] + ramp, 0, 100)
        elif inc.kind == "net_flood":
            net_rx[s:e] *= 80
            net_tx[s:e] *= 60
            cpu[s:e] = np.clip(cpu[s:e] + 15, 0, 100)

    df = pd.DataFrame(
        {
            "ts": ts,
            "cpu_pct": np.clip(cpu, 0, 100),
            "mem_pct": np.clip(mem, 0, 100),
            "disk_pct": np.clip(disk, 0, 100),
            "net_rx_bps": np.maximum(net_rx, 0).astype(np.int64),
            "net_tx_bps": np.maximum(net_tx, 0).astype(np.int64),
            "load1": np.maximum(load1, 0),
        }
    )
    return df, labels, incidents
