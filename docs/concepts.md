# Concepts — 設計思想

## なぜ作るか

レバレッジが「良いプロンプトを書く」から「良いループを設計する」へ移った。価値が高く自動化しにくいのは、
検証ゲート・停止条件の設計と、**ループ自身を改善するメタループ**。ベンダー(Claude Code)が出荷するのは
primitive(`claude -p`、git worktree、skills、subagents)であり、ループの中身(目標契約・SKILL.md・検証・
停止条件)は自分で書く。メタループには run の**透明性と再現性**が要るが、ネイティブが吐くのは
time/turns/tokens どまり。「どの skill 版 × どの目標契約 × どのモデルで、どの結果か」を突き合わせる層は
提供されない。**その突き合わせ層(計測配管)を自作する。**

## 種類A / 種類B

人間の作業を2種類に分け、扱いを正反対にする。

- **種類A = メカニクス**(dispatch・実行・証拠収集・コミット・インデックス更新・表示)。設計に鈍感で自動化が安く、
  人間がやっても何も学べない。**全自動化し、人間の習慣にしない。**
- **種類B = 判断**(生の run を読み、信用できるか・どこで壊れるかを評価し、学びと「次に自動検証へ入れるべき
  チェック」を言語化する)。**自動化・要約・代行しない。** 将来の自動 verifier / eval gate を正しく設計するための
  入力(R&D)であり、持ち越し可能なスキルそのもの。

手動レビューを飛ばして自動検証を組むと「間違ったものをチェックする verifier」ができる(検証の死角)。
生の run を人間が見て失敗の形を学んだ結果が、将来の自動チェックの仕様になる。

唯一の硬い制約: **GUI は判断を生成・要約・推奨・自動入力しない**。事実要約(runner が作る)と証拠表示まで。
verdict の妥当性・信用度・学びは人間が空欄に書く。

## 単一の真実 = file-based contract

| 層 | 役割 | 再生成 |
|---|---|---|
| `data/tasks/*.md` | 目標契約(入力) | 人間が書く / プロンプト生成 |
| `runs/<id>.md` + `runs/<id>/` | run 記録と証拠(真実の源) | runner が書く |
| `repo/<name>/conventions.md` | 承認済みの設計規範(run に注入される) | 人間が昇格時に確定 |
| `repo/<name>/candidates.md` | 規範候補の控え室(注入されない) | runner が起草 / 人間が裁定 |
| `review-notes.md` | 種類B の R&D ログ | 人間が書く |
| `loop.db`(SQLite) | 派生インデックス | `just reindex` で MD から完全再生成 |
| DuckDB | 分析レンズ(状態なし) | — |
| Web GUI | 契約ファイルを編集する面(独自ストアなし) | — |

`rm loop.db && just reindex` で SQLite が MD から完全復元できる = SQLite は authoritative でない、の証明。

## 6つのコアモジュール(記事)との対応

| モジュール | 本プロジェクトでの実装 |
|---|---|
| **Automations** | runner が次タスク自動選択 + 自動コミット。手動 `just run` + launchd WatchPaths(data/tasks 変更) |
| **Worktrees** | `git worktree` を run ごとに(loop repo 内 `.loop-worktrees/` に固定配置) |
| **Skills** | `.claude/skills/`(SKILL.md / task-author)。runner は skill_sha を run に記録 |
| **Sub-agents** | Author(プラン)→ Implementer → Verifier の分離。Verifier は別モデル必須。revise は Implementer を `--resume` で差し戻し |
| **Connectors** | ローカル FS / git / shell。証拠はローカルテスト実行から。promote 時は GitHub(PR / CI / Copilot レビュー) |
| **Memory** | `runs/*.md` + 証拠 + `review-notes.md` + SKILL.md(=契約)。SQLite/DuckDB はその派生。記憶は2系統: ①**事実記憶**(同一 repo で通った検証コマンド・直近 verdict・失敗事実)を Author/Implementer/Verifier に自動注入(種類A)し、回すほど repo に習熟する。②**手続き的記憶=規範**(`conventions.md`。下記参照)。どちらも**人間の判断(学び/review-notes)はエージェントに渡さない**=メタループ(人間が skill/ゲート/契約を改善する燃料) |

