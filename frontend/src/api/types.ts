export type ObserverStatus = "online" | "offline" | "unknown";
export type Severity = "info" | "warning" | "critical";
export type AlertState = "firing" | "acknowledged" | "resolved";
export type AlertSource = "rule" | "anomaly" | "watchdog";

export interface Observer {
  id: string;
  name: string;
  labels: Record<string, string>;
  created_at: string;
  last_heartbeat: string | null;
  status: ObserverStatus;
}

export interface MetricPoint {
  ts: string;
  cpu_pct: number | null;
  cpu_max: number | null;
  mem_pct: number | null;
  mem_max: number | null;
  disk_pct: number | null;
  net_rx_bps: number | null;
  net_tx_bps: number | null;
  load1: number | null;
  samples: number;
}

export interface Rule {
  id: string;
  name: string;
  metric: string;
  op: "gt" | "lt" | "gte" | "lte";
  threshold: number;
  for_seconds: number;
  severity: Severity;
  enabled: boolean;
  observer_selector: Record<string, string> | null;
}

export interface Alert {
  id: string;
  observer_id: string;
  rule_id: string | null;
  source: AlertSource;
  severity: Severity;
  state: AlertState;
  fired_at: string;
  acked_at: string | null;
  resolved_at: string | null;
  summary: string;
  anomaly_score: number | null;
}

export interface AlertEvent {
  id: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  event_hash: string;
  prev_hash: string | null;
  batch_id: number | null;
}

export interface TriageResult {
  id: string;
  alert_id: string;
  model: string;
  hypothesis: string;
  suggested_runbook: string;
  confidence: number;
  created_at: string;
}

export interface LedgerBatch {
  id: number;
  merkle_root: string;
  first_event_id: number;
  last_event_id: number;
  tx_hash: string | null;
  chain_id: number;
  chain_batch_id: number | null;
  block_number: number | null;
  anchored_at: string | null;
  status: "pending" | "anchored" | "failed";
}

export interface VerifyEvent {
  event_id: number;
  event_type: string;
  created_at: string;
  local_hash: string;
  stored_hash: string;
  hash_matches_stored: boolean;
  batch_id: number | null;
  on_chain_root: string | null;
  valid: boolean | null;
  status?: string;
}

export interface VerifyResult {
  alert_id: string;
  events: VerifyEvent[];
  all_verified: boolean;
  tampered_event_ids: number[];
}

export interface MLModelRow {
  id: string;
  observer_id: string | null;
  algo: string;
  trained_at: string;
  window_hours: number;
  artifact_path: string;
  metrics: EvalReport | null;
}

export interface EvalSide {
  precision: number;
  recall: number;
  f1: number;
  mean_detection_delay_min: number | null;
  false_alarms_per_day: number;
  incidents_detected: number;
  incidents_total: number;
}

export interface EvalReport {
  threshold: number;
  ml: EvalSide;
  static_rules: EvalSide;
  memory_leak_detected_earlier_by_min: number | null;
}

export interface WsMessage {
  kind: string;
  data: Record<string, unknown>;
  channel: string;
}
