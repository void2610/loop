"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ArchiveTaskButton } from "@/components/tasks/ArchiveTaskButton";
import { RepoBadge } from "@/components/tasks/RepoBadge";
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
import { ApiError, api, type LastRun, type TaskRow } from "@/lib/api";

type VerdictVariant = "pass" | "fail" | "handoff" | "outline";

function verdictVariant(v: string | null | undefined): VerdictVariant {
  if (v === "pass" || v === "fail" || v === "handoff") return v;
  return "outline";
}

export function TaskList() {
  // 生成中判定は API の generating(= data/.gen.lock の有無)を唯一の真実にする。
  // URL の ?generating=1 は初回バナーの即時表示シードのみ(ロックが出るまでの一瞬を埋める)。
  const urlGenerating = useSearchParams().get("generating") === "1";
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [last, setLast] = useState<Record<string, LastRun>>({});
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [generating, setGenerating] = useState(urlGenerating);
  const genActive = generating;

  const load = useCallback(async (archived: boolean) => {
    try {
      const res = await api.listTasks({ include_archived: archived || undefined });
      setTasks(res.tasks);
      setLast(res.last);
      setRunning(res.running);
      setGenerating(res.generating); // gen ロックが外れたら必ず false になる(stuck しない)
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "タスク一覧の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(includeArchived);
  }, [load, includeArchived]);

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

      <div className="flex justify-end">
        <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground">
          <input
            type="checkbox"
            className="accent-primary"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          アーカイブ済みも表示
        </label>
      </div>

      <div className="surface overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
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
              <TableCell colSpan={5} className="text-primary">
                ⏳ 生成中 … Claude Code が目標契約を設計しています(数十秒)。完了すると行が確定します。
              </TableCell>
            </TableRow>
          )}
          {tasks.length === 0 && !genActive ? (
            <TableRow>
              <TableCell colSpan={6} className="text-muted-foreground">
                タスクがありません。「＋ 新規」で追加してください。
              </TableCell>
            </TableRow>
          ) : (
            tasks.map((t) => {
              const lr = t.id ? last[t.id] : undefined;
              const goalFirst = (t.goal ?? "").split("\n")[0];
              return (
                <TableRow key={t.id} className="transition-colors hover:bg-accent/40">
                  <TableCell>
                    <RepoBadge repo={t.repo} />
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/tasks/${encodeURIComponent(t.id)}`}
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
                      <Link href={`/runs/${encodeURIComponent(lr.run_id)}`}>
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
                        disabled={running}
                        onStarted={() => void load(includeArchived)}
                      />
                      <ArchiveTaskButton taskId={t.id} archived={!!t.archived} onChanged={() => void load(includeArchived)} />
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
