# Configuration — 設定とスキーマ

## `loop.toml`

```toml
[loop]
model = "claude-sonnet-4-6"          # 既定モデル(タスク/役割で上書き可)
max_turns = 40                       # turn 上限(暴走ループの一次ガード)
max_budget_usd = 2.0                 # コスト上限(各 claude 呼び出しに効く)
timeout_seconds = 1800               # wall-clock タイムアウト
verifier_attempts = 3                # Verifier が handoff のとき read-only 再判定する回数
max_attempts = 2                     # 実装が timeout/error のとき run 全体を再試行する上限
default_allowed_tools = ["Read","Edit","Write","Grep","Glob","Bash"]  # タスク未指定時のフォールバック
permission_mode = "default"

[agents]                             # Sub-agents 3役 + 生成。Verifier は implementer と別モデル必須
explorer_model    = "claude-haiku-4-5-20251001"
implementer_model = "claude-sonnet-4-6"
verifier_model    = "claude-opus-4-8"
author_model      = "claude-sonnet-4-6"   # プロンプト→目標契約の生成
explorer_tools    = ["Read","Grep","Glob"]
implementer_tools = ["Read","Edit","Write","Bash","Grep","Glob"]
verifier_tools    = ["Read","Grep","Glob"]

[data]
dir = "data"                         # 契約データの置き場(別 private git repo)
```

> **リポジトリ構成([repo] デフォルト対象 / [repos] レジストリ)は loop.toml に書かない。**
> マシン固有なので gitignore された `loop.local.toml` に置き、`load_config` がマージする
> (`loop.local.toml.example` 参照)。未指定時の対象 repo は `"."`(loop 自身)にフォールバック。

```toml
# loop.local.toml(gitignore)
[repos]
myproject = "/Users/me/Documents/GitHub/myproject"
[repo]                               # 任意。既定対象。未設定なら "."
path = "myproject"
```

> 起動時に `verifier_model == implementer_model` だと警告(記事の Sub-agents の意図が無効化されるため)。

## タスク(目標契約)`data/tasks/<id>.md`

1 タスク = 1 ファイル。YAML front-matter + 自由メモ本文。runner は `data/tasks/` をファイル名昇順で走査し、
最初の `status: todo` を実行する(名前で優先度制御。`_`/`.` 始まりはスキップ)。

```markdown
---
id: <一意。省略時はファイル名 stem>
repo: <登録名 / 絶対パス / none / 省略=デフォルト>
goal: |
  達成したいこと(複数行可)
accept:                  # 受け入れ基準(人間可読。定量的に)
  - ...
verify: <決定論コマンド。worktree で実行し exit 0 = test pass。空なら Verifier 判定に委ねる>
constraints:             # 禁止領域・制約(任意)
  - ...
allowed_tools: Read,Edit,Write,Bash   # headless に事前認可(カンマ区切り or リスト)
max_attempts: 1          # (任意) run 全体の再試行上限。非冪等タスク(外部FS書き換え等)は 1
status: todo             # todo | pass | fail | timeout | handoff(runner が更新)
---

(自由メモ)
```

ルール: **数値・コマンドで二値判定できる受け入れ基準を必須に**。落ちないタスクはループに載せない。
Web GUI(`/todo`)から一覧・項目別フォーム編集・新規作成・プロンプト生成・実行・削除ができる。

### repo の指定

| 値 | 挙動 |
|---|---|
| 省略 / 空 | `[repo].path`(デフォルト) |
| `[repos]` の登録名 | そのパス |
| 絶対 / 相対パス | そのまま(`~` 展開) |
| `none` | git worktree を作らず一時ディレクトリで実行(外部FS作業向け) |

worktree は対象 repo に依らず **loop repo 内 `.loop-worktrees/<run_id>`(gitignore)** に固定配置。

## SQLite インデックス(`loop.db`)

front-matter をそのまま列にした派生ビュー。authoritative ではない。`just reindex` で `runs/*.md` から
完全再生成できる。列: `run_id, task, verdict, reviewed, model, cost_usd, turns, duration_ms, session_id,
repo_sha, skill_sha, goal_contract_sha, started_at, md_path, test_verdict, verifier_verdict,
verifier_confidence, repo`。

## DuckDB 分析(`stats.py` + `queries/*.sql`)

`loop.db` を attach し `queries/*.sql` を実行(`runs` ビューとして参照)。

- `pass_rate_by_skill.sql` — skill 版ごとの pass 率と平均コスト
- `verdict_summary.sql` — verdict ごとの件数・未レビュー・平均コスト/ターン
- `gaming_suspects.sql` — **テスト緑 × Verifier fail**(gaming / 部分未達の疑い。最重要の R&D シグナル)

`just stats`(canned 全実行)/ `just stats-sql "SELECT …"`(ad-hoc)。

## 環境変数 / 前提

- `claude`(Claude Code CLI、headless `-p`)、`uv`(PEP 723 inline deps を自動解決)、`git`。
- `just` は任意。`EDITOR`(既定 nvim)= `just review` の着地先。
- **global `~/.claude/settings.json` が `Bash(*)`/`Write`/`auto` を許可していても**、read-only 役と生成は
  `--disallowedTools` で変更系ツールを禁止して read-only を強制する。

## WatchPaths(launchd, opt-in)

`just watch-install` が `launchd/com.loop.watch.plist.example` のパスを実環境に置換して生成・配置。
`data/tasks/` の変更で `runner.py run` を1回起動(timer ベースの無人 cadence ではない)。
`just watch-uninstall` で解除。
