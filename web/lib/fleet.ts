/**
 * Fleet: 複数 PC を 1 つの GUI から扱う面。
 *
 * 設計: 真実は各 PC の data/ に分散(各 PC は自分の run のみ持つ)。
 * 各 peer は自分の Next フロント(Tailnet)を公開し、Fleet 画面はそれを並列 fetch して merge する。
 * BFF は作らない(Next の rewrites は静的で、動的 peer 解決には不向き)。
 * server-side fetch なので CORS 関係なし。peer unreachable は per-host エラーとして残す(全体は落とさない)。
 */
import {
  ApiError,
  type BranchesResponse,
  type EvidenceMeta,
  type GenerateAccepted,
  type GenerateInput,
  type JudgmentInput,
  type LiveSnapshot,
  type ReposResponse,
  type RunDetail,
  type RunListResponse,
  type RunRow,
  type RunStartResult,
  type TaskDetail,
  type TaskInput,
  type TaskListResponse,
  type TranscriptResponse,
} from "./api";
import type { components } from "./types";

export type FleetInfo = components["schemas"]["FleetInfo"];
export type FleetPeer = components["schemas"]["FleetPeer"];
export type PromptPreview = components["schemas"]["PromptPreview"];
export type AuthorPromptPreview = components["schemas"]["AuthorPromptPreview"];

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
  // 204 No Content は body 空。
  if (res.status === 204) return undefined as T;
  // peer プロキシは content-length を剥がす(streaming 対応の副作用)ため、text() 経由で
  // 安全に取り出す。空 body や非 JSON でも throw せず undefined 扱い。
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return undefined as T;
  }
}

