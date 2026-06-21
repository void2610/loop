/**
 * クライアント側 認証ヘルパ(§7)。判断生成・要約・推奨はしない。トークンの保持と中継のみ。
 *
 * 技術決定(§7.5 / §7.6):
 *  - JSON は同一オリジン(/api/* を Next rewrite で uvicorn へ)。CSRF 緩和のため
 *    トークンは Cookie ではなく Authorization ヘッダ + カスタムヘッダ X-Loop-CSRF で送る。
 *  - SSE は EventSource がヘッダを付けられないため、短命 signed query token を
 *    /api/auth/sse-token で都度発行し ?token= で載せる(web/lib/sse.ts の token 引数へ)。
 *  - フロントの scope 出し分けは UX であって防御ではない。最終ガードは必ずサーバ(§7.6)。
 *
 * 注意: /api/me と /api/auth/sse-token は webapp/auth.py のミドルウェアが直接応答する
 * (OpenAPI には出ないため types.ts に型が無い。ここで契約形を明示する)。
 *
 * ## 配線状況(2026-06 時点・未配線=将来用)
 * 現状の運用は Tailnet(WireGuard)前提で backend の Bearer は未設定のため(§7)、
 * authHeaders / bearerHeader / hasScope / canRead/Write/Execute は **どこからも呼ばれていない**。
 * 実際の認証配線は login 画面の getToken/setToken/clearToken + /api/me のみ。これらの helper を
 * 「認証が効いている」と誤読しないこと。Bearer 認証を有効化する際は lib/http.ts の transport
 * (peerFetchJson)に authHeaders() を、SSE 購読(lib/sse.ts)に sse-token を配線する。
 */

/** /api/me の応答(webapp/auth.py の _handle_me)。 */
export type MeResponse = {
  actor: string | null;
  scope: AuthScope[];
  authenticated: boolean;
  auth_required: boolean;
};

export type AuthScope = "read" | "write" | "execute";

/** /api/auth/sse-token の応答。 */
export type SseTokenResponse = {
  token: string;
  expires_in: number;
};

const TOKEN_KEY = "loop.auth.token";

/** ブラウザに保持した Bearer トークンを取り出す(無ければ null)。SSR では常に null。 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Bearer トークンを保存(ログイン)。空なら消去。 */
export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // localStorage 不可(プライベートモード等)は黙ってトークン無し運用にフォールバック
  }
}

export function clearToken(): void {
  setToken(null);
}

/**
 * クラス W(書き込み/実行起動)に付ける認証ヘッダ。
 * Authorization(あれば)+ X-Loop-CSRF=1。GET(参照)には不要。
 */
export function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { "X-Loop-CSRF": "1" };
  const t = getToken();
  if (t) h["Authorization"] = `Bearer ${t}`;
  return h;
}

/** 参照(GET)にだけ Authorization を付けたいとき用(CSRF ヘッダは付けない)。 */
export function bearerHeader(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

const BASE = "";

/** 現在のトークンの scope と認証状態を取得。ボタン出し分け(§7.6)に使う。 */
export async function fetchMe(): Promise<MeResponse> {
  const res = await fetch(`${BASE}/api/me`, { headers: bearerHeader() });
  if (!res.ok) {
    return { actor: null, scope: [], authenticated: false, auth_required: true };
  }
  return (await res.json()) as MeResponse;
}

/**
 * SSE 用の短命 signed query token を発行(read 主体のみ。§7.6a)。
 * 取得した token を web/lib/sse.ts の subscribeMonitor/subscribeRun の第2/第3引数に渡す。
 */
export async function requestSseToken(): Promise<string | undefined> {
  const res = await fetch(`${BASE}/api/auth/sse-token`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) return undefined; // ローカル no-op 環境では token 不要(undefined で素通し)
  const j = (await res.json()) as SseTokenResponse;
  return j.token;
}

/** scope を満たすか(UI 出し分け専用。サーバ側 require_scope が最終ガード)。 */
export function hasScope(me: MeResponse | null, needed: AuthScope): boolean {
  if (me === null) return false;
  if (!me.auth_required) return true; // ローカル no-op: 全操作可
  return me.scope.includes(needed);
}

export const canRead = (me: MeResponse | null): boolean => hasScope(me, "read");
export const canWrite = (me: MeResponse | null): boolean => hasScope(me, "write");
export const canExecute = (me: MeResponse | null): boolean => hasScope(me, "execute");
