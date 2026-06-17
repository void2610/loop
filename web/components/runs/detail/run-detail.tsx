"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { api, ApiError, type RunDetail } from "@/lib/api";
import { MessageSquareText } from "lucide-react";

import { repoLabel } from "@/lib/repoLabel";
import { ArchiveRunButton } from "@/components/runs/ArchiveRunButton";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";

import {
  JudgmentForm,
  type JudgmentFormHandle,
  type JudgmentValues,
} from "@/components/judgment/judgment-form";

import { EvidencePanel } from "./evidence-panel";
import { FrontMatter } from "./front-matter";
import { Summary } from "./summary";
import { Verifier } from "./verifier";
import { VerdictBadge } from "./verdict-badge";

function fmString(fm: { [key: string]: unknown }, key: string): string {
  const v = fm[key];
  return typeof v === "string" ? v : v === null || v === undefined ? "" : String(v);
}

function isReviewed(fm: { [key: string]: unknown }): boolean {
  return ["true", "1"].includes(fmString(fm, "reviewed").toLowerCase());
}

// run 詳細 + 判断。j/k で前後 run、⌘↵ で保存(§6.5)。
// 左カラム=事実(front-matter / summary / Verifier / 証拠)、右カラム=判断ペイン。
export function RunDetailView({ runId }: { runId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [neighbors, setNeighbors] = useState<{ prev: string | null; next: string | null }>({
    prev: null,
    next: null,
  });
  const formRef = useRef<JudgmentFormHandle>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    (async () => {
      try {
        const d = await api.runDetail(runId);
        if (!cancelled) setDetail(d);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "run の取得に失敗しました");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, reloadKey]);

  // 前後 run の id を一覧順(started_at DESC)から導出。j=次(下)/k=前(上)。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api.listRuns();
        if (cancelled) return;
        const ids = list.runs.map((r) => r.run_id);
        const i = ids.indexOf(runId);
        setNeighbors({
          prev: i > 0 ? ids[i - 1] : null,
          next: i >= 0 && i < ids.length - 1 ? ids[i + 1] : null,
        });
      } catch {
        // 一覧取得失敗時は j/k 無効でよい(詳細表示は継続)。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const goNext = useCallback(() => {
    if (neighbors.next) router.push(`/runs/${encodeURIComponent(neighbors.next)}`);
  }, [neighbors.next, router]);

  const goPrev = useCallback(() => {
    if (neighbors.prev) router.push(`/runs/${encodeURIComponent(neighbors.prev)}`);
  }, [neighbors.prev, router]);

  // j/k はフィールド外のときのみ。⌘↵ はフィールド内でも保存(フォーム側でも捕捉)。
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      const inField =
        t != null && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        formRef.current?.save();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (inField) return;
      if (e.key === "j") {
        e.preventDefault();
        goNext();
      } else if (e.key === "k") {
        e.preventDefault();
        goPrev();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext, goPrev]);

  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/runs" className="text-sm text-primary hover:underline">
          ← 一覧
        </Link>
        <p className="text-sm text-verdict-fail">{error}</p>
      </div>
    );
  }

  if (!detail) {
    return <p className="text-sm text-muted-foreground">読み込み中…</p>;
  }

  const fm = detail.front_matter;
  const reviewed = isReviewed(fm);
  const verdict = fmString(fm, "verdict");
  const repo = fmString(fm, "repo");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/runs" className="text-sm text-primary hover:underline">
          ← 一覧
        </Link>
        <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <button
            type="button"
            onClick={goPrev}
            disabled={!neighbors.prev}
            className="rounded px-2 py-1 hover:bg-accent disabled:opacity-40"
          >
            k 前
          </button>
          <button
            type="button"
            onClick={goNext}
            disabled={!neighbors.next}
            className="rounded px-2 py-1 hover:bg-accent disabled:opacity-40"
          >
            j 次
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{repoLabel(repo)}</Badge>
        <h2 className="font-mono text-lg font-bold tracking-tight">{detail.run_id}</h2>
        <VerdictBadge verdict={verdict} />
        {reviewed ? (
          <Badge variant="outline">reviewed ✓</Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            未レビュー
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Link
            href={`/runs/${encodeURIComponent(detail.run_id)}/transcript`}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            <MessageSquareText />
            transcript
          </Link>
          <ArchiveRunButton
            runId={detail.run_id}
            archived={!!fm.archived && fm.archived !== "false"}
            onChanged={() => setReloadKey((k) => k + 1)}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        {/* 左: 事実(スクロール可) */}
        <div className="min-w-0 space-y-4">
          <FrontMatter fm={fm} />
          <Summary summary={detail.summary} />
          <Verifier verifier={detail.verifier} />
          <EvidencePanel runId={detail.run_id} />
        </div>

        {/* 右: 判断ペイン(ビューポート縦を判断記入へ最大化) */}
        <div className="sticky top-20 flex h-[calc(100vh-6rem)] min-w-0 flex-col">
          <JudgmentForm
            ref={formRef}
            runId={detail.run_id}
            fields={detail.judgment_fields}
            values={detail.judgment as JudgmentValues}
            reviewed={reviewed}
            onSaved={goNext}
          />
        </div>
      </div>
    </div>
  );
}
