---
type: Trap
title: proxy_headers と /api 403(serve 経由で auth が非 localhost 誤判定)
description: uvicorn の proxy_headers は既定有効で X-Forwarded-For を信用し request.client.host を上書きする。auth.py が非 localhost と誤判定し read も 403。webapp/main.py は proxy_headers=False を明示する。
resource: webapp/main.py
timestamp: 2026-06-23T07:19:07Z
tags: [uvicorn, auth, tailscale, proxy_headers]
---

`uvicorn` の `proxy_headers` は**既定で有効**で、Next rewrite / tailscaled が付けた `X-Forwarded-For`
(元クライアント = Tailscale IP)を信用し `request.client.host` を上書きする → `auth.py` が「非 localhost」と誤判定し
read も **403**。

**`webapp/main.py` は `proxy_headers=False` を明示**する(auth.py 自身「X-Forwarded-For は信用しない」前提と一致)。
serve 経由で `/knowledge` は 200 だが `/api/*` だけ 403 ならこれ。

関連: [just app の tailscale 経路](/traps/just-app-tailscale-path.md)
