"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";

import { ArchiveTaskButton } from "@/components/tasks/ArchiveTaskButton";
import { RepoBadge } from "@/components/repo-badge";
import { RunTaskButton } from "@/components/tasks/RunTaskButton";
import { TaskForm } from "@/components/tasks/TaskForm";
import { useMeta } from "@/components/tasks/useMeta";
import { Badge } from "@/components/ui/badge";
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
  const backLink = (
    <Link
      href="/tasks"
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="size-4" aria-hidden />
      タスク一覧
    </Link>
  );

  if (error || !detail) {
    return (
      <div className="space-y-4">
        {backLink}
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error ?? "タスクの取得に失敗しました"}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {backLink}

      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 pb-4">
        <RepoBadge repo={detail.fields.repo} />
        <h1 className="font-mono text-lg font-bold tracking-tight">{detail.fields.task_id}</h1>
        <Badge variant="outline" className="text-muted-foreground">編集</Badge>
        <div className="ml-auto">
          <ArchiveTaskButton
            taskId={detail.fields.task_id}
            onChanged={() => {
              router.push("/tasks");
              router.refresh();
            }}
          />
        </div>
      </div>

      <div className="surface p-5">
        <TaskForm
          mode="edit"
          initial={detail.fields}
          repos={meta?.repos ?? []}
          statuses={meta?.statuses ?? []}
          body={detail.body}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-border/60 pt-4">
        <RunTaskButton taskId={detail.fields.task_id} confirmRun variant="default">
          ▶ このタスクを実行
        </RunTaskButton>
        <span className="text-sm text-muted-foreground">
          未保存の編集は反映されません。先に保存してください。
        </span>
      </div>
    </div>
  );
}
