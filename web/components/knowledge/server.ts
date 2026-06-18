/**
 * 知識(規範記憶)エンドポイントの Server Component 用 fetch ヘルパ。
 *
 * lib/api.ts は相対 BASE(ブラウザ→Next rewrite)なので Server Component から叩けない。
 * ダッシュボード(charts/api.ts)と同様、ここは絶対 URL + no-store で都度取得する。read-only。
 * 事実(現在の知識・候補・起草エージェントの動作履歴)をそのまま受け取るだけ(解釈・推奨はしない)。
 */
import type { NormsResponse } from "@/lib/api";

const BASE = process.env.API_BASE ?? "http://127.0.0.1:8765";

export async function getNorms(): Promise<NormsResponse | null> {
  try {
    const res = await fetch(`${BASE}/api/norms`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as NormsResponse;
  } catch {
    // API 未起動でもページを壊さない(null=データなし表示)
    return null;
  }
}
