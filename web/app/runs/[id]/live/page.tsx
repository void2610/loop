import { RunLivePage } from "@/components/monitor/RunLivePage";

// 実行中 run のライブ transcript。Next 15: params/searchParams は Promise なので server で unwrap。
// ?host=<peer name> で Fleet 他 host の run を購読(空なら自 host)。
export default async function RunLiveRoute({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ host?: string }>;
}) {
  const { id } = await params;
  const { host } = await searchParams;
  return <RunLivePage runId={id} host={host} />;
}