## 規範記憶(手続き的記憶)— 事実記憶とは別系統

事実記憶(検証コマンド・失敗シグネチャ)は exit code で測れる客観的事実で、優秀なモデルなら数ターンで自己解決する運用上の失敗が多い。それとは別に、**「このリポジトリではどう振る舞うべきか」という規範**(設計・思想・振る舞い)を育てる層を持つ。例:「新機能はインターフェース境界を先に定義してから実装する」「DI 登録は Installer に集約し各クラスで `new` しない」。これらは exit code では検証できないため、**エージェントに確定させず、人間が承認したものだけを注入する**。

規範は repo 単位で 3 層に分離する(`data/repo/<name>/`):

- `conventions.md` — **承認済みの規範**。これだけが run に注入される。人間が昇格させたものだけ。
- `candidates.md` — **昇格待ちの控え室**。注入されない。エージェントが起草し、人間が裁定する。これが種類A/種類Bの分離線。
- `CLAUDE.md`(`data/` 直下)— 人間が書く憲法。最優先・エージェント不可侵。

フロー(種類A → 種類B → 注入):

1. **起草(種類A・自動)**: **摩擦のある run**(Implementer の revise 差し戻し / Verifier の handoff / 人間レビューで verdict が覆る)でだけ、起草エージェント(read-only・構造化出力・確定権なし)が構造化サマリ+diff+差し戻し理由から規範候補を起草し、`candidates.md` へ追記する(毎 run ではない。空振りは run の `norms.json` に残す)。人間の `review-notes.md` は入力にしない(種類B 侵食を防ぐ)。
2. **昇格(種類B・人間。絶対に自動化しない)**: `uv run runner.py norms` で pending 候補を一覧し、`promote <id>` / `reject <id>` で裁定する。promote は候補の規範文を `conventions.md` へ追記し、**統合・上書き・文言調整・剪定は人間が `conventions.md` を直接編集して**行う(将来 Web から)。CLI/GUI は規範文を自動生成・要約・推奨しない。
3. **注入(種類A・自動)**: 以降の run 開始時に `conventions.md`(承認済みのみ)を Author/Implementer/Verifier へ事実ブリーフとは**別セクション**で注入する。`candidates.md` は注入しない。

**優先順位は `CLAUDE.md`(憲法) > `conventions.md`(承認済み規範) > 過去 run の事実ブリーフ**。注入文の冒頭に明示する。`conventions.md` が無ければ何も注入されず、摩擦が無ければ起草もされない(常時オンで分岐を増やさない)。`loop.db` の `norm_candidates` は派生インデックスで、`just reindex` が MD から完全再生成する(SQLite は authoritative にしない)。

## 公開エンジン / 非公開データ

engine(このコード)は公開 OSS、データ(目標契約・run・判断・設計ドキュメント)は private。
分離は `loop.toml [data] dir = "data"` 一点で表現され、engine は `data/` を `.gitignore` する。
`data/` 自体は独立した git repo にでき(`just init-data`)、runner の auto-commit はそちらへ向く。

## 隔離は sandbox ではない

worktree 分離は「**git レベルの作業分離・diff 管理**」であって「副作用の封じ込め(sandbox)」ではない。
Bash は絶対パスで worktree 外も触れる。外部FS を触るタスクの安全性は、隔離ではなく
**タスクの constraints**(バックアップ先行・削除禁止・件数不変 verify など)で担保する。
read-only 役(Verifier)と生成(Author)は `--disallowedTools` で変更系ツールを禁止し、global settings
(`Bash(*)`/`Write` 許可)を上書きして read-only を強制する。
