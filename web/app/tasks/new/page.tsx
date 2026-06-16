"use client";

import Link from "next/link";

import { GenerateForm } from "@/components/tasks/GenerateForm";
import { useMeta } from "@/components/tasks/useMeta";

// 新規タスクをプロンプトから作成(Claude Code が目標契約へ変換)。repo 選択必須 + 自動実行トグル。
export default function NewTaskPage() {
  const { meta, error, loading } = useMeta();

  return (
    <div className="space-y-5">
      <p>
        <Link href="/tasks" className="text-sm text-muted-foreground underline">
          ← タスク一覧
        </Link>
      </p>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          新規タスクをプロンプトから作成
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          やりたいことを自然言語で書いてください。専用 skill を付けて Claude Code に依頼し、
          検証可能な目標契約(goal / accept / verify / constraints / allowed_tools)へ変換します。
          生成後に内容を確認・修正できます。
        </p>
      </div>

      {loading && <p className="text-sm text-muted-foreground">読み込み中…</p>}
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {meta && <GenerateForm repos={meta.repos} />}
    </div>
  );
}
