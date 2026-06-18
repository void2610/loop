"use client";

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// awaiting 中の run に人間の続行指示を送るパネル。
// 事実(エージェントが詰まった理由)を表示し、人間が自由記述で指示する。GUI は選択肢・判断を生成しない。
export function InterventionPanel({ runId }: { runId: string }) {
  const [awaiting, setAwaiting] = React.useState(false);
  const [question, setQuestion] = React.useState<string | null>(null);
  const [text, setText] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const snap = await api.runLive(runId);
        if (!alive) return;
        const phase = (snap.status as { phase?: string } | null)?.phase;
        setAwaiting(phase === "awaiting");
        setQuestion(snap.intervention ?? null);
      } catch {
        /* 一時的な取得失敗は無視(次の poll で回復) */
      }
    };
    void poll();
    const t = setInterval(poll, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [runId]);

  const onSend = async () => {
    const t = text.trim();
    if (!t) return;
    setSending(true);
    setError(null);
    try {
      await api.sendMessage(runId, t);
      setText("");
      setNotice("続行指示を送信しました。同一セッションで続行します…");
      setAwaiting(false); // 送信後は次の poll で awaiting が解ける
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "送信に失敗しました");
    } finally {
      setSending(false);
    }
  };

  if (!awaiting) {
    return notice ? <p className="text-sm text-muted-foreground">{notice}</p> : null;
  }

  return (
    <div className="surface space-y-3 border-verdict-handoff/40 p-4">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 animate-pulse rounded-full bg-verdict-handoff" />
        <p className="text-sm font-medium text-foreground">人間の続行指示を待っています(awaiting)</p>
      </div>
      {question ? (
        <div className="space-y-1">
          <p className="th-label">エージェントが詰まった理由(事実)</p>
          <p className="whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-sm text-foreground/90">{question}</p>
        </div>
      ) : null}
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="続行指示・選択の決定を書く(同一セッションへそのまま渡されます)"
        className="text-sm"
      />
      {error ? <p className="text-sm text-verdict-fail">{error}</p> : null}
      <div className="flex justify-end">
        <Button onClick={onSend} disabled={sending || !text.trim()}>
          {sending ? "送信中…" : "続行指示を送る"}
        </Button>
      </div>
    </div>
  );
}
