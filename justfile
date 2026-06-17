# Loop Engineering 計測配管の薄いラッパ。実体は runner.py / tui.py / stats.py。
# 種類A(メカニクス)は全自動。種類B(判断)は just review / just tui から nvim に着地して人間が書く。

# 次の todo を 1 件 headless 実行 → 検証 → コミット → MD 生成 → SQLite upsert(全自動)
run:
    uv run runner.py run

# 次の未レビュー run を nvim で開く → 保存で reviewed 化・コミット・upsert(自動)
review:
    uv run runner.py review

# バックエンド(FastAPI: /api + /legacy)のみ起動。:8765
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

# 読み取り専用 TUI(別ビュー / 残置)。判断は nvim 着地で書く
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
