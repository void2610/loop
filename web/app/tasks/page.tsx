import { Suspense } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { TaskList } from "@/components/tasks/TaskList";
import { Button } from "@/components/ui/button";

export const metadata = { title: "Tasks — loop" };

// data/tasks/ の目標契約(TODO)一覧。表示=API の事実のみ(状態は持たない)。
export default function TasksPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Tasks"
        description="data/tasks/ の目標契約。作成・編集・実行はすべて runner 経由で MD と git に着地する。"
        actions={
          <Link href="/tasks/new">
            <Button>
              <Plus />
              新規タスク
            </Button>
          </Link>
        }
      />
      <Suspense fallback={<p className="text-sm text-muted-foreground">読み込み中…</p>}>
        <TaskList />
      </Suspense>
    </div>
  );
}
