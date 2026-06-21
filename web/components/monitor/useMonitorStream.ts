"use client";

import * as React from "react";

import { api, type MonitorSnapshot, type QueueItem, type RunRow } from "@/lib/api";
import type { FleetPeer } from "@/lib/fleet";
import { subscribeMonitor } from "@/lib/sse";

import { snapshotToRuns, statusToRuns, type RunStatus } from "./normalize";

/** Fleet 用に host を持たせた QueueItem。merge view で「どの PC のキューか」を出す。 */
export type QueueItemWithHost = QueueItem & { host?: string };

export type MonitorState = {
  runs: RunStatus[];
  recent: RunRow[];
  queue: QueueItemWithHost[];
  maxConcurrency: number;
  unreviewed: number;
  pending: number;
  phases: string[][];
  connected: boolean;
  loading: boolean;
  error: string | null;
};

const INITIAL: MonitorState = {
  runs: [],
  recent: [],
  queue: [],
  maxConcurrency: 1,
  unreviewed: 0,
  pending: 0,
  phases: [],
  connected: false,
  loading: true,
  error: null,
};

type Target = { name: string; url?: string };

type PerHostState = {
  runs: RunStatus[];
  snap?: MonitorSnapshot;
  connected: boolean;
};

/**
 * monitor トップの状態。REST 初回スナップショット + SSE 増分。
 * 進行中 run は loop.db に行が無いのが正しい(§3.0)ため runs[] は SSE/status 由来。
 * run_done を受けたら REST を再取得して recent / counts を更新する(SSE は事実トリガのみ)。
 *
 * Fleet: peers を渡すと各 peer に並列 subscribe(self も含む)。host バッジ付きで merge。
 * peers が undefined / 空なら従来通り自 host のみ(同一オリジン)。
 */
export function useMonitorStream(peers?: FleetPeer[], token?: string): MonitorState {
  const [state, setState] = React.useState<MonitorState>(INITIAL);

  // peers 配列を毎 render で再生成しないよう name+url の連結文字列で memo。
  const targetsKey = React.useMemo(
    () => (peers ?? []).map((p) => `${p.name}|${p.url}|${p.is_self ? "1" : "0"}`).join(","),
    [peers],
  );
  const targets: Target[] = React.useMemo(() => {
    if (!peers || peers.length === 0) return [{ name: "" }];
    return peers.map((p) => ({ name: p.name, url: p.is_self ? undefined : p.url }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetsKey]);

  React.useEffect(() => {
    // 各 peer の状態を ref 的に保持し、setState は毎回 merge した形を渡す。
    const perHost: Record<string, PerHostState> = {};
    for (const t of targets) perHost[t.name] = { runs: [], connected: false };

    const recompute = () => {
      const entries = Object.entries(perHost);
      const mergedRuns = entries.flatMap(([host, s]) =>
        s.runs.map((r) => ({ ...r, host: r.host ?? host })),
      );
      const mergedQueue: QueueItemWithHost[] = entries.flatMap(([host, s]) =>
        (s.snap?.queue ?? []).map((q) => ({ ...q, host })),
      );
      const mergedRecent: RunRow[] = entries.flatMap(([, s]) => s.snap?.recent ?? []);
      const maxConcSum = entries.reduce((acc, [, s]) => acc + (s.snap?.max_concurrency ?? 0), 0);
      const unrev = entries.reduce((acc, [, s]) => acc + (s.snap?.unreviewed ?? 0), 0);
      const pending = entries.reduce((acc, [, s]) => acc + (s.snap?.pending ?? 0), 0);
      const anyConnected = entries.some(([, s]) => s.connected);
      const phases =
        entries.find(([, s]) => (s.snap?.phases ?? []).length > 0)?.[1].snap?.phases ?? [];
      setState({
        runs: mergedRuns,
        recent: mergedRecent,
        queue: mergedQueue,
        maxConcurrency: maxConcSum > 0 ? maxConcSum : 1,
        unreviewed: unrev,
        pending: pending,
        phases,
        connected: anyConnected,
        loading: false,
        error: null,
      });
    };

    const refetchOne = async (peer: Target) => {
      try {
        if (peer.url) {
          // peer 経由: peer の Next フロント越しに /api/monitor を取る(rewrite が backend に転送)
          const res = await fetch(`${peer.url.replace(/\/+$/, "")}/api/monitor`);
          const snap = (await res.json()) as MonitorSnapshot;
          perHost[peer.name].snap = snap;
          perHost[peer.name].runs = snapshotToRuns(snap);
        } else {
          // 自 host: 同一オリジン経由の api.monitor()
          const snap = await api.monitor();
          perHost[peer.name].snap = snap;
          perHost[peer.name].runs = snapshotToRuns(snap);
        }
      } catch {
        // peer offline 等は無視(全体は落とさない)
      }
      recompute();
    };

    // 初回 fetch
    for (const t of targets) void refetchOne(t);

    // SSE: 各 peer に subscribe(self は peerBase 省略で同一オリジン経由)
    const closers: (() => void)[] = [];
    for (const t of targets) {
      const close = subscribeMonitor(
        {
          status: (d) => {
            perHost[t.name].connected = true;
            perHost[t.name].runs = statusToRuns(d);
            recompute();
          },
          run_done: () => {
            void refetchOne(t);
          },
          heartbeat: () => {
            if (!perHost[t.name].connected) {
              perHost[t.name].connected = true;
              recompute();
            }
          },
          error: () => {
            perHost[t.name].connected = false;
            recompute();
          },
        },
        token,
        t.url,
      );
      closers.push(close);
    }

    // SSE が rewrite でバッファされ status が届かない場合の保険(REST を権威にポーリング)。
    const poll = setInterval(() => {
      for (const t of targets) void refetchOne(t);
    }, 4000);

    return () => {
      clearInterval(poll);
      closers.forEach((c) => c());
    };
  }, [targets, token]);

  return state;
}
