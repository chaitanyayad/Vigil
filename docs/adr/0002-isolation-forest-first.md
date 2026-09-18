# ADR 0002 — IsolationForest before deep models

**Status:** accepted

## Context
Anomaly detection on 6 host metrics at 1-minute resolution, per observer, trained on ≤ 7 days
of data, retrained nightly, inferring every minute on a laptop-class CPU.

## Decision
IsolationForest (scikit-learn) over raw values + rolling means + time-of-day/day-of-week
encodings. No LSTM/transformer in v1.

## Rationale
- Data volume per observer (≤ 10k rows) is far below what sequence models need.
- Training takes seconds on CPU; nightly retrain per observer stays free.
- Rolling-std features were measured to *hurt* (diluted splits → ~2x detection delay on the
  synthetic benchmark) and were dropped — evidence-driven feature selection beats bigger models
  at this data size.
- Two operational fixes mattered more than model choice: per-model threshold calibration
  (0.5th percentile of training scores — raw scores don't transfer between models) and a
  3-consecutive-minute streak requirement (false-alarm control).

## Consequences
- Point-wise recall is modest; incident-level detection (4/4 on the synthetic set, memory leak
  ~170 min before static thresholds) is what we optimise and report.
- Future work: seasonal decomposition or a small autoencoder once real multi-week data exists.
