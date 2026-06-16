"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";

// タスク削除(unlink + commit)。git 履歴には残るが data/tasks/<id>.md を消す。
export function DeleteTaskButton({
  taskId,
  onDeleted,
}: {
  taskId: string;
  onDeleted?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function del() {
    if (!window.confirm(`${taskId} を削除しますか?(git 履歴には残ります)`)) return;
    setError(null);
    setBusy(true);
    try {
      await api.deleteTask(taskId);
      onDeleted?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "削除に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={del}>
        削除
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  );
}
