"use client";

import { useState } from "react";

import { Button, type ButtonProps } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { peerApi } from "@/lib/fleet";

// 当該タスクを今すぐ background 実行する(x-loop-exec)。
// .run.lock 進行中は API が 409 busy を返す → そのまま事実として表示する。
// Fleet: host を渡すと該当 peer 経由で実行する(host 空なら自 host)。
export function RunTaskButton({
  taskId,
  host,
  disabled,
  confirmRun = false,
  variant,
  size,
  children,
  onStarted,
}: {
  taskId: string;
  host?: string;
  disabled?: boolean;
  confirmRun?: boolean;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  children?: React.ReactNode;
  onStarted?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    if (
      confirmRun &&
      !window.confirm(`${taskId} を今すぐ実行しますか?(3役 run が background で走ります)`)
    ) {
      return;
    }
    setMsg(null);
    setBusy(true);
    try {
      const res = await peerApi.runTask(host, taskId);
      if (res.accepted) {
        setMsg("▶ 実行を開始しました(background)");
        onStarted?.();
      } else {
        setMsg(res.reason === "busy" ? "他の run が進行中です" : (res.reason ?? "実行できませんでした"));
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setMsg("他の run が進行中のため実行できませんでした");
      } else {
        const m = err instanceof ApiError ? err.message : "実行に失敗しました";
        setMsg(m);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button
        type="button"
        variant={variant ?? "outline"}
        size={size ?? "sm"}
        disabled={disabled || busy}
        onClick={run}
      >
        {children ?? "実行"}
      </Button>
      {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
    </span>
  );
}
