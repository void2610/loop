"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DeleteTaskButton } from "@/components/tasks/DeleteTaskButton";
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
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [last, setLast] = useState<Record<string, LastRun>>({});
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.listTasks();
      setTasks(res.tasks);
      setLast(res.last);
      setRunning(res.running);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "タスク一覧の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
      {running && (
        <p className="rounded-md border border-verdict-handoff/40 bg-verdict-handoff/10 px-3 py-2 text-sm text-verdict-handoff">
          ● run 実行中(data/.run.lock)。完了まで新規実行は待機されます。
        </p>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>repo</TableHead>
            <TableHead>id</TableHead>
            <TableHead>status</TableHead>
            <TableHead>goal</TableHead>
            <TableHead>最新 run</TableHead>
            <TableHead className="text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.length === 0 ? (
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
                <TableRow key={t.id}>
                  <TableCell>
                    <RepoBadge repo={t.repo} />
                  </TableCell>
                  <TableCell>
                    <Link href={`/tasks/${encodeURIComponent(t.id)}`} className="underline">
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
                        onStarted={() => void load()}
                      />
                      <DeleteTaskButton taskId={t.id} onDeleted={() => void load()} />
                    </div>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">
        実行順はファイル名昇順(先頭の todo が「次」)。「実行」は当該タスクを今すぐ
        background 実行。
      </p>
    </div>
  );
}
