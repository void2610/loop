"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";

import { RoleTabs } from "./RoleTabs";
import { TranscriptEventView } from "./TranscriptEventView";
import { ROLES, useRunLive, type RoleKey } from "./useRunLive";

// 末尾追従は「ユーザーが最下部にいるとき」だけ(途中を読んでいるなら飛ばさない / §3.5)。
const STICK_THRESHOLD_PX = 80;

export function LiveTranscript({ runId, token }: { runId: string; token?: string }) {
  const { byRole, phase, ended, connected } = useRunLive(runId, token);
  const [active, setActive] = React.useState<RoleKey>("implementer");

  // phase が来たらそのロールへ追従(ユーザーが手動選択した後も最新へ寄せる)。
  React.useEffect(() => {
    if (phase === "implementer" || phase === "verifier") {
      setActive(phase);
    }
  }, [phase]);

  const tabs = ROLES.map((r) => ({
    key: r.key,
    label: r.label,
    badge:
      byRole[r.key].length > 0 ? (
        <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
          {byRole[r.key].length}
        </Badge>
      ) : null,
  }));

  const events = byRole[active];
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const stickRef = React.useRef(true);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickRef.current = distance < STICK_THRESHOLD_PX;
  };

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events.length, active]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <RoleTabs tabs={tabs} active={active} onSelect={(k) => setActive(k as RoleKey)} />
        <div className="flex items-center gap-2">
          {ended ? (
            <Badge variant="secondary">完了</Badge>
          ) : connected ? (
            <Badge variant="outline" className="gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              接続中
            </Badge>
          ) : (
            <Badge variant="outline">切断</Badge>
          )}
          {phase ? <Badge variant="outline">phase: {phase}</Badge> : null}
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="max-h-[70vh] space-y-1 overflow-y-auto rounded-lg border border-border bg-background p-2"
      >
        {events.length === 0 ? (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground">
            {ended
              ? "このロールのイベントはありません。"
              : "イベント待機中…(runner の出力を追従しています)"}
          </p>
        ) : (
          events.map((ev, i) => <TranscriptEventView key={i} ev={ev} />)
        )}
      </div>
    </div>
  );
}
