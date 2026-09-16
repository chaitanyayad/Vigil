# Noisy Neighbour

One workload starving others on a shared host.

## Symptoms
- Elevated CPU/load or IO wait without any single service's own traffic increasing
- Latency degradation on services whose own metrics look calm
- On VMs: steal time (`%st` in top) climbing

## Diagnose
1. `top` / `pidstat` — is a co-located workload consuming disproportionate CPU/IO?
2. `iostat -x 1` — device saturation (%util) from someone else's IO.
3. On cloud VMs: check CPU steal; the neighbour may be outside your VM entirely.
4. Compare against the host's other observers/labels in the dashboard.

## Mitigate
- Apply/repair resource limits: cgroups, container CPU/memory limits, IO weights.
- Move the heavy workload to a dedicated node; cordon it in the scheduler.
- On cloud steal: resize to a dedicated/burst-protected instance class.

## Verify
- Victim services' latency recovers with no change to their own config.
- Limits are codified (compose/k8s manifests) so the situation can't silently return.
