"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { TaskForm, emptyFields } from "@/components/tasks/TaskForm";
import { useMeta } from "@/components/tasks/useMeta";

// 目標契約を手書きで新規作成する。保存で data/tasks/<id>.md へ書き込み + commit。
export default function NewTaskManualPage() {
  const { meta, error, loading } = useMeta();

  return (
    <div className="space-y-5">
      <Link
        href="/tasks/new"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        プロンプトから作成
      </Link>

      <PageHeader
        title="新規タスク(手動)"
        description="目標契約を手書きで。作成で data/tasks/<id>.md へ書き込み + commit。"
      />

      {loading && <p className="text-sm text-muted-foreground">読み込み中…</p>}
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {meta && (
        <div className="surface p-5">
          <TaskForm
            mode="create"
            initial={emptyFields()}
            repos={meta.repos}
            statuses={meta.statuses}
            body=""
          />
        </div>
      )}
    </div>
  );
}
