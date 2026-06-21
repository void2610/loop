/**
 * Server Component 用の no-store fetch。lib/api.ts は相対 BASE(ブラウザ→Next rewrite)なので
 * server からは叩けず、絶対 URL が要る。self は backend(:8765)直、peer は Next フロント(:3000)の
 * /api/peer/<host>/* 経由(rewrite で peer backend へ転送)。
 *
 * これ以前は charts/api.ts・knowledge/server.ts・dashboard が同じ BASE/FRONT_BASE/no-store/
 * try-catch-null を個別に持っていた。read-only(分析・知識は最新スナップショットを観測するだけ)。
 */
const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8765";
const FRONT_BASE = process.env.FRONT_BASE ?? "http://127.0.0.1:3000";

function serverUrl(path: string, host?: string): string {
  return host
    ? `${FRONT_BASE}/api/peer/${encodeURIComponent(host)}${path}`
    : `${API_BASE}/api${path}`;
}

/** /api<path> を no-store で GET。API 未起動 / loop.db 未生成 / !ok でもページを壊さず null を返す。 */
export async function serverGet<T>(path: string, host?: string): Promise<T | null> {
  try {
    const res = await fetch(serverUrl(path, host), { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** Fleet の他 host 名一覧(self を除く)。Fleet off / 取得失敗時は空(=自 host のみ)。 */
export async function serverPeerNames(): Promise<string[]> {
  const info = await serverGet<{ peers: { name: string; is_self: boolean }[] }>("/fleet/peers");
  return info ? info.peers.filter((p) => !p.is_self).map((p) => p.name) : [];
}
