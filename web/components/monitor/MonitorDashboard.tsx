"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { repoLabel } from "@/lib/repoLabel";
import type { RunRow } from "@/lib/api";

import { RunStatusCard } from "./RunStatusCard";
import { useMonitorStream } from "./useMonitorStream";

function verdictVariant(v?: string | null): "pass" | "fail" | "handoff" | "outline" {
  if (v === "pass" || v === "fail" || v === "handoff") return v;
  return "outline";
}

function RecentRow({ row }: { row: RunRow }) {
  return (
    <Link
      href={`/runs/${encodeURIComponent(row.run_id)}`}
      className="flex items-center justify-between gap-3 rounded-md px-3 py-2 transition-colors hover:bg-accent"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{row.task ?? row.run_id}</p>
        <p className="truncate font-mono text-xs text-muted-foreground">{row.run_id}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant="outline">{repoLabel(row.repo)}</Badge>
        {row.verdict ? (
          <Badge variant={verdictVariant(row.verdict)}>{row.verdict}</Badge>
        ) : null}
        {row.reviewed ? null : (
          <Badge variant="secondary" className="text-[10px]">
            未レビュー
          </Badge>
        )}
      </div>
    </Link>
  );
}

export function MonitorDashboard() {
  const { runs, recent, unreviewed, pending, connected, loading, error } =
    useMonitorStream();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Monitor"
        description="進行中 run のライブ監視(SSE)。事実の表示のみ — 判断・要約は生成しない。"
        actions={
          <Badge variant="outline" className="gap-1.5">
            <span
              className={
                connected
                  ? "h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500"
                  : "h-1.5 w-1.5 rounded-full bg-muted-foreground"
              }
            />
            {connected ? "ストリーム接続中" : "未接続"}
          </Badge>
        }
      />

      {error ? (
        <Card>
          <CardContent className="py-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardContent className="flex items-baseline justify-between py-4">
            <span className="text-sm text-muted-foreground">未レビュー</span>
            <span className="text-2xl font-bold tabular-nums">{unreviewed}</span>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-baseline justify-between py-4">
            <span className="text-sm text-muted-foreground">未着手 TODO</span>
            <span className="text-2xl font-bold tabular-nums">{pending}</span>
          </CardContent>
        </Card>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground">進行中の run</h2>
        {runs.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {loading ? "読み込み中…" : "進行中の run はありません。"}
            </CardContent>
          </Card>
        ) : (
          // 最初から配列 grid(§3.7-5): 並列化が来ても N>1 でコード変更不要。
          <div className="grid gap-4 lg:grid-cols-2">
            {runs.map((r) => (
              <RunStatusCard key={r.run_id} run={r} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground">最近の run</h2>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">直近の完了 run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-0.5 pt-0">
            {recent.length === 0 ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">まだありません。</p>
            ) : (
              recent.map((row) => <RecentRow key={row.run_id} row={row} />)
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
