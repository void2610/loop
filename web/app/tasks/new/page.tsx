"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { GenerateForm } from "@/components/tasks/GenerateForm";

// 新規タスクをプロンプトから作成(Claude Code が目標契約へ変換)。host / repo 選択必須 + 自動実行トグル。
// Fleet: GenerateForm が内部で fleetInfo を取り host セレクタを出す(repos / branches は該当 host から取得)。
export default function NewTaskPage() {
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

      <div className="surface max-w-3xl p-5">
        <GenerateForm />
      </div>
    </div>
  );
}