/** peer 経由で生テキスト(証拠ファイル本文等)を取る。404 等は ApiError。 */
async function peerFetchText(host: string | undefined, path: string): Promise<string> {
  const url = host ? `/api/peer/${encodeURIComponent(host)}${path}` : `/api${path}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "network error");
  }
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return await res.text();
}

function qsString(params?: RunsParams): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Fleet 用に host を指定できる版の write/read API。host 空なら api.* と同じ自 host 経由。 */
export const peerApi = {
  // 一覧 / 詳細 / 証拠 / transcript
  listRuns: (host: string | undefined, params?: RunsParams) =>
    peerFetchJson<RunListResponse>(host, `/runs${qsString(params)}`),
  runDetail: (host: string | undefined, runId: string) =>
    peerFetchJson<RunDetail>(host, `/runs/${encodeURIComponent(runId)}`),
  runEvidence: (host: string | undefined, runId: string) =>
    peerFetchJson<EvidenceMeta>(host, `/runs/${encodeURIComponent(runId)}/evidence`),
  runFile: (host: string | undefined, runId: string, name: string) =>
    peerFetchText(host, `/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`),
  runTranscript: (host: string | undefined, runId: string) =>
    peerFetchJson<TranscriptResponse>(host, `/runs/${encodeURIComponent(runId)}/transcript`),
  // ライブ / 介入 / 停止
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
  // 完了 run に追加指示を投じて Implementer を resume + Verifier 監査(同じ run_id を保つ)
  continueRun: (host: string | undefined, runId: string, text: string) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/continue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  // 種類A: dispatch / 判断書き戻し / アーカイブ
  dispatch: (host: string | undefined) =>
    peerFetchJson<RunStartResult>(host, `/dispatch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  submitJudgment: (host: string | undefined, runId: string, j: JudgmentInput) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/judgment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(j),
    }),
  archiveRun: (host: string | undefined, runId: string, archived: boolean) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/archive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived }),
    }),
  // tasks
  listTasks: (host: string | undefined, params?: { include_archived?: boolean }) => {
    const qs = params?.include_archived ? `?include_archived=true` : "";
    return peerFetchJson<TaskListResponse>(host, `/tasks${qs}`);
  },
  taskDetail: (host: string | undefined, taskId: string) =>
    peerFetchJson<TaskDetail>(host, `/tasks/${encodeURIComponent(taskId)}`),
  // run 起動時に Implementer に渡る brief(憲法 / 規範 / 過去 run の事実)と Author プランを取得
  taskPromptPreview: (host: string | undefined, taskId: string) =>
    peerFetchJson<PromptPreview>(host, `/tasks/${encodeURIComponent(taskId)}/prompt-preview`),
  // タスク生成時に Author に渡る user メッセージを事前に組み立てる(read-only / subprocess 起動なし)
  authorPromptPreview: (host: string | undefined, body: { prompt: string; repo: string }) =>
    peerFetchJson<AuthorPromptPreview>(host, `/tasks/generate/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  runTask: (host: string | undefined, taskId: string) =>
    peerFetchJson<RunStartResult>(host, `/tasks/${encodeURIComponent(taskId)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  archiveTask: (host: string | undefined, taskId: string, archived: boolean) =>
    peerFetchJson<void>(host, `/tasks/${encodeURIComponent(taskId)}/archive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived }),
    }),
  createTask: (host: string | undefined, body: TaskInput) =>
    peerFetchJson<{ task_id: string }>(host, `/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateTask: (host: string | undefined, taskId: string, body: TaskInput) =>
    peerFetchJson<{ task_id: string }>(host, `/tasks/${encodeURIComponent(taskId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // タスク生成(プロンプト→目標契約)。host 指定でその peer の Author に作らせる。
  generate: (host: string | undefined, body: GenerateInput) =>
    peerFetchJson<GenerateAccepted>(host, `/tasks/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // repo メタ
  listRepos: (host: string | undefined) =>
    peerFetchJson<ReposResponse>(host, `/repos`),
  repoBranches: (host: string | undefined, repo: string) =>
    peerFetchJson<BranchesResponse>(host, `/repos/branches?repo=${encodeURIComponent(repo)}`),
  // タスク生成(Author)の履歴一覧。
  listGens: (host: string | undefined, limit = 30) =>
    peerFetchJson<{ generations: GenSummary[] }>(host, `/gen?limit=${limit}`),
  // タスク生成を途中停止(stop マーカー → cmd_gen の watcher が subprocess を kill)。
  stopGen: (host: string | undefined, genId: string) =>
    peerFetchJson<void>(host, `/gen/${encodeURIComponent(genId)}/stop`, { method: "POST" }),
};

export type GenSummary = {
  gen_id: string;
  status: "ok" | "fail" | "running" | string;
  task_id: string | null;
  error: string | null;
  started_at: string | null;
};

export type GenSummaryWithHost = GenSummary & { host: string };

/** 全 peer の /api/gen を並列 fetch し host 付きで時刻降順 merge。 */
export async function fetchAllPeerGens(peers: FleetPeer[], limit = 30): Promise<GenSummaryWithHost[]> {
  const results = await Promise.all(
    peers.map(async (p) => {
      try {
        const res = await peerApi.listGens(p.is_self ? undefined : p.name, limit);
        return res.generations.map((g) => ({ ...g, host: p.name }));
      } catch {
        return [] as GenSummaryWithHost[];
      }
    }),
  );
  return results
    .flat()
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
    .slice(0, limit);
}

/** Fleet 用に host を持たせた TaskRow(merge view で「どの PC のタスクか」を出す)。 */
export type TaskRowWithHost = components["schemas"]["TaskRow"] & { host: string };

/** 全 peers に並列で /tasks を fetch して per-host のままで返す。merge は呼び出し側で。 */
export async function fetchAllPeerTasks(
  peers: FleetPeer[],
  params?: { include_archived?: boolean },
): Promise<{ peer: FleetPeer; ok: boolean; error?: string; tasks: TaskRowWithHost[]; last: Record<string, components["schemas"]["LastRun"]>; running: boolean; generating: boolean }[]> {
  return Promise.all(
    peers.map(async (p) => {
      try {
        const res = await peerApi.listTasks(p.is_self ? undefined : p.name, params);
        return {
          peer: p,
          ok: true,
          tasks: res.tasks.map((t) => ({ ...t, host: p.name })),
          last: res.last,
          running: res.running,
          generating: res.generating,
        };
      } catch (e) {
        return {
          peer: p,
          ok: false,
          error: e instanceof Error ? e.message : "unreachable",
          tasks: [],
          last: {},
          running: false,
          generating: false,
        };
      }
    }),
  );
}
