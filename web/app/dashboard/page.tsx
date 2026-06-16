/**
 * 分析ダッシュボード(§5)。事実の集計提示のみ。read-only。
 *
 * 絶対原則: 判断(種類B)を生成しない。閾値超過に「危険」「要改善」等のラベル・色(赤=悪)・
 * 推奨・序列・自動要約を付けない。API は生値、ここは中立色 + 数値の表示に徹する(§5.6)。
 * データ源は loop.db(MD 派生の使い捨てインデックス)。封筒の source/generated_at で明示する。
 *
 * Server Component で各 API を no-store fetch(分析は最新スナップショット。SSE/自動ポーリングはしない)。
 */
import Link from "next/link";

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

import { analytics } from "@/components/charts/api";
import { BarChart, type BarDatum } from "@/components/charts/BarChart";
import { LineChart } from "@/components/charts/LineChart";
import { RefreshButton } from "@/components/charts/RefreshButton";
import { ScatterChart, type ScatterPoint } from "@/components/charts/ScatterChart";
import {
  asNum,
  asPercent,
  asUsd,
  passRateByDay,
  shortSha,
} from "@/components/charts/transform";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [summaryEnv, passRateEnv, verdictEnv, gamingEnv, costEnv] = await Promise.all([
    analytics.summary(),
    analytics.passRateBySkill(),
    analytics.verdictSummary(),
    analytics.gamingSuspects(),
    analytics.costTimeline(),
  ]);

  const summary = summaryEnv?.rows[0] ?? null;
  const passRows = passRateEnv?.rows ?? [];
  const verdictRows = verdictEnv?.rows ?? [];
  const gamingRows = gamingEnv?.rows ?? [];
  const costRows = costEnv?.rows ?? [];

  // 取得した封筒のうち最も新しい注記をデータ源表示に使う(loop.db = 使い捨てインデックスの明示)。
  const sourceNote =
    summaryEnv?.source ??
    passRateEnv?.source ??
    "loop.db (derived index; authoritative=runs/*.md)";
  const generatedAt =
    summaryEnv?.generated_at ?? passRateEnv?.generated_at ?? null;

  const passRateBars: BarDatum[] = passRows.map((r) => ({
    label: shortSha(r.skill_sha),
    value: r.pass_rate ?? 0,
    note: `n=${r.n}`,
    title: `${r.skill_sha ?? "(none)"} — pass_rate=${asPercent(r.pass_rate)}, avg_cost=${asUsd(r.avg_cost)}, n=${r.n}`,
  }));

  const passRateLine = passRateByDay(costRows);

  const scatter: ScatterPoint[] = costRows.map((r) => ({
    x: r.turns ?? 0,
    y: r.cost_usd ?? 0,
    category: r.verdict ?? "",
    title: `${r.run_id}: turns=${asNum(r.turns)}, cost=${asUsd(r.cost_usd)} (${r.verdict ?? "—"})`,
  }));

  const cards = summary
    ? [
        { label: "総 run", value: summary.total_runs },
        { label: "レビュー済", value: summary.reviewed },
        { label: "未レビュー", value: summary.unreviewed },
        { label: "pass", value: summary.pass },
        { label: "fail", value: summary.fail },
        { label: "skill 種類", value: summary.distinct_skills },
      ]
    : [];

  const apiDown = summaryEnv === null && passRateEnv === null && verdictEnv === null;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            集計の事実提示(read-only)。評価・推奨はしない。判断は run 詳細で人間が行う。
          </p>
        </div>
        <RefreshButton />
      </div>

      <p className="text-xs text-muted-foreground">
        データ源: {sourceNote}
        {generatedAt && <> / 取得: {generatedAt}</>}
      </p>

      {apiDown && (
        <Card>
          <CardHeader>
            <CardTitle>データを取得できません</CardTitle>
            <CardDescription>
              API(127.0.0.1:8765)が未起動、または loop.db が未生成の可能性があります。
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* サマリ数値カード群(素の数字。色付けなし) */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((c) => (
          <Card key={c.label}>
            <CardHeader className="p-4">
              <CardDescription>{c.label}</CardDescription>
              <CardTitle className="text-2xl tabular-nums">{c.value ?? 0}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* pass 率(skill 別)。中立単色。良し悪しの含意を避ける */}
        <Card>
          <CardHeader>
            <CardTitle>pass 率(skill 別)</CardTitle>
            <CardDescription>
              skill_sha ごとの pass / 件数。バー脇の n は件数。色は中立(評価しない)。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <BarChart data={passRateBars} max={1} format={(v) => asPercent(v)} />
          </CardContent>
        </Card>

        {/* pass 率の時系列(日次ビニング)。事実点のみ。トレンドラインは引かない */}
        <Card>
          <CardHeader>
            <CardTitle>pass 率の時系列</CardTitle>
            <CardDescription>
              日次バケットの pass / 件数。点はその日の率(トレンド断定はしない)。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart data={passRateLine} max={1} yFormat={(v) => asPercent(v)} />
          </CardContent>
        </Card>

        {/* verdict 構成。件数。未レビューは別バッジで数値併記。「未レビュー=悪」の色付けはしない */}
        <Card>
          <CardHeader>
            <CardTitle>verdict 構成</CardTitle>
            <CardDescription>verdict ごとの件数・未レビュー数・平均コスト/ターン。</CardDescription>
          </CardHeader>
          <CardContent>
            {verdictRows.length === 0 ? (
              <p className="text-sm text-muted-foreground">データなし</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>verdict</TableHead>
                    <TableHead className="text-right">件数</TableHead>
                    <TableHead className="text-right">未レビュー</TableHead>
                    <TableHead className="text-right">平均コスト</TableHead>
                    <TableHead className="text-right">平均ターン</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {verdictRows.map((r) => (
                    <TableRow key={r.verdict ?? "(none)"}>
                      <TableCell className="font-mono">{r.verdict ?? "(none)"}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.n}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.unreviewed}</TableCell>
                      <TableCell className="text-right tabular-nums">{asUsd(r.avg_cost)}</TableCell>
                      <TableCell className="text-right tabular-nums">{asNum(r.avg_turns, 1)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* コスト/turns 分布。色=verdict は識別用カテゴリ色(評価ではない) */}
        <Card>
          <CardHeader>
            <CardTitle>コスト / ターン分布</CardTitle>
            <CardDescription>x=turns, y=cost_usd、点=run。色は verdict の識別色。</CardDescription>
          </CardHeader>
          <CardContent>
            <ScatterChart data={scatter} xLabel="turns" yLabel="cost_usd" />
          </CardContent>
        </Card>
      </div>

      {/* gaming 疑い一覧。機械的事実(test pass/none かつ verifier fail)を並べるだけ。断定しない */}
      <Card>
        <CardHeader>
          <CardTitle>test pass/none かつ verifier fail の run</CardTitle>
          <CardDescription>
            機械的条件で抽出した run(started_at 降順)。各行から run 詳細へ。確信度は Verifier の事実値を表示するのみ。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {gamingRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">該当 run なし</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>run_id</TableHead>
                  <TableHead>task</TableHead>
                  <TableHead>test</TableHead>
                  <TableHead>verifier</TableHead>
                  <TableHead>confidence</TableHead>
                  <TableHead>started_at</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {gamingRows.map((r) => (
                  <TableRow key={r.run_id}>
                    <TableCell className="font-mono">
                      <Link href={`/runs/${encodeURIComponent(r.run_id)}`} className="underline-offset-4 hover:underline">
                        {r.run_id}
                      </Link>
                    </TableCell>
                    <TableCell>{r.task ?? "—"}</TableCell>
                    <TableCell className="font-mono">{r.test_verdict ?? "—"}</TableCell>
                    <TableCell className="font-mono">{r.verifier_verdict ?? "—"}</TableCell>
                    <TableCell className="font-mono">{r.verifier_confidence ?? "—"}</TableCell>
                    <TableCell className="tabular-nums">{r.started_at ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {gamingEnv?.has_more && (
            <p className="mt-3 text-xs text-muted-foreground">さらに古い run があります(limit 到達)。</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
