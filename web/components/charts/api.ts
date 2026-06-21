/**
 * 分析エンドポイント(/api/analytics/*)の fetch ヘルパ。
 *
 * lib/api.ts(read-only)は analytics を持たないため、ダッシュボード専用にここで定義する。
 * 全て GET・read-only。loop.db 直読みの集計を「そのまま」受け取るだけで、解釈・序列・推奨はしない。
 * Server Component から no-store で都度取得(分析は最新スナップショット。ライブ更新はしない)。
 */
import { serverGet } from "@/lib/server-fetch";
import type {
  CostTimelineRow,
  GamingSuspectRow,
  PassRateRow,
  StatsEnvelope,
  SummaryRow,
  VerdictSummaryRow,
} from "./types";

const get = <R,>(path: string, host?: string) => serverGet<StatsEnvelope<R>>(path, host);

/** Fleet 用: host を指定するとその peer の analytics を取る(空なら自 host)。 */
export const analytics = {
  summary: (host?: string) => get<SummaryRow>("/analytics/summary", host),
  passRateBySkill: (host?: string) => get<PassRateRow>("/analytics/pass-rate-by-skill", host),
  verdictSummary: (host?: string) => get<VerdictSummaryRow>("/analytics/verdict-summary", host),
  gamingSuspects: (host?: string) => get<GamingSuspectRow>("/analytics/gaming-suspects", host),
  costTimeline: (host?: string) => get<CostTimelineRow>("/analytics/cost-timeline", host),
};
