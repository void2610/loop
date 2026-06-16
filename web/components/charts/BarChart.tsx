/**
 * 横棒チャート(中立単色)。pass 率など「良し悪しの含意を避けたい」指標用(§5.5/5.6)。
 *
 * 評価色(赤=悪 等)を一切使わない。バーは単色(--primary)。値の整形(% 表示)は呼び出し側。
 * 依存追加を避けるため Recharts ではなく素の SVG/div で描く(機能は同等の事実提示)。
 */
"use client";

import { cn } from "@/lib/utils";

export type BarDatum = {
  label: string;
  value: number; // 0..max
  /** バー脇に添える素の数値注記(例: n=12)。意味づけはしない。 */
  note?: string;
  /** ツールチップ等に出す生テキスト。 */
  title?: string;
};

type Props = {
  data: BarDatum[];
  /** 値の最大(未指定なら data の最大値)。0..1 の率なら 1 を渡す。 */
  max?: number;
  /** 値の表示整形(例: (v)=>`${(v*100).toFixed(0)}%`)。API は生値、整形はここ。 */
  format?: (v: number) => string;
  className?: string;
};

export function BarChart({ data, max, format, className }: Props) {
  const hi = max ?? Math.max(1, ...data.map((d) => d.value));
  const fmt = format ?? ((v: number) => String(v));
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">データなし</p>;
  }
  return (
    <div className={cn("space-y-2", className)}>
      {data.map((d, i) => {
        const pct = hi > 0 ? Math.max(0, Math.min(1, d.value / hi)) * 100 : 0;
        return (
          <div key={`${d.label}-${i}`} title={d.title} className="flex items-center gap-3 text-sm">
            <div className="w-24 shrink-0 truncate font-mono text-xs text-muted-foreground" title={d.label}>
              {d.label}
            </div>
            <div className="relative h-5 flex-1 overflow-hidden rounded bg-muted">
              <div
                className="h-full rounded bg-primary/70"
                style={{ width: `${pct}%` }}
                aria-label={`${d.label}: ${fmt(d.value)}`}
              />
            </div>
            <div className="w-28 shrink-0 text-right tabular-nums">
              <span>{fmt(d.value)}</span>
              {d.note && <span className="ml-2 text-xs text-muted-foreground">{d.note}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
