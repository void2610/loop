/**
 * Fleet: 複数 PC を 1 つの GUI から扱う面。
 *
 * 設計: 真実は各 PC の data/ に分散(各 PC は自分の run のみ持つ)。
 * 各 peer は自分の Next フロント(Tailnet)を公開し、Fleet 画面はそれを並列 fetch して merge する。
 * BFF は作らない(Next の rewrites は静的で、動的 peer 解決には不向き)。
 * server-side fetch なので CORS 関係なし。peer unreachable は per-host エラーとして残す(全体は落とさない)。
 */
import { ApiError, type LiveSnapshot, type RunListResponse, type RunRow, type RunStartResult } from "./api";
import type { components } from "./types";

export type FleetInfo = components["schemas"]["FleetInfo"];
export type FleetPeer = components["schemas"]["FleetPeer"];

/** host 名タグ付きの run 行(merge view で使う)。 */
export type RunRowWithHost = RunRow & { host: string };

/** peer ごとの fetch 結果(成否どちらも残す)。 */
export type PeerRunsResult = {
  peer: FleetPeer;
  ok: boolean;
  error?: string;
  runs: RunRowWithHost[];
  verdicts: string[];
};

/** 自 host の /api/fleet/peers を取得。peers が空なら Fleet off(従来通り単一 PC)。 */
export async function getFleetInfo(): Promise<FleetInfo> {
  const res = await fetch("/api/fleet/peers");
  if (!res.ok) throw new Error(`fleet info: HTTP ${res.status}`);
  return (await res.json()) as FleetInfo;
}

type RunsParams = { verdict?: string; reviewed?: 0 | 1; task?: string; include_archived?: boolean };

function qs(params?: RunsParams): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** 1 peer から /api/runs を取得。失敗してもエラーを返り値に閉じ込める。 */
export async function fetchPeerRuns(peer: FleetPeer, params?: RunsParams): Promise<PeerRunsResult> {
  // 自分自身は同一オリジン経由で(rewrite に乗せて余分なホップを避ける)。
  const base = peer.is_self ? "" : peer.url;
  try {
    const res = await fetch(`${base}/api/runs${qs(params)}`);
    if (!res.ok) {
      return { peer, ok: false, error: `HTTP ${res.status}`, runs: [], verdicts: [] };
    }
    const body = (await res.json()) as RunListResponse;
    const runs: RunRowWithHost[] = body.runs.map((r) => ({ ...r, host: peer.name }));
    return { peer, ok: true, runs, verdicts: body.verdicts };
  } catch (e) {
    return { peer, ok: false, error: e instanceof Error ? e.message : "unreachable", runs: [], verdicts: [] };
  }
}

/** 全 peers に並列 fetch して結果配列を返す(per-host のまま。merge は呼び出し側で)。 */
export async function fetchAllPeerRuns(peers: FleetPeer[], params?: RunsParams): Promise<PeerRunsResult[]> {
  return Promise.all(peers.map((p) => fetchPeerRuns(p, params)));
}

/**
 * host name から peer の Next フロント URL を解決。self / 未登録 / Fleet off なら "" を返す
 * (空文字 = 同一オリジン経由 = 従来挙動)。lib/sse.ts の peerBase 引数や peer-aware fetch に渡す。
 */
export function resolvePeerBase(fleet: FleetInfo | null | undefined, host: string | undefined): string {
  if (!host || !fleet) return "";
  const peer = fleet.peers.find((p) => p.name === host);
  if (!peer || peer.is_self) return "";
  return peer.url.replace(/\/+$/, "");
}

/**
 * peer-aware な JSON fetch。POST/GET/DELETE 等の JSON 系を host 指定で叩く。
 * - host が空 / undefined → 同一オリジン /api/<path>(自 host = 従来挙動)
 * - host 指定 → /api/peer/<host>/<path>(Next route handler のプロキシ経由)
 * 既存 api.ts と同じ ApiError を投げる(呼び出し側のエラー処理を変えない)。
 */
async function peerFetchJson<T>(
  host: string | undefined,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = host ? `/api/peer/${encodeURIComponent(host)}${path}` : `/api${path}`;
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "network error");
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      const d = body.detail;
      if (typeof d === "string") detail = d;
      else if (d && typeof d === "object") {
        const m = (d as { message?: unknown }).message;
        if (typeof m === "string") detail = m;
      }
    } catch {
      /* 非 JSON の応答はそのまま HTTP ステータスを使う */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Fleet 用に host を指定できる版の write/read API。host 空なら api.* と同じ自 host 経由。 */
export const peerApi = {
  runLive: (host: string | undefined, runId: string) =>
    peerFetchJson<LiveSnapshot>(host, `/runs/${encodeURIComponent(runId)}/live`),
  sendMessage: (host: string | undefined, runId: string, text: string) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stopRun: (host: string | undefined, runId: string) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" }),
  dispatch: (host: string | undefined) =>
    peerFetchJson<RunStartResult>(host, `/dispatch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
};
