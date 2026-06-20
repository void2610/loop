/**
 * Fleet peer プロキシ: /api/peer/<host>/<...path> → <peer.url>/api/<path>
 *
 * 目的: client から他 host の /api/* を同一オリジン経由で叩けるようにする(SSE / POST / DELETE 全部)。
 * これによって他 host の /runs/<id>/live(SSE)や dispatch、介入(/runs/<id>/message)を
 * 既存の useMonitorStream / api.* と同じパターンで使えるようになる(差分は base URL の前置だけ)。
 *
 * 設計上のポイント:
 *  - body は req.body をそのまま pipe(streaming POST に対応)。duplex: 'half' は Node fetch で必須。
 *  - upstream のレスポンスも body を ReadableStream のまま Response に渡す(SSE のチャンクが切れない)。
 *  - dynamic = 'force-dynamic' で Next の静的化・キャッシュを無効化(SSE / 長時間レスポンスを切らない)。
 *  - peer 名 → URL の解決は自 host の /api/fleet/peers から取り、プロセス内でキャッシュ(設定変更は再起動前提)。
 *  - 真実は分散したまま。このルートは単なる素通し(誰がどの host を担当するかの集約は backend に持たない)。
 */
import { NextRequest } from "next/server";

const SELF_BACKEND = process.env.API_BASE ?? "http://127.0.0.1:8765";

let peersCache: Promise<Record<string, string>> | null = null;

function getPeersMap(): Promise<Record<string, string>> {
  if (peersCache) return peersCache;
  peersCache = fetch(`${SELF_BACKEND}/api/fleet/peers`)
    .then((r) => r.json())
    .then((data: { peers: { name: string; url: string }[] }) =>
      Object.fromEntries(data.peers.map((p) => [p.name, p.url.replace(/\/+$/, "")])));
  // 失敗したらキャッシュをクリアして次回再試行可能に
  peersCache.catch(() => {
    peersCache = null;
  });
  return peersCache;
}

async function proxy(req: NextRequest, host: string, path: string[]) {
  const peers = await getPeersMap();
  const base = peers[host];
  if (!base) {
    return new Response(JSON.stringify({ detail: `unknown peer: ${host}` }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  }

  const target = `${base}/api/${path.map((p) => encodeURIComponent(p)).join("/")}${req.nextUrl.search}`;

  // ホップバイホップ系と Host を除いて転送(残りはそのまま信用)。
  const headers = new Headers();
  req.headers.forEach((v, k) => {
    const lk = k.toLowerCase();
    if (lk === "host" || lk === "connection" || lk === "content-length") return;
    headers.set(k, v);
  });

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    // Next の data cache に乗せない(SSE / live API は常にフレッシュ・stream)。
    cache: "no-store",
  };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = req.body as unknown as BodyInit;
    init.duplex = "half";
  }

  const upstream = await fetch(target, init);
  // hop-by-hop と Next が再付与するヘッダを除く(content-length は stream で変わる、
  // content-encoding を残すと client が二重解凍を試みる、transfer-encoding は Next が管理)。
  const resHeaders = new Headers(upstream.headers);
  resHeaders.delete("content-encoding");
  resHeaders.delete("content-length");
  resHeaders.delete("transfer-encoding");
  resHeaders.delete("connection");
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}

type Ctx = { params: Promise<{ host: string; path: string[] }> };

async function handler(req: NextRequest, ctx: Ctx) {
  const { host, path } = await ctx.params;
  return proxy(req, host, path);
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const HEAD = handler;
export const OPTIONS = handler;

// 動的化を強制(Next の data cache に乗せない)。
export const dynamic = "force-dynamic";

// 注意: SSE(text/event-stream)はこの handler で中継しない。Next standalone は Node/Edge いずれの
// runtime でも response stream を buffer してしまい最初の event が即時 flush されない(実測 4s で 0 bytes)。
// SSE はブラウザから対象 peer の backend(:8765)を EventSource で直接叩く設計に倣う(別フェーズ)。
// このプロキシは GET / POST / DELETE 等の JSON ボディに使う(dispatch, message, ファイル取得等)。
