/**
 * Fleet: 複数 PC を 1 つの GUI から扱う面。
 *
 * 設計: 真実は各 PC の data/ に分散(各 PC は自分の run のみ持つ)。
 * 各 peer は自分の Next フロント(Tailnet)を公開し、Fleet 画面はそれを並列 fetch して merge する。
 * BFF は作らない(Next の rewrites は静的で、動的 peer 解決には不向き)。
 * server-side fetch なので CORS 関係なし。peer unreachable は per-host エラーとして残す(全体は落とさない)。
 */
import type { RunListResponse, RunRow } from "./api";
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
