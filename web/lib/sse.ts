/**
 * SSE 購読の薄い枠。本実装(再接続戦略・並行 run 多重化)は WS4。
 *
 * 技術決定: SSE はブラウザ→FastAPI 直 + CORS。EventSource はヘッダを付けられないため、
 * 認証は短命 signed query token をクエリで載せる(P0 は no-op。実体は WS6)。
 * 凍結したイベント形(§2.3 / §8.6):
 *  - /api/stream/monitor: event=status|run_done|heartbeat
 *  - /api/runs/{id}/stream: event=event|phase|end
 * SSE は事実イベントの追記専用。判断・要約を一切流さない。
 */
import type { TranscriptEvent } from "./api";

/** EventSource の接続 base。JSON の同一オリジン rewrite とは別に FastAPI を直叩きする。 */
const SSE_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

// --- monitor ストリームのイベント形(凍結) ---
export type MonitorStatusData = Record<string, unknown> | null;
export type RunDoneData = { run_id: string };
export type HeartbeatData = { t: number };

// --- per-run ストリームのイベント形(凍結) ---
export type RunStreamEventData = TranscriptEvent & { role?: string };
export type PhaseData = { phase: string };
export type EndData = { run_id: string };

export type MonitorHandlers = {
  status?: (d: MonitorStatusData) => void;
  run_done?: (d: RunDoneData) => void;
  heartbeat?: (d: HeartbeatData) => void;
  error?: (e: Event) => void;
};

export type RunStreamHandlers = {
  event?: (d: RunStreamEventData) => void;
  phase?: (d: PhaseData) => void;
  end?: (d: EndData) => void;
  error?: (e: Event) => void;
};

/** token は WS6 で実体化する短命 signed query token(P0 は undefined)。 */
function sseUrl(path: string, token?: string, peerBase?: string): string {
  // peerBase が指定されたとき(Fleet で他 host を購読)は、その peer の backend URL を直接叩く。
  // 注: peer の url は :3000 の Next フロントを指す。SSE は backend(:8765)を叩く必要があるため、
  // :3000 → :8765 に置き換える(各 PC で tailscale serve --bg --http=8765 8765 が出ている前提)。
  const base = peerBase ? peerBase.replace(/:3000$/, ":8765") : SSE_BASE;
  const fallback = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1";
  const u = new URL(`${base}/api${path}`, fallback);
  if (token) u.searchParams.set("token", token);
  return u.toString();
}

function on<T>(es: EventSource, name: string, cb?: (d: T) => void) {
  if (!cb) return;
  es.addEventListener(name, (e) => {
    try {
      cb(JSON.parse((e as MessageEvent).data) as T);
    } catch {
      // data が JSON でないイベントは無視(heartbeat 等の最小化に備える)
    }
  });
}

/** end イベントで EventSource を close(EventSource は接続切れで自動再接続するため、終了を明示しないと
 *  過去イベントが無限ループで再送される)。 */
function onEnd<T>(es: EventSource, cb?: (d: T) => void) {
  es.addEventListener("end", (e) => {
    try {
      if (cb) cb(JSON.parse((e as MessageEvent).data) as T);
    } catch {
      /* JSON でない場合も close は必ず実行 */
    }
    es.close();
  });
}

/** monitor 全体の SSE を購読。peerBase 指定で Fleet の他 host を購読。戻り値の close() で解放。 */
export function subscribeMonitor(
  handlers: MonitorHandlers,
  token?: string,
  peerBase?: string,
): () => void {
  const es = new EventSource(sseUrl("/stream/monitor", token, peerBase));
  on(es, "status", handlers.status);
  on(es, "run_done", handlers.run_done);
  on(es, "heartbeat", handlers.heartbeat);
  if (handlers.error) es.addEventListener("error", handlers.error);
  return () => es.close();
}

/** 進行中 run のライブ transcript SSE を購読。peerBase 指定で Fleet の他 host を購読。 */
export function subscribeRun(
  runId: string,
  handlers: RunStreamHandlers,
  token?: string,
  peerBase?: string,
): () => void {
  const es = new EventSource(sseUrl(`/runs/${encodeURIComponent(runId)}/stream`, token, peerBase));
  on(es, "event", handlers.event);
  on(es, "phase", handlers.phase);
  onEnd(es, handlers.end);
  if (handlers.error) es.addEventListener("error", handlers.error);
  return () => es.close();
}

// --- タスク生成(Author)ストリーム ---
export type GenEventData = TranscriptEvent & { role?: string };
export type GenResult = { status: "ok" | "fail" | "stopped"; task_id?: string | null; error?: string | null };
export type GenEndData = { gen_id: string; result: GenResult };

export type GenStreamHandlers = {
  event?: (d: GenEventData) => void;
  end?: (d: GenEndData) => void;
  error?: (e: Event) => void;
};

/** タスク生成(Author)のライブ transcript SSE を購読。peerBase 指定で他 host を購読。 */
export function subscribeGen(
  genId: string,
  handlers: GenStreamHandlers,
  token?: string,
  peerBase?: string,
): () => void {
  const es = new EventSource(sseUrl(`/gen/${encodeURIComponent(genId)}/stream`, token, peerBase));
  on(es, "event", handlers.event);
  onEnd(es, handlers.end);
  if (handlers.error) es.addEventListener("error", handlers.error);
  return () => es.close();
}
