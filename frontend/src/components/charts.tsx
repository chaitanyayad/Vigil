import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Alert, MetricPoint } from "../api/types";
import { fmtBps } from "../lib/ws";

/** Tiny inline sparkline for fleet cards — pure SVG, no axes. */
export function Sparkline({
  values,
  color = "var(--s1)",
  width = 120,
  height = 28,
}: {
  values: (number | null)[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const pts = values.filter((v): v is number => v != null);
  if (pts.length < 2) return <div style={{ width, height }} className="text-muted text-xs">–</div>;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  let d = "";
  values.forEach((v, i) => {
    if (v == null) return;
    const x = i * step;
    const y = height - 2 - ((v - min) / span) * (height - 4);
    d += d ? ` L${x.toFixed(1)},${y.toFixed(1)}` : `M${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
    </svg>
  );
}

const tooltipStyle = {
  background: "var(--surface-2)",
  border: "1px solid var(--ring)",
  borderRadius: 6,
  fontSize: 12,
  color: "var(--ink)",
};

export interface MetricSpec {
  key: keyof MetricPoint;
  label: string;
  color: string;
  unit: "pct" | "bps" | "raw";
}

export const METRIC_SPECS: MetricSpec[] = [
  { key: "cpu_pct", label: "CPU", color: "var(--s1)", unit: "pct" },
  { key: "mem_pct", label: "Memory", color: "var(--s2)", unit: "pct" },
  { key: "disk_pct", label: "Disk", color: "var(--s3)", unit: "pct" },
  { key: "net_rx_bps", label: "Net RX", color: "var(--s4)", unit: "bps" },
  { key: "net_tx_bps", label: "Net TX", color: "var(--s5)", unit: "bps" },
  { key: "load1", label: "Load (1m)", color: "var(--s6)", unit: "raw" },
];

function fmtValue(v: number | null, unit: MetricSpec["unit"]): string {
  if (v == null) return "–";
  if (unit === "pct") return `${v.toFixed(1)}%`;
  if (unit === "bps") return fmtBps(v);
  return v.toFixed(2);
}

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

/** One metric, one axis, area chart with crosshair tooltip + alert markers. */
export function MetricChart({
  points,
  spec,
  alerts = [],
}: {
  points: MetricPoint[];
  spec: MetricSpec;
  alerts?: Alert[];
}) {
  const data = points.map((p) => ({
    t: new Date(p.ts).getTime(),
    v: p[spec.key] as number | null,
  }));
  const gid = `grad-${spec.key}`;
  const markers = alerts
    .map((a) => {
      const t = new Date(a.fired_at).getTime();
      const nearest = data.reduce(
        (best, d) => (Math.abs(d.t - t) < Math.abs(best.t - t) ? d : best),
        data[0] ?? { t: 0, v: null },
      );
      return nearest?.v != null ? { t: nearest.t, v: nearest.v, alert: a } : null;
    })
    .filter((m): m is { t: number; v: number; alert: Alert } => m != null);

  return (
    <div className="card p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium" style={{ color: spec.color }}>
          ● <span className="text-ink-2">{spec.label}</span>
        </span>
        <span className="text-xs text-muted mono">
          {fmtValue((data.at(-1)?.v ?? null) as number | null, spec.unit)}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={130}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={spec.color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={spec.color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--grid)" strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t) => timeFmt.format(t)}
            stroke="var(--baseline)"
            tick={{ fill: "var(--muted)", fontSize: 10 }}
            tickLine={false}
            minTickGap={60}
          />
          <YAxis
            width={44}
            stroke="transparent"
            tick={{ fill: "var(--muted)", fontSize: 10 }}
            tickLine={false}
            domain={spec.unit === "pct" ? [0, 100] : [0, "auto"]}
            tickFormatter={(v) => (spec.unit === "bps" ? fmtBps(v).replace(/b\/s$/, "") : String(v))}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(t) => timeFmt.format(t as number)}
            formatter={(v) => [fmtValue(v as number, spec.unit), spec.label]}
            cursor={{ stroke: "var(--muted)", strokeWidth: 1, strokeDasharray: "3 3" }}
          />
          <Area
            type="monotone"
            dataKey="v"
            stroke={spec.color}
            strokeWidth={2}
            fill={`url(#${gid})`}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          {markers.map((m) => (
            <ReferenceDot
              key={m.alert.id}
              x={m.t}
              y={m.v}
              r={5}
              fill={m.alert.severity === "critical" ? "var(--crit)" : "var(--warn)"}
              stroke="var(--surface)"
              strokeWidth={2}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
