"""Feature builder for anomaly detection.

Input: per-observer 1-minute DataFrame with columns
  ts, cpu_pct, mem_pct, disk_pct, net_rx_bps, net_tx_bps, load1
Output: feature matrix = raw values + rolling means (5m, 30m) + time-of-day
(sin/cos) + day-of-week (sin/cos).

Rolling std features were evaluated and dropped: they dilute the signal in
IsolationForest's random splits and cost ~2x detection delay on the synthetic
benchmark (see tests/test_ml.py::test_full_eval_ml_beats_rules_on_memory_leak).
"""

import numpy as np
import pandas as pd

BASE_COLS = ["cpu_pct", "mem_pct", "disk_pct", "net_rx_bps", "net_tx_bps", "load1"]
ROLL_WINDOWS = [5, 30]  # minutes


def feature_columns() -> list[str]:
    cols = list(BASE_COLS)
    for c in BASE_COLS:
        for w in ROLL_WINDOWS:
            cols.append(f"{c}_mean{w}")
    cols += ["hod_sin", "hod_cos", "dow_sin", "dow_cos"]
    return cols


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """df must be sorted by ts at 1-minute cadence. Returns features indexed
    like df (leading rows with insufficient history are back-filled)."""
    df = df.sort_values("ts").reset_index(drop=True)
    out = pd.DataFrame(index=df.index)
    for c in BASE_COLS:
        series = pd.to_numeric(df[c], errors="coerce").astype(float)
        out[c] = series
        for w in ROLL_WINDOWS:
            out[f"{c}_mean{w}"] = series.rolling(window=w, min_periods=1).mean()

    ts = pd.to_datetime(df["ts"], utc=True)
    hod = ts.dt.hour + ts.dt.minute / 60.0
    out["hod_sin"] = np.sin(2 * np.pi * hod / 24.0)
    out["hod_cos"] = np.cos(2 * np.pi * hod / 24.0)
    dow = ts.dt.dayofweek
    out["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    out["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)

    return out[feature_columns()].ffill().bfill().fillna(0.0)
