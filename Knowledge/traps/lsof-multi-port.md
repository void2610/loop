---
type: Trap
title: lsof の複数ポート指定は各ポートに -i が要る
description: lsof -ti tcp:3000 tcp:8765 は 2 つ目が裸の引数(ファイル名)扱いで PID を一切返さない。正しくは -ti tcp:3000 -i tcp:8765。
resource: justfile
timestamp: 2026-06-23T07:19:07Z
tags: [macos, ports, just-app, EADDRINUSE]
---

`lsof -ti tcp:3000 tcp:8765` は 2 つ目の `tcp:8765` が**裸の引数(ファイル名)扱い**になり
`status error ... No such file or directory` で **PID を一切返さず**、`xargs kill` が空振りする
(= 旧 node が一度も殺されず再起動が EADDRINUSE で死ぬ真因だった)。

正しくは `lsof -ti tcp:3000 -i tcp:8765`(各ポートに `-i`)。

付随する罠:
- `lsof` は片方のポートが空でもマッチ時に exit 1 を返す。`set -e` 下で `p="$(lsof ...)"` が recipe を即死させるので、ヘルパは `|| true` で exit 0 を保証し、ループ判定は exit code でなく**出力の有無**(`[ -n "$p" ]`)で行う。
- standalone Next の常駐 node は起動直後に cmdline を `next-server (vX)` へ改名するので `pkill -f 'standalone/server.js'` では掴めない。掃除は**ポート経由(lsof)を主**にする。

関連: [just app の tailscale 経路](/traps/just-app-tailscale-path.md)
