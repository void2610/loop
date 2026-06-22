---
type: Invariant
title: 2 repo 分離(engine 公開 / data 非公開)
description: engine はコードだけの公開 repo、契約データは data 配下の別 private repo。data を含む履歴を public engine に push しない。知識バンドルもこの境界を踏襲する。
resource: .gitignore
timestamp: 2026-06-23T07:19:07Z
tags: [invariant, two-repo, public-private, push]
---

loop は **2 リポジトリ構成**:
- engine(このリポジトリ・public)= **コードだけの公開 repo**(`void2610/loop`)。
- data(`data/` 配下の別 private repo・`void2610/loop-data`)= 目標契約・run 記録・証拠・判断・設計メモ。

engine は `data/` を `.gitignore` する。runner / API の auto-commit は **data 側へ行く**(engine 宛て auto_commit は知識コミット段以外に存在しない)。

# 不変条件

- **2 repo を取り違えない。** 契約データの変更は `git -C data ...`、コードは engine。
- **data を含む履歴を public(engine)に push しない。** 過去に engine へ data/設計メモを誤って含めた事故あり(force-push で除去済み)。
- engine に紛れ込みやすいもの: ルート直下の設計メモ `*.md`(→ `data/plans/`)、生成物、`data/`。コミット前に `git status` を確認。
- 作業が一段落したら明示指示が無くても自動 commit/push してよいが、**push 前に必ず `git status` で 2 repo 分離を確認**。混入の疑いがあれば push せず手を止めて報告。

# 知識バンドルへの継承

- engine `Knowledge/`(公開)= 設計知識・罠・不変条件。
- data `Knowledge/`(非公開・`Knowledge/private` symlink 経由)= run 横断の学び・判断(種類B)。
- 橋渡しリンク `Knowledge/private` は gitignored で public 履歴に入れない。詳細は [conventions-loop](/conventions-loop.md)。

関連: [絶対原則](/design/invariants.md)
