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

import { RepoBadge } from "./RepoBadge";
import { RunVerdictBadge } from "./RunVerdictBadge";

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

export function RunsTable({ runs, onChanged }: { runs: RunRow[]; onChanged?: () => void }) {
  const router = useRouter();

  if (runs.length === 0) {
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
          {runs.map((r) => (
            <TableRow
              key={r.run_id}
              className="cursor-pointer transition-colors hover:bg-accent/40"
              onClick={() => router.push(`/runs/${encodeURIComponent(r.run_id)}`)}
            >
              <TableCell>
                <RepoBadge repo={r.repo} />
              </TableCell>
              <TableCell className="font-mono text-xs text-foreground/90">{r.run_id}</TableCell>
              <TableCell>
                <RunVerdictBadge verdict={r.verdict} />
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
