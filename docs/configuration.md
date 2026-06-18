# Configuration — 設定とスキーマ

## `loop.toml`

```toml
[loop]
model = "claude-sonnet-4-6"          # 既定モデル(タスク/役割で上書き可)
max_turns = 40                       # turn 上限(暴走ループの一次ガード)
max_budget_usd = 2.0                 # コスト上限(各 claude 呼び出しに効く)
timeout_seconds = 1800               # wall-clock タイムアウト
verifier_attempts = 3                # Verifier が handoff のとき read-only 再判定する回数
implementer_revise_rounds = 2        # Verifier が revise のとき同一セッションへ差し戻す往復上限
intervention_timeout_seconds = 1800  # handoff/上限超過で awaiting にし Web の続行指示を待つ秒数(超過で handoff)
max_attempts = 2                     # 実装が timeout/error のとき run 全体を再試行する上限
default_allowed_tools = ["Read","Edit","Write","Grep","Glob","Bash"]  # タスク未指定時のフォールバック
permission_mode = "default"
max_concurrency = 1                  # 同時 run 本数(1=従来の直列)

# promote(run=pass を PR 化し CI+Copilot が green まで自動修正)。既定 false。merge は人間。
promote_on_pass = false
promote_rounds = 3                   # CI/Copilot 差し戻しの往復上限(超過は handoff)
ci_timeout_seconds = 1800            # CI 完了待ちタイムアウト
copilot_timeout_seconds = 600        # Copilot レビュー投稿待ちタイムアウト

repo_history_runs = 8                # 同一 repo の過去 run の事実を各役へ渡す件数(0=無効。人間の判断は渡さない)

[agents]                             # Sub-agents + 生成。Verifier は implementer と別モデル必須
implementer_model = "claude-sonnet-4-6"   # 主力。差し戻し時は --resume で継続
verifier_model    = "claude-opus-4-8"     # 別モデル必須
author_model      = "claude-sonnet-4-6"   # プロンプト→目標契約 + 実装プラン + 規範候補の起草(旧 Explorer を統合)
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
repo: <登録名 / 絶対パス / 省略=デフォルト(常に git repo)>
goal: |
  達成したいこと(複数行可)
accept:                  # 受け入れ基準(人間可読。定量的に)
  - ...
verify: <決定論コマンド。worktree で実行し exit 0 = test pass。空なら Verifier 判定に委ねる>
constraints:             # 禁止領域・制約(任意)
  - ...
allowed_tools: Read,Edit,Write,Bash   # headless に事前認可(カンマ区切り or リスト)
max_attempts: 1          # (任意) run 全体の再試行上限。非冪等タスク(外部FS書き換え等)は 1
status: todo             # todo | pass | fail | handoff | timeout | stopped | awaiting-merge(runner が更新)
---

(自由メモ)
```

プロンプト生成タスクは Author が repo を read-only 調査して詳細な実装プランを書き、**body 外のサイドカー
`data/tasks/plans/<id>.md`** に保存する(契約を肥らせない / Web 編集と独立)。run 時はこのプランを Implementer へ渡す。

ルール: **数値・コマンドで二値判定できる受け入れ基準を必須に**。落ちないタスクはループに載せない。
Web GUI(`/tasks`)から一覧・項目別フォーム編集・新規作成・プロンプト生成・実行・アーカイブができる(削除はしない)。

### repo の指定

| 値 | 挙動 |
|---|---|
| 省略 / 空 | `[repo].path`(デフォルト。未設定なら `"."` = loop 自身) |
| `[repos]` の登録名 | そのパス |
| 絶対 / 相対パス | そのまま(`~` 展開) |

対象は**常に git repo 前提**(旧 `none`/no-repo モードは撤去)。worktree は対象 repo に依らず
**loop repo 内 `.loop-worktrees/<run_id>`(gitignore)** に固定配置。

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
- `just` は任意。判断(種類B)の入力は Web の判断フォーム(`/runs/<id>`)で行う(nvim 連携は廃止)。
- **global `~/.claude/settings.json` が `Bash(*)`/`Write`/`auto` を許可していても**、read-only 役と生成は
  `--disallowedTools` で変更系ツールを禁止して read-only を強制する。

## WatchPaths(launchd, opt-in)

`just watch-install` が `launchd/com.loop.watch.plist.example` のパスを実環境に置換して生成・配置。
`data/tasks/` の変更で `runner.py run` を1回起動(timer ベースの無人 cadence ではない)。
`just watch-uninstall` で解除。
