# Usage — セットアップと操作

## セットアップ

```sh
# 前提: claude(Claude Code CLI) / uv / git。just は任意。
git clone <engine repo>
cd loop
just init-data                 # data/ を private git repo として初期化(初回のみ)
# 別プロジェクトを登録: loop.local.toml(gitignore)の [repos] に name = "/path" を追記
# データを private remote に置くなら: git -C data remote add origin <private-url>
```

`just` が無ければ各コマンドの `uv run ...` を直接実行(下表)。

## CLI コマンド

| やること | just | 直接 |
|---|---|---|
| 次の todo を1件実行 | `just run` | `uv run runner.py run [task_id]` |
| プロンプトからタスク生成 | — | `uv run runner.py gen "<依頼>" [--repo <r>] [--run]` |
| 次の未レビュー run を nvim で開く | `just review` | `uv run runner.py review` |
| 規範候補の一覧/昇格/却下(種類B) | — | `uv run runner.py norms [list\|promote <id>\|reject <id>\|draft <run_id>]` |
| run 一覧 | `just status` | `uv run runner.py status` |
| SQLite を MD から再生成 | `just reindex` | `rm -f data/loop.db && uv run runner.py reindex` |
| DuckDB 分析 | `just stats` / `just stats-sql "SQL"` | `uv run stats.py ["SQL"]` |
| Web(フロント+バック同時起動) | `just app` | フロント build 後 backend:8765 + frontend:3000 |
| backend のみ(/api + SSE) | `just web` | `uv run webapp/main.py` |
| TUI | `just tui` | `uv run tui.py` |
| WatchPaths 導入/解除 | `just watch-install` / `just watch-uninstall` | — |

`runner.py run <task_id>` で特定タスクを指定実行できる(Web の「実行」ボタンが使う)。同時実行は
`data/.run.lock` で排他(進行中は他の run を弾く)。

## Web UI ツアー(Next.js: http://localhost:3000)

UI は **Next(`web/`)に一本化**(旧 Jinja は撤去)。FastAPI は `/api`(JSON+SSE)を出し、Next が rewrite で
`:8765` へプロキシ。ナビ: **Runs · Tasks · Dashboard**。

### Runs `/runs`
repo バッジ + run_id + verdict + reviewed + cost + 開始時刻。verdict / reviewed / task でフィルタ。
**実行中の run** は上部カード + テーブル最上部に「実行中 · <フェーズ>」行として出る(クリックでライブ)。
「次の todo を実行」で dispatch。アーカイブはアイコンのみ(削除はしない)。

### run detail `/runs/<id>`
- 左: front-matter(PR があれば `pr_url`)、**事実要約**(runner 生成)、**Verifier の判定**(証拠)、
  diff(色付き)、検証出力、transcript リンク。
- 右: **判断フォーム**(信用できるか / 失敗・リスク / 自動検証に入れるべきチェック / 学び)。常に空で出る
  (GUI は判断を生成・提案しない)。submit で契約ファイルへ書き戻し → reviewed 化 → コミット → 再導出。
- `/runs/<id>/live`: 役割ごとのイベントを会話ビューで near-real-time 表示(実行中)。
- `/runs/<id>/transcript`: 会話ビュー(プロンプト/思考/ツール/結果)。

### Tasks `/tasks`
タスク一覧(repo バッジ / id / status / goal / 最新 run / 実行・アーカイブ)。実行中は `.run.lock` を検知して
インジケータ表示・実行ボタン無効。生成中は `.gen.lock` を検知して表示。

- **`/tasks/new`(プロンプト生成、既定)**: やりたいことを日本語で書く → **repo を選択(必須)** →
  「Claude Code に作らせる」。専用 skill(task-author)+ 構造化出力で**検証可能な目標契約**に変換し、
  repo を read-only 調査して実装プランを `tasks/plans/<id>.md` に生成。background(数十秒)、完了後に一覧へ。
  **自動実行トグル** ON ならそのまま実行。
- **`/tasks/<id>`(編集)**: 項目別フォーム(repo / goal / accept・constraints は ＋− 行 / verify /
  allowed_tools / max_attempts / status / メモ)。保存で `data/tasks/<id>.md` へ書き戻し + コミット。
- `/tasks/new/manual`: 手動フォーム(プロンプトを使わない)。

### Dashboard `/dashboard`(読み取り専用)
集計の事実提示: 未レビュー件数・pass/fail 等の指標とチャート(DuckDB 由来)。

## 典型ワークフロー

1. **タスクを作る**: `/tasks/new` で依頼を書き repo を選ぶ → 生成。または `/tasks/<id>` / 手動フォームで直接書く。
2. **実行する**: 一覧/編集の「実行」、`just run`(次の todo)、または WatchPaths(`data/tasks/` 変更)。
3. **監視する**: `/runs` の実行中行 → `/runs/<id>/live` でライブ transcript。
4. **(任意)promote**: `promote_on_pass=true` なら pass の成果が自動で PR 化され、CI+Copilot が green まで回る(merge は人間)。
5. **レビューする(種類B)**: `/runs/<id>` の判断フォーム or `just review`。信用できるか・失敗の形・
   次に自動検証へ入れるべきチェックを書く → `review-notes.md` に蓄積。レビューで verdict を覆すときは run MD の
   front-matter に `human_verdict: <verdict>` を書く(reviewed 化時に規範候補が自動起草される。手動は `runner.py norms draft <run_id>`)。
6. **規範を育てる(種類B)**: 摩擦 run から起草された規範候補を `runner.py norms` で裁定し、`conventions.md` へ昇格(文言確定は人間)。
   昇格した規範は以降の run に注入される(優先順位 `CLAUDE.md > conventions.md > 過去 run の事実`)。
7. **分析する**: `just stats`(特に `gaming_suspects` = テスト緑 × Verifier fail)で skill 版ごとの傾向を見る。

## トラブルシュート

- **`just` 未導入**: `uv run ...` を直接実行。
- **run が始まらない / 「別の run が進行中」**: `data/.run.lock` が残留していないか確認(異常終了時は手動削除)。
- **SQLite がおかしい**: `just reindex`(MD から完全再生成。データは MD が真実なので失われない)。
- **生成が失敗する**: 文言を変えて再試行、または手動フォーム(`/tasks/new/manual`)で書く。
- **`just app` 再起動でポート衝突**: `lsof -ti tcp:3000 tcp:8765 | xargs kill -9` で解放してから起動。
- **非冪等タスクの再試行で壊れる**: タスクに `max_attempts: 1` を指定。
