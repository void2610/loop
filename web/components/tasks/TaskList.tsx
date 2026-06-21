"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ArchiveToggle } from "@/components/archive-toggle";
import { ArchiveTaskButton } from "@/components/tasks/ArchiveTaskButton";
import { RepoBadge } from "@/components/repo-badge";
import { RunTaskButton } from "@/components/tasks/RunTaskButton";
import { Badge } from "@/components/ui/badge";
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
  fetchAllPeerTasks,
  getFleetInfo,
  type FleetInfo,
  type TaskRowWithHost,
} from "@/lib/fleet";

type VerdictVariant = "pass" | "fail" | "handoff" | "outline";

function verdictVariant(v: string | null | undefined): VerdictVariant {
  if (v === "pass" || v === "fail" || v === "handoff") return v;
  return "outline";
}

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
  const genActive = generating;
  const selfName = fleetInfo?.self_name ?? "local";
  const showHost = (fleetInfo?.peers.length ?? 0) > 0;

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
        if (fleetInfo.peers.length === 0) {
          // Fleet off: 自 host のみ(従来挙動)。host バッジは self_name で埋める。
          const res = await import("@/lib/api").then((m) => m.api.listTasks(params));
          setTasks(res.tasks.map((t) => ({ ...t, host: selfName })));
          setLast(
            Object.fromEntries(Object.entries(res.last).map(([k, v]) => [lastKey(selfName, k), v])),
          );
          setRunning(res.running);
          setGenerating(res.generating);
          setPeerErrors([]);
        } else {
          const results = await fetchAllPeerTasks(fleetInfo.peers, params);
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
        }
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "タスク一覧の取得に失敗しました");
      } finally {
        setLoading(false);
      }
    },
    [fleetInfo, selfName],
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

      <div className="flex justify-end">
        <ArchiveToggle checked={includeArchived} onChange={setIncludeArchived} />
      </div>

      <div className="surface overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {showHost ? <TableHead className="th-label">host</TableHead> : null}
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
              <TableCell colSpan={showHost ? 6 : 5} className="text-primary">
                ⏳ 生成中 … Claude Code が目標契約を設計しています(数十秒)。完了すると行が確定します。
              </TableCell>
            </TableRow>
          )}
          {tasks.length === 0 && !genActive ? (
            <TableRow>
              <TableCell colSpan={showHost ? 7 : 6} className="text-muted-foreground">
                タスクがありません。「＋ 新規」で追加してください。
              </TableCell>
            </TableRow>
          ) : (
            tasks.map((t) => {
              const lr = t.id ? last[lastKey(t.host, t.id)] : undefined;
              const goalFirst = (t.goal ?? "").split("\n")[0];
              const hostQuery = showHost ? `?host=${encodeURIComponent(t.host)}` : "";
              return (
                <TableRow key={`${t.host}-${t.id}`} className="transition-colors hover:bg-accent/40">
                  {showHost ? (
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {t.host}
                    </TableCell>
                  ) : null}
                  <TableCell>
                    <RepoBadge repo={t.repo} />
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/tasks/${encodeURIComponent(t.id)}${hostQuery}`}
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
                      <Link href={`/runs/${encodeURIComponent(lr.run_id)}${hostQuery}`}>
                        <Badge variant={verdictVariant(lr.verdict)}>
                          {lr.verdict ?? "—"}
                        </Badge>
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-2">
                      <RunTaskButton
                        taskId={t.id}
                        host={showHost && t.host !== selfName ? t.host : undefined}
                        disabled={running}
                        onStarted={() => void load(includeArchived)}
                      />
                      <ArchiveTaskButton
                        taskId={t.id}
                        host={showHost && t.host !== selfName ? t.host : undefined}
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
