---
type: System
title: runner — 一本道ランナー
description: Implementer/Verifier の永続セッション実行・revise・生成(gen)・promote・status・archive を担う種類A の実行層。
resource: runner.py
timestamp: 2026-06-23T07:19:07Z
tags: [runner, roles, promote, revise]
---

`runner.py` = 計測配管の実行層(種類A)。実行系(`claude -p` / `git worktree`)はネイティブに委ね、突き合わせに徹する。

# 役割フロー(現行)

`Author プラン → Implementer(自己テストまで)→ 決定論ゲート → Verifier 監査 →(revise / 人間介入は同一セッションへ send)→ [promote: pass のみ]`

- 全役は **`RoleSession`**(`claude -p --input-format/--output-format stream-json` の永続双方向セッション)で動く。
  追加指示(revise / 人間介入)は `send()` で同一セッションへ user メッセージ注入に一本化([json-schema/stream-json の罠](/traps/json-schema-structured-output.md))。
- **Author = Explorer 統合**: 生成時に repo を read-only 調査し詳細プランを `tasks/plans/<id>.md` に出力。run 時はこのプランを Implementer に渡す。
- **revise ループ**: Verifier は `pass/fail/revise/handoff`。`revise` は `required_changes` を付けて Implementer に差し戻し同一セッション継続。上限 `loop.implementer_revise_rounds`(既定 2)。超過でも pass にせず handoff。
- **promote 段**: run=pass を PR 化し GitHub CI + Copilot レビューが green になるまで差し戻す(種類A)。green でも `awaiting-merge` で確定(真の完了は人間の PR マージ後)。merge は人間。
- **repo 単位 serial / parallel**: `[repos]` 値を `{ path, mode = "serial" }` にすると worktree を作らず repo 本体で 1 本ずつ作業(Unity 等)。`_serial_lock` で同一 serial repo を直列化。既定は parallel(worktree 並列)。

# 知識の読み書き(本バンドル関連)

- `build_knowledge_brief(cfg)` が `[knowledge].bundles` を anchor(ROOT)起点で絶対化し Author/Implementer に渡す([anchor 解決規則](/conventions-loop.md))。
- `_finalize_run` 近傍の知識コミット段が、run が触れた engine/data の知識変更を `knowledge:` 接頭辞で commit(`judgment: human` / `decisions/` は除外・engine は自動 push しない)。

関連: [loopdb](/systems/loopdb.md) / [webapp](/systems/webapp.md) / [絶対原則](/design/invariants.md)
