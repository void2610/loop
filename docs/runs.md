# Runs — 実行ライフサイクル

## 1 run の流れ(`runner.cmd_run` → `_run_attempt`)

```
次の todo タスクを選択(data/tasks/*.md をファイル名昇順、最初の status:todo)
  ↓  .run.lock を O_EXCL で取得(単一オペレータの atomic claim)
repo 解決(task.repo)→ git worktree 隔離(repo は常に在る前提)
  ↓
1) 事前情報   Author 生成の実装プラン(tasks/plans/<id>.md)を Implementer へ
              (旧 Explorer は廃止。Author が生成時に repo を read-only 調査しプランを書く)
2) Implementer 主力モデル / read-write … プラン + 目標契約で実装し、自分でテストまで実行(= 本作業)
   ↓ diff を change.patch に
3) 決定論ゲート run_verify … task.verify を worktree で実行 → test_verdict ∈ {pass, fail, none}(床)
4) Verifier    別モデル / read-only / 構造化出力 … 受け入れ基準とテスト妥当性を独立監査
              → verifier_verdict ∈ {pass, fail, revise, handoff}
   ↓ revise なら required_changes を付けて Implementer に差し戻し(同一セッションを --resume で継続)
   ↑__________ 上限 implementer_revise_rounds まで(3→4 を再判定)。超過は handoff
  ↓
final = combine(test_verdict, verifier_verdict)
  ↓
worktree 内コミット(loop/<run_id> ブランチに成果)
  ↓ [final=pass かつ promote_on_pass なら] promote 段(下記)
runs/<id>.md 生成 → status 更新 → SQLite upsert → data repo へ auto-commit → worktree 後始末 → .run.lock 解放
```

各役割は `claude -p --output-format stream-json --verbose` で実行し、イベントを
`runs/<id>/{role}.stream.jsonl` へ逐次書き出す(Web のライブ表示用)。最終 `result` イベントから
結果(`structured_output` / `total_cost_usd` / `num_turns` / `session_id` 等)を復元する。
差し戻し(revise)は `session_id` を `--resume` に渡し、Implementer が実装時の文脈を保持したまま再実装する。

実行機構は全役 **`RoleSession`(`claude -p` を stream-json で双方向に開いた永続セッション)**。one-shot と
`--resume` 再 spawn は廃止し、revise も人間介入も **同一セッションへ user メッセージを `send`** する一経路に統一。

**人間介入(awaiting)= 責務分離**:
- **実装中**の方針疑問・権限不足 → Implementer が出力冒頭に `NEEDS_HUMAN:` を付けてターンを区切る → `_drive_implementer`
  が **Verifier より前に** awaiting にして人間の続行指示を待つ(**主経路**)。
- **実装後**の結果/テスト欠陥 → Verifier の責務。`revise` で自動修正(人間不要)。
- Verifier の handoff / revise 上限超過 → **最後の安全網**としてだけ人間へ。

いずれも `runs/<id>/inbox.jsonl` を待つ(`intervention_timeout_seconds`、超過で handoff)。Web の `/runs/<id>/live` が
詰まった理由(`intervention`)を表示し、`POST /api/runs/<id>/message` で指示を送ると **同一セッションへ注入して続行**。
GUI は事実表示のみで選択肢・判断を生成しない。

**Verifier は inbox の人間回答も入力に取る**(`_inbox_human_input`)。人間の承認/指示は実装者の自己申告ではなく
**人間=種類B の権威**なので、「人間承認が要る/ポリシー決定」系の基準はこれに照らして判定し、承認の証跡が
worktree に残っていなくても誤 handoff しない(実装が承認内容と一致するかは引き続き diff/ファイルで検証)。

各役には **同一 repo の過去 run の客観的事実ブリーフ**(`build_repo_brief`、`repo_history_runs` 件)も注入する:
過去に exit0 で通った検証コマンド / 失敗の事実 / 直近 verdict 台帳(アーカイブ run は除外)。**人間の判断は含めない**
(学び・review-notes はメタループ専用)。run が貯まるほど、その repo に対する新インスタンスの習熟が上がる。

## verdict 合成

`test_verdict ∈ {pass, fail, none}`(none = `verify` 未指定)、`verifier_verdict ∈ {pass, fail, revise, handoff}`。
`revise` は**最終 verdict ではなくループの駆動**: Implementer に差し戻して再実装→再判定する。下表は revise ループ収束後の合成。

| test | verifier | final | 意味 |
|---|---|---|---|
| fail | (何でも) | **fail** | 客観的失敗。Verifier の根拠は記録するが覆さない(決定論ゲートは床) |
| pass / none | fail | **fail** | テスト緑でも gaming / 部分未達を Verifier が捕捉 |
| pass / none | handoff | **handoff** | Verifier が判定保留、または revise 上限超過 → 人間へ |
| pass / none | pass | **pass** | テスト緑(or なし)かつ Verifier 合格 |

`verify` 未指定でも Verifier の判断で pass/fail し得る(従来の一律 handoff を脱する)。
`revise` 上限(`implementer_revise_rounds`)を超えても通せなければ **pass にせず handoff**(死角を作らない)。

## handoff とは

「機械では二値判定しきれない → 人間に引き渡す」状態。悪い結果ではなく、自動ゲートが自信を持って pass/fail
と言えないとき**勝手に通さず人間に渡す**安全弁。Verifier が構造化出力を返せない / error / timeout / 中断のときも
安全側で handoff(暗黙 pass にしない)。

