/**
 * 手動「更新」ボタン。分析は静的事実なので自動ポーリングはしない(ライブは §4 の責務。§5.7)。
 * router.refresh() で Server Component を no-store 再取得させる。
 */
"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";

export function RefreshButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button variant="outline" size="sm" disabled={pending} onClick={() => start(() => router.refresh())}>
      {pending ? "更新中…" : "更新"}
    </Button>
  );
}
