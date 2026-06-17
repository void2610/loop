import { Badge } from "@/components/ui/badge";
import { repoLabel } from "@/lib/repoLabel";

// repo を事実として表示するだけ(整形は repoLabel = webapp/util.py:repo_label の写し)。
// mono=true は一覧の等幅表示向け。
export function RepoBadge({
  repo,
  mono = false,
}: {
  repo: string | null | undefined;
  mono?: boolean;
}) {
  const isNone = (repo ?? "").trim().toLowerCase() === "none";
  return (
    <Badge
      variant={isNone ? "outline" : "secondary"}
      title={repo ?? "(デフォルト)"}
      className={mono ? "font-mono" : undefined}
    >
      {repoLabel(repo)}
    </Badge>
  );
}
