/**
 * 知識(規範記憶)エンドポイントの Server Component 用 fetch ヘルパ。
 *
 * lib/api.ts は相対 BASE(ブラウザ→Next rewrite)なので Server Component から叩けない。
 * ダッシュボード(charts/api.ts)と同様、ここは絶対 URL + no-store で都度取得する。read-only。
 * 事実(現在の知識・候補・起草エージェントの動作履歴)をそのまま受け取るだけ(解釈・推奨はしない)。
 */
import type { NormsResponse } from "@/lib/api";
import { serverGet } from "@/lib/server-fetch";

export function getNorms(): Promise<NormsResponse | null> {
  return serverGet<NormsResponse>("/norms");
}
