"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";

/**
 * 規範候補の昇格/却下ボタン(人間=種類B の操作の中継)。
 * GUI は判断を生成・推奨しない。どちらを選ぶかは人間が決め、ここは API へ素通すだけ。
 * pending な候補にのみ表示する(promoted/rejected は確定済みなので操作不可)。
 */
export function CandidateActions({ candidateId }: { candidateId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState<"promote" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(kind: "promote" | "reject") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "promote") await api.promoteNorm(candidateId);
      else await api.rejectNorm(candidateId);
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作に失敗しました");
    } finally {
      setBusy(null);
    }
  }

  const disabled = busy !== null || pending;

  return (
    <div className="flex items-center justify-end gap-2">
      {error && <span className="text-xs text-destructive">{error}</span>}
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => act("reject")}
        title="この候補を却下(削除はしない。status=rejected)"
      >
        <X className="size-3.5" aria-hidden />
        却下
      </Button>
      <Button
        size="sm"
        disabled={disabled}
        onClick={() => act("promote")}
        title="conventions.md へ昇格(以後 run に注入される)"
      >
        <Check className="size-3.5" aria-hidden />
        承認
      </Button>
    </div>
  );
}
