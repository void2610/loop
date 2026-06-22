---
type: System
title: webapp + web — FastAPI /api と Next.js フロント
description: FastAPI は /api(JSON+SSE)のみ供給、Next.js(web/)が唯一の UI。Fleet で複数 PC を 1 GUI に merge。GUI は判断を生成しない。
resource: webapp/main.py
timestamp: 2026-06-23T07:19:07Z
tags: [fastapi, nextjs, sse, fleet, ui]
---

`webapp/`(FastAPI)+ `web/`(Next.js App Router + TS + Tailwind + shadcn/ui)。

- FastAPI は `/api/*`(JSON + SSE)のみ。Next が `next.config.ts` の rewrite で `/api/*` を `:8765` の uvicorn へプロキシ(単一オリジン)。legacy Jinja は撤去済み。
- **GUI は事実表示のみ・判断を生成しない**([絶対原則](/design/invariants.md))。`## 判断` / judgment フォームは常に空で出す。
- **Fleet**: 複数 PC を 1 GUI に merge。各 peer の `/api` を server-side で並列 fetch し host バッジ付き merge view。SSE は peer の backend(`:8765`)をブラウザから直接購読(peer プロキシは buffer して即時 flush されないため)。
- 本番起動は standalone(`node .next/standalone/server.js`)。起動は唯一 `just app`([起動の罠](/traps/just-app-tailscale-path.md) / [lsof の罠](/traps/lsof-multi-port.md) / [proxy_headers と 403](/traps/proxy-headers-auth-403.md))。

関連: [runner](/systems/runner.md) / [loopdb](/systems/loopdb.md)
