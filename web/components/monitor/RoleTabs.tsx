"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

// 依存追加(radix tabs)はネットワーク不可のため不採用。3 役固定の軽量タブを自前実装する。
export type RoleTab = {
  key: string;
  label: string;
  badge?: React.ReactNode;
};

export function RoleTabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: RoleTab[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div
      role="tablist"
      className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1"
    >
      {tabs.map((t) => {
        const selected = t.key === active;
        return (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={selected}
            onClick={() => onSelect(t.key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              selected
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <span>{t.label}</span>
            {t.badge}
          </button>
        );
      })}
    </div>
  );
}
