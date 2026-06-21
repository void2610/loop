"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/**
 * プロンプトプレビューの 1 セクション(折りたたみ + 文字数バッジ + 空表示)。
 * Author プロンプト(AuthorPromptPreviewView)と注入プロンプト(PromptInjectionView)で共有する。
 * 事実(注入される本文)の表示のみ。空は「(注入されません)」と明示する。
 */
export function PromptSection({
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
