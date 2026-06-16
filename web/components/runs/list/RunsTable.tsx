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

export function RunsTable({ runs }: { runs: RunRow[] }) {
  const router = useRouter();

  if (runs.length === 0) {
    return (
      <div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">
        該当 run なし
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>repo</TableHead>
            <TableHead>run</TableHead>
            <TableHead>verdict</TableHead>
            <TableHead>rev</TableHead>
            <TableHead className="text-right">cost</TableHead>
            <TableHead className="text-right">turns</TableHead>
            <TableHead>started</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((r) => (
            <TableRow
              key={r.run_id}
              className="cursor-pointer"
              onClick={() => router.push(`/runs/${encodeURIComponent(r.run_id)}`)}
            >
              <TableCell>
                <RepoBadge repo={r.repo} />
              </TableCell>
              <TableCell className="font-mono text-xs">{r.run_id}</TableCell>
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
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
