# Host Down

Observer stopped heartbeating — the host (or the agent) is gone.

## Symptoms
- `observer_down` alert; last heartbeat older than 45 s
- No metrics arriving from the host at all (distinct from "metrics bad")

## Diagnose
1. Can you reach it? `ping`, then SSH. No ping → host/network; ping but no
   SSH → host wedged or auth layer down.
2. Cloud console / hypervisor: is the instance running? Recent maintenance events?
3. If the host is up but the agent died: check agent logs and OOM-killer
   (`dmesg | grep -i kill`) — a memory incident can take the agent with it.
4. Check whether multiple observers dropped at once → network partition or
   orchestrator-side problem, not this host.

## Mitigate
- Host wedged: reboot via console; capture console output first.
- Agent-only failure: restart the agent (it will flush its buffered samples).
- Real hardware failure: fail over the workload, replace the node.

## Verify
- Heartbeats resume; the observer_down alert auto-resolves.
- Buffered metrics from the outage window appear in the dashboard (agent ring buffer).
