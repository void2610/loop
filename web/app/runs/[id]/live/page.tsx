import { RunLivePage } from "@/components/monitor/RunLivePage";

// 実行中 run のライブ transcript。Next 15: params は Promise なので server で unwrap。
export default async function RunLiveRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RunLivePage runId={id} />;
}
