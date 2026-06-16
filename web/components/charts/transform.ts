/**
 * 集計行 → チャート入力への純変換(フロント側ビニング/短縮表示。§5.5)。
 *
 * ここでやるのは「事実の整形」だけ。閾値判定・評価ラベル・推奨・トレンド断定はしない(§5.6)。
 */
import type { CostTimelineRow } from "./types";

/** skill_sha を先頭 7 桁に短縮(表示整形)。 */
export function shortSha(sha: string | null | undefined): string {
  const s = (sha ?? "").trim();
  if (!s) return "(none)";
  return s.slice(0, 7);
}

/** started_at(ISO8601)の日付部分(YYYY-MM-DD)。不正/欠損は null。 */
export function dayKey(started: string | null | undefined): string | null {
  const s = (started ?? "").trim();
  if (s.length < 10) return null;
  const d = s.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : null;
}

/**
 * cost-timeline 行を日次バケットへ畳み、各日の pass 率(pass / 件数)を出す。
 * 事実点のみ(トレンドラインは引かない)。日付昇順で返す。
 */
export function passRateByDay(rows: CostTimelineRow[]): { x: string; y: number; note: string }[] {
  const bucket = new Map<string, { pass: number; total: number }>();
  for (const r of rows) {
    const k = dayKey(r.started_at);
    if (!k) continue;
    const b = bucket.get(k) ?? { pass: 0, total: 0 };
    b.total += 1;
    if (r.verdict === "pass") b.pass += 1;
    bucket.set(k, b);
  }
  return Array.from(bucket.entries())
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([day, b]) => ({
      x: day,
      y: b.total > 0 ? b.pass / b.total : 0,
      note: `${b.pass}/${b.total}`,
    }));
}

/** 0..1 の率を % 文字列に(整形のみ。API は生値)。 */
export function asPercent(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

/** コストを $ 表示に。 */
export function asUsd(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `$${v.toFixed(2)}`;
}

/** 数値を素のまま(欠損は —)。 */
export function asNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(digits);
}
