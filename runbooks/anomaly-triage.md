# Anomaly Triage (no matching static rule)

The ML detector flagged behaviour outside the learned baseline, but no static
threshold fired. Treat as an early-warning investigation, not an incident yet.

## Symptoms
- `source=anomaly` alert with a negative anomaly score
- Individual metrics may all be inside "acceptable" static ranges

## Diagnose
1. Open the observer detail chart with the anomaly-score overlay: which metric
   diverged from its usual daily pattern at that time?
2. Compare against the same hour yesterday / last week — is this a new shape
   or a known weekly pattern the model hasn't seen enough of?
3. Check co-occurring events: deploys, cron jobs, traffic shifts, config changes.
4. Look at the other hosts with the same labels — fleet-wide drift means an
   upstream cause (release, dependency), single-host drift means local cause.

## Mitigate
- If it's the leading edge of a known failure shape (memory ramp, disk slope):
  jump to that runbook now — you're early, use the time.
- If it's benign novelty (new legitimate workload): acknowledge the alert; the
  nightly retrain will absorb the new baseline.

## Verify
- Score returns above threshold and the alert auto-resolves, or the incident
  is reclassified under a specific runbook.
