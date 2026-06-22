---
type: System
title: loopdb — SQLite インデックス層(派生・再生成可能)
description: MD 契約ファイルから派生する SQLite インデックス。just reindex で完全再生成でき、rm loop.db && reindex で壊れない(不変条件)。
resource: loopdb.py
timestamp: 2026-06-23T07:19:07Z
tags: [sqlite, derived, reindex]
---

`loopdb.py` = SQLite インデックス層。**MD 派生**であり一次データではない([ファイルが真実](/design/invariants.md))。

- `just reindex` で MD 契約ファイルから完全再生成できる。`rm loop.db && reindex` で壊れないことが不変条件。
- DuckDB(`stats.py` + `queries/`)は分析レンズ。これも派生。
- 知識バンドルに索引が要る場合も同じ原則: ファイルが真実、索引は再生成可能な派生として後付けする。

関連: [runner](/systems/runner.md) / [webapp](/systems/webapp.md)
