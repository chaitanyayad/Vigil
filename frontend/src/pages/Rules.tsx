import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { Rule, Severity } from "../api/types";
import { Card, Empty, ErrorNote, SectionTitle, SeverityBadge, Spinner } from "../components/ui";

const METRICS = ["cpu_pct", "mem_pct", "disk_pct", "net_rx_bps", "net_tx_bps", "load1"];
const OPS = [
  { v: "gt", label: ">" },
  { v: "gte", label: "≥" },
  { v: "lt", label: "<" },
  { v: "lte", label: "≤" },
];

const EMPTY_FORM = {
  name: "",
  metric: "cpu_pct",
  op: "gt",
  threshold: 85,
  for_seconds: 300,
  severity: "warning" as Severity,
  enabled: true,
};

function RuleForm({ initial, onDone }: { initial?: Rule; onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState(initial ?? EMPTY_FORM);
  const save = useMutation({
    mutationFn: () =>
      initial
        ? api(`/v1/rules/${initial.id}`, { method: "PATCH", body: JSON.stringify(form) })
        : api("/v1/rules", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      onDone();
    },
  });
  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Card className="p-4 mb-4">
      {save.error != null && <ErrorNote error={save.error} />}
      <div className="grid gap-3 md:grid-cols-6 items-end">
        <div className="md:col-span-2">
          <label className="microlabel block mb-1">Name</label>
          <input className="field w-full" value={form.name} onChange={(e) => set("name", e.target.value)} />
        </div>
        <div>
          <label className="microlabel block mb-1">Metric</label>
          <select className="field w-full" value={form.metric} onChange={(e) => set("metric", e.target.value)}>
            {METRICS.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div className="flex gap-2">
          <div>
            <label className="microlabel block mb-1">Op</label>
            <select className="field" value={form.op} onChange={(e) => set("op", e.target.value)}>
              {OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="microlabel block mb-1">Threshold</label>
            <input
              className="field w-24" type="number" value={form.threshold}
              onChange={(e) => set("threshold", Number(e.target.value))}
            />
          </div>
        </div>
        <div>
          <label className="microlabel block mb-1">Hold (s)</label>
          <input
            className="field w-full" type="number" min={0} value={form.for_seconds}
            onChange={(e) => set("for_seconds", Number(e.target.value))}
          />
        </div>
        <div>
          <label className="microlabel block mb-1">Severity</label>
          <select className="field w-full" value={form.severity} onChange={(e) => set("severity", e.target.value)}>
            <option>info</option><option>warning</option><option>critical</option>
          </select>
        </div>
      </div>
      <div className="flex gap-2 mt-4">
        <button className="btn btn-primary" onClick={() => save.mutate()} disabled={save.isPending || !form.name}>
          {initial ? "Save changes" : "Create rule"}
        </button>
        <button className="btn" onClick={onDone}>Cancel</button>
      </div>
    </Card>
  );
}

export default function Rules() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api<Rule[]>("/v1/rules") });
  const del = useMutation({
    mutationFn: (id: string) => api(`/v1/rules/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
  const toggle = useMutation({
    mutationFn: (r: Rule) =>
      api(`/v1/rules/${r.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !r.enabled }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });

  return (
    <div>
      <SectionTitle
        right={
          editing == null && (
            <button className="btn btn-primary text-xs" onClick={() => setEditing("new")}>
              + New rule
            </button>
          )
        }
      >
        Threshold rules
      </SectionTitle>
      {editing != null && (
        <RuleForm initial={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />
      )}
      {rules.isLoading && <Spinner />}
      {rules.error != null && <ErrorNote error={rules.error} />}
      {rules.data?.length === 0 && editing == null && (
        <Empty>
          No rules. Create one, or seed defaults: <span className="mono">python scripts/seed_rules.py</span>
        </Empty>
      )}
      <div className="space-y-2">
        {(rules.data ?? []).map((r) => (
          <Card key={r.id} className="px-4 py-3 flex items-center gap-4">
            <button
              onClick={() => toggle.mutate(r)}
              title={r.enabled ? "Disable" : "Enable"}
              className="w-8 h-4.5 rounded-full relative shrink-0 transition-colors"
              style={{ background: r.enabled ? "var(--good)" : "var(--baseline)", height: 18 }}
            >
              <span
                className="absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-all"
                style={{ left: r.enabled ? 16 : 2 }}
              />
            </button>
            <div className="flex-1 min-w-0">
              <span className="font-medium">{r.name}</span>
              <span className="mono text-xs text-ink-2 ml-3">
                {r.metric} {OPS.find((o) => o.v === r.op)?.label} {r.threshold}
                {r.for_seconds > 0 && ` for ${r.for_seconds}s`}
              </span>
            </div>
            <SeverityBadge severity={r.severity} />
            <button className="btn text-xs py-1" onClick={() => setEditing(r)}>Edit</button>
            <button className="btn-danger btn text-xs py-1" onClick={() => del.mutate(r.id)}>Delete</button>
          </Card>
        ))}
      </div>
    </div>
  );
}
