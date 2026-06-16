import { TranscriptView } from "@/components/runs/detail/transcript-view";

// 完成 run の transcript 会話ビュー。取得はクライアントから /api/* を直接叩く(run 詳細と同方式)。
export default async function RunTranscriptPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TranscriptView runId={id} />;
}
