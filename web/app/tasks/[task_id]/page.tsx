import { EditTaskClient } from "@/components/tasks/EditTaskClient";

// 目標契約(TODO)の編集 + 実行 + 削除。書き込みは runner 経由で data/ MD と git に着地。
export default async function EditTaskPage({
  params,
}: {
  params: Promise<{ task_id: string }>;
}) {
  const { task_id } = await params;
  return <EditTaskClient taskId={task_id} />;
}
