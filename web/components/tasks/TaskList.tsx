"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ArchiveToggle } from "@/components/archive-toggle";
import { ArchiveTaskButton } from "@/components/tasks/ArchiveTaskButton";
import { RepoBadge } from "@/components/repo-badge";
import { RunTaskButton } from "@/components/tasks/RunTaskButton";
import { VerdictBadge } from "@/components/verdict-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, type LastRun } from "@/lib/api";
import {
  fetchAllPeerGens,
  fetchAllPeerTasks,
  getFleetInfo,
  type FleetInfo,
  type GenSummaryWithHost,
  type TaskRowWithHost,
} from "@/lib/fleet";
import { runHref, taskHref } from "@/lib/runHost";

// host バッジ付きの LastRun キー: "<host>::<task_id>"(同 id が host を跨いで衝突しても分離する)
function lastKey(host: string, taskId: string): string {
  return `${host}::${taskId}`;
}

export function TaskList() {
  // 生成中判定は API の generating(= data/.gen.lock の有無)を唯一の真実にする。
  // URL の ?generating=1 は初回バナーの即時表示シードのみ(ロックが出るまでの一瞬を埋める)。
  const urlGenerating = useSearchParams().get("generating") === "1";
  const [tasks, setTasks] = useState<TaskRowWithHost[]>([]);
  const [last, setLast] = useState<Record<string, LastRun>>({});
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [generating, setGenerating] = useState(urlGenerating);
  // Fleet: peers が空なら自 host のみ。複数 peer ならすべてから merge fetch。
  const [fleetInfo, setFleetInfo] = useState<FleetInfo | null>(null);
  const [peerErrors, setPeerErrors] = useState<{ name: string; error: string }[]>([]);
  const [gens, setGens] = useState<GenSummaryWithHost[]>([]);
  const genActive = generating;

  useEffect(() => {
    void getFleetInfo()
      .then(setFleetInfo)
      .catch(() => setFleetInfo({ self_name: null, peers: [] }));
  }, []);

  const load = useCallback(
    async (archived: boolean) => {
      if (!fleetInfo) return;
      try {
        const params = { include_archived: archived || undefined };
        // backend は peers 設定が空でも自 host を 1 件返す。常に全 peer 並列 fetch。
        const results = await fetchAllPeerTasks(fleetInfo.peers, params);
        // 同タイミングで生成履歴も refresh(失敗 / 実行中も上部に出すため)
        void fetchAllPeerGens(fleetInfo.peers, 10).then(setGens);
        const mergedTasks = results.flatMap((r) => r.tasks);
        const mergedLast: Record<string, LastRun> = {};
        let anyRunning = false;
        let anyGenerating = false;
        for (const r of results) {
          for (const [tid, lr] of Object.entries(r.last)) {
            mergedLast[lastKey(r.peer.name, tid)] = lr;
          }
          if (r.running) anyRunning = true;
          if (r.generating) anyGenerating = true;
        }
        setTasks(mergedTasks);
        setLast(mergedLast);
        setRunning(anyRunning);
        setGenerating(anyGenerating);
        setPeerErrors(
          results.filter((r) => !r.ok).map((r) => ({ name: r.peer.name, error: r.error ?? "unknown" })),
        );
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "タスク一覧の取得に失敗しました");
      } finally {
        setLoading(false);
      }
    },
    [fleetInfo],
  );

  useEffect(() => {
    if (!fleetInfo) return;
    void load(includeArchived);
  }, [load, includeArchived, fleetInfo]);

  // 生成中(gen ロック有り)の間だけ 3s ポーリング。ロックが外れれば次の poll で停止する。
  useEffect(() => {
    if (!generating) return;
    const iv = setInterval(() => void load(includeArchived), 3000);
    return () => clearInterval(iv);
  }, [generating, includeArchived, load]);

  if (loading) {
    return <p className="text-sm text-muted-foreground">読み込み中…</p>;
  }
  if (error) {
    return (
      <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {error}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {genActive && (
        <p className="flex items-center gap-2 rounded-md border border-primary/40 bg-primary/10 px-3 py-2 text-sm text-primary">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary" />
          ⏳ タスクを生成中(Claude Code が目標契約を設計中・数十秒)。完了すると下の一覧に現れます。
        </p>
      )}

      {running && (
        <p className="rounded-md border border-verdict-handoff/40 bg-verdict-handoff/10 px-3 py-2 text-sm text-verdict-handoff">
          ● run 実行中(data/.run.lock)。完了まで新規実行は待機されます。
        </p>
      )}

      {peerErrors.length > 0 ? (
        <div className="rounded-lg border border-verdict-fail/40 bg-verdict-fail/5 p-3 text-sm">
          <p className="font-medium text-verdict-fail">到達できなかった host があります(タスクを取得できず)</p>
          <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
            {peerErrors.map((p) => (
              <li key={p.name}>
                <span className="font-mono">{p.name}</span>: {p.error}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {(() => {
        // 30 分超で完了した生成は出さない(実行中・直近のみ残す)。
        // gen_id の prefix `YYYY-MM-DD-HHMMSS` を時刻として読む(信頼できる唯一の時刻情報)。
        const cutoff = Date.now() - 30 * 60 * 1000;
        const _re = /^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})/;
        const recentGens = gens.filter((g) => {
          if (g.status === "running") return true;
          const m = _re.exec(g.gen_id);
          if (!m) return true;
          const t = new Date(
            Number(m[1]), Number(m[2]) - 1, Number(m[3]),
            Number(m[4]), Number(m[5]), Number(m[6]),
          ).getTime();
          return t >= cutoff;
        });
        return recentGens.length > 0 ? (
        <div className="space-y-2">
          <p className="th-label">
            最近の生成試行(直近 30 分・実行中)
            <span className="ml-2 font-normal tabular-nums text-muted-foreground">
              {recentGens.length}
            </span>
          </p>
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
            {recentGens.map((g) => {
              const color =
                g.status === "ok"
                  ? "text-verdict-pass"
                  : g.status === "fail"
                    ? "text-verdict-fail"
                    : "text-primary";
              const label =
                g.status === "ok" ? "✓ 生成完了" : g.status === "fail" ? "✗ 失敗" : "● 実行中";
              return (
                <li key={`${g.host}-${g.gen_id}`} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className={`shrink-0 ${color}`}>{label}</span>
                  <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                    {g.host}
                  </span>
                  <Link
                    href={`/tasks/new/generating?id=${encodeURIComponent(g.gen_id)}&host=${encodeURIComponent(g.host)}`}
                    className="shrink-0 font-mono text-xs text-foreground underline-offset-2 hover:underline"
                  >
                    {g.gen_id}
                  </Link>
                  {g.task_id ? (
                    <Link
                      href={taskHref(g.task_id, g.host)}
                      className="shrink-0 rounded border border-border px-1.5 py-0.5 text-xs hover:bg-accent"
                    >
                      {g.task_id}
                    </Link>
                  ) : null}
                  {g.error ? (
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                      {g.error}
                    </span>
                  ) : (
                    <span className="min-w-0 flex-1" />
                  )}
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">
                    {g.started_at ?? ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null;
      })()}

      <div className="flex justify-end">
        <ArchiveToggle checked={includeArchived} onChange={setIncludeArchived} />
      </div>

      <div className="surface overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="th-label">host</TableHead>
            <TableHead className="th-label">repo</TableHead>
            <TableHead className="th-label">id</TableHead>
            <TableHead className="th-label">status</TableHead>
            <TableHead className="th-label">goal</TableHead>
            <TableHead className="th-label">最新 run</TableHead>
            <TableHead className="th-label text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {genActive && (
            <TableRow className="bg-primary/5">
              <TableCell>
                <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary align-middle" />
              </TableCell>
              <TableCell colSpan={6} className="text-primary">
                ⏳ 生成中 … Claude Code が目標契約を設計しています(数十秒)。完了すると行が確定します。
              </TableCell>
            </TableRow>
          )}
          {tasks.length === 0 && !genActive ? (
            <TableRow>
              <TableCell colSpan={7} className="text-muted-foreground">
                タスクがありません。「＋ 新規」で追加してください。
              </TableCell>
            </TableRow>
          ) : (
            tasks.map((t) => {
              const lr = t.id ? last[lastKey(t.host, t.id)] : undefined;
              const goalFirst = (t.goal ?? "").split("\n")[0];
              return (
                <TableRow key={`${t.host}-${t.id}`} className="transition-colors hover:bg-accent/40">
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {t.host}
                  </TableCell>
                  <TableCell>
                    <RepoBadge repo={t.repo} />
                  </TableCell>
                  <TableCell>
                    <Link
                      href={taskHref(t.id, t.host)}
                      className="font-mono text-xs font-medium text-foreground/90 hover:text-primary hover:underline"
                    >
                      {t.id}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {t.status ?? "todo"}
                  </TableCell>
                  <TableCell className="max-w-md truncate text-muted-foreground">
                    {goalFirst}
                  </TableCell>
                  <TableCell>
                    {lr ? (
                      <Link href={runHref(lr.run_id, t.host)}>
                        <VerdictBadge verdict={lr.verdict} emptyDash />
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-2">
                      <RunTaskButton
                        taskId={t.id}
                        host={t.host}
                        disabled={running}
                        onStarted={() => void load(includeArchived)}
                      />
                      <ArchiveTaskButton
                        taskId={t.id}
                        host={t.host}
                        archived={!!t.archived}
                        onChanged={() => void load(includeArchived)}
                      />
                    </div>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        実行順はファイル名昇順(先頭の todo が「次」)。「実行」は当該タスクを今すぐ
        background 実行。
      </p>
    </div>
  );
}
