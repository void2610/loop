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

### 2 台目以降の Mac を Fleet に加える

1 つの Web GUI から複数 PC を扱う Fleet(`configuration.md` 参照)を立てる手順。各 PC で 1 回ずつ:

```sh
# 1) data repo を clone(remote は最初の PC で設定したものを使う)
git clone <private data repo URL> ~/loop-data
# 2) engine を clone してそこへ symlink で data を差す
git clone <engine URL> ~/loop && cd ~/loop && ln -s ~/loop-data data
# 3) この PC 用ディレクトリを切る(衝突回避)
mkdir -p data/hosts/<this-host>
# 4) loop.local.toml を作る(gitignore)
cp loop.local.toml.example loop.local.toml
#    [data] dir = "data/hosts/<this-host>" / [fleet] self と peers を全 PC 分書く
# 5) Tailscale 認証済みで起動(各 PC で実行)
just app
```

**Fleet を成立させる条件**:

- すべての PC が同じ Tailnet にログイン済み(`tailscale status` で互いに見える)。
- すべての PC の `loop.local.toml [fleet].peers` に **同じ peer リスト** を書く(各 PC 自身も含む)。
- すべての PC で `just app` が立ち上がっており、`:3000` と `:8765` が tailscale serve に出ている(`just app` が両方とも自動で出す)。

これで任意の PC の Web GUI(`http://<host>.<tailnet>.ts.net:3000`)を開けば、Runs / Tasks / Dashboard が
全 host を merge view で出し、各 row の host バッジから該当 PC のライブ・介入・dispatch・判断レビューに辿れる。

## CLI コマンド

| やること | just | 直接 |
|---|---|---|
| 次の todo を1件実行 | `just run` | `uv run runner.py run [task_id]` |
| プロンプトからタスク生成 | — | `uv run runner.py gen "<依頼>" [--repo <r>] [--run] [--base-branch <b>] [--no-pr]` |
| 規範候補の一覧/昇格/却下(種類B) | — | `uv run runner.py norms [list\|promote <id>\|reject <id>\|draft <run_id>]` |
| PR マージ待ち run の確認(マージ済み→pass 昇格) | — | `uv run runner.py merges` |
| run 一覧 | `just status` | `uv run runner.py status` |
| SQLite を MD から再生成 | `just reindex` | `rm -f data/loop.db && uv run runner.py reindex` |
| DuckDB 分析 | `just stats` / `just stats-sql "SQL"` | `uv run stats.py ["SQL"]` |
| Web(フロント+バック+ Tailnet 前段)| `just app` | 唯一の公式起動口。127.0.0.1:3000 / Tailnet どちらからでも届く |
| backend のみ(/api + SSE) | `just web` | `uv run webapp/main.py` |
| WatchPaths 導入/解除 | `just watch-install` / `just watch-uninstall` | — |

`runner.py run <task_id>` で特定タスクを指定実行できる(Web の「実行」ボタンが使う)。同時実行は
`data/.run.lock` で排他(進行中は他の run を弾く)。

## Web UI ツアー(Next.js: http://localhost:3000)

UI は **Next(`web/`)に一本化**(旧 Jinja は撤去)。FastAPI は `/api`(JSON+SSE)を出し、Next が rewrite で
`:8765` へプロキシ。ナビ: **Runs · Tasks · Knowledge · Dashboard**。

### Runs `/runs`
repo バッジ + run_id + verdict + reviewed + cost + 開始時刻。verdict / reviewed / task でフィルタ。
**実行中の run** は上部カード + テーブル最上部に「実行中 · <フェーズ>」行として出る(クリックでライブ)。
**人間の介入待ち(awaiting)**は最上部にオレンジ枠で、**PR マージ待ち(awaiting-merge)**は緑枠で PR 状態 + 「PR を開く」付きで出る
(人間が PR をマージすると run が `pass` に昇格し消える)。
「次の todo を実行」で dispatch。アーカイブはアイコンのみ(削除はしない)。

**Fleet(複数 PC)**: `loop.local.toml [fleet]` を設定すると、`host` 列が追加され全 peer の完了 run + 実行中 run を
merge view で表示する。到達できなかった peer は一覧上部に「offline」として残る(全体は落ちない)。

- **実行中 run**: 各 peer の monitor SSE を並列購読し host バッジ付きで上部カードに出る。クリックで該当 host の
  `/runs/<id>/live?host=<host>` に遷移し、その peer の backend に直接 SSE 接続(`:8765` 経由)。
