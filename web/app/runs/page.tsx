import { RunsView } from "@/components/runs/list/RunsView";

export const metadata = {
  title: "Runs — loop",
};

// run 一覧。データ取得とフィルタ状態は client(RunsView)に閉じる。
export default function RunsPage() {
  return <RunsView />;
}
