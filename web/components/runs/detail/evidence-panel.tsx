"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { DiffView } from "./diff-view";

// 遅延 fetch される証拠ファイル 1 件。展開時に初めて本文を取りに行く(§2.2: 詳細 JSON を軽く保つ)。
type LazyFileProps = {
  runId: string;
  name: string;
  title: string;
  render: (body: string) => React.ReactNode;
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function LazyFile({ runId, name, title, render }: LazyFileProps) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBody = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const text = await api.runFile(runId, name);
      setBody(text);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [runId, name]);

  // 展開され、かつ未取得のときだけ 1 回 fetch する。
  useEffect(() => {
    if (open && body === null && !loading && error === null) void fetchBody();
  }, [open, body, loading, error, fetchBody]);

  return (
    <div className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium hover:bg-accent"
      >
        <span>
          {title} <span className="font-mono text-muted-foreground">({name})</span>
        </span>
        <span className="text-muted-foreground">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <div className="border-t border-border p-3">
          {loading ? <p className="text-sm text-muted-foreground">読み込み中…</p> : null}
          {error ? <p className="text-sm text-verdict-fail">{error}</p> : null}
          {body !== null ? render(body) : null}
        </div>
      ) : null}
    </div>
  );
}

type EvidenceFile = { name: string; size: number; exists: boolean };

// 証拠パネル: meta(存在/サイズ)を先に取り、本文はオンデマンドで遅延ロード(§2.2)。
export function EvidencePanel({ runId }: { runId: string }) {
  const [files, setFiles] = useState<EvidenceFile[] | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meta = await api.runEvidence(runId);
        if (!cancelled) setFiles(meta.files as EvidenceFile[]);
      } catch (e) {
        if (!cancelled) setMetaError(e instanceof ApiError ? e.message : "取得に失敗しました");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const present = (name: string): EvidenceFile | undefined =>
    files?.find((f) => f.name === name && f.exists);

  const patch = present("change.patch");
  const testOut = present("test-output.txt");
  const transcript = present("transcript.jsonl");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">証拠</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {metaError ? <p className="text-sm text-verdict-fail">{metaError}</p> : null}
        {files === null && metaError === null ? (
          <p className="text-sm text-muted-foreground">読み込み中…</p>
        ) : null}

        {testOut ? (
          <LazyFile
            runId={runId}
            name="test-output.txt"
            title={`検証出力 · ${formatBytes(testOut.size)}`}
            render={(body) => (
              <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                {body}
              </pre>
            )}
          />
        ) : null}

        {patch ? (
          <LazyFile
            runId={runId}
            name="change.patch"
            title={`diff · ${formatBytes(patch.size)}`}
            render={(body) => <DiffView patch={body} />}
          />
        ) : null}

        {transcript ? (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <Link
              href={`/runs/${encodeURIComponent(runId)}/transcript`}
              className="font-medium text-primary hover:underline"
            >
              transcript を会話ビューで開く
            </Link>
            <a
              href={`/api/runs/${encodeURIComponent(runId)}/files/transcript.jsonl`}
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground hover:underline"
            >
              生 JSONL · {formatBytes(transcript.size)}
            </a>
          </p>
        ) : null}

        {files !== null && !testOut && !patch && !transcript ? (
          <p className="text-sm text-muted-foreground">証拠ファイルなし</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
