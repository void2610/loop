"use client";

import { useState } from "react";
import { Archive, ArchiveRestore } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { peerApi } from "@/lib/fleet";
import { useRunHost } from "@/lib/runHost";

// run のアーカイブ/解除。削除はしない(run=契約・真実の源)。UI から隠すだけ。
// Fleet: RunHostContext から host を取り、該当 peer 経由でアーカイブ操作する。
export function ArchiveRunButton({
  runId,
  archived = false,
  onChanged,
  host: hostProp,
}: {
  runId: string;
  archived?: boolean;
  onChanged?: () => void;
  /** Context を介さない呼び出し(RunsTable 行)で直接 host を渡す抜け道 */
  host?: string;
}) {
  const ctxHost = useRunHost();
  const host = hostProp ?? ctxHost;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setError(null);
    setBusy(true);
    try {
      await peerApi.archiveRun(host, runId, !archived);
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
