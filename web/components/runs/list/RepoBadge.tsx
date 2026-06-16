import { Badge } from "@/components/ui/badge";
import { repoLabel } from "@/lib/repoLabel";

// repo を目立つバッジで表示(task 名と同等以上の重要情報)。整形は repoLabel に委ねる。
export function RepoBadge({ repo }: { repo: string | null | undefined }) {
  const isNone = (repo ?? "").trim().toLowerCase() === "none";
  return (
    <Badge variant={isNone ? "outline" : "secondary"} className="font-mono">
      {repoLabel(repo)}
    </Badge>
  );
}
