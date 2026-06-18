"use client";

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";

// 実行中/awaiting の run を停止する。active な間だけ表示し、停止すると stopped で正常終了する。
export function StopRunButton({ runId }: { runId: string }) {
  const [active, setActive] = React.useState(false);
  const [stopping, setStopping] = React.useState(false);
  const [requested, setRequested] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const snap = await api.runLive(runId);
        if (!alive) return;
        const phase = (snap.status as { phase?: string } | null)?.phase;
        setActive(snap.status != null && phase !== "done");
      } catch {
        /* 取得失敗は無視 */
      }
    };
    void poll();
    const t = setInterval(poll, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [runId]);

  if (requested) {
    return <span className="text-xs text-muted-foreground">停止を要求しました(まもなく終了)</span>;
  }
  if (!active) return null;

  const onStop = async () => {
    setStopping(true);
    setError(null);
    try {
      await api.stopRun(runId);
      setRequested(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "停止に失敗しました");
      setStopping(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={onStop}
        disabled={stopping}
        className="border-verdict-fail/40 text-verdict-fail hover:bg-verdict-fail/10 hover:text-verdict-fail"
      >
        {stopping ? "停止中…" : "この run を停止"}
      </Button>
      {error ? <span className="text-xs text-verdict-fail">{error}</span> : null}
    </div>
  );
}
