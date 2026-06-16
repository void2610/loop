# loop — Loop Engineering 計測配管 (v4)

Claude Code を headless で回す「ループ」の **計測層** だけを自作したもの。
実行系(`claude -p` / `git worktree`)はネイティブに委ねる。設計ドキュメントは
非公開データ側(`data/plans/`)に置く。

## 中心思想 — 仕事を2種類に分ける

- **種類A = メカニクス**(dispatch / 実行 / 証拠収集 / コミット / インデックス / 表示)→ **全自動**。
- **種類B = 判断**(生の run を読み、信用できるか・どこで壊れるか・次に自動検証へ入れるべきチェックを言語化)→ **絶対に自動化しない**。これがメタループの本体で持ち越し可能なスキル。

GUI も SQL も「種類B を肩代わりする道具」ではない。唯一の硬い制約: **GUI は判断を生成・要約・推奨・自動入力しない**(事実要約と証拠表示まで)。

## 単一の真実は file-based contract

`runs/*.md`(front-matter 含む)＋ per-run 証拠ディレクトリ ＋ `review-notes.md` ＋ git。
`loop.db`(SQLite)はそこから導出される **使い捨て派生インデックス**で、`rm loop.db && just reindex` で完全復元できる。DuckDB も状態を持たない。Web GUI は契約ファイルを **編集する面**(独自の権威ストアを持たない)。

## 公開エンジン / 非公開データの分離

このリポジトリ(エンジン)は **コードだけ**を持つ公開 repo。契約データ(目標契約・run 記録・証拠・判断・設計ドキュメント)は **`data/` 配下の別 git repo**(private またはローカルのみ)に置き、エンジン側は `data/` を `.gitignore` する。runner / Web GUI は `loop.toml` の `data.dir` 経由で `data/` を読み書きし、auto-commit も `data/` 側へ行う。

```
clone 後に1回:
  just init-data        # data/ を private git repo として初期化
  # 必要なら: git -C data remote add origin <private-remote>
```

`data/` には `TODO.md`・`review-notes.md`・`runs/`・`plans/`(設計ドキュメント)が入る。公開 repo には絶対パス等を含めない(launchd plist は `*.example` をローカル生成)。

## 使い方

`just` 未インストールなら各行の `uv run ...` を直接実行(下の対応表)。

| やること | コマンド | 種別 |
|---|---|---|
| TODO の次タスクを実行(実行→検証→コミット→MD→upsert) | `just run` / `uv run runner.py run` | A 全自動 |
| **Web GUI(編集面)で triage し判断を書く** | `just web` / `uv run webapp/main.py` → http://127.0.0.1:8765 | B 入力 |
| 次の未レビュー run を nvim で開き判断を書く | `just review` / `uv run runner.py review` | B 着地 |
| run を一覧・triage(読み取り専用 TUI / 残置の別ビュー) | `just tui` / `uv run tui.py` | A ナビ |
| SQLite を MD から完全再生成 | `just reindex` | A |
| DuckDB 分析(canned / ad-hoc) | `just stats` / `just stats-sql "SELECT …"` | A |
| verdict・reviewed 一覧 | `just status` | A |
| TODO.md 変更で自動起動(opt-in) | `just watch-install` / `just watch-uninstall` | A |

### レビュー(種類B)の流れ — Web GUI(v4 既定)

1. `just web` → ブラウザで http://127.0.0.1:8765 を開き run を triage(verdict / reviewed / task でフィルタ)。
2. run をクリック → detail で front-matter・**事実要約(runner 生成)**・diff・証拠・transcript を読む。
3. **判断フォーム**(信用できるか / 失敗・リスク / 自動検証に入れるべきチェック / 学び)に書いて submit。
   フォームは常に**空**で出る(GUI は判断を生成・提案しない)。
4. submit で backend が `runs/<id>.md` の判断セクションへ書き戻し、「自動検証に入れるべきチェック」を
   `review-notes.md` に追記し、`reviewed:true` 化 → コミット → SQLite 再導出(すべて種類A、自動)。

書き込み先は常に契約ファイル。`just tui`(`e` で nvim 着地)/ `just review` も同じ契約ファイルを編集する別経路として残してある。

## 1 run の流れ(runner.py / 種類A)

`TODO.md` パース → `git worktree` 隔離 → **3役 Sub-agents** → 自動チェックポイントコミット(成果を `loop/<id>` ブランチへ)→ `runs/<id>.md` 生成(front-matter・証拠・判断は空 / `reviewed:false`)→ SQLite upsert → worktree 後始末。

3役(記事の Sub-agents モジュール。`[agents]` でモデル/ツールを指定):

1. **Explorer**(高速モデル / read-only)— 実装せず、関連ファイル・前提・リスクを調査。失敗しても継続。
2. **Implementer**(主力モデル / read-write)— Explorer findings + 目標契約で実装。
3. **決定論テスト**(`verify`)→ `test_verdict ∈ {pass, fail, none}`。
4. **Verifier**(**別モデル必須** / read-only / 構造化出力)— 自己申告を信じず受け入れ基準を独立判定。test gaming / 部分未達を疑う。→ `verifier_verdict ∈ {pass, fail, handoff}`。

最終 verdict = `combine(test, verifier)`: test=fail なら fail / verifier=fail なら fail(テスト緑でも gaming を捕捉)/ verifier=handoff なら handoff / それ以外 pass。Verifier の判定は **事実セクション**に記録し、`## 判断`(種類B)は空のまま人間が書く。

- 停止条件: turn 上限 `--max-turns`(暴走の一次ガード)+ `--max-budget-usd` + wall-clock タイムアウトの3段。各役呼び出しに効く。
- コストは約3倍(1 run = 3 モデル呼び出し)。`verifier_model` は `implementer_model` と別にすること(同一なら起動時警告)。
- 再現性: `--bare` を使わず、`skill_sha` と `goal_contract_sha` を front-matter に刻む。
- 「やったこと」は Implementer の最終出力をそのまま載せる(runner は再要約しない=種類B を侵さない)。

## 構成

```
エンジン(公開 repo):
  loop.toml          設定(モデル / 予算上限 / タイムアウト / allowed_tools / repo / data.dir)
  runner.py          一本道ランナー + 判断書き戻し(種類A)
  loopdb.py          SQLite インデックス層
  webapp/            ★編集面: FastAPI + HTMX(判断・review-notes を契約ファイルへ書く)
  tui.py             ★別ビュー(残置): Textual TUI(読み取り専用 + nvim 着地)
  stats.py + queries/ ★派生: DuckDB 分析
  launchd/*.example  WatchPaths トリガー(ローカルでパスを埋めて生成)
  .claude/skills/    SKILL.md(ネイティブ、git 管理、SHA を run に記録)

data/(別の private git repo / .gitignore):
  TODO.md            目標契約キュー(```yaml ブロック。数値で二値判定できる verify 必須)
  review-notes.md    種類B の R&D ログ(failure mode → 入れるべき自動チェック)
  runs/<id>.md       ★契約: run レコード(真実の源)
  runs/<id>/         ★契約: 証拠(result.json / test-output.txt / change.patch / transcript.jsonl)
  plans/             設計ドキュメント(loop-engineering-plan*.md)
  loop.db            ★派生: SQLite(.gitignore、再生成可能)
```

## やらないこと(plan §3.2)

timer ベースの無人 cadence / durable execution / **種類B の自動生成(GUI・runner による判断・学び・review-notes の自動記入や推奨)** / 外部連携(Linear・GitHub API・Slack)は作らない。合図が立つまで保留。
