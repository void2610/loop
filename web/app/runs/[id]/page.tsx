import { RunDetailView } from "@/components/runs/detail/run-detail";

// run 詳細。データ取得と判断保存はクライアントから FastAPI(/api/*)を直接叩く(§6.2)。
// ?host=<peer name> で Fleet 他 host の run を表示(空なら自 host)。
export default async function RunDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ host?: string }>;
}) {
  const { id } = await params;
  const { host } = await searchParams;
  return <RunDetailView runId={id} host={host} />;
}
