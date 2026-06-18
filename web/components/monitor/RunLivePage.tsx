"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { InterventionPanel } from "./InterventionPanel";
import { LiveTranscript } from "./LiveTranscript";
import { StopRunButton } from "./StopRunButton";

export function RunLivePage({ runId }: { runId: string }) {
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
              href={`/runs/${encodeURIComponent(runId)}`}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              詳細
            </Link>
          </div>
          <StopRunButton runId={runId} />
        </div>
        <h1 className="text-xl font-bold tracking-tight">ライブ transcript</h1>
        <p className="font-mono text-xs text-muted-foreground">{runId}</p>
      </div>
      <InterventionPanel runId={runId} />
      <LiveTranscript runId={runId} />
    </div>
  );
}
