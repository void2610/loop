"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Save } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/**
 * 承認済み知識(conventions.md)の編集。人間=種類B が知識を磨き込む面(統合・剪定・修正)。
 * promote は追記専用なので、重複や陳腐化した規範を直す唯一の更新口。中身は人間が書く(GUI は生成しない)。
 * 保存は無変換で MD + git に着地させる中継のみ。
 */
export function ConventionsEditor({ repo, initial }: { repo: string; initial: string }) {
  const router = useRouter();
  const [text, setText] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const dirty = text !== initial;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.putConventions(repo, text);
      setSavedAt(new Date().toLocaleTimeString());
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={Math.min(20, Math.max(6, text.split("\n").length + 1))}
        spellCheck={false}
        placeholder="承認済みの規範はまだありません。候補を承認するか、ここに直接書いて保存できます。"
        className="font-mono text-xs leading-relaxed"
      />
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          ここを直接編集して run に注入される知識を更新します(重複の統合・剪定・修正)。
          {savedAt && !dirty && <span className="ml-2 text-foreground">保存しました {savedAt}</span>}
        </p>
        <div className="flex items-center gap-2">
          {error && <span className="text-xs text-destructive">{error}</span>}
          <Button size="sm" disabled={!dirty || saving || pending} onClick={save}>
            <Save className="size-3.5" aria-hidden />
            保存
          </Button>
        </div>
      </div>
    </div>
  );
}
