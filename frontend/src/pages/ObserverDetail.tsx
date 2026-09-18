import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Alert, MetricPoint, Observer } from "../api/types";
import { METRIC_SPECS, MetricChart } from "../components/charts";
import { ErrorNote, SectionTitle, Spinner, StatusDot } from "../components/ui";
import { timeAgo } from "../lib/ws";

const RANGES = [
  { label: "1h", minutes: 60, step: 60 },
  { label: "6h", minutes: 360, step: 300 },
  { label: "24h", minutes: 1440, step: 900 },
  { label: "7d", minutes: 10080, step: 3600 },
];

export default function ObserverDetail() {
  const { id } = useParams<{ id: string }>();
  const [range, setRange] = useState(RANGES[0]);

  const observer = useQuery({
    queryKey: ["observers", id],
    queryFn: () => api<Observer>(`/v1/observers/${id}`),
  });
  const metrics = useQuery({
    queryKey: ["metrics", id, range.label],
    queryFn: () =>
      api<{ points: MetricPoint[] }>(
        `/v1/metrics?observer_id=${id}&step=${range.step}&from=${new Date(
          Date.now() - range.minutes * 60000,
        ).toISOString()}`,
      ),
    refetchInterval: 30000,
  });
  const alerts = useQuery({
    queryKey: ["alerts", "observer", id],
    queryFn: () => api<Alert[]>(`/v1/alerts?observer_id=${id}`),
    refetchInterval: 15000,
  });

  if (observer.isLoading) return <Spinner />;
  if (observer.error) return <ErrorNote error={observer.error} />;
  const obs = observer.data!;
  const points = metrics.data?.points ?? [];
  const rangeStart = Date.now() - range.minutes * 60000;
  const markers = (alerts.data ?? []).filter((a) => new Date(a.fired_at).getTime() >= rangeStart);
  const anomalies = markers.filter((a) => a.source === "anomaly");

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <div className="text-xs text-muted mb-1">
            <Link to="/fleet" className="hover:text-ink">Fleet</Link> / {obs.name}
          </div>
          <h1 className="text-xl font-semibold flex items-center gap-3">
            {obs.name}
            <StatusDot status={obs.status} live />
          </h1>
          <div className="text-xs text-muted mt-1">
            heartbeat {timeAgo(obs.last_heartbeat)} · id <span className="mono">{obs.id}</span>
          </div>
        </div>
        <div className="flex rounded overflow-hidden border hairline">
          {RANGES.map((r) => (
            <button
              key={r.label}
              onClick={() => setRange(r)}
              className="px-3 py-1.5 text-xs"
              style={{
                background: r.label === range.label ? "var(--surface-2)" : "transparent",
                color: r.label === range.label ? "var(--ink)" : "var(--muted)",
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {anomalies.length > 0 && (
        <div
          className="mb-4 rounded border px-3 py-2 text-sm"
          style={{ borderColor: "var(--s6)", background: "rgba(144,133,233,.08)" }}
        >
          <span style={{ color: "var(--s6)" }}>◆ ML anomaly</span>{" "}
          <span className="text-ink-2">
            {anomalies[0].summary}
            {anomalies[0].anomaly_score != null &&
              ` (score ${anomalies[0].anomaly_score.toFixed(3)})`}
          </span>
        </div>
      )}

      {metrics.isLoading ? (
        <Spinner />
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))" }}>
          {METRIC_SPECS.map((spec) => (
            <MetricChart key={String(spec.key)} points={points} spec={spec} alerts={markers} />
          ))}
        </div>
      )}

      <div className="mt-6">
        <SectionTitle>Alerts on this host</SectionTitle>
        {(alerts.data ?? []).length === 0 ? (
          <div className="text-muted text-sm">No alerts recorded.</div>
        ) : (
          <div className="space-y-1 text-sm">
            {(alerts.data ?? []).slice(0, 20).map((a) => (
              <Link
                key={a.id}
                to={`/alerts?focus=${a.id}`}
                className="flex items-center gap-3 card px-3 py-2 hover:border-[var(--s1)]"
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{
                    background:
                      a.state === "resolved"
                        ? "var(--good)"
                        : a.severity === "critical"
                          ? "var(--crit)"
                          : "var(--warn)",
                  }}
                />
                <span className="truncate flex-1 text-ink-2">{a.summary}</span>
                <span className="text-xs text-muted shrink-0">{timeAgo(a.fired_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
