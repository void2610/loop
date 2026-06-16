"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";

// プロンプト → 目標契約の生成(202 非ブロッキング)。
// 生成役は runner 側で read-only 強制。GUI/BFF は LLM を呼ばず prompt を中継するだけ。
// repo は必須(推定しない)。auto_run は生成後の即時実行トグル。
export function GenerateForm({ repos }: { repos: string[] }) {
  const [prompt, setPrompt] = useState("");
  const [repo, setRepo] = useState("");
  const [autoRun, setAutoRun] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 'none' は専用選択肢として最後に出すので一覧からは除外する(legacy todo_new.html 踏襲)。
  const registered = repos.filter((r) => r.toLowerCase() !== "none");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!repo) {
      setError("対象リポジトリを選択してください(推定はしません)");
      return;
    }
    if (!prompt.trim()) {
      setError("依頼内容を入力してください");
      return;
    }
    setSubmitting(true);
    try {
      await api.generate({ prompt, repo, auto_run: autoRun });
      setAccepted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "生成の起動に失敗しました");
      setSubmitting(false);
    }
  }

  if (accepted) {
    return (
      <div className="max-w-3xl space-y-3">
        <p className="rounded-md border border-verdict-pass/40 bg-verdict-pass/10 px-3 py-2 text-sm text-verdict-pass">
          生成を受け付けました(Claude Code がタスクを設計中。数十秒)。
          {autoRun && " 生成後そのまま実行されます。"}
        </p>
        <p className="text-sm text-muted-foreground">
          完了すると <a className="underline" href="/tasks">タスク一覧</a> に新しい目標契約が現れます。
          内容を確認・修正してから実行してください。
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="max-w-3xl space-y-5">
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="gen-repo">
          対象リポジトリ{" "}
          <span className="font-normal text-muted-foreground">(必須。推定はしません)</span>
        </Label>
        <select
          id="gen-repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          required
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <option value="" disabled>
            — リポジトリを選択 —
          </option>
          <option value="default">デフォルト</option>
          {registered.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
          <option value="none">none(外部FS・git なし)</option>
        </select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="gen-prompt">依頼内容</Label>
        <Textarea
          id="gen-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          required
          autoFocus
          placeholder={
            "例: package.json のテストが CI で間欠失敗する。原因を直して 10 回連続で通るようにして。\n例: docs/ の壊れた相対リンクを全部見つけて修正して。"
          }
        />
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={autoRun}
          onChange={(e) => setAutoRun(e.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        作成後すぐに自動実行する
      </label>

      <div className="flex items-center gap-4">
        <Button type="submit" disabled={submitting}>
          {submitting ? "生成中…" : "▶ Claude Code に作らせる"}
        </Button>
        <a href="/tasks/new/manual" className="text-sm text-muted-foreground underline">
          手動で書く
        </a>
      </div>
    </form>
  );
}
