---
type: Trap
title: --max-turns は --help に出ないが実在する
description: claude バイナリは --max-turns <turns> を受け付ける。停止条件は turn + budget + wall-clock の 3 段。
resource: runner.py
timestamp: 2026-06-23T07:19:07Z
tags: [headless, claude-cli, stop-condition]
---

`claude --help` に出ないが、バイナリは `--max-turns <turns>` を受け付ける(実在）。

停止条件は 3 段で持つ:
1. **turn 上限**(`--max-turns`)= 暴走ループの一次ガード。
2. **予算**(`--max-budget-usd`)。ただし 2026/6/15 以降この支出は対話枠でなく Agent SDK クレジットから引かれるため、サブスク型ランナーのセッション枯渇は budget では守れない。
3. **wall-clock**(`threading.Timer`)。

→ turn + wall-clock の併用に意味がある(budget だけに頼らない)。

関連: [global settings の allow が勝つ](/traps/global-settings-allow-wins.md)
