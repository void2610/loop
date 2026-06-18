# loop — Loop Engineering 計測配管

ローカル macOS で **Claude Code を headless で回す「ループ」の計測・統制層**だけを自作したもの。
実行系(`claude -p` / `git worktree`)はネイティブに委ね、突き合わせ層(run 記録・証拠・検証ゲート・
Sub-agents(Author/Implementer/Verifier)+ 差し戻し + PR promote・SQLite/DuckDB・Web UI)を実装する。

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
just app                        # 起動(http://127.0.0.1:3000 / Tailnet 内なら http://<host>.ts.net:3000)
# あるいは CLI:
uv run runner.py run            # 次の todo タスクを1件実行
uv run runner.py status         # run 一覧
```

Web UI で「Tasks → ＋新規」からやりたいことを日本語で書くと、Claude Code が**検証可能な目標契約 + 実装プラン**に変換する。
作成後トグルで自動実行も可能。

## 1 run の流れ(種類A / runner.py)

`data/tasks/*.md` から次の `todo` を選択 → **対象 repo 解決** → `git worktree` 隔離 →
**Author プラン → Implementer → 決定論ゲート → Verifier 監査 →(revise / 人間介入)** → verdict 合成 →
自動チェックポイントコミット →(pass かつ promote 有効なら **PR 提出→CI/Copilot green まで自動修正→マージ待ち**)→
`runs/<id>.md` 生成(判断は空 / `reviewed:false`)→ SQLite upsert → 後始末。

- **実行機構**: 各役は **`claude -p` を stream-json で双方向に開いた永続セッション(`RoleSession`)**。one-shot と
  `--resume` 再 spawn は廃止し、revise も人間介入も **同一セッションへ user メッセージを送る**一経路に統一。
- **役割**: Author(生成時に repo を read-only 調査し実装プランを書く=旧 Explorer 統合)→ Implementer
  (主力/read-write/自己テストまで)→ 決定論ゲート(`verify`)→ Verifier(**別モデル必須**/read-only/構造化出力で
  独立監査。test gaming を疑う。人間の介入回答も入力に取る)。
- **revise(実装後の欠陥)**: Verifier が `revise` を返すと `required_changes` を付けて同一セッションへ差し戻し
  →再ゲート→再監査(上限 `implementer_revise_rounds`)。**自動・人間不要**。
- **人間介入(実装中の判断/権限)**: Implementer が詰まると `NEEDS_HUMAN:` で止まる → `awaiting`。Web の Runs 一覧/
  ライブから続行指示を送ると同一セッションへ注入して続行。UI から **run の停止**も可能(→ `stopped`)。
- **verdict**: `pass`(promote 時はマージ済み)/ `fail` / `handoff`(人間判断要)/ `timeout` / `stopped`(人間が停止)/
  `awaiting-merge`(promote 後・PR マージ待ち)。合成: test=fail→fail / verifier=fail→fail / verifier=handoff→handoff / 他→pass。
- **promote(任意 `promote_on_pass`)**: pass の成果を PR 化し **GitHub CI + Copilot** が green まで自動修正 → **`awaiting-merge`**。
  **人間が PR をマージして初めて `pass`(真の完了)**。自動 merge はしない。
- **停止条件3段**: `--max-turns` / `--max-budget-usd` / wall-clock タイムアウト。
- **read-only 強制**: Verifier/生成は `--disallowedTools` で変更系ツールを禁止(global settings を上書き)。

詳細は [docs/runs.md](./docs/runs.md)。

## 複数リポジトリ

タスクの `repo` で対象を指定: **`loop.local.toml [repos]`(gitignore)** の登録名 / 絶対パス / 未指定=デフォルト。
対象は常に git repo 前提。worktree は対象 repo に依らず **loop repo 内 `.loop-worktrees/`(gitignore)に固定配置**。

## Web UI(Next.js / http://localhost:3000)

| ページ | 内容 |
|---|---|
| `/runs` | run 一覧。**人間の介入待ち(awaiting)**=オレンジ枠 /**PR マージ待ち(awaiting-merge)**=緑枠(PR 状態+PR リンク)/ 実行中 を上部に強調。verdict/フィルタ/dispatch |
| `/runs/<id>` | run detail(front-matter・事実要約・diff・証拠・**判断フォーム**・PR リンク) |
| `/runs/<id>/live` | ライブ transcript +**続行指示パネル(awaiting 時)**+**「この run を停止」** |
| `/runs/<id>/transcript` | transcript を会話ビューで表示 |
| `/tasks` | タスク一覧(repo バッジ / status / 最新 run / 実行・アーカイブ) |
| `/tasks/new` | **プロンプトからタスク生成**(repo 選択必須 + 自動実行トグル) |
| `/tasks/<id>` | タスク編集(項目別フォーム / ＋−行) |
| `/dashboard` | 集計の事実提示(未レビュー件数・指標・チャート) |

判断・review-notes・タスクの書き込み先は常に契約ファイル。詳細は [docs/usage.md](./docs/usage.md)。

## 構成

```
engine(公開 repo):
  loop.toml           設定([loop]/[agents]/[data]。repo 構成は loop.local.toml)
  runner.py           一本道ランナー: Author/Implementer/Verifier / revise / 人間介入 / promote / merges / 生成(種類A)
  loopdb.py           SQLite インデックス層(MD 派生・再生成可能)
  webapp/             FastAPI(/api JSON + SSE。UI 供給は Next)
  web/                Next.js(App Router)+ TS + Tailwind + shadcn/ui = 唯一の UI
  stats.py + queries/ DuckDB 分析
  launchd/*.example   WatchPaths トリガー(data/tasks 変更で起動)
  .claude/skills/     SKILL.md / task-author(タスク生成スキル)

data/(別の private git repo / engine からは .gitignore):
  tasks/<id>.md       目標契約(1 タスク=1 ファイル / YAML front-matter)
  tasks/plans/<id>.md Author 生成の実装プラン(サイドカー)
  review-notes.md     種類B の R&D ログ
  runs/<id>.md        ★契約: run レコード(真実の源)
  runs/<id>/          ★契約: 証拠(result.json / *.stream.jsonl / test-output / change.patch / transcript / promote.json)
  plans/              設計ドキュメント
  loop.db             ★派生: SQLite(.gitignore、再生成可能)
```

## コマンド(`just` / 直接 `uv run`)

| | コマンド |
|---|---|
| 次の todo を実行 | `just run` / `uv run runner.py run [task_id]` |
| プロンプト生成 | `uv run runner.py gen "<依頼>" [--repo <r>] [--run]` |
| 規範候補の昇格/却下(種類B) | `uv run runner.py norms [list\|promote <id>\|reject <id>]` |
| PR マージ待ち run の確認(マージ済み→pass 昇格) | `uv run runner.py merges` |
| Web(フロント+バック) | `just app`(UI: http://127.0.0.1:3000、Tailnet 内なら http://&lt;host&gt;.ts.net:3000) |
| backend のみ | `just web` |
| 再インデックス | `just reindex` |
| DuckDB 分析 | `just stats` / `just stats-sql "SELECT …"` |
| 一覧 | `just status` |
| WatchPaths 導入/解除 | `just watch-install` / `just watch-uninstall` |

## やらないこと

timer ベースの無人 cadence / durable execution / **種類B の自動生成(判断・学びの自動記入や推奨)** /
外部連携(Linear・GitHub API・Slack)は作らない。
