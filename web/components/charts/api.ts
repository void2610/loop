/**
 * 分析エンドポイント(/api/analytics/*)の fetch ヘルパ。
 *
 * lib/api.ts(read-only)は analytics を持たないため、ダッシュボード専用にここで定義する。
 * 全て GET・read-only。loop.db 直読みの集計を「そのまま」受け取るだけで、解釈・序列・推奨はしない。
 * Server Component から no-store で都度取得(分析は最新スナップショット。ライブ更新はしない)。
 */
import type {
  CostTimelineRow,
  GamingSuspectRow,
  PassRateRow,
  StatsEnvelope,
  SummaryRow,
  VerdictSummaryRow,
} from "./types";

const BASE = process.env.API_BASE ?? "http://127.0.0.1:8765";

async function get<R>(path: string): Promise<StatsEnvelope<R> | null> {
  try {
    const res = await fetch(`${BASE}/api${path}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as StatsEnvelope<R>;
  } catch {
    // API 未起動 / loop.db 未生成でもページを壊さない(null=データなし表示)
    return null;
  }
}

export const analytics = {
  summary: () => get<SummaryRow>("/analytics/summary"),
  passRateBySkill: () => get<PassRateRow>("/analytics/pass-rate-by-skill"),
  verdictSummary: () => get<VerdictSummaryRow>("/analytics/verdict-summary"),
  gamingSuspects: () => get<GamingSuspectRow>("/analytics/gaming-suspects"),
  costTimeline: () => get<CostTimelineRow>("/analytics/cost-timeline"),
};
