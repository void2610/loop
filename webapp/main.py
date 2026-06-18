# /// script
# requires-python = "==3.12.*"
# dependencies = ["fastapi", "uvicorn[standard]", "pyyaml"]
# ///
"""ASGI エントリ。app を組み立てるだけに痩せた層(§8.1.1)。

新エンドポイント追加で main.py を触らせない設計: webapp/api/ に router を足せば自動収集。
中心思想: GUI/API は判断を生成・要約・推奨・自動入力しない。書き込みは runner 経由で
data/ の MD と git にのみ着地。FastAPI は import runner / import loopdb を維持。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# uv run webapp/main.py(スクリプト実行)でも webapp パッケージを解決できるよう repo root を通す
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from webapp.api import api_router  # noqa: E402
from webapp.auth import AuthMiddleware  # noqa: E402

app = FastAPI(title="loop")
app.add_middleware(AuthMiddleware)  # P0: 127.0.0.1 のみ通す no-op(実体は WS6)

# SSE はブラウザ→FastAPI 直(クロスオリジン)。EventSource 接続のため CORS を許可する。
# JSON は Next の同一オリジン rewrite 経由なので CORS 不要。許可元は dev 既定 + env で上書き。
_origins_env = os.environ.get("LOOP_WEB_ORIGINS")
_allowed_origins = (
    [o.strip() for o in _origins_env.split(",") if o.strip()]
    if _origins_env
    else ["http://localhost:3000", "http://127.0.0.1:3000"]
)
app.add_middleware(  # CORS を最外層に(SSE のプリフライト/レスポンスヘッダ付与)
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(api_router)  # /api/* = JSON + SSE 面(唯一の UI 供給は Next:web/)


@app.get("/", include_in_schema=False)
def root():
    # UI は Next(:3000)。バックエンド直叩きのルートはフロントへ寄せる。
    return RedirectResponse(_allowed_origins[0], status_code=307)


if __name__ == "__main__":
    import uvicorn
    # proxy_headers=False: tailscaled / Next rewrite が付ける X-Forwarded-For を信用せず
    # request.client.host を素のソケットアドレス(常に 127.0.0.1)のままにする。
    # これを外すと Tailnet 経由の /api/* が auth.py で「非 localhost」と誤判定され 403(§4)。
    uvicorn.run(app, host="127.0.0.1", port=8765, proxy_headers=False)
