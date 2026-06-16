# Usage — セットアップと操作

## セットアップ

```sh
# 前提: claude(Claude Code CLI) / uv / git。just は任意。
git clone <engine repo>
cd loop
just init-data                 # data/ を private git repo として初期化(初回のみ)
# 必要なら別プロジェクトを登録: loop.toml の [repos] に name = "/path" を追記
# データを private remote に置くなら: git -C data remote add origin <private-url>
```

`just` が無ければ各コマンドの `uv run ...` を直接実行(下表)。

## CLI コマンド

| やること | just | 直接 |
|---|---|---|
| 次の todo を1件実行 | `just run` | `uv run runner.py run [task_id]` |
| プロンプトからタスク生成 | — | `uv run runner.py gen "<依頼>" [--repo <r>] [--run]` |
| 次の未レビュー run を nvim で開く | `just review` | `uv run runner.py review` |
| run 一覧 | `just status` | `uv run runner.py status` |
| SQLite を MD から再生成 | `just reindex` | `rm -f data/loop.db && uv run runner.py reindex` |
| DuckDB 分析 | `just stats` / `just stats-sql "SQL"` | `uv run stats.py ["SQL"]` |
| Web UI | `just web` | `uv run webapp/main.py` |
| TUI | `just tui` | `uv run tui.py` |
| WatchPaths 導入/解除 | `just watch-install` / `just watch-uninstall` | — |

`runner.py run <task_id>` で特定タスクを指定実行できる(Web の「実行」ボタンが使う)。同時実行は
`data/.run.lock` で排他(進行中は他の run を弾く)。

## Web UI ツアー(http://127.0.0.1:8765)

ナビ: **loop(run 一覧) · TODO · 監視**。

### run 一覧 `/`
repo バッジ + run_id + verdict + reviewed + cost + 開始時刻。verdict / reviewed / task でフィルタ。
「次の todo を実行」で dispatch。

### run detail `/run/<id>`
- 左: front-matter、**事実要約**(runner 生成)、**Verifier の判定**(証拠)、diff(色付き)、検証出力、
  transcript リンク。
- 右: **判断フォーム**(信用できるか / 失敗・リスク / 自動検証に入れるべきチェック / 学び)。常に空で出る
  (GUI は判断を生成・提案しない)。submit すると契約ファイルへ書き戻し → reviewed 化 → コミット → 再導出。
- `/run/<id>/transcript` で会話ビュー(プロンプト/思考/ツール/結果の吹き出し)。

### TODO `/todo`
タスク一覧(repo バッジ / id / status / goal / 最新 run / 実行・削除)。実行中は `.run.lock` を検知して
インジケータ表示・実行ボタン無効。

- **`/todo/new`(プロンプト生成、既定)**: やりたいことを日本語で書く → **repo を選択(必須)** →
  「Claude Code に作らせる」。専用 skill(task-author)+ 構造化出力で**検証可能な目標契約**に変換。
  生成は background(数十秒)で走り、完了後に一覧へ現れる。**自動実行トグル** ON ならそのまま実行。
- **`/todo/<id>`(編集)**: 項目別フォーム(repo / goal / accept・constraints は ＋− 行 / verify /
  allowed_tools / max_attempts / status / メモ)。保存で `data/tasks/<id>.md` へ書き戻し + コミット。
  「▶ このタスクを実行」で background 実行。
- `/todo/new/manual`: 手動フォーム(プロンプトを使わない)。

### 監視 `/monitor`(読み取り専用)
- **実行中の run**: repo バッジ・task・**フェーズ進行**(Explorer → Implementer → 検証)・経過秒。
- 保留 todo / 未レビュー run の件数、直近 12 run。
- 3 秒自動更新。実行が無ければ「アイドル」。
- **`▶ ライブ transcript を見る`** → `/monitor/live/<id>`: 役割ごとのイベントを会話ビューで near-real-time
  表示(実行中は 2 秒更新、完了で停止)。

## 典型ワークフロー

1. **タスクを作る**: `/todo/new` で依頼を書き repo を選ぶ → 生成。または `/todo/<id>` / 手動フォームで直接書く。
2. **実行する**: 一覧/編集の「実行」、`just run`(次の todo)、または WatchPaths(`data/tasks/` 変更)。
3. **監視する**: `/monitor` でフェーズ、`/monitor/live/<id>` でライブ transcript。
4. **レビューする(種類B)**: `/run/<id>` の判断フォーム or `just review`。信用できるか・失敗の形・
   次に自動検証へ入れるべきチェックを書く → `review-notes.md` に蓄積。
5. **分析する**: `just stats`(特に `gaming_suspects` = テスト緑 × Verifier fail)で skill 版ごとの傾向を見る。

## トラブルシュート

- **`just` 未導入**: `uv run ...` を直接実行。
- **run が始まらない / 「別の run が進行中」**: `data/.run.lock` が残留していないか確認(異常終了時は手動削除)。
- **SQLite がおかしい**: `just reindex`(MD から完全再生成。データは MD が真実なので失われない)。
- **生成が失敗する**: 文言を変えて再試行、または手動フォーム(`/todo/new/manual`)で書く。
- **非冪等タスクの再試行で壊れる**: タスクに `max_attempts: 1` を指定。