## リトライ(人間送りを減らす)

`loop.toml [loop]`:

- **`verifier_attempts`(既定3)**: Verifier が handoff を返す間、**read-only のまま再判定**。Verifier は読むだけ=
  冪等で副作用ゼロなので、transient な判定不能(crash/timeout)が人間送りになるのを防ぐ。
- **`implementer_revise_rounds`(既定2)**: Verifier が `revise` を返したとき、`required_changes` を付けて
  Implementer を **`--resume`(実装文脈を保持)**で差し戻し→再ゲート→再監査する往復の上限。0 で無効。超過は handoff。
- **`max_attempts`(既定2)**: **実装が timeout/error で確定しなかったときだけ**、新しい worktree で run 全体を
  再試行(`-retryN`)。決定済みの pass/fail/handoff は再試行しない。

**冪等性の前提**: run 全体の再試行は git worktree 内で完結する冪等タスクを想定。外部FS を書き換える非冪等タスクは
タスクに `max_attempts: 1` を指定する(再試行でバックアップが空になり verify が壊れる、等を防ぐ)。

## 停止条件(3段)

- **`--max-turns`**(暴走ループの一次ガード)
- **`--max-budget-usd`**(コスト上限)
- **wall-clock タイムアウト**(`timeout_seconds`、runner が `threading.Timer` で kill)

`--max-budget-usd` の支出は 2026/6/15 以降 Agent SDK クレジットから引かれるため、サブスク型ランナーの
セッション枯渇は budget だけでは守れない。turn + wall-clock の併用に意味がある。

## 再現性

- `--bare` を使わず SKILL.md を自動探索させ、使用した skill のツリー SHA を `skill_sha` に刻む。
- `repo_sha`(対象 repo の HEAD)、`goal_contract_sha`(目標契約の正規化ハッシュ)も記録。
- モデル版はドリフトしうるので bit-exact 再現は狙わない。`just stats` の `pass_rate_by_skill` で
  skill 版ごとの pass 率を統計的に見る。

## run レコード(`runs/<id>.md`)

front-matter(runner が自動生成):

```
task, verdict, reviewed, repo, test_verdict, verifier_verdict, verifier_confidence,
model, cost_usd, turns, duration_ms, session_id, repo_sha, skill_sha, goal_contract_sha, pr_url, started_at
```

本文セクション:

- `## エージェントがやったこと` — Implementer の最終出力(runner は再要約しない)
- `## 役割別実行` — 役割 × model / cost / turns の表
- `## Verifier の判定` — verdict / confidence / gaming 疑い / 理由 / 基準ごと(**事実表示**。種類B ではない)
- `## 証拠` — test-output / change.patch / transcript へのリンク
- `## 判断` — **人間がここだけ書く(種類B)**。`### 信用できるか / 失敗・リスク / 自動検証に入れるべきチェック / 学び`

証拠ディレクトリ `runs/<id>/`: `implementer|verifier.result.json`、`*.stream.jsonl`(ライブ用)、
`test-output.txt`、`change.patch`、`transcript.jsonl`、`verifier.json`、`verifier.roundN.json`(差し戻し各回)、
`promote.roundN.json` / `promote.json`(promote 有効時)。

## promote 段(PR 提出 → CI + Copilot が green まで)

`loop.toml [loop] promote_on_pass = true`(既定 false)のとき、**final=pass の成果を PR 化**して外部の自動レビューに通す。
あなたの「ローカル完了 → PR 提出 → Copilot レビュー → 指摘修正 → PR 更新」を headless 化したもの。

```
loop/<id> を push → PR 作成 → Copilot レビュー要求(REST)
ループ(上限 promote_rounds):
  CI 完了待ち(gh pr checks)+ Copilot レビュー待ち(reviewThreads 出現)
  CI 失敗ログ + 未解決 Copilot スレッドを収集
  → Implementer に --resume で差し戻し → 修正 → push → resolve → 再レビュー
CI green かつ Copilot 未解決ゼロ → verdict=awaiting-merge(真の完了は人間の PR マージ後)
```

- **merge はしない**(結果を確定する人間の判断=種類B)。green でも `pass` にせず **`awaiting-merge`** で記録し、
  プロセス・worktree は解放する(PR は GitHub に残る)。green 不達・上限超過は handoff。
- **真の完了 = 人間が PR をマージしたとき**。`check_pr_merge`(Web の `GET /api/runs/<id>/pr` / CLI `runner.py merges`)が
  gh で PR 状態を確認し、**マージ済みを検知したら verdict を `pass` へ昇格**(種類A)。Runs 一覧は `awaiting-merge` の run を
  「PR マージ待ち」カードで上部に出し、PR 状態 + 「PR を開く」を表示。
- Copilot レビュー要求は `gh pr edit --add-reviewer` が無言失敗するため REST(`requested_reviewers` に
  `copilot-pull-request-reviewer[bot]`)で行う。設定: `promote_rounds` / `ci_timeout_seconds` / `copilot_timeout_seconds`。

## レビュー(種類B)

run 完了後 `reviewed: false`。Web の判断フォーム(`/runs/<id>`)で判断を書くと、
契約ファイル(`runs/<id>.md` の判断セクション)へ書き戻し、「自動検証に入れるべきチェック」を `review-notes.md`
へ追記し、`reviewed: true` 化 → コミット → SQLite 再導出(すべて種類A、自動)。
