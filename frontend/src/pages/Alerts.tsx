import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Alert, AlertEvent, Observer, TriageResult, VerifyResult } from "../api/types";
import {
  Card,
  Empty,
  ErrorNote,
  SectionTitle,
  SeverityBadge,
  SourceBadge,
  Spinner,
  StateBadge,
} from "../components/ui";
import { shortHash, timeAgo } from "../lib/ws";

const STATES = ["all", "firing", "acknowledged", "resolved"] as const;

function TriageCard({ alertId }: { alertId: string }) {
  const qc = useQueryClient();
  const triage = useQuery({
    queryKey: ["alerts", alertId, "triage"],
    queryFn: () => api<TriageResult[]>(`/v1/alerts/${alertId}/triage`),
  });
  const run = useMutation({
    mutationFn: () => api(`/v1/alerts/${alertId}/triage`, { method: "POST" }),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ["alerts", alertId, "triage"] }), 4000);
    },
  });
  const latest = triage.data?.[0];

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="microlabel">AI triage</span>
        <button className="btn text-xs py-1" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Asking Gemini…" : latest ? "Re-triage" : "Run triage"}
        </button>
      </div>
      {run.error != null && <ErrorNote error={run.error} />}
      {latest ? (
        <div className="text-sm space-y-2">
          <p className="text-ink-2">{latest.hypothesis}</p>
          <div className="flex items-center gap-4 text-xs">
            <span>
              runbook{" "}
              <span className="mono px-1.5 py-0.5 rounded" style={{ background: "var(--surface-2)", color: "var(--s3)" }}>
                {latest.suggested_runbook}
              </span>
            </span>
            <span className="text-muted">
              confidence{" "}
              <span style={{ color: latest.confidence > 0.7 ? "var(--good)" : "var(--warn)" }}>
                {(latest.confidence * 100).toFixed(0)}%
              </span>
            </span>
            <span className="text-muted mono">{latest.model}</span>
          </div>
        </div>
      ) : (
        <p className="text-muted text-xs">
          No triage yet. Runs automatically for critical alerts when GEMINI_API_KEY is set.
        </p>
      )}
    </div>
  );
}

