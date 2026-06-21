/**
 * HTTP transport の単一プリミティブ。api.ts(自 host・凍結面)と fleet.ts(peerApi)が共有する。
 *
 * 設計: 同一オリジン(/api/*)と peer プロキシ(/api/peer/<host>/*)を peerPath で 1 つに畳み、
 * fetch + ApiError 解析 + 空/非 JSON body の寛容な扱いをここだけに置く。
 * これ以前は api.ts の request と fleet.ts の peerFetchJson が同じロジックを二重実装していた。
 */

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

export type Query = Record<string, string | number | boolean | null | undefined>;

/** クエリ文字列を組む。空文字 / null / undefined は落とす(従来 3 箇所でコピペされていた)。 */
export function qs(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** host 空 / undefined → /api<path>(同一オリジン)。host 指定 → /api/peer/<host><path>(Next プロキシ)。 */
export function peerPath(host: string | undefined, path: string): string {
  return host ? `/api/peer/${encodeURIComponent(host)}${path}` : `/api${path}`;
}

/** JSON body 付き POST/PUT の RequestInit を組む(peerApi の手組み 11 反復を畳む)。 */
export function jsonInit(method: string, body: unknown = {}): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/** FastAPI の {detail:{code,message}} / {detail:"..."} / 文字列 body から code と message を拾う。 */
async function parseApiError(res: Response): Promise<ApiError> {
  let code: string | undefined;
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const j = (await res.json()) as { detail?: unknown } | unknown;
    const d = (j as { detail?: unknown })?.detail ?? j;
    if (d && typeof d === "object") {
      const o = d as { code?: string; message?: string; detail?: string };
      code = o.code;
      detail = o.message ?? o.detail ?? detail;
    } else if (typeof d === "string") {
      detail = d;
    }
  } catch {
    // body が JSON でない(text/plain 等)場合はそのまま statusText
  }
  return new ApiError(res.status, detail, code);
}

/**
 * peer-aware な JSON fetch。host 空なら同一オリジン、指定ありなら peer プロキシ経由。
 * peer プロキシは content-length を剥がす(streaming 対応の副作用)ため text() 経由で安全に取り出し、
 * 空 body / 非 JSON / 204 は undefined を返す(throw しない)。
 */
export async function peerFetchJson<T>(
  host: string | undefined,
  path: string,
  init?: RequestInit,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(peerPath(host, path), init);
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "network error");
  }
  if (!res.ok) throw await parseApiError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return undefined as T;
  }
}

/** peer 経由で生テキスト(証拠ファイル本文等)を取る。!ok は ApiError。 */
export async function peerFetchText(host: string | undefined, path: string): Promise<string> {
  let res: Response;
  try {
    res = await fetch(peerPath(host, path));
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "network error");
  }
  if (!res.ok) throw await parseApiError(res);
  return await res.text();
}
