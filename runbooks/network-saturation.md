# Network Saturation

Rx/Tx throughput far above baseline, saturating the link.

## Symptoms
- `net_rx_bps` / `net_tx_bps` orders of magnitude above the diurnal norm
- Packet loss, retransmits, timeouts on services using the host
- CPU often elevated from interrupt/softirq handling

## Diagnose
1. `iftop` / `nethogs` — which flow and process dominate?
2. Direction matters: inbound flood (DDoS, misrouted traffic, replication storm)
   vs outbound (backup job, data exfil, misconfigured client retry loop).
3. Check conntrack table and SYN backlog for attack patterns.
4. Correlate with scheduled jobs: backups, replication resyncs, large deploys.

## Mitigate
- Legitimate bulk transfer: rate-limit it (`tc`, application-level throttle) or
  reschedule off-peak.
- Retry storm: fix or circuit-break the client; exponential backoff.
- Attack traffic: apply upstream filtering/ACLs; engage the network provider.

## Verify
- Throughput back inside the normal band; retransmit rate normal.
- The source (job/client) has a throttle so it doesn't recur.
