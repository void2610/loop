"use client";

import { useRouter } from "next/navigation";

import type { RunRow } from "@/lib/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { ArchiveRunButton } from "@/components/runs/ArchiveRunButton";
import type { RunStatus } from "@/components/monitor/normalize";

import { RepoBadge } from "@/components/repo-badge";
import { VerdictBadge } from "@/components/verdict-badge";

// RunRow は loop.db 行の射影で catch-all キー(cost_usd/turns 等)が unknown 型。
// 表示整形はフロントの責務(§2.2)。数値以外は空表示にして事実を歪めない。
function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function formatCost(v: unknown): string {
  const n = asNumber(v);
  return n === null ? "" : `$${n.toFixed(3)}`;
}

function formatStarted(v: string | null | undefined): string {
  return (v ?? "").slice(0, 19);
}

export function RunsTable({
  runs,
  active = [],
  onChanged,
}: {
  runs: RunRow[];
  active?: RunStatus[];
  onChanged?: () => void;
}) {
  const router = useRouter();

  if (runs.length === 0 && active.length === 0) {
    return (
      <div className="surface flex flex-col items-center gap-1 p-12 text-center">
        <p className="text-sm font-medium text-foreground">該当する run がありません</p>
        <p className="text-xs text-muted-foreground">フィルタを変えるか、タスクを実行すると run が記録されます。</p>
      </div>
    );
  }

  return (
    <div className="surface overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="th-label">repo</TableHead>
            <TableHead className="th-label">run</TableHead>
            <TableHead className="th-label">verdict</TableHead>
            <TableHead className="th-label">rev</TableHead>
            <TableHead className="th-label text-right">cost</TableHead>
            <TableHead className="th-label text-right">turns</TableHead>
            <TableHead className="th-label">started</TableHead>
            <TableHead className="th-label text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {active.map((r) => {
            const awaiting = r.phase === "awaiting";
            return (
            <TableRow
              key={`active-${r.run_id}`}
              className={
                awaiting
                  ? "cursor-pointer bg-verdict-handoff/10 transition-colors hover:bg-verdict-handoff/15"
                  : "cursor-pointer bg-primary/5 transition-colors hover:bg-primary/10"
              }
              onClick={() => router.push(`/runs/${encodeURIComponent(r.run_id)}/live`)}
            >
              <TableCell>
                <RepoBadge repo={r.repo} mono />
              </TableCell>
              <TableCell className="font-mono text-xs text-foreground/90">{r.run_id}</TableCell>
              <TableCell>
                {awaiting ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-verdict-handoff/20 px-2 py-0.5 text-xs font-semibold text-verdict-handoff">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-verdict-handoff" />
                    人間の介入待ち
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                    実行中{r.phase ? ` · ${r.phase}` : ""}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground">·</TableCell>
              <TableCell className="text-right tabular-nums" />
              <TableCell className="text-right tabular-nums" />
              <TableCell className="font-mono text-xs text-muted-foreground">
                {formatStarted(r.started_at)}
              </TableCell>
              <TableCell className="text-right text-xs text-muted-foreground">
                {awaiting ? "指示を送る →" : "ライブ →"}
              </TableCell>
            </TableRow>
            );
          })}
          {runs.map((r) => (
            <TableRow
              key={r.run_id}
              className="cursor-pointer transition-colors hover:bg-accent/40"
              onClick={() => router.push(`/runs/${encodeURIComponent(r.run_id)}`)}
            >
              <TableCell>
                <RepoBadge repo={r.repo} mono />
              </TableCell>
              <TableCell className="font-mono text-xs text-foreground/90">{r.run_id}</TableCell>
              <TableCell>
                <VerdictBadge verdict={r.verdict} emptyDash />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {r.reviewed ? "✓" : "·"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatCost(r["cost_usd"])}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {asNumber(r["turns"]) ?? ""}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {formatStarted(r.started_at)}
              </TableCell>
              <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                <ArchiveRunButton
                  runId={r.run_id}
                  archived={!!r.archived}
                  onChanged={() => onChanged?.()}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
