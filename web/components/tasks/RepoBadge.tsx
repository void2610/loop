import { Badge } from "@/components/ui/badge";
import { repoLabel } from "@/lib/repoLabel";

// repo を事実として表示するだけ(整形は repoLabel = webapp/util.py:repo_label の写し)。
export function RepoBadge({ repo }: { repo: string | null | undefined }) {
  const isNone = (repo ?? "").trim().toLowerCase() === "none";
  return (
    <Badge variant={isNone ? "outline" : "secondary"} title={repo ?? "(デフォルト)"}>
      {repoLabel(repo)}
    </Badge>
  );
}
