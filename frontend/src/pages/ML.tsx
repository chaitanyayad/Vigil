import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EvalReport, EvalSide, MLModelRow, Observer } from "../api/types";
import { Card, Empty, ErrorNote, SectionTitle, Spinner } from "../components/ui";
import { timeAgo } from "../lib/ws";

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "–" : v.toFixed(digits);
}

function EvalTable({ report }: { report: EvalReport }) {
  const rows: { label: string; get: (s: EvalSide) => string }[] = [
    { label: "Precision", get: (s) => fmt(s.precision) },
    { label: "Recall", get: (s) => fmt(s.recall) },
    { label: "F1", get: (s) => fmt(s.f1) },
    { label: "Mean detection delay (min)", get: (s) => fmt(s.mean_detection_delay_min, 1) },
    { label: "False alarms / day", get: (s) => fmt(s.false_alarms_per_day) },
    { label: "Incidents detected", get: (s) => `${s.incidents_detected}/${s.incidents_total}` },
  ];
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="microlabel text-left border-b hairline">
            <th className="px-4 py-2.5 font-medium">Metric (synthetic incident set)</th>
            <th className="px-4 py-2.5 font-medium" style={{ color: "var(--s1)" }}>● IsolationForest</th>
            <th className="px-4 py-2.5 font-medium" style={{ color: "var(--s2)" }}>● Static rules</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b hairline last:border-0">
              <td className="px-4 py-2.5 text-ink-2">{r.label}</td>
              <td className="px-4 py-2.5 mono">{r.get(report.ml)}</td>
              <td className="px-4 py-2.5 mono">{r.get(report.static_rules)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {report.memory_leak_detected_earlier_by_min != null && (
        <div className="px-4 py-3 text-sm border-t hairline">
          <span style={{ color: "var(--good)" }}>▸</span> Memory-leak ramp caught{" "}
          <span className="font-semibold" style={{ color: "var(--good)" }}>
            {report.memory_leak_detected_earlier_by_min} minutes earlier
          </span>{" "}
          than the static ruleset.
        </div>
      )}
    </Card>
  );
}

export default function ML() {
  const qc = useQueryClient();
  const models = useQuery({ queryKey: ["ml", "models"], queryFn: () => api<MLModelRow[]>("/v1/ml/models") });
  const evalReport = useQuery({
    queryKey: ["ml", "eval"],
    queryFn: () => api<{ available: boolean; report?: EvalReport }>("/v1/ml/eval"),
  });
  const observers = useQuery({ queryKey: ["observers"], queryFn: () => api<Observer[]>("/v1/observers") });
  const train = useMutation({
    mutationFn: () => api("/v1/ml/train", { method: "POST" }),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["ml"] });
      }, 8000);
    },
  });
  const nameById = new Map((observers.data ?? []).map((o) => [o.id, o.name]));

  return (
    <div className="space-y-8">
      <div>
        <SectionTitle
          right={
            <button className="btn btn-primary text-xs" onClick={() => train.mutate()} disabled={train.isPending}>
              {train.isPending ? "Training…" : "Train global model"}
            </button>
          }
        >
          Anomaly detection — rules vs ML
        </SectionTitle>
        {train.error != null && <ErrorNote error={train.error} />}
        {evalReport.isLoading && <Spinner />}
        {evalReport.data?.available && evalReport.data.report ? (
          <EvalTable report={evalReport.data.report} />
        ) : (
          !evalReport.isLoading && (
            <Empty>
              No eval report yet — train a model (needs ≥ 1h of ingested metrics), or run{" "}
              <span className="mono">python -m vigil.ml.eval</span>.
            </Empty>
          )
        )}
      </div>

      <div>
        <SectionTitle>Trained models</SectionTitle>
        {models.isLoading && <Spinner />}
        {models.data?.length === 0 && <Empty>No models trained yet. The nightly job trains at 02:00 UTC.</Empty>}
        {(models.data ?? []).length > 0 && (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="microlabel text-left border-b hairline">
                  <th className="px-4 py-2.5 font-medium">Scope</th>
                  <th className="px-4 py-2.5 font-medium">Algorithm</th>
                  <th className="px-4 py-2.5 font-medium">Trained</th>
                  <th className="px-4 py-2.5 font-medium">Window</th>
                  <th className="px-4 py-2.5 font-medium">F1 (synthetic)</th>
                </tr>
              </thead>
              <tbody>
                {(models.data ?? []).map((m) => (
                  <tr key={m.id} className="border-b hairline last:border-0">
                    <td className="px-4 py-2.5">
                      {m.observer_id ? nameById.get(m.observer_id) ?? m.observer_id : (
                        <span style={{ color: "var(--s1)" }}>global</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 mono text-ink-2">{m.algo}</td>
                    <td className="px-4 py-2.5 text-muted">{timeAgo(m.trained_at)}</td>
                    <td className="px-4 py-2.5 text-ink-2">{m.window_hours}h</td>
                    <td className="px-4 py-2.5 mono">{fmt(m.metrics?.ml.f1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
