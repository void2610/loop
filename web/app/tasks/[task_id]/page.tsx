import { EditTaskClient } from "@/components/tasks/EditTaskClient";

// 目標契約(TODO)の編集 + 実行 + 削除。書き込みは runner 経由で data/ MD と git に着地。
// ?host=<peer name> で Fleet 他 host のタスクを編集(空なら自 host)。
export default async function EditTaskPage({
  params,
  searchParams,
}: {
  params: Promise<{ task_id: string }>;
  searchParams: Promise<{ host?: string }>;
}) {
  const { task_id } = await params;
  const { host } = await searchParams;
  return <EditTaskClient taskId={task_id} host={host} />;
}
