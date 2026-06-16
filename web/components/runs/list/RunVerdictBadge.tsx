import { Badge, type BadgeProps } from "@/components/ui/badge";

// verdict 文字列を badge variant へ写す。色は事実の表示整形であり判断生成ではない。
function variantOf(verdict: string | null | undefined): BadgeProps["variant"] {
  switch ((verdict ?? "").toLowerCase()) {
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

export function RunVerdictBadge({ verdict }: { verdict: string | null | undefined }) {
  const v = (verdict ?? "").trim();
  if (v === "") return <span className="text-muted-foreground">—</span>;
  return <Badge variant={variantOf(v)}>{v}</Badge>;
}
