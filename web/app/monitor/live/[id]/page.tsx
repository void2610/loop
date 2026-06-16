import { RunLivePage } from "@/components/monitor/RunLivePage";

// Next 15: dynamic route の params は Promise。server で unwrap して client へ渡す。
export default async function MonitorLivePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RunLivePage runId={id} />;
}
