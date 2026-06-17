import { Badge, type BadgeProps } from "@/components/ui/badge";

// verdict 文字列 → Badge variant。色は事実の表示整形であり判断生成ではない(§6.7)。
function variantFor(verdict: string): BadgeProps["variant"] {
  switch (verdict.toLowerCase()) {
    case "pass":
      return "pass";
    case "fail":
      return "fail";
    case "handoff":
      return "handoff";
    default:
      return "outline";
  }
}

// emptyDash=true は一覧向け(空を「—」で詰める)。既定は詳細向けに "verdict なし" バッジ。
export function VerdictBadge({
  verdict,
  emptyDash = false,
}: {
  verdict: string | null | undefined;
  emptyDash?: boolean;
}) {
  const v = (verdict ?? "").trim();
  if (!v) {
    return emptyDash ? (
      <span className="text-muted-foreground">—</span>
    ) : (
      <Badge variant="outline">verdict なし</Badge>
    );
  }
  return <Badge variant={variantFor(v)}>{v}</Badge>;
}
