"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { peerApi, type PromptPreview } from "@/lib/fleet";

// run 起動時に Implementer に渡る brief を全文で見せる(GUI は判断を生成しない: 事実表示のみ)。
// 構成: 憲法 / 規範 / 過去 run の事実 / Author プラン / 実装プロンプト全文。
// 「判定器が pass にしたが人間が拒否した過去 run」が repo_brief にどう乗っているかを直接読める。
export function PromptInjectionView({ taskId, host }: { taskId: string; host?: string }) {
  const [data, setData] = useState<PromptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    peerApi
      .taskPromptPreview(host, taskId)
      .then((d) => alive && setData(d))
      .catch((err) => {
        if (!alive) return;
        setError(err instanceof ApiError ? err.message : "プレビューの取得に失敗しました");
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [taskId, host, nonce]);

  if (loading) return <p className="text-sm text-muted-foreground">プレビュー読み込み中…</p>;
  if (error) {
    return (
      <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (!data) return null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">
          run 起動時にこの内容が Implementer に渡ります
          {data.repo ? (
            <>
              {" "}(repo:{" "}
              <code className="font-mono text-xs">{data.repo}</code>)
            </>
          ) : null}
        </span>
        <Badge variant="outline" className="ml-auto text-muted-foreground">
          repo_history_runs = {data.repo_history_runs}
        </Badge>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setNonce((n) => n + 1)}
          title="再取得"
        >
          <RefreshCw className="size-3.5" aria-hidden />
        </Button>
      </div>

      <Section title="① 憲法 (constitution.md / 最優先・不可侵)" body={data.constitution} />
      <Section title="② このリポジトリの設計規範 (conventions.md / 人間が承認済み)" body={data.norms} />
      <Section
        title="③ 過去 run からの事実 (build_repo_brief / 同一 repo・archived 除外)"
        body={data.repo_brief}
        hint="判定器が pass にしたが人間が拒否した run も、ここでは verdict=pass として直近 run 台帳に残ります(人間の判定は注入しない設計)。"
      />
      <Section title="④ タスク契約 (goal / accept / constraints / verify)" body={data.task_contract} />
      <Section title="⑤ Author の実装プラン (tasks/plans/<id>.md)" body={data.author_plan} />
      <Section
        title="Implementer に渡る全文(① + ② + ③ + ④ + ⑤ を slash command で連結)"
        body={data.implementer_full}
        defaultOpen={false}
      />
    </div>
  );
}

function Section({
  title,
  body,
  hint,
  defaultOpen,
}: {
  title: string;
  body: string;
  hint?: string;
  defaultOpen?: boolean;
}) {
  const initial = defaultOpen ?? (body.trim().length > 0);
  const [open, setOpen] = useState(initial);
  const empty = body.trim().length === 0;
  return (
    <div className="rounded-md border border-border/60 bg-card/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/30"
      >
        {open ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <span className="font-medium">{title}</span>
        {empty ? (
          <Badge variant="outline" className="ml-auto text-muted-foreground">
            (空)
          </Badge>
        ) : (
          <Badge variant="outline" className="ml-auto text-muted-foreground">
            {body.length.toLocaleString()} chars
          </Badge>
        )}
      </button>
      {open && (
        <div className="border-t border-border/40 px-3 py-2">
          {hint ? <p className="mb-2 text-xs text-muted-foreground">{hint}</p> : null}
          {empty ? (
            <p className="text-xs text-muted-foreground">(注入されません)</p>
          ) : (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-2 font-mono text-xs leading-relaxed">
              {body}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
