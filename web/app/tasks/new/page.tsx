"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { GenerateForm } from "@/components/tasks/GenerateForm";
import { useMeta } from "@/components/tasks/useMeta";

// 新規タスクをプロンプトから作成(Claude Code が目標契約へ変換)。repo 選択必須 + 自動実行トグル。
export default function NewTaskPage() {
  const { meta, error, loading } = useMeta();

  return (
    <div className="space-y-5">
      <Link
        href="/tasks"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        タスク一覧
      </Link>

      <PageHeader
        title="新規タスク(プロンプト)"
        description="やりたいことを自然言語で。専用 skill を付けて Claude Code に依頼し、検証可能な目標契約(goal / accept / verify / constraints / allowed_tools)へ変換します。生成後に内容を確認・修正できます。"
      />

      {loading && <p className="text-sm text-muted-foreground">読み込み中…</p>}
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {meta && (
        <div className="surface max-w-3xl p-5">
          <GenerateForm repos={meta.repos} />
        </div>
      )}
    </div>
  );
}
