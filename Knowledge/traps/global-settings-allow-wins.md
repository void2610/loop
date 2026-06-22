---
type: Trap
title: global settings の allow が --allowedTools を勝つ
description: ~/.claude/settings.json が Bash(*)/Write/defaultMode:auto を許可しているため、headless の --allowedTools は実質スコープにならない。read-only 役は --disallowedTools で強制する。
resource: runner.py
timestamp: 2026-06-23T07:19:07Z
tags: [headless, permissions, read-only]
---

グローバル `~/.claude/settings.json` が `Bash(*)` / `Write` / `defaultMode: auto` を許可しているため、
headless の `--allowedTools` は**実質スコープにならない**(settings の allow が勝つ)。

read-only を強制したい役(Explorer/Verifier/タスク生成)は
**`--disallowedTools Write Edit MultiEdit NotebookEdit Bash`** を付ける(`runner.WRITE_TOOLS` / `read_only=True`)。
`--disallowedTools` は allow より優先される。

この上書きが無いと、生成が「依頼を実際に実行」しようとして read-only 拒否で turn を空回りし、遅くなる/副産物ファイルが出る。

関連: [--max-turns は隠れている](/traps/max-turns-hidden.md)
