"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { DeleteTaskButton } from "@/components/tasks/DeleteTaskButton";
import { RepoBadge } from "@/components/tasks/RepoBadge";
import { RunTaskButton } from "@/components/tasks/RunTaskButton";
import { TaskForm } from "@/components/tasks/TaskForm";
import { useMeta } from "@/components/tasks/useMeta";
import { ApiError, api, type TaskDetail } from "@/lib/api";

export function EditTaskClient({ taskId }: { taskId: string }) {
  const router = useRouter();
  const { meta } = useMeta();
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .taskDetail(taskId)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch((err) => {
        if (alive) {
          setError(
            err instanceof ApiError
              ? err.status === 404
                ? `タスクが見つかりません: ${taskId}`
                : err.message
              : "タスクの取得に失敗しました"
          );
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [taskId]);

  if (loading) {
    return <p className="text-sm text-muted-foreground">読み込み中…</p>;
  }
  if (error || !detail) {
    return (
      <div className="space-y-4">
        <p>
          <Link href="/tasks" className="text-sm text-muted-foreground underline">
            ← タスク一覧
          </Link>
        </p>
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error ?? "タスクの取得に失敗しました"}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <p>
        <Link href="/tasks" className="text-sm text-muted-foreground underline">
          ← タスク一覧
        </Link>
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <RepoBadge repo={detail.fields.repo} />
        <h1 className="text-2xl font-bold tracking-tight">{detail.fields.task_id} を編集</h1>
        <span className="text-sm text-muted-foreground">
          (目標契約 / 保存で data/tasks/&lt;id&gt;.md へ書き込み)
        </span>
      </div>

      <TaskForm
        mode="edit"
        initial={detail.fields}
        repos={meta?.repos ?? []}
        statuses={meta?.statuses ?? []}
        body={detail.body}
      />

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <RunTaskButton taskId={detail.fields.task_id} confirmRun variant="default">
          ▶ このタスクを実行
        </RunTaskButton>
        <span className="text-sm text-muted-foreground">
          未保存の編集は反映されません。先に保存してください。
        </span>
        <div className="ml-auto">
          <DeleteTaskButton
            taskId={detail.fields.task_id}
            onDeleted={() => {
              router.push("/tasks");
              router.refresh();
            }}
          />
        </div>
      </div>
    </div>
  );
}
