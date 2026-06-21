"use client";

import { useState } from "react";
import { Archive, ArchiveRestore } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { peerApi } from "@/lib/fleet";

// タスクのアーカイブ/解除。削除はしない(ログは資産)。archived フラグを立てて UI から隠すだけ。
// Fleet: host を渡すと該当 peer 経由でアーカイブ操作。
export function ArchiveTaskButton({
  taskId,
  host,
  archived = false,
  onChanged,
}: {
  taskId: string;
  host?: string;
  archived?: boolean;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setError(null);
    setBusy(true);
    try {
      await peerApi.archiveTask(host, taskId, !archived);
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  const label = archived ? "アーカイブ解除" : "アーカイブ";
  return (
    <span className="inline-flex items-center gap-1.5">
      {error && <span className="text-xs text-destructive">{error}</span>}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={busy}
        onClick={toggle}
        title={label}
        aria-label={label}
        className="size-8 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
      >
        {archived ? <ArchiveRestore /> : <Archive />}
      </Button>
    </span>
  );
}
