"use client";

import * as React from "react";

import { api, type MonitorSnapshot, type RunRow } from "@/lib/api";
import { subscribeMonitor } from "@/lib/sse";

import { snapshotToRuns, statusToRuns, type RunStatus } from "./normalize";

export type MonitorState = {
  runs: RunStatus[];
  recent: RunRow[];
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
  unreviewed: 0,
  pending: 0,
  phases: [],
  connected: false,
  loading: true,
  error: null,
};

/**
 * monitor トップの状態。REST 初回スナップショット + SSE 増分。
 * 進行中 run は loop.db に行が無いのが正しい(§3.0)ため runs[] は SSE/status 由来。
 * run_done を受けたら REST を再取得して recent / counts を更新する(SSE は事実トリガのみ)。
 */
export function useMonitorStream(token?: string): MonitorState {
  const [state, setState] = React.useState<MonitorState>(INITIAL);

  const refetch = React.useCallback(async () => {
    try {
      const snap: MonitorSnapshot = await api.monitor();
      setState((prev) => ({
        ...prev,
        recent: snap.recent ?? [],
        unreviewed: snap.unreviewed ?? 0,
        pending: snap.pending ?? 0,
        phases: snap.phases ?? [],
        // SSE 未到達の初期表示用に REST の status からも runs を導く(配列化)。
        runs: prev.connected ? prev.runs : snapshotToRuns(snap),
        loading: false,
        error: null,
      }));
    } catch (e) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error: e instanceof Error ? e.message : "監視データの取得に失敗しました",
      }));
    }
  }, []);

  React.useEffect(() => {
    void refetch();
    const close = subscribeMonitor(
      {
        status: (d) => {
          setState((prev) => ({ ...prev, connected: true, runs: statusToRuns(d) }));
        },
        run_done: () => {
          void refetch();
        },
        heartbeat: () => {
          setState((prev) => (prev.connected ? prev : { ...prev, connected: true }));
        },
        error: () => setState((prev) => ({ ...prev, connected: false })),
      },
      token
    );
    return () => close();
  }, [refetch, token]);

  return state;
}
