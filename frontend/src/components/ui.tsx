import type { ReactNode } from "react";
import type { AlertState, ObserverStatus, Severity } from "../api/types";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="microlabel">{children}</h2>
      {right}
    </div>
  );
}

const STATUS_COLOR: Record<ObserverStatus, string> = {
  online: "var(--good)",
  offline: "var(--crit)",
  unknown: "var(--muted)",
};

export function StatusDot({ status, live = false }: { status: ObserverStatus; live?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block w-2 h-2 rounded-full ${status === "online" && live ? "live-dot" : ""}`}
        style={{ background: STATUS_COLOR[status] }}
      />
      <span className="text-ink-2 capitalize">{status}</span>
    </span>
  );
}

const SEV: Record<Severity, { bg: string; fg: string; icon: string }> = {
  info: { bg: "rgba(137,135,129,.15)", fg: "var(--ink-2)", icon: "ℹ" },
  warning: { bg: "rgba(250,178,25,.14)", fg: "var(--warn)", icon: "▲" },
  critical: { bg: "rgba(208,59,59,.16)", fg: "#e66767", icon: "●" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEV[severity];
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
      style={{ background: s.bg, color: s.fg }}
    >
      <span aria-hidden>{s.icon}</span>
      {severity}
    </span>
  );
}

const STATE: Record<AlertState, { fg: string; label: string }> = {
  firing: { fg: "#e66767", label: "firing" },
  acknowledged: { fg: "var(--warn)", label: "acked" },
  resolved: { fg: "var(--good)", label: "resolved" },
};

export function StateBadge({ state }: { state: AlertState }) {
  const s = STATE[state];
  return (
    <span className="text-xs font-medium uppercase tracking-wider" style={{ color: s.fg }}>
      {s.label}
    </span>
  );
}

export function SourceBadge({ source }: { source: string }) {
  const label = source === "anomaly" ? "ML anomaly" : source === "watchdog" ? "watchdog" : "rule";
  const color = source === "anomaly" ? "var(--s6)" : source === "watchdog" ? "var(--s2)" : "var(--s1)";
  return (
    <span
      className="text-[11px] px-1.5 py-0.5 rounded border"
      style={{ color, borderColor: "var(--ring)" }}
    >
      {label}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-muted text-center py-10">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div
      className="rounded border px-3 py-2 text-sm my-2"
      style={{ borderColor: "var(--crit)", color: "#e66767", background: "rgba(208,59,59,.08)" }}
    >
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Spinner() {
  return <div className="text-muted py-8 text-center">Loading…</div>;
}
