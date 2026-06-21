"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { RowListEditor } from "@/components/tasks/RowListEditor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, type TaskFields, type TaskInput } from "@/lib/api";
import { peerApi } from "@/lib/fleet";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

// 空の編集フォーム初期値(新規 manual 用)。
export function emptyFields(): TaskFields {
  return {
    task_id: "",
    goal: "",
    repo: "",
    base_branch: "",
    no_pr: false,
    accept: [],
    verify: "",
    constraints: [],
    allowed_tools: "",
    max_attempts: "",
    status: "todo",
    body: "",
  };
}

// 目標契約(TODO)の作成/編集フォーム。書き込みは api 経由で runner → data/ MD + git に着地。
// GUI は判断を生成しない: フィールドは人間入力をそのまま中継するだけ。
export function TaskForm({
  mode,
  initial,
  repos,
  statuses,
  body,
  host,
}: {
  mode: "create" | "edit";
  initial: TaskFields;
  repos: string[];
  statuses: string[];
  body: string;
  // Fleet: 編集対象が他 host のタスクのときは peer 経由で書き戻す(新規作成は host=undefined=自 host)。
  host?: string;
}) {
  const router = useRouter();
  const isNew = mode === "create";

  const [taskId, setTaskId] = useState(initial.task_id);
  const [goal, setGoal] = useState(initial.goal);
  const [repo, setRepo] = useState(initial.repo);
  const [baseBranch, setBaseBranch] = useState(initial.base_branch || "");
  const [noPr, setNoPr] = useState(initial.no_pr ?? false);
  const [branches, setBranches] = useState<string[]>([]);
  const [accept, setAccept] = useState<string[]>(initial.accept);
  const [verify, setVerify] = useState(initial.verify);
  const [constraints, setConstraints] = useState<string[]>(initial.constraints);
  const [allowedTools, setAllowedTools] = useState(initial.allowed_tools);
  const [maxAttempts, setMaxAttempts] = useState(initial.max_attempts);
  const [status, setStatus] = useState(initial.status || "todo");
  const [note, setNote] = useState(body);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const statusOptions = statuses.length > 0 ? statuses : ["todo"];

  // 選択 repo のブランチ候補を取得(base_branch の datalist 用)。none は空、空欄=デフォルト repo。
  // 新規作成時、baseBranch が空なら API の default で初期化する(既存編集時は initial を尊重)。
  useEffect(() => {
    if (repo.toLowerCase() === "none") {
      setBranches([]);
      return;
    }
    let live = true;
    api
      .repoBranches(repo)
      .then((r) => {
        if (!live) return;
        setBranches(r.branches);
        if (r.default) setBaseBranch((prev) => prev || r.default!);
      })
      .catch(() => live && setBranches([]));
    return () => {
      live = false;
    };
  }, [repo]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (isNew && !ID_PATTERN.test(taskId)) {
      setError("id は英数字始まりで . _ - のみ使用できます");
      return;
    }
    const payload: TaskInput = {
      task_id: isNew ? taskId : null,
      goal,
      repo,
      base_branch: baseBranch,
      no_pr: noPr,
      accept,
      verify,
      constraints,
      allowed_tools: allowedTools,
      max_attempts: maxAttempts,
      status,
      body: note,
    };
    setSaving(true);
    try {
      if (isNew) {
        // 新規作成は基本「自 host で作る」運用。host 指定があればその peer に作る。
        const res = host ? await peerApi.createTask(host, payload) : await api.createTask(payload);
        const q = host ? `?host=${encodeURIComponent(host)}` : "";
        router.push(`/tasks/${encodeURIComponent(res.task_id)}${q}`);
        router.refresh();
      } else {
        await peerApi.updateTask(host, initial.task_id, payload);
        setSaved(true);
        router.refresh();
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "保存に失敗しました";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-3xl space-y-5">
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {saved && (
        <p className="rounded-md border border-verdict-pass/40 bg-verdict-pass/10 px-3 py-2 text-sm text-verdict-pass">
          保存しました(data repo へコミット済み)。
        </p>
      )}

      {isNew && (
        <div className="space-y-1.5">
          <Label htmlFor="task_id">
            id{" "}
            <span className="font-normal text-muted-foreground">
              (ファイル名。英数字と . _ -。先頭は英数字)
            </span>
          </Label>
          <Input
            id="task_id"
            value={taskId}
            onChange={(e) => setTaskId(e.target.value)}
            placeholder="例: fix-flaky-test"
            required
          />
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="repo">
            repo{" "}
            <span className="font-normal text-muted-foreground">
              (対象リポジトリ。登録名 or 絶対パス。外部FS作業は none。空=デフォルト)
            </span>
          </Label>
          <Input
            id="repo"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            list="repolist"
            placeholder="(デフォルト)"
          />
          <datalist id="repolist">
            {repos.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="base_branch">
            base_branch{" "}
            <span className="font-normal text-muted-foreground">
              (起点ブランチ。loop/&lt;id&gt; をここから切る。空=現在の HEAD)
            </span>
          </Label>
          <Input
            id="base_branch"
            value={baseBranch}
            onChange={(e) => setBaseBranch(e.target.value)}
            list="branchlist"
            placeholder="(HEAD)"
            disabled={repo.toLowerCase() === "none"}
          />
          <datalist id="branchlist">
            {branches.map((b) => (
              <option key={b} value={b} />
            ))}
          </datalist>
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={noPr}
          onChange={(e) => setNoPr(e.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        PR を出さない(ローカル検証用。pass しても promote せず loop/&lt;id&gt; ブランチに留める)
      </label>

      <div className="space-y-1.5">
        <Label htmlFor="goal">
          goal{" "}
          <span className="font-normal text-muted-foreground">
            (達成したいこと。複数行可)
          </span>
        </Label>
        <Textarea
          id="goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={4}
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label>
          accept{" "}
          <span className="font-normal text-muted-foreground">
            (受け入れ基準。項目ごと。数値で二値判定できるように)
          </span>
        </Label>
        <RowListEditor
          rows={accept}
          onChange={setAccept}
          placeholder="受け入れ基準を1つ"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="verify">
          verify{" "}
          <span className="font-normal text-muted-foreground">
            (決定論の検証コマンド。exit 0 = test pass。空なら Verifier 判定に委ねる)
          </span>
        </Label>
        <Textarea
          id="verify"
          value={verify}
          onChange={(e) => setVerify(e.target.value)}
          rows={3}
          spellCheck={false}
          className="font-mono"
        />
      </div>

      <div className="space-y-1.5">
        <Label>
          constraints{" "}
          <span className="font-normal text-muted-foreground">
            (禁止領域・制約。項目ごと。任意)
          </span>
        </Label>
        <RowListEditor
          rows={constraints}
          onChange={setConstraints}
          placeholder="制約を1つ"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="allowed_tools">
            allowed_tools{" "}
            <span className="font-normal text-muted-foreground">(カンマ区切り)</span>
          </Label>
          <Input
            id="allowed_tools"
            value={allowedTools}
            onChange={(e) => setAllowedTools(e.target.value)}
            placeholder="Read, Edit, Write, Bash"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="max_attempts">
            max_attempts{" "}
            <span className="font-normal text-muted-foreground">(任意。非冪等は 1)</span>
          </Label>
          <Input
            id="max_attempts"
            type="number"
            min={1}
            value={maxAttempts}
            onChange={(e) => setMaxAttempts(e.target.value)}
            placeholder="既定"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="status">status</Label>
          <select
            id="status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {statusOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="body">
          メモ{" "}
          <span className="font-normal text-muted-foreground">
            (自由記述。front-matter の後に置かれる。任意)
          </span>
        </Label>
        <Textarea
          id="body"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
        />
      </div>

      <div>
        <Button type="submit" disabled={saving}>
          {saving ? "保存中…" : isNew ? "作成" : "保存"}
        </Button>
      </div>
    </form>
  );
}
