/**
 * 折れ線チャート(中立単色・事実点のみ)。pass 率の時系列など(§5.5)。
 *
 * トレンドライン・予測・回帰は引かない(断定=判断)。点を時系列順に結ぶだけ。
 * 依存追加を避けるため素の SVG で描く。
 */
"use client";

import { cn } from "@/lib/utils";
import { numFormatter, type NumFmt } from "@/components/charts/transform";

export type LinePoint = {
  x: string; // 表示ラベル(日付バケット等)
  y: number; // 0..max
  note?: string;
};

type Props = {
  data: LinePoint[];
  max?: number;
  yFormat?: NumFmt;
  className?: string;
  height?: number;
};

export function LineChart({ data, max, yFormat, className, height = 180 }: Props) {
  const fmt = numFormatter(yFormat);
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">データなし</p>;
  }
  const W = 600;
  const H = height;
  const pad = { l: 44, r: 12, t: 12, b: 28 };
  const hi = max ?? Math.max(1e-9, ...data.map((d) => d.y));
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const px = (i: number) =>
    pad.l + (data.length === 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const py = (v: number) => pad.t + innerH - (hi > 0 ? (v / hi) * innerH : 0);
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"} ${px(i)} ${py(d.y)}`).join(" ");

  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="折れ線">
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
          {fmt(hi)}
        </text>
        <text x={pad.l - 6} y={pad.t + innerH} textAnchor="end" className="fill-muted-foreground text-[10px]">
          {fmt(0)}
        </text>
        <path d={path} fill="none" className="stroke-primary" strokeWidth={1.5} />
        {data.map((d, i) => (
          <circle key={`${d.x}-${i}`} cx={px(i)} cy={py(d.y)} r={2.5} className="fill-primary">
            <title>{`${d.x}: ${fmt(d.y)}${d.note ? ` (${d.note})` : ""}`}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}
