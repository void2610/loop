"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { LiveTranscript } from "./LiveTranscript";

export function RunLivePage({ runId }: { runId: string }) {
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Link
          href="/monitor"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Monitor へ戻る
        </Link>
        <h1 className="text-xl font-bold tracking-tight">ライブ transcript</h1>
        <p className="font-mono text-xs text-muted-foreground">{runId}</p>
      </div>
      <LiveTranscript runId={runId} />
    </div>
  );
}