- **介入(続行指示)/ 停止**: `/runs/<id>/live?host=<host>` の InterventionPanel / StopRunButton が `host` 経由で
  `/api/peer/<host>/runs/<id>/message`・`/stop` を peer プロキシで叩く。
- **dispatch**: 一覧右上に host セレクタ(`peers >= 2` のとき表示)。選んだ host で `/api/peer/<host>/dispatch` を
  叩いて「その PC の次の todo」を起動する。

### run detail `/runs/<id>`
- 左: front-matter(PR があれば `pr_url`)、**事実要約**(runner 生成)、**Verifier の判定**(証拠)、
  diff(色付き)、検証出力、transcript リンク。
- 右: **判断フォーム**(信用できるか / 失敗・リスク / 自動検証に入れるべきチェック / 学び)。常に空で出る
  (GUI は判断を生成・提案しない)。submit で契約ファイルへ書き戻し → reviewed 化 → コミット → 再導出。
- `/runs/<id>/live`: 役割ごとのイベントを会話ビューで near-real-time 表示(実行中)。run が `awaiting`
  (実装中の `NEEDS_HUMAN`、または handoff/revise 上限)のときは、詰まった理由と**続行指示の入力欄**が出る →
  送信すると同一セッションへ注入されて続行する。右上の**「この run を停止」**でいつでも停止できる(`stopped` で正常終了)。
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

### Knowledge `/knowledge`(規範記憶)
規範記憶を 1 面で提示: **現在の知識**(`conventions.md` = run に注入される承認済み規範)/ **起草された候補**
(`candidates.md` = 承認待ち)/ **起草エージェントの動作履歴**(どの run で何をトリガーに起草し、抽出・空振り・
失敗のいずれだったか。`runs/<id>/norms.json` 由来)。候補の昇格/却下は人間が押す中継(`CandidateActions`)で、
**GUI はどれを承認すべきかの示唆・序列付けをしない**(種類B は人間)。データ源は `data/` の MD で read-only。

### Dashboard `/dashboard`(読み取り専用)
集計の事実提示: 未レビュー件数・pass/fail 等の指標とチャート(DuckDB 由来)。

## 典型ワークフロー

1. **タスクを作る**: `/tasks/new` で依頼を書き repo を選ぶ → 生成。または `/tasks/<id>` / 手動フォームで直接書く。
2. **実行する**: 一覧/編集の「実行」、`just run`(次の todo)、または WatchPaths(`data/tasks/` 変更)。
3. **監視する**: `/runs` の実行中行 → `/runs/<id>/live` でライブ transcript。
4. **promote**: pass の成果は自動で PR 化され、CI+Copilot が green まで回る(merge は人間)。個別タスクで PR を出したくないときは task に `no_pr: true` を付ける。
5. **レビューする(種類B)**: `/runs/<id>` の判断フォーム(Web)。信用できるか・失敗の形・
   次に自動検証へ入れるべきチェックを書く → `review-notes.md` に蓄積。runner の verdict を覆すときは
   フォームの「verdict を覆す」select(or run MD front-matter の `human_verdict: <verdict>`)で選ぶ
   → 保存時に front-matter へ刻まれ、覆しなら規範候補が自動起草される(手動は `runner.py norms draft <run_id>`)。
6. **規範を育てる(種類B)**: 摩擦 run から起草された規範候補を `runner.py norms` で裁定し、`conventions.md` へ昇格(文言確定は人間)。
   昇格した規範は以降の run に注入される(優先順位 `憲法(constitution.md) > conventions.md > 過去 run の事実`)。
7. **分析する**: `just stats`(特に `gaming_suspects` = テスト緑 × Verifier fail)で skill 版ごとの傾向を見る。

## トラブルシュート

- **`just` 未導入**: `uv run ...` を直接実行。
- **run が始まらない / 「別の run が進行中」**: `data/.run.lock` が残留していないか確認(異常終了時は手動削除)。
- **SQLite がおかしい**: `just reindex`(MD から完全再生成。データは MD が真実なので失われない)。
- **生成が失敗する**: 文言を変えて再試行、または手動フォーム(`/tasks/new/manual`)で書く。
- **ポート衝突で起動失敗**: `just app` は起動前に :3000/:8765 を kill するので通常気にしなくてよい。
- **非冪等タスクの再試行で壊れる**: タスクに `max_attempts: "1"` を quoted で指定(unquoted int は YAML が int でパースして TaskDetail API が 500 になる)。
