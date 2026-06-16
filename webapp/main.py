# /// script
# requires-python = "==3.12.*"
# dependencies = ["fastapi", "uvicorn[standard]", "jinja2", "python-multipart", "pyyaml"]
# ///
"""ASGI エントリ。app を組み立てるだけに痩せた層(§8.1.1)。

新エンドポイント追加で main.py を触らせない設計: webapp/api/ に router を足せば自動収集。
中心思想: GUI/API は判断を生成・要約・推奨・自動入力しない。書き込みは runner 経由で
data/ の MD と git にのみ着地。FastAPI は import runner / import loopdb を維持。
"""

from __future__ import annotations

import sys
from pathlib import Path

# uv run webapp/main.py(スクリプト実行)でも webapp パッケージを解決できるよう repo root を通す
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from webapp import legacy  # noqa: E402
from webapp.api import api_router  # noqa: E402
from webapp.auth import AuthMiddleware  # noqa: E402

app = FastAPI(title="loop")
app.add_middleware(AuthMiddleware)  # P0: 127.0.0.1 のみ通す no-op(実体は WS6)
app.include_router(api_router)  # /api/* = 新 JSON + SSE 面
app.include_router(legacy.router)  # /legacy/* = 現 Jinja(退避・無改造)


@app.get("/", include_in_schema=False)
def root():
    # 旧トップは当面 legacy へ寄せる。P1 完了で Next へ向ける(§8.1.1)
    return RedirectResponse("/legacy/", status_code=307)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
