/**
 * 型付き fetch クライアント。OpenAPI(webapp/schemas.py 正本)生成の types.ts を通す。
 *
 * 凍結面(read-only): 後続ワークストリームは本ファイルを書き換えず、ここの関数を import する。
 * 中心思想: API は事実の配送のみ。判断生成・要約・推奨はバック/フロント双方で行わない。
 * 書き込み(judgment/task)は runner 経由で data/ の MD と git に着地する素通し口を叩くだけ。
 */
import type { components } from "./types";

type Schemas = components["schemas"];

// --- 公開する型エイリアス(各ページはこれを import。types.ts は直接触らない) ---
export type RunRow = Schemas["RunRow"];
export type RunListResponse = Schemas["RunListResponse"];
export type RunDetail = Schemas["RunDetail"];
export type EvidenceMeta = Schemas["EvidenceMeta"];
export type EvidenceFileMeta = Schemas["EvidenceFileMeta"];

// schemas.py の TranscriptEvent はレスポンスで参照されず OpenAPI components に出ない
// (events は dict[str,Any] 配列で素通し)ため、契約形をここで明示する(§2.2)。
// extra="allow" 由来の追加キー(collapse 等)を許す。
export type TranscriptEvent = {
  cls: string;
  label: string;
  body: string;
  ts: string;
  [key: string]: unknown;
};
export type TranscriptResponse = Schemas["TranscriptResponse"];
export type TaskRow = Schemas["TaskRow"];
export type TaskListResponse = Schemas["TaskListResponse"];
export type TaskFields = Schemas["TaskFields"];
export type TaskDetail = Schemas["TaskDetail"];
export type TaskInput = Schemas["TaskInput"];
export type JudgmentInput = Schemas["JudgmentInput"];
export type GenerateInput = Schemas["GenerateInput"];
export type ReposResponse = Schemas["ReposResponse"];
export type BranchesResponse = Schemas["BranchesResponse"];
export type MonitorSnapshot = Schemas["MonitorSnapshot"];
export type LiveSnapshot = Schemas["LiveSnapshot"];
export type PrStatus = Schemas["PrStatus"];
export type LiveRole = Schemas["LiveRole"];
export type MetaResponse = Schemas["MetaResponse"];
export type RunStartResult = Schemas["RunStartResult"];
export type LastRun = Schemas["LastRun"];
export type NormsResponse = Schemas["NormsResponse"];
export type NormRepo = Schemas["NormRepo"];
export type NormCandidate = Schemas["NormCandidate"];
export type NormActivity = Schemas["NormActivity"];
export type ConventionsInput = Schemas["ConventionsInput"];

