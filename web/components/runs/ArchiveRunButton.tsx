"use client";

import { useState } from "react";
import { Archive, ArchiveRestore } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";

// run のアーカイブ/解除。削除はしない(run=契約・真実の源)。UI から隠すだけ。
export function ArchiveRunButton({
  runId,
  archived = false,
  onChanged,
}: {
  runId: string;
  archived?: boolean;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setError(null);
    setBusy(true);
    try {
      await api.archiveRun(runId, !archived);
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
