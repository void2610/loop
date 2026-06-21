/**
 * Fleet: 複数 PC を 1 つの GUI から扱う面。
 *
 * 設計: 真実は各 PC の data/ に分散(各 PC は自分の run のみ持つ)。
 * 各 peer は自分の Next フロント(Tailnet)を公開し、Fleet 画面はそれを並列 fetch して merge する。
 * BFF は作らない(Next の rewrites は静的で、動的 peer 解決には不向き)。
 * server-side fetch なので CORS 関係なし。peer unreachable は per-host エラーとして残す(全体は落とさない)。
 */
import {
  type BranchesResponse,
  type EvidenceMeta,
  type GenerateAccepted,
  type GenerateInput,
  type JudgmentInput,
  type LiveSnapshot,
  type PrStatus,
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
import { jsonInit, peerFetchJson, peerFetchText, qs } from "./http";
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

/** Fleet 用に host を指定できる版の write/read API。host 空なら api.* と同じ自 host 経由。 */
export const peerApi = {
  // 一覧 / 詳細 / 証拠 / transcript
  listRuns: (host: string | undefined, params?: RunsParams) =>
    peerFetchJson<RunListResponse>(host, `/runs${qs(params)}`),
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
  // awaiting-merge run の PR 状態(マージ済みなら server 側で pass へ昇格)。Fleet では run の host へ。
  runPr: (host: string | undefined, runId: string) =>
    peerFetchJson<PrStatus>(host, `/runs/${encodeURIComponent(runId)}/pr`),
  sendMessage: (host: string | undefined, runId: string, text: string) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/message`, jsonInit("POST", { text })),
  stopRun: (host: string | undefined, runId: string) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" }),
  // 完了 run に追加指示を投じて Implementer を resume + Verifier 監査(同じ run_id を保つ)
  continueRun: (host: string | undefined, runId: string, text: string) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/continue`, jsonInit("POST", { text })),
  // 種類A: dispatch / 判断書き戻し / アーカイブ
  dispatch: (host: string | undefined) =>
    peerFetchJson<RunStartResult>(host, `/dispatch`, jsonInit("POST")),
  submitJudgment: (host: string | undefined, runId: string, j: JudgmentInput) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/judgment`, jsonInit("POST", j)),
  archiveRun: (host: string | undefined, runId: string, archived: boolean) =>
    peerFetchJson<void>(host, `/runs/${encodeURIComponent(runId)}/archive`, jsonInit("POST", { archived })),
  // tasks
  listTasks: (host: string | undefined, params?: { include_archived?: boolean }) =>
    peerFetchJson<TaskListResponse>(host, `/tasks${qs(params)}`),
  taskDetail: (host: string | undefined, taskId: string) =>
    peerFetchJson<TaskDetail>(host, `/tasks/${encodeURIComponent(taskId)}`),
  // run 起動時に Implementer に渡る brief(憲法 / 規範 / 過去 run の事実)と Author プランを取得
  taskPromptPreview: (host: string | undefined, taskId: string) =>
    peerFetchJson<PromptPreview>(host, `/tasks/${encodeURIComponent(taskId)}/prompt-preview`),
  // タスク生成時に Author に渡る user メッセージを事前に組み立てる(read-only / subprocess 起動なし)
  authorPromptPreview: (host: string | undefined, body: { prompt: string; repo: string }) =>
    peerFetchJson<AuthorPromptPreview>(host, `/tasks/generate/preview`, jsonInit("POST", body)),
  runTask: (host: string | undefined, taskId: string) =>
    peerFetchJson<RunStartResult>(host, `/tasks/${encodeURIComponent(taskId)}/run`, jsonInit("POST")),
  archiveTask: (host: string | undefined, taskId: string, archived: boolean) =>
    peerFetchJson<void>(host, `/tasks/${encodeURIComponent(taskId)}/archive`, jsonInit("POST", { archived })),
  createTask: (host: string | undefined, body: TaskInput) =>
    peerFetchJson<{ task_id: string }>(host, `/tasks`, jsonInit("POST", body)),
  updateTask: (host: string | undefined, taskId: string, body: TaskInput) =>
    peerFetchJson<{ task_id: string }>(host, `/tasks/${encodeURIComponent(taskId)}`, jsonInit("PUT", body)),
  // タスク生成(プロンプト→目標契約)。host 指定でその peer の Author に作らせる。
  generate: (host: string | undefined, body: GenerateInput) =>
    peerFetchJson<GenerateAccepted>(host, `/tasks/generate`, jsonInit("POST", body)),
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
  // gen_id は YYYY-MM-DD-HHMMSS-gen で時系列順の文字列。started_at の書式ブレで sort が崩れない。
  return results
    .flat()
    .sort((a, b) => (b.gen_id ?? "").localeCompare(a.gen_id ?? ""))
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
