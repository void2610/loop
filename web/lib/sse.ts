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
function sseUrl(path: string, token?: string): string {
  const u = new URL(`${SSE_BASE}/api${path}`, typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1");
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

/** monitor 全体の SSE を購読。戻り値の close() で解放する。 */
export function subscribeMonitor(handlers: MonitorHandlers, token?: string): () => void {
  const es = new EventSource(sseUrl("/stream/monitor", token));
  on(es, "status", handlers.status);
  on(es, "run_done", handlers.run_done);
  on(es, "heartbeat", handlers.heartbeat);
  if (handlers.error) es.addEventListener("error", handlers.error);
  return () => es.close();
}

/** 進行中 run のライブ transcript SSE を購読。戻り値の close() で解放する。 */
export function subscribeRun(
  runId: string,
  handlers: RunStreamHandlers,
  token?: string
): () => void {
  const es = new EventSource(sseUrl(`/runs/${encodeURIComponent(runId)}/stream`, token));
  on(es, "event", handlers.event);
  on(es, "phase", handlers.phase);
  on(es, "end", handlers.end);
  if (handlers.error) es.addEventListener("error", handlers.error);
  return () => es.close();
}
