"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import {
  fetchAllPeerRuns,
  getFleetInfo,
  peerApi,
  type FleetInfo,
  type PeerRunsResult,
  type RunRowWithHost,
} from "@/lib/fleet";

import { ArchiveToggle } from "@/components/archive-toggle";
import { PageHeader } from "@/components/page-header";
import { RunStatusCard } from "@/components/monitor/RunStatusCard";
import { useMonitorStream } from "@/components/monitor/useMonitorStream";

import { MergeWaitCard } from "./MergeWaitCard";
import { RunsFilterBar, type RunsFilter } from "./RunsFilterBar";
import { RunsTable } from "./RunsTable";

const EMPTY_FILTER: RunsFilter = { verdict: "", reviewed: "", task: "" };

export function RunsView() {
  const [filter, setFilter] = useState<RunsFilter>(EMPTY_FILTER);
  const [runs, setRuns] = useState<RunRowWithHost[]>([]);
  const [verdicts, setVerdicts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dispatching, setDispatching] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  // Fleet: peers が空なら従来通り単一 PC 表示。複数 peer なら全 peer から並列 fetch する。
  const [fleetInfo, setFleetInfo] = useState<FleetInfo | null>(null);
  const [peerErrors, setPeerErrors] = useState<{ name: string; error: string }[]>([]);
  // dispatch する host の選択(初期値は self、Fleet off なら未使用)
  const [dispatchHost, setDispatchHost] = useState<string>("");
  // 実行中 run は loop.db 未登録なので SSE(status.json 由来)から取り、一覧の上に出す。
  // Fleet: peers を渡すと全 host の monitor SSE を merge view(各 active run に host バッジ)。
  const { runs: activeRuns, queue, maxConcurrency } = useMonitorStream(fleetInfo?.peers);
  // 人間の介入待ち(awaiting)は最優先で目立たせる。それ以外の実行中とは分ける。
  const awaitingRuns = activeRuns.filter((r) => r.phase === "awaiting");
  const runningRuns = activeRuns.filter((r) => r.phase !== "awaiting");
  // PR マージ待ち(awaiting-merge)= 真の完了前。loop.db 由来。一覧上部に PR 状態付きで出す。
  const mergeWaitRuns = runs.filter((r) => r.verdict === "awaiting-merge");
  const tableRuns = runs.filter((r) => r.verdict !== "awaiting-merge");

  // 連打・タイプ中の古いレスポンスで新しい結果を上書きしないための世代カウンタ。
  const reqSeq = useRef(0);

  // Fleet 情報は初回 1 回だけ取る(設定変更時は再起動前提)。dispatchHost は self に初期化。
  useEffect(() => {
    void getFleetInfo()
      .then((f) => {
        setFleetInfo(f);
        if (f.self_name) setDispatchHost(f.self_name);
      })
      .catch(() => setFleetInfo({ self_name: null, peers: [] }));
  }, []);

  const load = useCallback(
    async (f: RunsFilter, archived: boolean) => {
      if (!fleetInfo) return; // peers 取得待ち
      const seq = ++reqSeq.current;
      setLoading(true);
      setError(null);
      const params = {
        verdict: f.verdict || undefined,
        reviewed: f.reviewed === "" ? undefined : (Number(f.reviewed) as 0 | 1),
        task: f.task || undefined,
        include_archived: archived || undefined,
      };
      try {
        if (fleetInfo.peers.length === 0) {
          // Fleet off: 従来通り自 host のみ。host バッジは self_name で埋める。
          const res = await api.listRuns(params);
          if (seq !== reqSeq.current) return;
          const self = fleetInfo.self_name ?? "local";
          setRuns(res.runs.map((r) => ({ ...r, host: self })));
          if (res.verdicts.length > 0) setVerdicts(res.verdicts);
          setPeerErrors([]);
        } else {
          // Fleet on: 全 peer 並列 fetch。エラー peer は per-host のまま残し全体は落とさない。
          const results: PeerRunsResult[] = await fetchAllPeerRuns(fleetInfo.peers, params);
          if (seq !== reqSeq.current) return;
          const merged = results
            .flatMap((r) => r.runs)
            .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
          setRuns(merged);
          const allVerdicts = Array.from(new Set(results.flatMap((r) => r.verdicts)));
          if (allVerdicts.length > 0) setVerdicts(allVerdicts);
          setPeerErrors(
            results.filter((r) => !r.ok).map((r) => ({ name: r.peer.name, error: r.error ?? "unknown" })),
          );
        }
      } catch (e) {
        if (seq !== reqSeq.current) return;
        setError(e instanceof ApiError ? e.message : "run 一覧の取得に失敗しました");
        setRuns([]);
      } finally {
        if (seq === reqSeq.current) setLoading(false);
      }
    },
    [fleetInfo],
  );

  // task テキスト入力はデバウンス、verdict/reviewed は即時反映。
  useEffect(() => {
    if (!fleetInfo) return;
    const t = setTimeout(() => void load(filter, includeArchived), 250);
    return () => clearTimeout(t);
  }, [filter, includeArchived, load, fleetInfo]);

  const onDispatch = useCallback(async () => {
    setDispatching(true);
    setNotice(null);
    setError(null);
    try {
      // Fleet 有効時は指定 host へ peer プロキシ経由で dispatch、無効なら従来の自 host へ。
      const useFleet = (fleetInfo?.peers.length ?? 0) > 0;
      const hostForDispatch = useFleet && dispatchHost && dispatchHost !== fleetInfo?.self_name
        ? dispatchHost
        : undefined;
      const res = hostForDispatch
        ? await peerApi.dispatch(hostForDispatch)
        : await api.dispatch();
      if (res.accepted) {
        setNotice(
          hostForDispatch
            ? `host ${hostForDispatch} で run を起動しました。完了後に一覧へ反映されます。`
            : "run を起動しました。完了後に一覧へ反映されます。",
        );
      } else {
        setNotice(
          res.reason === "busy"
            ? "別の run が実行中です。"
            : "起動できませんでした。"
        );
      }
    } catch (e) {
      // busy は 409。それ以外も含めメッセージを素通しで表示する。
      setError(e instanceof ApiError ? e.message : "dispatch に失敗しました");
    } finally {
      setDispatching(false);
    }
  }, [fleetInfo, dispatchHost]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Runs"
        description="run の事実一覧。行クリックで詳細(判断レビュー)へ。"
        actions={
          <ArchiveToggle checked={includeArchived} onChange={setIncludeArchived} />
        }
      />

      <RunsFilterBar
        filter={filter}
        verdicts={verdicts}
        count={runs.length}
        dispatching={dispatching}
        onChange={setFilter}
        onDispatch={onDispatch}
        hostOptions={fleetInfo?.peers.map((p) => p.name) ?? []}
        dispatchHost={dispatchHost}
        onDispatchHostChange={setDispatchHost}
      />

      {awaitingRuns.length > 0 ? (
        <div className="space-y-2 rounded-lg border border-verdict-handoff/50 bg-verdict-handoff/5 p-3">
          <p className="flex items-center gap-2 text-sm font-semibold text-verdict-handoff">
            <span className="h-2 w-2 animate-pulse rounded-full bg-verdict-handoff" />
            人間の介入待ち({awaitingRuns.length})— クリックして続行指示を送ってください
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {awaitingRuns.map((r) => (
              <RunStatusCard key={r.run_id} run={r} />
            ))}
          </div>
        </div>
      ) : null}

      {runningRuns.length > 0 ? (
        <div className="space-y-2">
          <p className="th-label">
            実行中(クリックでライブ)
            <span className="ml-2 font-normal tabular-nums text-muted-foreground">
              {runningRuns.length} / {maxConcurrency} 同時
            </span>
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {runningRuns.map((r) => (
              <RunStatusCard key={r.run_id} run={r} />
            ))}
          </div>
        </div>
      ) : null}

      {queue.length > 0 ? (
        <div className="space-y-2">
          <p className="th-label">
            待機キュー
            <span className="ml-2 font-normal tabular-nums text-muted-foreground">
              {queue.length}
            </span>
          </p>
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
            {queue.map((q, i) => (
              <li key={q.id ?? i} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="w-5 shrink-0 text-right tabular-nums text-muted-foreground">
                  {i + 1}
                </span>
                <Link
                  href={`/tasks/${encodeURIComponent(q.id ?? "")}`}
                  className="shrink-0 font-mono text-xs text-foreground underline-offset-2 hover:underline"
                >
                  {q.id}
                </Link>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{q.goal}</span>
                {q.repo ? (
                  <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    {q.repo}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {mergeWaitRuns.length > 0 ? (
        <div className="space-y-2 rounded-lg border border-verdict-pass/40 bg-verdict-pass/5 p-3">
          <p className="text-sm font-semibold text-verdict-pass">
            PR マージ待ち({mergeWaitRuns.length})— 人間が PR をマージすると run が真に完了します
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {mergeWaitRuns.map((r) => (
              <MergeWaitCard
                key={r.run_id}
                run={r}
                onMerged={() => void load(filter, includeArchived)}
              />
            ))}
          </div>
        </div>
      ) : null}

      {peerErrors.length > 0 ? (
        <div className="rounded-lg border border-verdict-fail/40 bg-verdict-fail/5 p-3 text-sm">
          <p className="font-medium text-verdict-fail">到達できなかった host があります(完了 run を取得できず)</p>
          <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
            {peerErrors.map((p) => (
              <li key={p.name}>
                <span className="font-mono">{p.name}</span>: {p.error}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {notice ? (
        <p className="text-sm text-muted-foreground">{notice}</p>
      ) : null}
      {error ? (
        <p className="text-sm text-verdict-fail">{error}</p>
      ) : null}

      {loading && runs.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">
          読み込み中…
        </div>
      ) : (
        <RunsTable
          runs={tableRuns}
          active={activeRuns}
          onChanged={() => void load(filter, includeArchived)}
          showHost={(fleetInfo?.peers.length ?? 0) > 0}
          selfHost={fleetInfo?.self_name ?? undefined}
        />
      )}
    </div>
  );
}
