# Loop Engineering 計測配管の薄いラッパ。実体は runner.py / stats.py。
# 種類A(メカニクス)は全自動。種類B(判断)は Web(/runs/<id> 判断フォーム)で人間が書く。

# 次の todo を 1 件 headless 実行 → 検証 → コミット → MD 生成 → SQLite upsert(全自動)
run:
    uv run runner.py run

# バックエンドの契約テスト(API 契約 + loop.db 不変条件 + run ループ全経路)。リファクタの安全網。
test:
    uv run tests/test_api_contract.py
    uv run tests/test_loopdb.py
    uv run tests/test_verify_loop.py

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
    rm -rf .next/standalone/.next/static .next/standalone/public   # cp -r は標的既存だと static/static にネストする(非冪等)
    cp -r .next/static .next/standalone/.next/static
    [ -d public ] && cp -r public .next/standalone/public || true
    echo "frontend build 完了(.next/standalone)"

# Tailnet(VPN)経由でスマホ等から http://<host>.<tailnet>.ts.net:3000 でアクセスできるよう起動する。
# このリポジトリの**唯一の公式起動口**。手元 / 他デバイスのどちらからでも同じ手順で使える。
# 方式: frontend / backend とも 127.0.0.1 のまま、tailscaled を前段プロキシにする(`tailscale serve --http`)。
#   - macOS の Application Firewall は未署名の node への外部着信を block するが、着信を受けるのは
#     署名済み・許可済みの tailscaled なので回避できる(node 直バインドだと iPhone から届かない)。
#   - tailscaled→localhost→backend で接続元は常に 127.0.0.1。webapp は proxy_headers=False なので
#     X-Forwarded で汚染されず auth は loopback 素通し(§7 の Bearer は未設定でよい)。
#   - 経路の暗号化・デバイス認証は Tailscale(WireGuard)に委ねる。
# 安定性: ① 残存プロセスを pkill+lsof で掃除し **ポートが空くまで待つ**(kill 直後 bind の EADDRINUSE 回避)
#   ② tailscale serve は `--bg` で無音失敗しうるので **status で検証** ③ backend が **8765 を LISTEN するまで待って**
#   から node 起動(uvicorn 即死を検出)④ 終了時に serve を自動 off にし、設定漏れの中途半端な状態を残さない。
app: web-build
    #!/usr/bin/env bash
    set -euo pipefail
    # 残存 next-server / uvicorn が :3000/:8765 を握ると EADDRINUSE で起動失敗する。先に掃除する。
    # 罠: `lsof -ti tcp:3000 tcp:8765` は 2 つ目の tcp:8765 が裸の引数(ファイル名)扱いになり
    #     status error で **PID を一切返さない** → kill が空振りし旧 node が残る。各ポートに -i が要る。
    # lsof は片方のポートが空でも exit 1 を返す。set -e 下で死なないよう || true で 0 を保証する(出力は保持)。
    ports() { lsof -ti tcp:3000 -i tcp:8765 2>/dev/null || true; }
    pkill -9 -f 'webapp/main.py' 2>/dev/null || true   # uvicorn(まだ LISTEN 前で lsof に出ない個体の保険)
    # kill 直後に bind すると旧ソケットが残り EADDRINUSE で(特に背景の uvicorn が無音で)死ぬ。
    # ポートが実際に空くまで kill を繰り返す(exit code は当てにならないので出力の有無で判定)。
    for i in $(seq 1 50); do
        p="$(ports)"; [ -z "$p" ] && break
        echo "$p" | xargs kill -9 2>/dev/null || true
        sleep 0.2
    done
    if [ -n "$(ports)" ]; then
        echo "✗ :3000/:8765 がまだ使用中です。残存プロセスを手動で停止してください" >&2
        exit 1
    fi
    # tailscaled を前段に(ALF 回避)。--bg は非同期 + 冪等で、失敗しても script は止まらないため
    # 直後に `tailscale serve status` で設定反映を検証する(これが無いと「画面は出るが API が 403」になる)
    # :3000 は Next フロント、:8765 は backend(他 PC のブラウザから EventSource で SSE を直接購読)。
    tailscale serve --bg --http=3000 3000
    tailscale serve --bg --http=8765 8765
    if ! tailscale serve status 2>/dev/null | grep -q "proxy http://127.0.0.1:3000"; then
        echo "✗ tailscale serve(:3000)の設定が反映されていません。`tailscale serve status` を確認してください" >&2
        exit 1
    fi
    if ! tailscale serve status 2>/dev/null | grep -q "proxy http://127.0.0.1:8765"; then
        echo "✗ tailscale serve(:8765)の設定が反映されていません。`tailscale serve status` を確認してください" >&2
        exit 1
    fi
    FQDN=$(tailscale status --json | python3 -c "import sys,json;print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
    echo "起動: http://$FQDN:3000 (Tailnet 内のデバイスから)  /  backend 127.0.0.1:8765 (Tailnet: $FQDN:8765)  (Ctrl-C で停止)"
    # Ctrl-C / 異常終了で serve も off にする(永続設定の中途半端を残さない)。
    # 注意: kill 0 は同一プロセスグループ = 自分にも SIGTERM が届く。trap を解除してから kill しないと
    # 再帰呼び出しの無限ループに陥り、`tailscale serve off` を連打して新規 serve 設定を即削除する亡霊と化す(実地で踏んだ)
    cleanup() {
        trap - INT TERM EXIT
        tailscale serve --http=3000 off >/dev/null 2>&1 || true
        tailscale serve --http=8765 off >/dev/null 2>&1 || true
        kill 0 2>/dev/null || true
    }
    trap cleanup INT TERM EXIT
    uv run webapp/main.py &
    BACKEND_PID=$!
    # backend(uvicorn)が 8765 を LISTEN するまで待つ。先に node を出すと proxy が ECONNREFUSED を吐き、
    # uvicorn が EADDRINUSE 等で即死しても「画面は出るが API だけ死ぬ」状態に気づけない。
    for i in $(seq 1 50); do
        curl -fsS -o /dev/null http://127.0.0.1:8765/openapi.json 2>/dev/null && break
        kill -0 "$BACKEND_PID" 2>/dev/null || { echo "✗ backend(uvicorn)が起動に失敗しました(EADDRINUSE 等)" >&2; exit 1; }
        sleep 0.3
    done
    HOSTNAME=127.0.0.1 PORT=3000 node web/.next/standalone/server.js

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
