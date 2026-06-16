import { Badge } from "@/components/ui/badge";

// verdict 文字列 → Badge variant。事実の表示整形であり判断生成ではない(§6.7)。
function variantFor(verdict: string): "pass" | "fail" | "handoff" | "outline" {
  const v = verdict.toLowerCase();
  if (v === "pass") return "pass";
  if (v === "fail") return "fail";
  if (v === "handoff") return "handoff";
  return "outline";
}

export function VerdictBadge({ verdict }: { verdict: string | null | undefined }) {
  const v = (verdict ?? "").trim();
  if (!v) return <Badge variant="outline">verdict なし</Badge>;
  return <Badge variant={variantFor(v)}>{v}</Badge>;
}
