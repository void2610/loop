/**
 * Knowledge(知識更新エージェント=規範記憶)ページ。
 *
 * 全部を 1 面で見せる: 現在の知識(conventions.md=run に注入される承認済み規範)/ 起草された候補(承認待ち)/
 * 起草エージェントの動作履歴(どの run で何をトリガーに起草を試み、抽出・空振り・失敗のいずれだったか)。
 *
 * 絶対原則: GUI は判断(種類B)を生成・要約・推奨しない。候補は status を含め事実のまま並べ、
 * 昇格/却下は人間が押す中継(CandidateActions)。どれを承認すべきかの示唆・序列付けはしない。
 * データ源は data/ の MD(conventions.md / candidates.md / runs/<id>/norms.json)。read-only。
 */
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { RefreshButton } from "@/components/charts/RefreshButton";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { getNorms } from "@/components/knowledge/server";
import { CandidateActions } from "@/components/knowledge/CandidateActions";
import type { NormCandidate } from "@/lib/api";

export const dynamic = "force-dynamic";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  pending: "outline",
  promoted: "default",
  rejected: "secondary",
};

const OUTCOME_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  drafted: "default",
  empty: "outline",
  failed: "destructive",
};

const OUTCOME_LABEL: Record<string, string> = {
  drafted: "起草",
  empty: "空振り",
  failed: "失敗",
};

function RunLink({ runId }: { runId: string | null | undefined }) {
  if (!runId) return <span className="text-muted-foreground">—</span>;
  return (
    <Link
      href={`/runs/${encodeURIComponent(runId)}`}
      className="font-mono text-xs underline-offset-4 hover:underline"
    >
      {runId}
    </Link>
  );
}

function CandidatesTable({ candidates }: { candidates: NormCandidate[] }) {
  if (candidates.length === 0) {
    return <p className="text-sm text-muted-foreground">候補なし(摩擦のある run が出ると起草されます)。</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-24">status</TableHead>
          <TableHead>規範案(proposed_norm)</TableHead>
          <TableHead>観察された摩擦</TableHead>
          <TableHead className="w-36">起草元 run</TableHead>
          <TableHead className="w-44 text-right">操作(人間が決める)</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {candidates.map((c) => (
          <TableRow key={c.candidate_id}>
            <TableCell>
              <Badge variant={STATUS_VARIANT[c.status] ?? "outline"}>{c.status}</Badge>
            </TableCell>
            <TableCell className="max-w-md whitespace-pre-wrap">{c.proposed_norm || "—"}</TableCell>
            <TableCell className="max-w-sm whitespace-pre-wrap text-sm text-muted-foreground">
              {c.observed_friction || "—"}
            </TableCell>
            <TableCell>
              <RunLink runId={c.run_id} />
              {c.drafted_at && (
                <div className="text-[11px] tabular-nums text-muted-foreground">{c.drafted_at}</div>
              )}
            </TableCell>
            <TableCell className="text-right">
              {c.status === "pending" ? (
                <CandidateActions candidateId={c.candidate_id} />
              ) : (
                <span className="text-xs text-muted-foreground">確定済み</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default async function KnowledgePage() {
  const data = await getNorms();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Knowledge"
        description="知識更新エージェント(規範記憶)の全体。現在の知識・承認待ちの候補・起草の動作履歴を 1 面で。承認/却下は人間が行う。"
        actions={<RefreshButton />}
      />

      {data === null ? (
        <Card>
          <CardHeader>
            <CardTitle>データを取得できません</CardTitle>
            <CardDescription>
              API(127.0.0.1:8765)が未起動の可能性があります。
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          {/* 起草エージェントの動作履歴: どの run で何をトリガーに起草を試み、結果どうだったか(事実のみ) */}
          <Card>
            <CardHeader>
              <CardTitle>知識更新エージェントの動作履歴</CardTitle>
              <CardDescription>
                摩擦のある run(revise / handoff / 人間の verdict 覆し)で起草を試みた記録。新しい順。
                抽出・空振り・失敗の事実を並べるだけ(再要約しない)。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {data.activity.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  起草はまだ走っていません(摩擦のある run が出ると起動します)。
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-40">started_at</TableHead>
                      <TableHead className="w-36">run</TableHead>
                      <TableHead className="w-28">repo</TableHead>
                      <TableHead className="w-24">結果</TableHead>
                      <TableHead>トリガー / 詳細</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.activity.map((a) => (
                      <TableRow key={a.run_id}>
                        <TableCell className="tabular-nums text-xs">{a.started_at ?? "—"}</TableCell>
                        <TableCell>
                          <RunLink runId={a.run_id} />
                        </TableCell>
                        <TableCell className="text-sm">{a.repo ?? "—"}</TableCell>
                        <TableCell>
                          <Badge variant={OUTCOME_VARIANT[a.outcome] ?? "outline"}>
                            {OUTCOME_LABEL[a.outcome] ?? a.outcome}
                            {a.outcome === "drafted" && ` ${a.drafted}`}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm">
                          <div>{a.trigger || "—"}</div>
                          {a.none_reason && (
                            <div className="text-xs text-muted-foreground">理由: {a.none_reason}</div>
                          )}
                          {a.error && <div className="text-xs text-destructive">{a.error}</div>}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* repo ごとの知識(conventions.md)+ 候補 */}
          {data.repos.length === 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>規範はまだありません</CardTitle>
                <CardDescription>
                  摩擦のある run が出ると候補が起草され、人間が承認したものが「現在の知識」になります。
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            data.repos.map((repo) => (
              <Card key={repo.name}>
                <CardHeader>
                  <CardTitle className="font-mono text-base">{repo.name}</CardTitle>
                  <CardDescription>
                    現在の知識(conventions.md)= run に注入される承認済み規範 / その下に承認待ちの候補。
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div>
                    <h3 className="mb-2 text-sm font-semibold">現在の知識(run に注入される)</h3>
                    {repo.has_conventions ? (
                      <pre className="surface overflow-x-auto rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap">
                        {repo.conventions}
                      </pre>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        承認済みの規範はまだありません(候補を承認すると注入対象になります)。
                      </p>
                    )}
                  </div>
                  <div>
                    <h3 className="mb-2 text-sm font-semibold">候補(承認待ちの控え室・注入されない)</h3>
                    <CandidatesTable candidates={repo.candidates} />
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </>
      )}
    </div>
  );
}
