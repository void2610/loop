"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { api, ApiError, type TranscriptEvent } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { TranscriptEventView } from "@/components/monitor/TranscriptEventView";

// 完成 run の transcript を会話ビューで表示(レガシー /run/<id>/transcript の移植)。
// 整形済みイベント(_parse_transcript 由来)を GET /api/runs/{id}/transcript から取り、
// monitor のライブ表示と同じ TranscriptEventView で描く(事実の整形のみ。要約・判断はしない)。
export function TranscriptView({ runId }: { runId: string }) {
  const [events, setEvents] = useState<TranscriptEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.runTranscript(runId);
        const evs = (data.events ?? []) as unknown as TranscriptEvent[];
        if (!cancelled) setEvents(evs);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof ApiError
              ? e.status === 404
                ? "この run に transcript はありません。"
                : e.message
              : "読み込みに失敗しました"
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link
          href={`/runs/${encodeURIComponent(runId)}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> run 詳細へ戻る
        </Link>
      </div>
      <div>
        <h1 className="text-xl font-bold tracking-tight">transcript</h1>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{runId}</p>
      </div>

      {error ? <p className="text-sm text-verdict-fail">{error}</p> : null}
      {events === null && error === null ? (
        <p className="text-sm text-muted-foreground">読み込み中…</p>
      ) : null}
      {events !== null && events.length === 0 ? (
        <p className="text-sm text-muted-foreground">イベントなし。</p>
      ) : null}

      {events !== null && events.length > 0 ? (
        <Card>
          <CardContent className="space-y-1 p-2">
            {events.map((ev, i) => (
              <TranscriptEventView key={i} ev={ev} />
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
