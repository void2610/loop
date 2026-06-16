/**
 * 散布図。x=turns, y=cost_usd、点=run。色は識別目的のカテゴリ色(評価色ではない。§5.5/5.6)。
 *
 * verdict ごとの色は「どの run か区別する」ための識別色であって、良し悪しの評価ではない。
 * その旨を凡例に明記する。依存追加を避けるため素の SVG で描く。
 */
"use client";

import { cn } from "@/lib/utils";

export type ScatterPoint = {
  x: number;
  y: number;
  category: string; // 識別用カテゴリ(verdict 等)
  title?: string;
};

type Props = {
  data: ScatterPoint[];
  xLabel: string;
  yLabel: string;
  className?: string;
  height?: number;
};

// verdict 識別色(評価ではなくカテゴリ識別)。verdict トークンを流用。
const CATEGORY_CLASS: Record<string, string> = {
  pass: "fill-verdict-pass",
  fail: "fill-verdict-fail",
  handoff: "fill-verdict-handoff",
  timeout: "fill-verdict-handoff",
};

function catClass(c: string): string {
  return CATEGORY_CLASS[c] ?? "fill-muted-foreground";
}

export function ScatterChart({ data, xLabel, yLabel, className, height = 240 }: Props) {
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">データなし</p>;
  }
  const W = 600;
  const H = height;
  const pad = { l: 52, r: 12, t: 12, b: 36 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const maxX = Math.max(1, ...data.map((d) => d.x));
  const maxY = Math.max(1e-9, ...data.map((d) => d.y));
  const px = (v: number) => pad.l + (v / maxX) * innerW;
  const py = (v: number) => pad.t + innerH - (v / maxY) * innerH;
  const categories = Array.from(new Set(data.map((d) => d.category)));

  return (
    <div className={cn("w-full", className)}>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="散布図">
          <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + innerH} className="stroke-border" strokeWidth={1} />
          <line
            x1={pad.l}
            y1={pad.t + innerH}
            x2={pad.l + innerW}
            y2={pad.t + innerH}
            className="stroke-border"
            strokeWidth={1}
          />
          <text x={pad.l - 6} y={pad.t + 4} textAnchor="end" className="fill-muted-foreground text-[10px]">
            {maxY.toFixed(2)}
          </text>
          <text x={pad.l - 6} y={pad.t + innerH} textAnchor="end" className="fill-muted-foreground text-[10px]">
            0
          </text>
          <text
            x={pad.l + innerW}
            y={pad.t + innerH + 20}
            textAnchor="end"
            className="fill-muted-foreground text-[10px]"
          >
            {xLabel}: {maxX}
          </text>
          <text x={pad.l} y={H - 4} className="fill-muted-foreground text-[10px]">
            {yLabel} / {xLabel}
          </text>
          {data.map((d, i) => (
            <circle key={`${d.title}-${i}`} cx={px(d.x)} cy={py(d.y)} r={3} className={catClass(d.category)} opacity={0.8}>
              <title>{d.title ?? `${xLabel}=${d.x}, ${yLabel}=${d.y} (${d.category})`}</title>
            </circle>
          ))}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>色 = verdict(識別用カテゴリ色。良し悪しの評価ではない):</span>
        {categories.map((c) => (
          <span key={c} className="inline-flex items-center gap-1">
            <svg width={10} height={10} aria-hidden>
              <circle cx={5} cy={5} r={4} className={catClass(c)} />
            </svg>
            {c || "(なし)"}
          </span>
        ))}
      </div>
    </div>
  );
}
