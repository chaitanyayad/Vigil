import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LedgerBatch } from "../api/types";
import { Card, Empty, ErrorNote, SectionTitle, Spinner } from "../components/ui";
import { shortHash, timeAgo } from "../lib/ws";

const SEPOLIA_ETHERSCAN = "https://sepolia.etherscan.io/tx/";

function TxLink({ batch }: { batch: LedgerBatch }) {
  if (!batch.tx_hash) return <span className="text-muted">–</span>;
  if (batch.chain_id === 11155111) {
    return (
      <a
        className="mono text-xs hover:underline"
        style={{ color: "var(--s1)" }}
        href={`${SEPOLIA_ETHERSCAN}${batch.tx_hash}`}
        target="_blank"
        rel="noreferrer"
      >
        {shortHash(batch.tx_hash, 14)} ↗
      </a>
    );
  }
  return (
    <span
      className="mono text-xs"
      title={`${batch.tx_hash} — local Anvil chain (id ${batch.chain_id}); inspect with: cast tx ${batch.tx_hash}`}
    >
      {shortHash(batch.tx_hash, 14)}{" "}
      <span className="text-muted">(anvil)</span>
    </span>
  );
}

const STATUS_COLOR = { anchored: "var(--good)", pending: "var(--warn)", failed: "var(--crit)" };

export default function Ledger() {
  const qc = useQueryClient();
  const batches = useQuery({
    queryKey: ["ledger"],
    queryFn: () => api<LedgerBatch[]>("/v1/ledger/batches"),
    refetchInterval: 20000,
  });
  const anchor = useMutation({
    mutationFn: () => api("/v1/ledger/anchor", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ledger"] }),
  });

  const anchored = (batches.data ?? []).filter((b) => b.status === "anchored").length;

  return (
    <div>
      <SectionTitle
        right={
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted">{anchored} anchored on-chain</span>
            <button className="btn text-xs" onClick={() => anchor.mutate()} disabled={anchor.isPending}>
              {anchor.isPending ? "Anchoring…" : "Anchor pending now"}
            </button>
          </div>
        }
      >
        Incident ledger
      </SectionTitle>
      <p className="text-xs text-muted mb-4 max-w-2xl">
        Every alert lifecycle event is hashed into an append-only chain; batches of events are
        Merkle-rooted and the 32-byte root anchored on-chain. Use “Verify integrity” on any alert to
        prove its history was not edited — or try{" "}
        <span className="mono">python scripts/tamper.py</span> and watch verification fail.
      </p>
      {anchor.error != null && <ErrorNote error={anchor.error} />}
      {batches.isLoading && <Spinner />}
      {batches.data?.length === 0 && <Empty>No batches yet — alert events will be batched automatically.</Empty>}
      {(batches.data ?? []).length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="microlabel text-left border-b hairline">
                <th className="px-4 py-2.5 font-medium">Batch</th>
                <th className="px-4 py-2.5 font-medium">Events</th>
                <th className="px-4 py-2.5 font-medium">Merkle root</th>
                <th className="px-4 py-2.5 font-medium">Tx</th>
                <th className="px-4 py-2.5 font-medium">Block</th>
                <th className="px-4 py-2.5 font-medium">Anchored</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {(batches.data ?? []).map((b) => (
                <tr key={b.id} className="border-b hairline last:border-0">
                  <td className="px-4 py-2.5 mono">#{b.id}</td>
                  <td className="px-4 py-2.5 mono text-ink-2">
                    {b.first_event_id}–{b.last_event_id}
                  </td>
                  <td className="px-4 py-2.5 mono text-ink-2" title={b.merkle_root}>
                    {shortHash(b.merkle_root, 16)}
                  </td>
                  <td className="px-4 py-2.5"><TxLink batch={b} /></td>
                  <td className="px-4 py-2.5 mono text-ink-2">{b.block_number ?? "–"}</td>
                  <td className="px-4 py-2.5 text-muted text-xs">
                    {b.anchored_at ? timeAgo(b.anchored_at) : "–"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className="text-xs font-medium uppercase tracking-wider"
                      style={{ color: STATUS_COLOR[b.status] }}
                    >
                      {b.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
