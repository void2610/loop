import { TranscriptView } from "@/components/runs/detail/transcript-view";

// 完成 run の transcript 会話ビュー。取得はクライアントから /api/* を直接叩く(run 詳細と同方式)。
// ?host=<peer name> で Fleet 他 host の run を表示。
export default async function RunTranscriptPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ host?: string }>;
}) {
  const { id } = await params;
  const { host } = await searchParams;
  return <TranscriptView runId={id} host={host} />;
}
