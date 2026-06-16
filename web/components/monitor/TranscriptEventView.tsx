"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import type { RunStreamEventData } from "@/lib/sse";

// cls ごとの色分け(現行 monitor_live.html の表示分岐を移植)。事実の整形のみ。
const CLS_STYLE: Record<string, string> = {
  user: "border-l-sky-500/60 bg-sky-500/5",
  assistant: "border-l-emerald-500/60 bg-emerald-500/5",
  think: "border-l-violet-500/50 bg-violet-500/5",
  tool: "border-l-amber-500/60 bg-amber-500/5",
  result: "border-l-zinc-500/50 bg-zinc-500/5",
};

function clsStyle(cls: string): string {
  return CLS_STYLE[cls] ?? "border-l-border bg-muted/20";
}

/** collapse:true(_parse_transcript 由来の純粋な表示ヒント)は初期折り畳み。 */
export function TranscriptEventView({ ev }: { ev: RunStreamEventData }) {
  const cls = typeof ev.cls === "string" ? ev.cls : "";
  const label = typeof ev.label === "string" ? ev.label : cls;
  const body = typeof ev.body === "string" ? ev.body : "";
  const ts = typeof ev.ts === "string" ? ev.ts : "";
  const collapse = ev.collapse === true;

  const [open, setOpen] = React.useState(!collapse);

  const header = (
    <div className="flex items-center gap-2 text-xs">
      {collapse ? (
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90"
          )}
        />
      ) : null}
      <span className="font-medium text-foreground">{label}</span>
      {ts ? <span className="text-muted-foreground">{ts}</span> : null}
    </div>
  );

  return (
    <div className={cn("border-l-2 px-3 py-2", clsStyle(cls))}>
      {collapse ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="w-full text-left"
        >
          {header}
        </button>
      ) : (
        header
      )}
      {open && body ? (
        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-foreground/90">
          {body}
        </pre>
      ) : null}
    </div>
  );
}
