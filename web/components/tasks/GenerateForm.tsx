"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AuthorPromptPreviewView } from "@/components/tasks/AuthorPromptPreviewView";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { getFleetInfo, peerApi, type FleetInfo } from "@/lib/fleet";

// プロンプト → 目標契約の生成(202 非ブロッキング)。
// 生成役は runner 側で read-only 強制。GUI/BFF は LLM を呼ばず prompt を中継するだけ。
// repo は必須(推定しない)。auto_run は生成後の即時実行トグル。
// Fleet: host セレクタで生成先 PC を選び、その peer の Author に作らせる(repos / branches も該当 host から取る)。
export function GenerateForm() {
  const router = useRouter();
  const [fleetInfo, setFleetInfo] = useState<FleetInfo | null>(null);
  const [host, setHost] = useState("");
  const [repos, setRepos] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [repo, setRepo] = useState("");
  const [baseBranch, setBaseBranch] = useState("");
  const [branches, setBranches] = useState<string[]>([]);
  const [noPr, setNoPr] = useState(false);
  const [autoRun, setAutoRun] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 初回: fleetInfo を取り、host を self に初期化。
  useEffect(() => {
    void getFleetInfo()
      .then((f) => {
        setFleetInfo(f);
        setHost(f.self_name ?? f.peers[0]?.name ?? "");
      })
      .catch(() => setFleetInfo({ self_name: null, peers: [] }));
  }, []);

  // host 変更時: その peer の repos を取得(repo セレクションはリセット)。
  useEffect(() => {
    if (!host) return;
    let live = true;
    peerApi
      .listRepos(host)
      .then((r) => {
        if (!live) return;
        setRepos(r.repos);
        setRepo("");
        setBaseBranch("");
        setBranches([]);
      })
      .catch(() => live && setRepos([]));
    return () => {
      live = false;
    };
  }, [host]);

  // 'none' は専用選択肢として最後に出すので一覧からは除外する。
  const registered = repos.filter((r) => r.toLowerCase() !== "none");

  // 選択 repo のブランチ候補を取得(base_branch の datalist 用)。none/未選択は空。
  // baseBranch は API が返す default で初期化(repo を変えるたびに上書き)。
  useEffect(() => {
    if (!host || !repo || repo.toLowerCase() === "none") {
      setBranches([]);
      setBaseBranch("");
      return;
    }
    let live = true;
    peerApi
      .repoBranches(host, repo)
      .then((r) => {
        if (!live) return;
        setBranches(r.branches);
        if (r.default) setBaseBranch(r.default);
      })
      .catch(() => live && setBranches([]));
    return () => {
      live = false;
    };
  }, [host, repo]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!host) {
      setError("生成する host を選択してください");
      return;
    }
    if (!repo) {
      setError("対象リポジトリを選択してください(推定はしません)");
      return;
    }
    if (!prompt.trim()) {
      setError("依頼内容を入力してください");
      return;
    }
    setSubmitting(true);
    try {
      const res = await peerApi.generate(host, {
        prompt,
        repo,
        base_branch: baseBranch,
        no_pr: noPr,
        auto_run: autoRun,
      });
      // 進行画面へ遷移し SSE で Author のライブ transcript を見せる(失敗時もここで通知)。
      const q = new URLSearchParams({ id: res.gen_id, host, autorun: autoRun ? "1" : "" });
      router.push(`/tasks/new/generating?${q.toString()}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "生成の起動に失敗しました");
      setSubmitting(false);
    }
  }

  if (!fleetInfo) {
    return <p className="text-sm text-muted-foreground">読み込み中…</p>;
  }

  return (
    <form onSubmit={onSubmit} className="max-w-3xl space-y-5">
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="gen-host">生成する host</Label>
        <select
          id="gen-host"
          value={host}
          onChange={(e) => setHost(e.target.value)}
          required
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {fleetInfo.peers.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="gen-repo">
          対象リポジトリ{" "}
          <span className="font-normal text-muted-foreground">(必須。推定はしません)</span>
        </Label>
        <select
          id="gen-repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          required
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <option value="" disabled>
            — リポジトリを選択 —
          </option>
          <option value="default">デフォルト</option>
          {registered.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
          <option value="none">none(外部FS・git なし)</option>
        </select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="gen-base-branch">
          起点ブランチ{" "}
          <span className="font-normal text-muted-foreground">
            (任意。既存ブランチを直す場合に選択。空=現在の HEAD)
          </span>
        </Label>
        <Input
          id="gen-base-branch"
          value={baseBranch}
          onChange={(e) => setBaseBranch(e.target.value)}
          list="gen-branchlist"
          placeholder="(HEAD)"
          disabled={!repo || repo.toLowerCase() === "none"}
        />
        <datalist id="gen-branchlist">
          {branches.map((b) => (
            <option key={b} value={b} />
          ))}
        </datalist>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="gen-prompt">依頼内容</Label>
        <Textarea
          id="gen-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          required
          autoFocus
          placeholder={
            "例: package.json のテストが CI で間欠失敗する。原因を直して 10 回連続で通るようにして。\n例: docs/ の壊れた相対リンクを全部見つけて修正して。"
          }
        />
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={noPr}
          onChange={(e) => setNoPr(e.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        PR を出さない(ローカル検証用。pass しても promote しない)
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={autoRun}
          onChange={(e) => setAutoRun(e.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        作成後すぐに自動実行する
      </label>

      <div className="flex items-center gap-4">
        <Button type="submit" disabled={submitting}>
          {submitting ? "生成中…" : "▶ Claude Code に作らせる"}
        </Button>
        <a href="/tasks/new/manual" className="text-sm text-muted-foreground underline">
          手動で書く
        </a>
      </div>

      <div className="surface p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Author に注入されるプロンプト(プレビュー)
        </h2>
        {host ? (
          <AuthorPromptPreviewView host={host} prompt={prompt} repo={repo} />
        ) : (
          <p className="text-sm text-muted-foreground">host を選択するとプレビューが出ます。</p>
        )}
      </div>
    </form>
  );
}