/** JSON は同一オリジン(/api/*)を Next rewrite で uvicorn へ転送する(§1.5)。 */
const BASE = "";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; body?: unknown; raw?: boolean } = {}
): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (opts.body !== undefined) {
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${BASE}/api${path}${qs(opts.query)}`, init);
  if (!res.ok) {
    let code: string | undefined;
    let detail = res.statusText;
    try {
      const j = await res.json();
      // FastAPI の HTTPException は {detail: {...}} 形。err() ヘルパ由来の {code,message} を拾う
      const d = j?.detail ?? j;
      if (d && typeof d === "object") {
        code = d.code;
        detail = d.message ?? d.detail ?? detail;
      } else if (typeof d === "string") {
        detail = d;
      }
    } catch {
      // body が JSON でない(text/plain 等)場合はそのまま statusText
    }
    throw new ApiError(res.status, detail, code);
  }
  if (res.status === 204 || opts.raw) {
    return (opts.raw ? await res.text() : undefined) as T;
  }
  return (await res.json()) as T;
}

// --- 読み取り(GET。副作用なし。reindex はインデックス再生成で契約ファイルを書き換えない) ---
export const api = {
  listRuns: (params?: { verdict?: string; reviewed?: 0 | 1; task?: string; include_archived?: boolean }) =>
    request<RunListResponse>("GET", "/runs", { query: params }),

  runDetail: (runId: string) =>
    request<RunDetail>("GET", `/runs/${encodeURIComponent(runId)}`),

  runEvidence: (runId: string) =>
    request<EvidenceMeta>("GET", `/runs/${encodeURIComponent(runId)}/evidence`),

  /** 証拠ファイル本文(text/plain)。allowlist 済みの name のみ。 */
  runFile: (runId: string, name: string) =>
    request<string>("GET", `/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`, {
      raw: true,
    }),

  runTranscript: (runId: string) =>
    request<TranscriptResponse>("GET", `/runs/${encodeURIComponent(runId)}/transcript`),

  monitor: () => request<MonitorSnapshot>("GET", "/monitor"),

  runLive: (runId: string) =>
    request<LiveSnapshot>("GET", `/runs/${encodeURIComponent(runId)}/live`),

  // awaiting 中の run へ続行指示を送る(inbox 経由で同一セッションへ注入)。
  sendMessage: (runId: string, text: string) =>
    request<void>("POST", `/runs/${encodeURIComponent(runId)}/message`, { body: { text } }),

  // 実行中/awaiting の run を停止(stopped で正常終了)。
  stopRun: (runId: string) =>
    request<void>("POST", `/runs/${encodeURIComponent(runId)}/stop`),

  // awaiting-merge の run の PR 状態(マージ済みなら server 側で pass に昇格)。
  runPr: (runId: string) =>
    request<PrStatus>("GET", `/runs/${encodeURIComponent(runId)}/pr`),

  listTasks: (params?: { include_archived?: boolean }) =>
    request<TaskListResponse>("GET", "/tasks", { query: params }),

  taskDetail: (taskId: string) =>
    request<TaskDetail>("GET", `/tasks/${encodeURIComponent(taskId)}`),

  repos: () => request<ReposResponse>("GET", "/repos"),

  repoBranches: (repo: string) =>
    request<BranchesResponse>("GET", `/repos/branches?repo=${encodeURIComponent(repo)}`),

  meta: () => request<MetaResponse>("GET", "/meta"),

  // --- 書き込み(runner 素通し。判断・契約は MD/git が正本) ---

  /** 判断の中継(A(中継))。人間入力の trust/risk/checks/learning をそのまま送る。204。 */
  putJudgment: (runId: string, body: JudgmentInput) =>
    request<void>("POST", `/runs/${encodeURIComponent(runId)}/judgment`, { body }),

  createTask: (body: TaskInput) =>
    request<{ task_id: string }>("POST", "/tasks", { body }),

  updateTask: (taskId: string, body: TaskInput) =>
    request<{ task_id: string }>("PUT", `/tasks/${encodeURIComponent(taskId)}`, { body }),

  /** タスクをアーカイブ/解除(削除しない=ログは資産。UI から隠すだけ)。204。 */
  archiveTask: (taskId: string, archived: boolean) =>
    request<void>("POST", `/tasks/${encodeURIComponent(taskId)}/archive`, { body: { archived } }),

  /** run をアーカイブ/解除(削除しない)。204。 */
  archiveRun: (runId: string, archived: boolean) =>
    request<void>("POST", `/runs/${encodeURIComponent(runId)}/archive`, { body: { archived } }),

  // --- 実行起動(x-loop-exec。claude -p を起動する RCE 露出点。busy は 409) ---

  runTask: (taskId: string) =>
    request<RunStartResult>("POST", `/tasks/${encodeURIComponent(taskId)}/run`, { body: {} }),

  generate: (body: GenerateInput) =>
    request<{ accepted: boolean }>("POST", "/tasks/generate", { body }),

  dispatch: () => request<RunStartResult>("POST", "/dispatch", { body: {} }),

  // --- norms(知識更新エージェント)。read + 昇格/却下の中継(中身の判断は人間=種類B) ---

  /** 現在の知識(conventions.md)+ 候補 + 起草エージェントの動作履歴。 */
  norms: () => request<NormsResponse>("GET", "/norms"),

  /** 候補を conventions.md へ昇格(人間が押す中継)。204。 */
  promoteNorm: (candidateId: string) =>
    request<void>("POST", `/norms/${encodeURIComponent(candidateId)}/promote`, { body: {} }),

  /** 候補を却下(人間が押す中継)。204。 */
  rejectNorm: (candidateId: string) =>
    request<void>("POST", `/norms/${encodeURIComponent(candidateId)}/reject`, { body: {} }),

  /** 承認済み知識(conventions.md)を人間が編集して保存(統合・剪定・修正)。204。 */
  putConventions: (repo: string, text: string) =>
    request<void>("PUT", `/norms/${encodeURIComponent(repo)}/conventions`, { body: { text } }),
};
