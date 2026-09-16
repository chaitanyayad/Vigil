# High CPU

Sustained CPU above threshold on a host.

## Symptoms
- `cpu_pct` pinned high (85%+) for minutes, load1 climbing with it
- Latency-sensitive services on the host respond slowly
- Often paired with a specific runaway process rather than uniform load

## Diagnose
1. `top -o %CPU` / `ps aux --sort=-%cpu | head` — identify the top consumer.
2. Check whether it's a known workload spike (cron, batch job, deploy) vs. a runaway.
3. `pidstat -u 1 5 -p <pid>` to confirm the process is busy-looping vs. doing real work.
4. Correlate with recent deploys or config changes on the host.

## Mitigate
- Runaway process: restart the offending service; capture a stack/profile first if possible
  (`py-spy dump`, `jstack`, `perf top`).
- Legitimate load: scale horizontally or throttle upstream traffic.
- If the host is shared ("noisy neighbour" pattern), cordon the heavy tenant.

## Verify
- CPU returns under threshold and the alert auto-resolves.
- No follow-on alerts (memory, load) on the same host within 15 minutes.
