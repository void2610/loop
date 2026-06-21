"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import * as React from "react";

import { getFleetInfo, resolvePeerBase, type FleetInfo } from "@/lib/fleet";
import { runHref } from "@/lib/runHost";

import { InterventionPanel } from "./InterventionPanel";
import { LiveTranscript } from "./LiveTranscript";
import { StopRunButton } from "./StopRunButton";

export function RunLivePage({ runId, host }: { runId: string; host?: string }) {
  // Fleet info を初回 fetch。host が指定されたとき peer.url を解決して SSE の base に渡す。
  // 解決前に LiveTranscript を出すと一瞬 self を購読してしまうので、fleet ロード後に render する。
  const [fleet, setFleet] = React.useState<FleetInfo | null>(null);
  React.useEffect(() => {
    void getFleetInfo()
      .then(setFleet)
      .catch(() => setFleet({ self_name: null, peers: [] }));
  }, []);

  const peerBase = resolvePeerBase(fleet, host);

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Link
              href="/runs"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Runs
            </Link>
            <Link
              href={runHref(runId, host)}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              詳細
            </Link>
          </div>
          <StopRunButton runId={runId} host={host} />
        </div>
        <h1 className="text-xl font-bold tracking-tight">ライブ transcript</h1>
        <p className="font-mono text-xs text-muted-foreground">
          {runId}
          {host ? (
            <span className="ml-2 rounded bg-muted px-1.5 py-0.5">host: {host}</span>
          ) : null}
        </p>
      </div>
      <InterventionPanel runId={runId} host={host} />
      {fleet === null ? (
        <div className="rounded-lg border border-border p-6 text-center text-sm text-muted-foreground">
          Fleet 情報を解決中…
        </div>
      ) : (
        <LiveTranscript runId={runId} peerBase={peerBase} />
      )}
    </div>
  );
}
