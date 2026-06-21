import { GeneratingView } from "@/components/tasks/GeneratingView";

// タスク生成(Author)のライブ進行画面。?id=<gen_id>&host=<host> で SSE を購読。
export default async function GeneratingPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string; host?: string; autorun?: string }>;
}) {
  const { id, host, autorun } = await searchParams;
  return <GeneratingView genId={id ?? ""} host={host ?? ""} autorun={autorun === "1"} />;
}
