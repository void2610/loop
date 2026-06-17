"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";

// タスクのアーカイブ/解除。削除はしない(ログは資産)。archived フラグを立てて UI から隠すだけ。
export function ArchiveTaskButton({
  taskId,
  archived = false,
  onChanged,
}: {
  taskId: string;
  archived?: boolean;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setError(null);
    setBusy(true);
    try {
      await api.archiveTask(taskId, !archived);
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={toggle}>
        {archived ? "アーカイブ解除" : "アーカイブ"}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  );
}
