---
type: Trap
title: --json-schema の出力は result.structured_output に入る
description: 構造化出力は result["structured_output"] にあり、json.loads(result["result"]) ではない。result 本文は散文。
resource: runner.py
timestamp: 2026-06-23T07:19:07Z
tags: [headless, claude-cli, json-schema]
---

`--json-schema` を渡したときの構造化出力は **`result.structured_output`** に入る。
`json.loads(result["result"])` ではない(`result` 本文は散文)。

実行は `--input-format stream-json --output-format stream-json --verbose` の双方向(`RoleSession`)。
プロンプトは `-p <arg>` でなく **stdin に user メッセージ(`{"type":"user",...}`)を 1 行流す**。
`run_turn()` は次の `type=="result"` イベントまで読み(`structured_output` 等含む)、セッションは開いたまま次の `send()` を待てる。