function VerifyStrip({ alertId }: { alertId: string }) {
  const verify = useQuery({
    queryKey: ["verify", alertId],
    queryFn: () => api<VerifyResult>(`/v1/ledger/verify/${alertId}`),
    enabled: false,
  });
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="microlabel">Ledger integrity</span>
        <button
          className="btn text-xs py-1"
          onClick={() => verify.refetch()}
          disabled={verify.isFetching}
        >
          {verify.isFetching ? "Verifying…" : "Verify integrity"}
        </button>
      </div>
      {verify.data && (
        <div className="flex flex-wrap gap-1.5">
          {verify.data.events.map((e) => {
            const color =
              e.valid === true ? "var(--good)" : e.valid === false ? "var(--crit)" : "var(--muted)";
            const label = e.valid === true ? "✓" : e.valid === false ? "✗" : "◌";
            return (
              <span
                key={e.event_id}
                title={`${e.event_type} · ${e.status ?? ""} · ${e.local_hash}`}
                className="text-xs px-2 py-1 rounded border mono"
                style={{ borderColor: color, color }}
              >
                {label} {e.event_type}
              </span>
            );
          })}
          {verify.data.tampered_event_ids.length > 0 && (
            <span className="text-xs w-full" style={{ color: "#e66767" }}>
              History was modified after anchoring — events{" "}
              {verify.data.tampered_event_ids.join(", ")} no longer match the on-chain root.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert, observers, open, onToggle }: {
  alert: Alert;
  observers: Map<string, string>;
  open: boolean;
  onToggle: () => void;
}) {
  const qc = useQueryClient();
  const events = useQuery({
    queryKey: ["alerts", alert.id, "events"],
    queryFn: () => api<AlertEvent[]>(`/v1/alerts/${alert.id}/events`),
    enabled: open,
  });
  const ack = useMutation({
    mutationFn: () => api(`/v1/alerts/${alert.id}/ack`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  return (
    <Card className={open ? "border-[var(--s1)]" : ""}>
      <button className="w-full text-left px-4 py-3 flex items-center gap-3" onClick={onToggle}>
        <StateBadge state={alert.state} />
        <SeverityBadge severity={alert.severity} />
        <SourceBadge source={alert.source} />
        <span className="flex-1 truncate text-ink-2">{alert.summary}</span>
        <span className="text-xs text-muted shrink-0">
          {observers.get(alert.observer_id) ?? "?"} · {timeAgo(alert.fired_at)}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t hairline pt-3 grid gap-5 lg:grid-cols-2">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="microlabel">Event timeline</span>
              {alert.state === "firing" && (
                <button className="btn text-xs py-1" onClick={() => ack.mutate()} disabled={ack.isPending}>
                  Acknowledge
                </button>
              )}
            </div>
            {events.isLoading ? (
              <Spinner />
            ) : (
              <ol className="relative ml-2 space-y-3 border-l hairline pl-4">
                {(events.data ?? []).map((e) => (
                  <li key={e.id} className="text-sm">
                    <span
                      className="absolute -left-[5px] mt-1 w-2 h-2 rounded-full"
                      style={{ background: "var(--s1)" }}
                    />
                    <div className="flex items-baseline gap-2">
                      <span className="font-medium">{e.event_type}</span>
                      <span className="text-xs text-muted">
                        {new Date(e.created_at).toLocaleString()}
                      </span>
                    </div>
                    <div className="text-[11px] mono text-muted mt-0.5" title={e.event_hash}>
                      {shortHash(e.event_hash, 18)}
                      {e.batch_id != null && (
                        <span className="ml-2" style={{ color: "var(--s3)" }}>
                          batch #{e.batch_id}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="space-y-5">
            <TriageCard alertId={alert.id} />
            <VerifyStrip alertId={alert.id} />
          </div>
        </div>
      )}
    </Card>
  );
}

export default function Alerts() {
  const [params] = useSearchParams();
  const [state, setState] = useState<(typeof STATES)[number]>("all");
  const [openId, setOpenId] = useState<string | null>(params.get("focus"));

  const alerts = useQuery({
    queryKey: ["alerts", state],
    queryFn: () => api<Alert[]>(`/v1/alerts${state === "all" ? "" : `?state=${state}`}`),
    refetchInterval: 10000,
  });
  const observers = useQuery({
    queryKey: ["observers"],
    queryFn: () => api<Observer[]>("/v1/observers"),
  });
  const nameById = new Map((observers.data ?? []).map((o) => [o.id, o.name]));

  return (
    <div>
      <SectionTitle
        right={
          <div className="flex rounded overflow-hidden border hairline">
            {STATES.map((s) => (
              <button
                key={s}
                onClick={() => setState(s)}
                className="px-3 py-1.5 text-xs capitalize"
                style={{
                  background: s === state ? "var(--surface-2)" : "transparent",
                  color: s === state ? "var(--ink)" : "var(--muted)",
                }}
              >
                {s}
              </button>
            ))}
          </div>
        }
      >
        Alerts
      </SectionTitle>
      {alerts.isLoading && <Spinner />}
      {alerts.error != null && <ErrorNote error={alerts.error} />}
      {alerts.data?.length === 0 && <Empty>No alerts{state !== "all" ? ` in state “${state}”` : ""}.</Empty>}
      <div className="space-y-2">
        {(alerts.data ?? []).map((a) => (
          <AlertRow
            key={a.id}
            alert={a}
            observers={nameById}
            open={openId === a.id}
            onToggle={() => setOpenId(openId === a.id ? null : a.id)}
          />
        ))}
      </div>
    </div>
  );
}
