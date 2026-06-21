"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api";
import { peerApi } from "@/lib/fleet";
import { runHref, useRunHost } from "@/lib/runHost";
import { isTerminalVerdict } from "@/lib/verdict";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// 完了 run に追加指示を投じて Implementer を resume + Verifier 監査(同じ run_id を保つ)。
// 同じ session を継続するので前文脈が保たれる。stream に continuation marker を挿入し
// 「中断」と「人間の追加プロンプト」が transcript で見える。
export function ContinuePanel({ runId, verdict }: { runId: string; verdict: string }) {
  const router = useRouter();
  const host = useRunHost();
  const [text, setText] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // 進行中(verdict 未確定)では出さない。完了済みのみ。
  if (!isTerminalVerdict(verdict)) return null;

  const onSubmit = async () => {
    const t = text.trim();
    if (!t) return;
    setSending(true);
    setError(null);
    try {
      await peerApi.continueRun(host, runId, t);
      // 同じ run_id のライブへ。stream に append されているので過去 + 続行が連続して見える。
      router.push(runHref(runId, host, "live"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "続行指示の送信に失敗しました");
      setSending(false);
    }
  };

  return (
    <div className="surface space-y-3 p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">続きを指示する</p>
        <span className="text-xs text-muted-foreground">
          前 session を resume して Implementer → Verifier(同じ run_id)
        </span>
      </div>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="例: テストは pass したけど accept #2 の意図と違う実装になっている。〜の方向に直して。"
        className="text-sm"
      />
      {error ? <p className="text-sm text-verdict-fail">{error}</p> : null}
      <div className="flex justify-end">
        <Button onClick={onSubmit} disabled={sending || !text.trim()}>
          {sending ? "送信中…" : "▶ 続行して走らせる"}
        </Button>
      </div>
    </div>
  );
}
