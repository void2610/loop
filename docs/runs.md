# Runs — 実行ライフサイクル

## 1 run の流れ(`runner.cmd_run` → `_run_attempt`)

```
次の todo タスクを選択(data/tasks/*.md をファイル名昇順、最初の status:todo)
  ↓  .run.lock を O_EXCL で取得(単一オペレータの atomic claim)
repo 解決(task.repo)→ worktree 隔離(none なら一時ディレクトリ)
  ↓
1) Explorer    高速モデル / read-only … 関連ファイル・前提・リスクを調査(失敗しても継続)
2) Implementer 主力モデル / read-write … Explorer findings + 目標契約で実装(= 本作業)
   ↓ diff を capture.patch に
3) 決定論テスト run_verify … task.verify を worktree で実行 → test_verdict ∈ {pass, fail, none}
4) Verifier    別モデル / read-only / 構造化出力 … 受け入れ基準を独立判定。test gaming を疑う
                                                  → verifier_verdict ∈ {pass, fail, handoff}
  ↓
final = combine(test_verdict, verifier_verdict)
  ↓
worktree 内コミット(loop/<run_id> ブランチに成果)→ runs/<id>.md 生成 → status 更新
  ↓ SQLite upsert → data repo へ auto-commit → worktree 後始末 → .run.lock 解放
```

各役割は `claude -p --output-format stream-json --verbose` で実行し、イベントを
`runs/<id>/{role}.stream.jsonl` へ逐次書き出す(Web のライブ表示用)。最終 `result` イベントから
結果(`structured_output` / `total_cost_usd` / `num_turns` 等)を復元する。

## verdict 合成

`test_verdict ∈ {pass, fail, none}`(none = `verify` 未指定)、`verifier_verdict ∈ {pass, fail, handoff}`。

| test | verifier | final | 意味 |
|---|---|---|---|
| fail | (何でも) | **fail** | 客観的失敗。Verifier の根拠は記録するが覆さない |
| pass / none | fail | **fail** | テスト緑でも gaming / 部分未達を Verifier が捕捉 |
| pass / none | handoff | **handoff** | Verifier が判定保留 → 人間へ |
| pass / none | pass | **pass** | テスト緑(or なし)かつ Verifier 合格 |

`verify` 未指定でも Verifier の判断で pass/fail し得る(従来の一律 handoff を脱する)。

## handoff とは

「機械では二値判定しきれない → 人間に引き渡す」状態。悪い結果ではなく、自動ゲートが自信を持って pass/fail
と言えないとき**勝手に通さず人間に渡す**安全弁。Verifier が構造化出力を返せない / error / timeout / 中断のときも
安全側で handoff(暗黙 pass にしない)。

## リトライ(人間送りを減らす)

`loop.toml [loop]`:

- **`verifier_attempts`(既定3)**: Verifier が handoff を返す間、**read-only のまま再判定**。Verifier は読むだけ=
  冪等で副作用ゼロなので、transient な判定不能(crash/timeout)が人間送りになるのを防ぐ。
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
model, cost_usd, turns, duration_ms, session_id, repo_sha, skill_sha, goal_contract_sha, started_at
```

本文セクション:

- `## エージェントがやったこと` — Implementer の最終出力(runner は再要約しない)
- `## 役割別実行` — 役割 × model / cost / turns の表
- `## Verifier の判定` — verdict / confidence / gaming 疑い / 理由 / 基準ごと(**事実表示**。種類B ではない)
- `## 証拠` — test-output / change.patch / transcript へのリンク
- `## 判断` — **人間がここだけ書く(種類B)**。`### 信用できるか / 失敗・リスク / 自動検証に入れるべきチェック / 学び`

証拠ディレクトリ `runs/<id>/`: `explorer|implementer|verifier.result.json`、`*.stream.jsonl`(ライブ用)、
`test-output.txt`、`change.patch`、`transcript.jsonl`、`verifier.json`。

## レビュー(種類B)

run 完了後 `reviewed: false`。Web の判断フォーム(`/run/<id>`)or `just review`(nvim 着地)で判断を書くと、
契約ファイル(`runs/<id>.md` の判断セクション)へ書き戻し、「自動検証に入れるべきチェック」を `review-notes.md`
へ追記し、`reviewed: true` 化 → コミット → SQLite 再導出(すべて種類A、自動)。
