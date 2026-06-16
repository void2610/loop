import { Suspense } from "react";
import Link from "next/link";

import { TaskList } from "@/components/tasks/TaskList";
import { Button } from "@/components/ui/button";

export const metadata = { title: "Tasks — loop" };

// data/tasks/ の目標契約(TODO)一覧。表示=API の事実のみ(状態は持たない)。
export default function TasksPage() {
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">タスク</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            data/tasks/ の目標契約。作成・編集・実行はすべて runner 経由で MD と git に着地する。
          </p>
        </div>
        <Link href="/tasks/new">
          <Button>＋ 新規</Button>
        </Link>
      </div>
      <Suspense fallback={<p className="text-sm text-muted-foreground">読み込み中…</p>}>
        <TaskList />
      </Suspense>
    </div>
  );
}
