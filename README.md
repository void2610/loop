# loop — Loop Engineering 計測配管

ローカル macOS で **Claude Code を headless で回す「ループ」の計測・統制層**だけを自作したもの。
実行系(`claude -p` / `git worktree`)はネイティブに委ね、突き合わせ層(run 記録・証拠・検証ゲート・
3役 Sub-agents・SQLite/DuckDB・Web UI)を実装する。

> 詳細は [docs/](./docs/) を参照:
> [concepts](./docs/concepts.md) ・ [usage](./docs/usage.md) ・ [runs](./docs/runs.md) ・ [configuration](./docs/configuration.md)

## 中心思想 — 仕事を2種類に分ける

- **種類A = メカニクス**(dispatch / 実行 / 証拠収集 / コミット / インデックス / 表示)→ **全自動**。
- **種類B = 判断**(生の run を読み、信用できるか・どこで壊れるか・次に自動検証へ入れるべきチェックを言語化)→ **絶対に自動化しない**。これがメタループの本体で、持ち越し可能なスキル。

唯一の硬い制約: **GUI は判断を生成・要約・推奨・自動入力しない**(事実要約と証拠表示まで)。

## 単一の真実は file-based contract

`data/tasks/*.md`(目標契約)＋ `runs/*.md`(run 記録、front-matter 含む)＋ per-run 証拠 ＋
`review-notes.md` ＋ git。`loop.db`(SQLite)は MD から導出される**使い捨てインデックス**で、
`just reindex` で完全再生成できる。DuckDB は分析レンズ、Web GUI は契約ファイルを**編集する面**(独自ストアなし)。

## 公開エンジン / 非公開データの分離

このリポジトリ(engine)は**コードだけ**の公開 repo。契約データ(目標契約・run 記録・証拠・判断・設計ドキュメント)は
**`data/` 配下の別 git repo**(private / ローカル)に置き、engine 側は `data/` を `.gitignore` する。
runner / Web GUI は `loop.toml` の `data.dir` 経由で `data/` を読み書きし、auto-commit も `data/` 側へ行う。

```sh
just init-data        # clone 直後: data/ を private git repo として初期化
```

## クイックスタート

前提: `claude`(Claude Code CLI)/ `uv` / `git`。`just` は任意(無ければ `uv run ...` を直接実行)。

```sh
just init-data                  # data/ 初期化(初回のみ)
just web                        # Web UI → http://127.0.0.1:8765
# あるいは CLI:
uv run runner.py run            # 次の todo タスクを1件実行
uv run runner.py status         # run 一覧
```

Web UI で「TODO → ＋新規」からやりたいことを日本語で書くと、Claude Code が**検証可能な目標契約**に変換する。
作成後トグルで自動実行も可能。

## 1 run の流れ(種類A / runner.py)

`data/tasks/*.md` から次の `todo` を選択 → **対象 repo 解決** → `git worktree` 隔離 →
**3役 Sub-agents(Explorer → Implementer → 決定論テスト → Verifier)** → verdict 合成 →
自動チェックポイントコミット → `runs/<id>.md` 生成(判断は空 / `reviewed:false`)→ SQLite upsert → 後始末。

- **3役**: Explorer(高速/read-only 調査)→ Implementer(主力/read-write 実装)→ 決定論テスト(`verify`)→
  Verifier(**別モデル必須**/read-only/構造化出力で独立判定。test gaming を疑う)。
- **verdict 合成**: test=fail→fail / verifier=fail→fail(テスト緑でも gaming 捕捉)/ verifier=handoff→handoff / 他→pass。
- **リトライ**(人間送り=handoff を減らす): Verifier の handoff は read-only のまま再判定(冪等)。実装が
  timeout/error で確定しなかったときだけ run 全体を再試行(冪等タスク前提。非冪等は `max_attempts:1`)。
- **停止条件3段**: `--max-turns` / `--max-budget-usd` / wall-clock タイムアウト。
- **read-only 強制**: Explorer/Verifier/生成は `--disallowedTools` で変更系ツールを禁止(global settings を上書き)。

詳細は [docs/runs.md](./docs/runs.md)。

## 複数リポジトリ

タスクの `repo` で対象を指定: `loop.toml [repos]` の登録名 / 絶対パス / 未指定=デフォルト /
`none`=外部FS作業(git worktree なしの一時ディレクトリ実行)。worktree は対象 repo に依らず
**loop repo 内 `.loop-worktrees/`(gitignore)に固定配置**。

## Web UI

| ページ | 内容 |
|---|---|
| `/` | run 一覧(repo バッジ / verdict / フィルタ / dispatch) |
| `/run/<id>` | run detail(front-matter・事実要約・diff・証拠・**判断フォーム**) |
| `/run/<id>/transcript` | transcript を会話ビューで表示 |
| `/todo` | タスク一覧(repo バッジ / status / 最新 run / 実行・削除) |
| `/todo/new` | **プロンプトからタスク生成**(repo 選択必須 + 自動実行トグル) |
| `/todo/<id>` | タスク編集(項目別フォーム / ＋−行) |
| `/monitor` | **監視ダッシュボード**(実行中フェーズ・件数・直近 run、自動更新) |
| `/monitor/live/<id>` | **実行中のライブ transcript**(役割ごと、near-real-time) |

判断・review-notes・タスクの書き込み先は常に契約ファイル。詳細は [docs/usage.md](./docs/usage.md)。

## 構成

```
engine(公開 repo):
  loop.toml           設定([loop]/[agents]/[repo]/[repos]/[data])
  runner.py           一本道ランナー: 3役 / retry / 生成 / status(種類A)
  loopdb.py           SQLite インデックス層(MD 派生・再生成可能)
  webapp/             FastAPI + HTMX(TODO 管理 / 判断 / 監視 / ライブ)
  tui.py              Textual TUI(読み取り専用 + nvim 着地)
  stats.py + queries/ DuckDB 分析
  launchd/*.example   WatchPaths トリガー(data/tasks 変更で起動)
  .claude/skills/     SKILL.md / task-author(タスク生成スキル)

data/(別の private git repo / engine からは .gitignore):
  tasks/<id>.md       目標契約(1 タスク=1 ファイル / YAML front-matter)
  review-notes.md     種類B の R&D ログ
  runs/<id>.md        ★契約: run レコード(真実の源)
  runs/<id>/          ★契約: 証拠(result.json / *.stream.jsonl / test-output / change.patch / transcript)
  plans/              設計ドキュメント
  loop.db             ★派生: SQLite(.gitignore、再生成可能)
```

## コマンド(`just` / 直接 `uv run`)

| | コマンド |
|---|---|
| 次の todo を実行 | `just run` / `uv run runner.py run [task_id]` |
| プロンプト生成 | `uv run runner.py gen "<依頼>" [--repo <r>] [--run]` |
| レビュー(nvim 着地) | `just review` / `uv run runner.py review` |
| Web UI | `just web` |
| TUI | `just tui` |
| 再インデックス | `just reindex` |
| DuckDB 分析 | `just stats` / `just stats-sql "SELECT …"` |
| 一覧 | `just status` |
| WatchPaths 導入/解除 | `just watch-install` / `just watch-uninstall` |

## やらないこと

timer ベースの無人 cadence / durable execution / **種類B の自動生成(判断・学びの自動記入や推奨)** /
外部連携(Linear・GitHub API・Slack)は作らない。
