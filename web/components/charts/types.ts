/**
 * 分析ダッシュボードの型(§5)。
 *
 * 行型は webapp/schemas.py を正本とする OpenAPI 生成型(@/lib/types)から導出する。
 * 手書き二重定義はしない(型ドリフトは gen:types 再生成 + typecheck で検出)。
 * 封筒(generated_at/source/has_more)は「loop.db は MD 派生の使い捨てインデックス」を
 * UI で明示するための注記。
 */
import type { components } from "@/lib/types";

type Schemas = components["schemas"];

export type StatsEnvelope<R> = {
  generated_at: string;
  source: string;
  rows: R[];
  has_more: boolean;
};

export type SummaryRow = Schemas["SummaryRow"];
export type PassRateRow = Schemas["PassRateRow"];
export type VerdictSummaryRow = Schemas["VerdictSummaryRow"];
export type GamingSuspectRow = Schemas["GamingSuspectRow"];
export type CostTimelineRow = Schemas["CostTimelineRow"];
