"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { repoLabel } from "@/lib/repoLabel";

import { ROLES } from "./useRunLive";
import type { RunStatus } from "./normalize";

function fmtElapsed(sec?: number): string {
  if (typeof sec !== "number" || sec < 0) return "--:--";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// Explorer→Implementer→Verifier の phase ステッパ。事実(.run.lock の phase)の表示のみ。
function PhaseStepper({ phase }: { phase?: string }) {
  const idx = ROLES.findIndex((r) => r.key === phase);
  return (
    <div className="flex items-center gap-1.5">
      {ROLES.map((r, i) => {
        const done = idx >= 0 && i < idx;
        const current = idx >= 0 && i === idx;
        return (
          <div key={r.key} className="flex items-center gap-1.5">
            <span
              className={
                current
                  ? "inline-flex items-center gap-1 rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary"
                  : done
                    ? "inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    : "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs text-muted-foreground/50"
              }
            >
              {current ? (
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
              ) : null}
              {r.label}
            </span>
            {i < ROLES.length - 1 ? (
              <span className="text-muted-foreground/40">›</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function RunStatusCard({ run }: { run: RunStatus }) {
  return (
    <Link href={`/runs/${encodeURIComponent(run.run_id)}/live`} className="block">
      <Card className="transition-colors hover:border-primary">
        <CardHeader className="space-y-2 pb-3">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base">{run.task ?? run.run_id}</CardTitle>
            <Badge variant="outline">{repoLabel(run.repo)}</Badge>
          </div>
          <p className="font-mono text-xs text-muted-foreground">{run.run_id}</p>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-3 pt-0">
          <PhaseStepper phase={run.phase} />
          <span className="font-mono text-sm tabular-nums text-muted-foreground">
            {fmtElapsed(run.elapsed)}
          </span>
        </CardContent>
      </Card>
    </Link>
  );
}
