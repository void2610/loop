"use client";

import { ApiError } from "@/lib/api";
import { peerApi } from "@/lib/fleet";
import { ArrowLeft, CheckCircle2, Loader2, OctagonX, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/page-header";
import { TranscriptEventView } from "@/components/monitor/TranscriptEventView";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getFleetInfo, resolvePeerBase, type FleetInfo } from "@/lib/fleet";
import { subscribeGen, type GenEventData, type GenResult } from "@/lib/sse";

// タスク生成(Author)のライブ進行画面。SSE で transcript を受け取り、end イベントで結果を表示。
// LangSmith 的に: think / assistant / tool 呼び出しが届いた瞬間に並ぶ。
export function GeneratingView({
  genId,
  host,
  autorun,
}: {
  genId: string;
  host: string;
  autorun: boolean;
}) {
  const router = useRouter();
  const [fleet, setFleet] = React.useState<FleetInfo | null>(null);
  const [events, setEvents] = React.useState<GenEventData[]>([]);
  const [result, setResult] = React.useState<GenResult | null>(null);
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    void getFleetInfo()
      .then(setFleet)
      .catch(() => setFleet({ self_name: null, peers: [] }));
  }, []);

  const peerBase = resolvePeerBase(fleet, host);

  React.useEffect(() => {
    if (!genId || fleet === null) return;
    setConnected(true);
    const close = subscribeGen(
      genId,
      {
        event: (d) => setEvents((prev) => [...prev, d]),
        end: (d) => {
          setResult(d.result);
          setConnected(false);
        },
        error: (e) => {
          setConnected(false);
          // sse.ts の error 多発しきい値で fatal=true が付与される。
          // gen は result が無いとフローが続けられないので fail で確定させる。
          if ((e as Event & { fatal?: boolean }).fatal && !result) {
            setResult({ status: "fail", task_id: null, error: "live connection failed" });
          }
        },
      },
      undefined,
      peerBase,
    );
    return () => {
      close();
      setConnected(false);
    };
  }, [genId, fleet, peerBase]);

  // 末尾追従(ユーザーが最下部にいる時だけ追従)
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const [stick, setStick] = React.useState(true);
  React.useEffect(() => {
    if (!stick) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events, stick]);

  if (!genId) {
    return <p className="text-sm text-verdict-fail">gen_id が指定されていません。</p>;
  }

  const ok = result?.status === "ok" && result.task_id;
  const fail = result?.status === "fail";
  const stopped = result?.status === "stopped";

  const [stopping, setStopping] = React.useState(false);
  const [stopError, setStopError] = React.useState<string | null>(null);
  const onStop = async () => {
    setStopping(true);
    setStopError(null);
    try {
      await peerApi.stopGen(host, genId);
      // gen.json に書かれ end イベントが来ると result が反映される(ここでは何もしない)
    } catch (e) {
      setStopError(e instanceof ApiError ? e.message : "停止に失敗しました");
      setStopping(false);
    }
  };

  return (
    <div className="space-y-5">
      <Link
        href="/tasks/new"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        新規タスク
      </Link>

      <PageHeader
        title="タスク生成中"
        description={`Author(Claude Code)が目標契約を起草しています。host: ${host || "—"} / gen_id: ${genId}`}
      />

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {result === null ? (
          <span className="inline-flex items-center gap-2 rounded-full bg-primary/15 px-3 py-1 text-primary">
            <Loader2 className="h-4 w-4 animate-spin" />
            生成中…{!connected ? "(接続切れ・再試行中)" : ""}
          </span>
        ) : ok ? (
          <span className="inline-flex items-center gap-2 rounded-full bg-verdict-pass/15 px-3 py-1 text-verdict-pass">
            <CheckCircle2 className="h-4 w-4" />
            生成完了: {result.task_id}
          </span>
        ) : stopped ? (
          <span className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-muted-foreground">
            <OctagonX className="h-4 w-4" />
            停止しました
          </span>
        ) : (
          <span className="inline-flex items-center gap-2 rounded-full bg-verdict-fail/15 px-3 py-1 text-verdict-fail">
            <XCircle className="h-4 w-4" />
            生成失敗
          </span>
        )}
        <span className="font-mono text-xs text-muted-foreground">events: {events.length}</span>
        {result === null ? (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto border-verdict-fail/40 text-verdict-fail hover:bg-verdict-fail/10 hover:text-verdict-fail"
            onClick={onStop}
            disabled={stopping}
          >
            {stopping ? "停止中…" : "停止する"}
          </Button>
        ) : null}
        {stopError ? <span className="text-xs text-verdict-fail">{stopError}</span> : null}
      </div>

      {fail && (
        <div className="rounded-md border border-verdict-fail/40 bg-verdict-fail/5 p-3 text-sm">
          <p className="font-medium text-verdict-fail">原因</p>
          <p className="mt-1 break-words font-mono text-xs text-muted-foreground">
            {result?.error ?? "(詳細不明)"}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            backend log(/tmp/loop-app.log)に Author の stderr / stop_reason が残ります。
          </p>
        </div>
      )}

      {ok && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => {
              const q = autorun ? "generating=0&autorun=1" : "";
              router.push(`/tasks${q ? `?${q}` : ""}`);
            }}
          >
            タスク一覧へ
          </Button>
          <Link
            className="text-sm text-muted-foreground underline"
            href={`/tasks/${encodeURIComponent(result?.task_id ?? "")}${host ? `?host=${encodeURIComponent(host)}` : ""}`}
          >
            タスク詳細を開く
          </Link>
        </div>
      )}

      <Card>
        <CardContent className="p-2">
          <div
            ref={scrollRef}
            onScroll={(e) => {
              const t = e.currentTarget;
              const atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 80;
              setStick(atBottom);
            }}
            className="max-h-[70vh] space-y-1 overflow-y-auto rounded-md bg-background p-2"
          >
            {events.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                {result === null
                  ? "イベント待機中…(Author の出力を追従しています)"
                  : "Author からのイベントはありませんでした。"}
              </p>
            ) : (
              events.map((ev, i) => <TranscriptEventView key={i} ev={ev} />)
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
