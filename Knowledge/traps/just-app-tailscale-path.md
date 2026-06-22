---
type: Trap
title: just app の tailscale 経路・PATH・亡霊 bash
description: Claude Code から just app を起動する際の罠。tailscale が PATH 外で command not found、detach 不足で serve 設定が消える、trap 再帰で亡霊 bash が serve off を連打する。
resource: justfile
timestamp: 2026-06-23T07:19:07Z
tags: [macos, tailscale, just-app, background, PATH]
---

`just app` は唯一の公式起動口(フロント build → backend :8765 + frontend :3000 + tailscaled 前段)。
Claude Code から起動するときに踏む罠:

# (1) tailscale が PATH 外(command not found / exit 127)

tailscale CLI は macOS App 内 `/Applications/Tailscale.app/Contents/MacOS/Tailscale`(先頭大文字)にあり、
Bash tool / `start_new_session=True` の Popen の PATH には入っていない。対話 shell では解決できるが Claude Code 起動環境では解決できない。

回避(macOS は case-insensitive FS なので `tailscale` で `Tailscale` バイナリに解決される):

```python
import subprocess, os
env = dict(os.environ)
env['PATH'] = '/Applications/Tailscale.app/Contents/MacOS:' + env.get('PATH','')
subprocess.Popen(['just','app'], cwd='/Users/shuya/Documents/GitHub/loop',
                 stdout=open('/tmp/just-app.log','w'), stderr=subprocess.STDOUT,
                 start_new_session=True, env=env)
```

# (2) detach 不足で serve 設定が消える / 亡霊 bash

Bash tool の `run_in_background` / `nohup ... &` だけだと harness の process group 終了で子が SIGHUP され、
recipe の EXIT trap が `tailscale serve off` を踏んで serve 設定が消える。さらに `trap ... INT TERM` 内の `kill 0` が
自分に SIGTERM を返して trap が再帰し、「`tailscale serve --http=3000 off` を連打する亡霊 bash」になる。

回避:
- Python の `subprocess.Popen(..., start_new_session=True)` で本当に新 session へ detach。
- recipe 側 cleanup は `trap - INT TERM EXIT` で自分の trap を外してから kill(justfile の `app` で対応済)。
- 亡霊が残ったら `pkill -9 -f 'tailscale serve --http=3000 off'`。

# (3) macOS Application Firewall / proxy_headers

未署名 node への外部着信は firewall が block するので**着信を署名済み tailscaled に受けさせる**(`tailscale serve`)。
serve 経由で `/api` だけ 403 なら [proxy_headers の罠](/traps/proxy-headers-auth-403.md)。

関連: [lsof 複数ポートの罠](/traps/lsof-multi-port.md)
