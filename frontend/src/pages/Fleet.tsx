import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Alert, MetricPoint, Observer } from "../api/types";
import { Sparkline } from "../components/charts";
import { Card, Empty, ErrorNote, SectionTitle, Spinner, StatusDot } from "../components/ui";
import { timeAgo } from "../lib/ws";

function ObserverCard({ observer, firing }: { observer: Observer; firing: Alert[] }) {
  const { data } = useQuery({
    queryKey: ["metrics", observer.id, "spark"],
    queryFn: () =>
      api<{ points: MetricPoint[] }>(
        `/v1/metrics?observer_id=${observer.id}&step=60&from=${new Date(Date.now() - 45 * 60000).toISOString()}`,
      ),
    refetchInterval: 30000,
  });
  const points = data?.points ?? [];
  const latest = points.at(-1);
  const mine = firing.filter((a) => a.observer_id === observer.id);

  return (
    <Link to={`/observers/${observer.id}`}>
      <Card className="p-4 hover:border-[var(--s1)] transition-colors h-full">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="font-medium truncate">{observer.name}</div>
            <div className="text-xs text-muted mt-0.5">
              heartbeat {timeAgo(observer.last_heartbeat)}
            </div>
          </div>
          <StatusDot status={observer.status} live />
        </div>
        <div className="flex items-end justify-between mt-4">
          <div>
            <div className="microlabel">CPU · last 45m</div>
            <Sparkline values={points.map((p) => p.cpu_pct)} />
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold">
              {latest?.cpu_pct != null ? `${latest.cpu_pct.toFixed(0)}%` : "–"}
            </div>
            <div className="text-xs text-muted">
              mem {latest?.mem_pct != null ? `${latest.mem_pct.toFixed(0)}%` : "–"}
            </div>
          </div>
        </div>
        {mine.length > 0 && (
          <div
            className="mt-3 pt-2 border-t text-xs"
            style={{ borderColor: "var(--ring)", color: "#e66767" }}
          >
            ● {mine.length} active alert{mine.length > 1 ? "s" : ""}
          </div>
        )}
        {Object.keys(observer.labels ?? {}).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(observer.labels).map(([k, v]) => (
              <span key={k} className="text-[10px] mono text-muted border rounded px-1 hairline">
                {k}={String(v)}
              </span>
            ))}
          </div>
        )}
      </Card>
    </Link>
  );
}

export default function Fleet() {
  const observers = useQuery({
    queryKey: ["observers"],
    queryFn: () => api<Observer[]>("/v1/observers"),
    refetchInterval: 15000,
  });
  const alerts = useQuery({
    queryKey: ["alerts", "firing"],
    queryFn: () => api<Alert[]>("/v1/alerts?state=firing"),
    refetchInterval: 15000,
  });

  if (observers.isLoading) return <Spinner />;
  if (observers.error) return <ErrorNote error={observers.error} />;
  const list = observers.data ?? [];
  const online = list.filter((o) => o.status === "online").length;

  return (
    <div>
      <SectionTitle
        right={
          <span className="text-xs text-muted">
            {online}/{list.length} online · {alerts.data?.length ?? 0} firing
          </span>
        }
      >
        Fleet overview
      </SectionTitle>
      {list.length === 0 ? (
        <Empty>
          No observers yet. Start an agent, or create one via{" "}
          <span className="mono">POST /v1/observers</span>.
        </Empty>
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {list.map((o) => (
            <ObserverCard key={o.id} observer={o} firing={alerts.data ?? []} />
          ))}
        </div>
      )}
    </div>
  );
}
