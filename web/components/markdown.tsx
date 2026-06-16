"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

// transcript のアシスタント発話など Markdown 本文を装飾表示する(事実の整形のみ。内容は改変しない)。
// dark テーマ前提で prose-invert。生 HTML は描かない(react-markdown 既定でサニタイズ)。
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={cn(
        "prose prose-invert prose-sm max-w-none break-words",
        "prose-headings:text-foreground prose-p:text-foreground/90 prose-li:text-foreground/90",
        "prose-strong:text-foreground prose-a:text-primary",
        "prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none",
        "prose-pre:bg-muted/40 prose-pre:text-foreground/90 prose-pre:text-xs",
        className
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
