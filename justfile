# Loop Engineering 計測配管の薄いラッパ。実体は runner.py / tui.py / stats.py。
# 種類A(メカニクス)は全自動。種類B(判断)は Web(/runs/<id> 判断フォーム)で人間が書く。

# 次の todo を 1 件 headless 実行 → 検証 → コミット → MD 生成 → SQLite upsert(全自動)
run:
    uv run runner.py run

# バックエンド(FastAPI: /api + SSE)のみ起動。:8765
web:
    uv run webapp/main.py

# フロント(Next.js)を本番ビルド。standalone に static を同梱する
web-build:
    #!/usr/bin/env bash
    set -euo pipefail
    cd web
    pnpm install
    pnpm build
    cp -r .next/static .next/standalone/.next/static
    [ -d public ] && cp -r public .next/standalone/public || true
    echo "frontend build 完了(.next/standalone)"

# フロントをビルドし、backend(:8765)と frontend(:3000)を同時起動。Ctrl-C で両方停止
app: web-build
    #!/usr/bin/env bash
    set -euo pipefail
    echo "起動: backend http://127.0.0.1:8765  /  frontend http://127.0.0.1:3000  (Ctrl-C で停止)"
    trap 'kill 0' EXIT INT TERM
    uv run webapp/main.py &
    PORT=3000 node web/.next/standalone/server.js

# Tailnet(VPN)経由でスマホ等から http://<host>.<tailnet>.ts.net:3000 でアクセスできるよう起動する。
# frontend を Tailscale IP のみにバインド(LAN 物理 IP には出さない)、backend は 127.0.0.1 のまま=
# RCE 露出点(dispatch/run/generate)を Tailnet 内デバイスに限定し、接続元 127.0.0.1 で auth 素通しを維持する。
# 経路の暗号化・デバイス認証は Tailscale(WireGuard)に委ねる(§7 の Bearer トークンは未設定でよい)。
app-tailnet: web-build
    #!/usr/bin/env bash
    set -euo pipefail
    TSIP=$(tailscale ip -4 | head -1)
    FQDN=$(tailscale status --json | python3 -c "import sys,json;print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
    echo "起動: http://$FQDN:3000 (Tailnet 内のスマホ等から)  /  backend 127.0.0.1:8765  (Ctrl-C で停止)"
    trap 'kill 0' EXIT INT TERM
    uv run webapp/main.py &
    HOSTNAME=$TSIP PORT=3000 node web/.next/standalone/server.js

# 読み取り専用 TUI(別ビュー / 残置)。判断の入力は Web で行う
tui:
    uv run tui.py

# loop.db を破棄し runs/*.md から完全再生成(ビューは捨ててよい)
reindex:
    rm -f loop.db && uv run runner.py reindex

# DuckDB 分析(canned: queries/*.sql を全実行)。ad-hoc: just stats-sql "SELECT ..."
stats:
    uv run stats.py

stats-sql sql:
    uv run stats.py "{{sql}}"

# 直近 run の verdict / reviewed を羅列(集計はしない)
status:
    uv run runner.py status

# API 契約テスト(inline script deps で webapp を 3.12 ピン実行。隔離 git repo で副作用を閉じる)
test:
    uv run tests/test_api_contract.py

# 契約データの private repo を初期化(公開エンジンを clone した直後に1回)
init-data:
    mkdir -p data/runs data/plans
    test -d data/.git || git -C data init
    mkdir -p data/tasks
    test -f data/review-notes.md || printf '# review-notes — 種類B の R&D ログ\n' > data/review-notes.md
    @echo "data/ を private git repo として初期化しました。data/tasks/<id>.md にタスクを置きます。"

# WatchPaths(data/tasks/ 変更で run 起動)を導入 / 解除。example からローカルパスを埋めて生成
watch-install:
    sed -e "s|__LOOP_DIR__|$(pwd)|g" -e "s|__UV__|$(command -v uv)|g" \
        launchd/com.loop.watch.plist.example > launchd/com.loop.watch.plist
    cp launchd/com.loop.watch.plist ~/Library/LaunchAgents/com.loop.watch.plist
    launchctl unload ~/Library/LaunchAgents/com.loop.watch.plist 2>/dev/null || true
    launchctl load ~/Library/LaunchAgents/com.loop.watch.plist
    @echo "WatchPaths 有効化。data/tasks/ を変更すると runner が起動します。"

watch-uninstall:
    launchctl unload ~/Library/LaunchAgents/com.loop.watch.plist 2>/dev/null || true
    rm -f ~/Library/LaunchAgents/com.loop.watch.plist
    @echo "WatchPaths 解除。"
