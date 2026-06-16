"use client";

import Link from "next/link";

import { TaskForm, emptyFields } from "@/components/tasks/TaskForm";
import { useMeta } from "@/components/tasks/useMeta";

// 目標契約を手書きで新規作成する。保存で data/tasks/<id>.md へ書き込み + commit。
export default function NewTaskManualPage() {
  const { meta, error, loading } = useMeta();

  return (
    <div className="space-y-5">
      <p>
        <Link href="/tasks/new" className="text-sm text-muted-foreground underline">
          ← プロンプトから作成
        </Link>
      </p>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">新規タスク(手動)</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          目標契約 / 作成で data/tasks/&lt;id&gt;.md へ書き込み。
        </p>
      </div>

      {loading && <p className="text-sm text-muted-foreground">読み込み中…</p>}
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {meta && (
        <TaskForm
          mode="create"
          initial={emptyFields()}
          repos={meta.repos}
          statuses={meta.statuses}
          body=""
        />
      )}
    </div>
  );
}
