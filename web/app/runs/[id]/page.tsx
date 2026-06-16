import { RunDetailView } from "@/components/runs/detail/run-detail";

// run 詳細。データ取得と判断保存はクライアントから FastAPI(/api/*)を直接叩く(§6.2)。
export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RunDetailView runId={id} />;
}
