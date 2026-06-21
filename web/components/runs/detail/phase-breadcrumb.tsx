"use client";

import { Check, Loader2, AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import { useRunLive } from "@/components/monitor/useRunLive";
import { useRunHost, useResolvedPeerBase } from "@/lib/runHost";
import { isTerminalVerdict } from "@/lib/verdict";
import { VerdictBadge } from "@/components/verdict-badge";

// run のワークフロー位置を可視化するパンくず風ステッパ。事実の表示のみ(§1.1: 判断生成しない)。
// 出典: runner.write_run_status が打つ phase("implementer"/"verifier"/"promote"/"awaiting")+ 完了時の verdict。
// 進行中は useRunLive の SSE で phase を購読 → リアルタイム更新。完了 run は verdict から static に導出する。

type StepKey = "implementer" | "verifier" | "promote" | "done";
type StepState = "pending" | "active" | "awaiting" | "done" | "skipped";

const STEPS: { key: StepKey; label: string }[] = [
  { key: "implementer", label: "Implementer" },
  { key: "verifier", label: "Verifier" },
  { key: "promote", label: "Promote" },
  { key: "done", label: "Done" },
];

// promote 段が「あったか/あるか」: ライブの phase=promote、または完了時 pr_url が刻まれているか、
// awaiting-merge は確定的に promote 経由(§4 verdict 合成)。
function promoteHappened(opts: {
  phase: string | null;
  verdict: string;
  prUrl: string;
  ended: boolean;
}): boolean {
  if (opts.phase === "promote") return true;
  if (opts.prUrl) return true;
  if (opts.verdict.toLowerCase() === "awaiting-merge") return true;
  // 完了済みで promote の痕跡が無ければ skipped(promote_on_pass=false など)
  return false;
}

// 各ステップの状態を決める。active は1つ、それ以前は done、awaiting は active 上の上書き表示。
function deriveStates(opts: {
  phase: string | null;
  verdict: string;
  prUrl: string;
  ended: boolean;
  active: boolean;
}): Record<StepKey, StepState> {
  const v = opts.verdict.toLowerCase();
  const out: Record<StepKey, StepState> = {
    implementer: "pending",
    verifier: "pending",
    promote: "pending",
    done: "pending",
  };

  // 進行中(SSE active かつ run MD 未確定)
  if (opts.active && !opts.ended) {
    if (opts.phase === "awaiting") {
      // どの段で詰まったかは status からは分からないので、最も近い直前段に awaiting を載せる
      // 既定は implementer(NEEDS_HUMAN の主経路)。verifier handoff は status をクリアしてから人間待ちにはしないため
      out.implementer = "awaiting";
      return out;
    }
    if (opts.phase === "implementer") {
      out.implementer = "active";
      return out;
    }
    if (opts.phase === "verifier") {
      out.implementer = "done";
      out.verifier = "active";
      return out;
    }
    if (opts.phase === "promote") {
      out.implementer = "done";
      out.verifier = "done";
      out.promote = "active";
      return out;
    }
    // 不明 phase: 安全側 = implementer active
    out.implementer = "active";
    return out;
  }

  // 完了済み: verdict から逆算
  out.implementer = "done";
  out.verifier = "done";
  out.promote = promoteHappened({ ...opts, phase: opts.phase }) ? "done" : "skipped";
  // awaiting-merge は「promote 通過済み・done 未確定」を表す(merge は人間)
  if (v === "awaiting-merge") {
    out.promote = "awaiting"; // PR マージ待ち = promote 段で人間待ち
    out.done = "pending";
    return out;
  }
  if (isTerminalVerdict(v)) {
    out.done = "done";
  }
  return out;
}

function StepPill({
  label,
  state,
  finalVerdict,
}: {
  label: string;
  state: StepState;
  finalVerdict?: string;
}) {
  const base =
    "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors";
  if (state === "active") {
    return (
      <span className={cn(base, "bg-primary/15 text-primary ring-1 ring-primary/40")}>
        <Loader2 className="h-3 w-3 animate-spin" />
        {label}
      </span>
    );
  }
  if (state === "awaiting") {
    return (
      <span
        className={cn(
          base,
          "bg-verdict-handoff/20 text-verdict-handoff ring-1 ring-verdict-handoff/50"
        )}
      >
        <AlertTriangle className="h-3 w-3" />
        {label}
        <span className="text-[10px] font-normal opacity-80">(人間待ち)</span>
      </span>
    );
  }
  if (state === "done") {
    // 最終 Done ステップは verdict バッジで色付け(事実の表示)
    if (finalVerdict) {
      return (
        <span className={cn(base, "bg-muted text-foreground")}>
          <Check className="h-3 w-3" />
          {label}
          <VerdictBadge verdict={finalVerdict} />
        </span>
      );
    }
    return (
      <span className={cn(base, "bg-muted text-muted-foreground")}>
        <Check className="h-3 w-3" />
        {label}
      </span>
    );
  }
  if (state === "skipped") {
    return (
      <span className={cn(base, "text-muted-foreground/40 line-through")}>{label}</span>
    );
  }
  // pending
  return (
    <span className={cn(base, "text-muted-foreground/50")}>{label}</span>
  );
}

export function PhaseBreadcrumb({
  runId,
  verdict,
  prUrl,
}: {
  runId: string;
  verdict: string;
  prUrl?: string;
}) {
  // Fleet: host が設定されているとき peer の SSE を購読する(fleet info を初回 1 回 fetch)。
  const host = useRunHost();
  const { peerBase } = useResolvedPeerBase(host);
  // SSE 購読: 進行中なら phase 変化を near-real-time で受け取る。完了済み run は接続直後 end が来て静的表示。
  const live = useRunLive(runId, undefined, peerBase);
  const states = deriveStates({
    phase: live.phase,
    verdict,
    prUrl: prUrl ?? "",
    ended: live.ended,
    active: !live.ended,
  });

  return (
    <nav
      aria-label="run phase"
      className="flex flex-wrap items-center gap-1.5 rounded-lg border bg-card px-3 py-2"
    >
      {STEPS.map((s, i) => (
        <div key={s.key} className="flex items-center gap-1.5">
          <StepPill
            label={s.label}
            state={states[s.key]}
            finalVerdict={s.key === "done" && states.done === "done" ? verdict : undefined}
          />
          {i < STEPS.length - 1 ? (
            <span aria-hidden className="text-muted-foreground/40">
              ›
            </span>
          ) : null}
        </div>
      ))}
    </nav>
  );
}
