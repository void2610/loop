"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api";
import { peerApi, type AuthorPromptPreview } from "@/lib/fleet";

// タスク生成時に Author に渡る user メッセージを事前に表示する(read-only / subprocess は起動しない)。
// GenerateForm で prompt / repo が変わるたびに 300ms debounce で再構築。
// 構成: 対象リポジトリ宣言 / 依頼本文 / 憲法 / 規範 / 過去 run の事実 / 連結後の全文。
export function AuthorPromptPreviewView({
  host,
  prompt,
  repo,
}: {
  host: string;
  prompt: string;
  repo: string;
}) {
  const [data, setData] = useState<AuthorPromptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!host) return;
    if (timer.current) clearTimeout(timer.current);
    setLoading(true);
    timer.current = setTimeout(async () => {
      try {
        const d = await peerApi.authorPromptPreview(host, { prompt, repo });
        setData(d);
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "プレビューの取得に失敗しました");
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [host, prompt, repo]);

  if (!data && loading) {
    return <p className="text-sm text-muted-foreground">プレビュー読み込み中…</p>;
  }
  if (error && !data) {
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
          このまま生成すると Author(task-author skill)に渡る user メッセージ
        </span>
        <Badge variant="outline" className="ml-auto text-muted-foreground">
          {data.inspect ? "inspect mode (repo を read-only 調査)" : "inspect なし(brief 注入なし)"}
        </Badge>
        <Badge variant="outline" className="text-muted-foreground">
          repo_history_runs = {data.repo_history_runs}
        </Badge>
        {loading ? (
          <Badge variant="outline" className="text-muted-foreground">更新中…</Badge>
        ) : null}
      </div>

      <Section title="① 対象リポジトリ宣言" body={data.repo_section} />
      <Section title="② 依頼(ユーザー入力)" body={data.request} />
      <Section
        title="③ 憲法 (constitution.md / 最優先)"
        body={data.constitution}
        hint={!data.inspect ? "inspect なし時は注入されません" : undefined}
      />
      <Section
        title="④ 設計規範 (conventions.md / 承認済み)"
        body={data.norms}
        hint={!data.inspect ? "inspect なし時は注入されません" : undefined}
      />
      <Section
        title="⑤ 過去 run からの事実 (build_repo_brief)"
        body={data.repo_brief}
        hint="判定器が pass にしたが人間が拒否した run も、ここでは直近 run 台帳に verdict=pass として残ります(human_verdict は注入に反映されていません)。"
      />
      <Section
        title="連結後の全文 (/loop-roles:task-author で claude -p に渡す user 入力)"
        body={data.wrapped}
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
