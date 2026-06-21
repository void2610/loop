/**
 * SSE / REST から来る監視データを「進行中 run の配列」へ正規化する。
 *
 * 中心思想: ここは事実(runner が .run.lock / status.json に書いた値)の整形のみ。
 * 判断・要約・推奨は一切作らない。§3.4/§3.7-5 の「最初から配列」決定に従い、
 * 単一 run(.run.lock)でも配列長 0/1 として扱う。並列化が来ても UI は不変。
 */
import type { MonitorStatusData } from "@/lib/sse";
import type { MonitorSnapshot } from "@/lib/api";

/** 1 run の進行ステータス(runner が書く事実の射影)。欠損は許容する。
 * Fleet: どの host(peer name)で動いているかを示す。useMonitorStream が常に peer name で埋める。 */
export type RunStatus = {
  run_id: string;
  host: string;
  task?: string;
  repo?: string;
  phase?: string;
  elapsed?: number;
  started_at?: string;
};

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function asNumber(v: unknown): number | undefined {
  return typeof v === "number" ? v : undefined;
}

function toRunStatus(o: Record<string, unknown>): RunStatus | null {
  const runId = asString(o.run_id);
  if (!runId) return null;
  // host は useMonitorStream の recompute で peer name に上書きされる(merge 時の責務)。
  return {
    run_id: runId,
    host: asString(o.host) ?? "",
    task: asString(o.task),
    repo: asString(o.repo),
    phase: asString(o.phase),
    elapsed: asNumber(o.elapsed),
    started_at: asString(o.started_at),
  };
}

/**
 * SSE の status イベント data を run 配列へ。
 * 供給側は将来 {runs:[...]} へ差し替わる(§3.4)が、現状の単一 .run.lock は
 * status オブジェクト 1 個 or {idle:true} で来うる。両形を吸収する。
 */
export function statusToRuns(data: MonitorStatusData): RunStatus[] {
  if (data === null || data === undefined) return [];
  if (typeof data !== "object") return [];
  const o = data as Record<string, unknown>;
  if (o.idle === true) return [];
  if (Array.isArray(o.runs)) {
    const out: RunStatus[] = [];
    for (const item of o.runs) {
      if (item && typeof item === "object") {
        const rs = toRunStatus(item as Record<string, unknown>);
        if (rs) out.push(rs);
      }
    }
    return out;
  }
  const single = toRunStatus(o);
  return single ? [single] : [];
}

/** REST の初回スナップショットを進行中 run 配列へ。active[](全 run)を優先し、無ければ単一 status へ後退。 */
export function snapshotToRuns(snap: MonitorSnapshot | null): RunStatus[] {
  if (!snap) return [];
  if (Array.isArray(snap.active)) {
    const out: RunStatus[] = [];
    for (const item of snap.active) {
      if (item && typeof item === "object") {
        const rs = toRunStatus(item as Record<string, unknown>);
        if (rs) out.push(rs);
      }
    }
    return out;
  }
  if (!snap.status) return [];
  const rs = toRunStatus(snap.status as Record<string, unknown>);
  return rs ? [rs] : [];
}
