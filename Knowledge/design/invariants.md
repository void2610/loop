---
type: Invariant
title: loop の絶対原則(壊すな)
description: 種類A は全自動 / 種類B は絶対自動化しない、ファイルが真実、削除しない=アーカイブ、Verifier 別モデル、検証の死角を作らない。
resource: runner.py
timestamp: 2026-06-23T07:19:07Z
tags: [invariant, type-a-b, file-based-contract]
---

CLAUDE.md §1 の絶対原則。OKF 化後もこれを死守する。

1. **種類A は全自動 / 種類B(判断)は絶対に自動化しない。**
   - 種類A = dispatch・実行・証拠収集・コミット・インデックス・表示。
   - 種類B = 人間が run を読んで「信用できるか/どこで壊れるか/次に自動検証へ入れるべきチェック/学び」を書く。
   - GUI・runner・API は判断を生成・要約・推奨・自動入力しない。事実要約と証拠表示まで。`## 判断` / judgment フォームは常に空で出す。

2. **ファイルが真実(file-based contract)。** `data/tasks/*.md` + `data/runs/<id>.md` + 証拠 + `review-notes.md` + git。
   `loop.db`(SQLite)は**派生**で `just reindex` で完全再生成できる(`rm loop.db && reindex` で壊れない=不変条件)。
   Web は契約ファイルを編集する面で独自ストアを持たない。知識バンドルも同様(ファイルが真実、索引は派生)。

3. **削除しない=アーカイブ。** ログは資産。タスク/run は `archived` フラグで UI から隠すだけ。削除エンドポイント・削除ボタンを復活させない。

4. **Verifier は Implementer と別モデル必須。** 同一だと起動時警告。read-only 役(Explorer/Verifier)と生成は変更系ツールを禁止([global settings の罠](/traps/global-settings-allow-wins.md))。

5. **検証の死角を作らない。** 自動で pass/fail と言い切れない時は `handoff`(人間へ)。"done" は自己申告であって証明ではない — 変更は実際に動かして証拠で示す。

関連: [2 repo 分離](/design/two-repo-split.md)
