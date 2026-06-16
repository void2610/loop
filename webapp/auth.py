"""認証土台。P0 は 127.0.0.1 のみ通す no-op ミドルウェア(§8.1.5 / §1.1 公開境界)。

実体(トークン/セッション/mTLS)は WS6(§6)で本書のインターフェースを差し替える。
P0〜P3 は localhost 固定の安全装置を保持。dispatch/run/generate は RCE 露出点。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# loopback のみ許可(P0 の境界)。実体認証は WS6 でここを拡張する
# "testclient" は Starlette TestClient の固定 host(テスト経路のみ)
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


class AuthMiddleware(BaseHTTPMiddleware):
    """P0: client.host が loopback なら素通し、それ以外は 403。判断・要約は一切しない。"""

    async def dispatch(self, request: Request, call_next):
        client = request.client
        host = client.host if client else None
        if host not in _LOOPBACK:
            return JSONResponse({"error": "forbidden", "detail": "P0: localhost only"}, status_code=403)
        return await call_next(request)
