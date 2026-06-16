/**
 * 分析ダッシュボードの型(§5)。
 *
 * これらは webapp/api/stats.py の StatsEnvelope に対応するが、当該エンドポイントは
 * lib/api.ts(read-only)と OpenAPI 生成型(types.ts)に含まれないため、ここで契約形を明示する。
 * source/generated_at は「loop.db は MD 派生の使い捨てインデックス」を UI で明示するための注記。
 */

export type StatsEnvelope<R> = {
  generated_at: string;
  source: string;
  rows: R[];
  has_more: boolean;
};

export type SummaryRow = {
  total_runs: number;
  reviewed: number;
  unreviewed: number;
  pass: number;
  fail: number;
  distinct_skills: number;
};

export type PassRateRow = {
  skill_sha: string | null;
  pass_rate: number | null;
  avg_cost: number | null;
  n: number;
};

export type VerdictSummaryRow = {
  verdict: string | null;
  n: number;
  unreviewed: number;
  avg_cost: number | null;
  avg_turns: number | null;
};

export type GamingSuspectRow = {
  run_id: string;
  task: string | null;
  test_verdict: string | null;
  verifier_verdict: string | null;
  verifier_confidence: string | null;
  started_at: string | null;
};

export type CostTimelineRow = {
  run_id: string;
  started_at: string | null;
  cost_usd: number | null;
  turns: number | null;
  verdict: string | null;
  skill_sha: string | null;
};
