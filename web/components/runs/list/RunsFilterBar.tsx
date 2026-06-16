"use client";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type ReviewedFilter = "" | "0" | "1";

export type RunsFilter = {
  verdict: string;
  reviewed: ReviewedFilter;
  task: string;
};

const selectClass = cn(
  "h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm",
  "transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
  "disabled:cursor-not-allowed disabled:opacity-50"
);

export function RunsFilterBar({
  filter,
  verdicts,
  count,
  dispatching,
  onChange,
  onDispatch,
}: {
  filter: RunsFilter;
  verdicts: string[];
  count: number;
  dispatching: boolean;
  onChange: (next: RunsFilter) => void;
  onDispatch: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        className={selectClass}
        value={filter.verdict}
        onChange={(e) => onChange({ ...filter, verdict: e.target.value })}
        aria-label="verdict で絞り込み"
      >
        <option value="">verdict: all</option>
        {verdicts.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>

      <select
        className={selectClass}
        value={filter.reviewed}
        onChange={(e) =>
          onChange({ ...filter, reviewed: e.target.value as ReviewedFilter })
        }
        aria-label="reviewed で絞り込み"
      >
        <option value="">reviewed: all</option>
        <option value="0">未レビュー</option>
        <option value="1">レビュー済</option>
      </select>

      <Input
        className="w-48"
        value={filter.task}
        onChange={(e) => onChange({ ...filter, task: e.target.value })}
        placeholder="task で絞り込み"
        aria-label="task で絞り込み"
      />

      <span className="text-sm text-muted-foreground">{count} runs</span>

      <div className="ml-auto">
        {/* dispatch は claude -p を起動する実行起動口(種類A)。判断は生成しない。 */}
        <Button onClick={onDispatch} disabled={dispatching}>
          {dispatching ? "起動中…" : "次の todo を実行"}
        </Button>
      </div>
    </div>
  );
}
