import Link from "next/link";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// 各ワークストリームの入口。リンク先は後続 WS が実装する(0.5 ゲートでは枠のみ)。
const ENTRIES = [
  { href: "/runs", title: "Runs", desc: "run 一覧・実行中のライブ・判断(種類B)レビュー" },
  { href: "/tasks", title: "Tasks", desc: "目標契約(TODO)の作成・編集・実行" },
  { href: "/dashboard", title: "Dashboard", desc: "集計の事実提示(read-only)" },
];

export default function Home() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">loop</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          file-based contract が単一の真実。GUI は事実の表示と人間入力の中継に徹する。
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {ENTRIES.map((e) => (
          <Link key={e.href} href={e.href} className="block">
            <Card className="transition-colors hover:border-primary">
              <CardHeader>
                <CardTitle>{e.title}</CardTitle>
                <CardDescription>{e.desc}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
