# Memory Leak

Slow, monotonic memory growth that ends in OOM if untreated.

## Symptoms
- `mem_pct` ramping steadily over hours — a slope, not a step
- Anomaly detector usually flags the ramp long before any static threshold trips
- Eventually: swap thrash, OOM-killer activity, service crashes

## Diagnose
1. `ps aux --sort=-%mem | head` — which process owns the growth?
2. Plot the process RSS over time (`pidstat -r 60`) — a straight upward line confirms a leak.
3. Check recent deploys of that service; leaks usually ship with a release.
4. Language-specific: heap dump (`jmap`, `tracemalloc`, `pprof`) to find the retained objects.

## Mitigate
- Short term: rolling restart of the leaking service to reclaim memory —
  schedule before projected OOM time (extrapolate the ramp).
- Guard the host: verify OOM-killer priorities / cgroup limits so the leak
  can't take down neighbours.
- Roll back the suspect release if the leak started right after a deploy.

## Verify
- Memory flat or sawtoothing (restarts) instead of ramping.
- File a bug with the heap-dump evidence; a restart is not a fix.
