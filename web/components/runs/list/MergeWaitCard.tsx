"use client";

import * as React from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { api, type RunRow, type PrStatus } from "@/lib/api";
import { runHref } from "@/lib/runHost";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RepoBadge } from "@/components/repo-badge";

// PR マージ待ち(awaiting-merge)の run。PR 状態を gh から取り、PR へのリンクを出す。
// PR がマージされると server 側で verdict=pass に昇格し、onMerged で一覧を更新して消える。
function ciLabel(ci: string | null | undefined): { text: string; cls: string } {
  switch (ci) {
    case "pass":
      return { text: "CI green", cls: "text-verdict-pass" };
    case "fail":
      return { text: "CI 失敗", cls: "text-verdict-fail" };
    case "pending":
      return { text: "CI 実行中", cls: "text-verdict-handoff" };
    default:
      return { text: "CI なし", cls: "text-muted-foreground" };
  }
}

export function MergeWaitCard({ run, onMerged }: { run: RunRow; onMerged: () => void }) {
  const [pr, setPr] = React.useState<PrStatus | null>(null);

  React.useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await api.runPr(run.run_id);
        if (!alive) return;
        setPr(s);
        if (s.merged) onMerged(); // マージ済み → server が pass 昇格済み。一覧を更新
      } catch {
        /* 取得失敗は無視 */
      }
    };
    void poll();
    const t = setInterval(poll, 8000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [run.run_id, onMerged]);

  const ci = ciLabel(pr?.ci);
  const state = pr?.state ?? "…";
  const host = (run as RunRow & { host?: string }).host;
  const href = runHref(run.run_id, host);
  // カード全面を run 詳細へのリンクにし、PR リンクは absolute Link の上に relative z-10 で重ねる
  // (Next の Link は <a> なのでネスト不可 → 「フル面オーバーレイ + 兄弟リンク」パターン)。
  return (
    <Card className="relative border-verdict-pass/40 bg-verdict-pass/5 transition-colors hover:border-verdict-pass">
      <Link
        href={href}
        aria-label={`run ${run.run_id} を開く`}
        className="absolute inset-0 z-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-verdict-pass"
      />
      <CardHeader className="relative z-10 pointer-events-none space-y-2 pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base">{run.task ?? run.run_id}</CardTitle>
          <RepoBadge repo={run.repo} />
        </div>
        <p className="font-mono text-xs text-muted-foreground">{run.run_id}</p>
      </CardHeader>
      <CardContent className="relative z-10 pointer-events-none flex items-center justify-between gap-3 pt-0">
        <div className="flex items-center gap-2 text-xs">
          <Badge variant="outline">PR {pr?.number ? `#${pr.number}` : ""} · {state}</Badge>
          <span className={ci.cls}>{ci.text}</span>
        </div>
        {pr?.url ? (
          <Link
            href={pr.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="pointer-events-auto inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary hover:text-primary"
          >
            <ExternalLink className="size-3.5" />
            PR を開く
          </Link>
        ) : null}
      </CardContent>
    </Card>
  );
}
