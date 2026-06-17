"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type RunRow } from "@/lib/api";

import { RunsFilterBar, type RunsFilter } from "./RunsFilterBar";
import { RunsTable } from "./RunsTable";

const EMPTY_FILTER: RunsFilter = { verdict: "", reviewed: "", task: "" };

export function RunsView() {
  const [filter, setFilter] = useState<RunsFilter>(EMPTY_FILTER);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [verdicts, setVerdicts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dispatching, setDispatching] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  // 連打・タイプ中の古いレスポンスで新しい結果を上書きしないための世代カウンタ。
  const reqSeq = useRef(0);

  const load = useCallback(async (f: RunsFilter, archived: boolean) => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.listRuns({
        verdict: f.verdict || undefined,
        reviewed: f.reviewed === "" ? undefined : (Number(f.reviewed) as 0 | 1),
        task: f.task || undefined,
        include_archived: archived || undefined,
      });
      if (seq !== reqSeq.current) return;
      setRuns(res.runs);
      // verdict 選択肢は API 由来(ハードコードしない)。レスポンスが空でも保持する。
      if (res.verdicts.length > 0) setVerdicts(res.verdicts);
    } catch (e) {
      if (seq !== reqSeq.current) return;
      setError(e instanceof ApiError ? e.message : "run 一覧の取得に失敗しました");
      setRuns([]);
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, []);

  // task テキスト入力はデバウンス、verdict/reviewed は即時反映。
  useEffect(() => {
    const t = setTimeout(() => void load(filter, includeArchived), 250);
    return () => clearTimeout(t);
  }, [filter, includeArchived, load]);

  const onDispatch = useCallback(async () => {
    setDispatching(true);
    setNotice(null);
    setError(null);
    try {
      const res = await api.dispatch();
      if (res.accepted) {
        setNotice("run を起動しました。完了後に一覧へ反映されます。");
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
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Runs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          run の事実一覧。行クリックで詳細(判断レビュー)へ。
        </p>
      </div>

      <RunsFilterBar
        filter={filter}
        verdicts={verdicts}
        count={runs.length}
        dispatching={dispatching}
        onChange={setFilter}
        onDispatch={onDispatch}
      />

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(e) => setIncludeArchived(e.target.checked)}
        />
        アーカイブ済みも表示
      </label>

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
        <RunsTable runs={runs} />
      )}
    </div>
  );
}
