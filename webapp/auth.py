"""認証・到達制御ミドルウェア(§7)。判断・要約・推奨・自動入力は一切しない。

脅威モデル(§7.1): /api/dispatch・/api/tasks/{id}/run・/api/tasks/generate は
claude -p(Bash 許可)を subprocess 起動する = 副作用クラス W のうち「実質 RCE」。
これらへの到達 = サーバ上での任意コード実行。localhost 固定は安全装置であってバグでない。

多層防御(本ファイルで実装):
  1. エンドポイント分類 R(参照)/ W(副作用: write/execute)を path で機械判定(§7.2)。
  2. 名前付き複数 Bearer トークン + scope(read/write/execute)。auth.toml or env。
     平文は保存せず sha256(salt) ハッシュ + 定数時間比較(§7.4)。
  3. クラス W は Origin/Referer チェック + カスタム CSRF ヘッダ必須(§7.5)。
  4. SSE は EventSource がヘッダを付けられないため短命 signed query token(HMAC+expiry)を
     発行/検証(§7.6a)。発行口は /api/auth/sse-token(read 必須)。
  5. 副作用クラス W を logs/audit.jsonl に追記専用で監査記録(誰が何を起動したか。§7.7)。

互換: トークン未設定 + loopback(127.0.0.1/::1/testclient)は P0 と同じ no-op 素通し。
これにより既存テスト・ローカル既定挙動を一切変えない(§7.11-1: デフォルトは現状維持)。
非 localhost への到達は、有効トークンが1つも無ければ fail-closed で 401。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runner  # noqa: E402

# loopback とみなす host(P0 の境界)。"testclient" は Starlette TestClient の固定 host
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}

# 副作用クラス W のうち実行起動系(x-loop-exec = RCE 露出点)。scope=execute を要求
_EXEC_PATTERNS = (
    re.compile(r"^/api/dispatch/?$"),
    re.compile(r"^/api/tasks/[^/]+/run/?$"),
    re.compile(r"^/api/tasks/generate/?$"),
    re.compile(r"^/api/runs/[^/]+/continue/?$"),
)
# 契約データ改変系(write/delete/judgment)。scope=write を要求
_WRITE_PATTERNS = (
    (re.compile(r"^/api/tasks/?$"), {"POST"}),
    (re.compile(r"^/api/tasks/[^/]+/?$"), {"PUT", "DELETE"}),
    (re.compile(r"^/api/runs/[^/]+/judgment/?$"), {"POST"}),
)
# SSE(EventSource)経路。Authorization を付けられないため query signed token で認可
_SSE_PATTERNS = (
    re.compile(r"^/api/stream/"),
    re.compile(r"^/api/runs/[^/]+/stream/?$"),
    re.compile(r"^/api/runs/[^/]+/live/?$"),
    re.compile(r"^/api/gen/[^/]+/stream/?$"),
)

# 監視だけのモバイル運用(§7.6a)で値を合成しない: SSE token の既定寿命
_SSE_TOKEN_TTL_SEC = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class _Token:
    __slots__ = ("name", "scope", "hash")

    def __init__(self, name: str, scope: list[str], digest: str) -> None:
        self.name = name
        self.scope = scope
        self.hash = digest


class AuthConfig:
    """auth.toml / 環境変数から認証設定を組む。判断は一切しない純データ。

    優先順: 環境変数 LOOP_AUTH_TOKENS(name:scope:plain 形)> auth.toml。
    平文トークンは即 sha256 ハッシュへ畳み、メモリにも平文を残さない。
    HMAC 署名鍵(SSE token 用)は LOOP_AUTH_SECRET / auth.toml [auth] secret。
    """

    def __init__(self) -> None:
        self.tokens: list[_Token] = []
        self.read_scope: str = "localhost"  # localhost | always | never
        self.allowed_origins: list[str] = []
        self.secret: bytes = b""
        self._load()

    @staticmethod
    def _hash_plain(plain: str, salt: str) -> str:
        h = hashlib.sha256((salt + plain).encode("utf-8")).hexdigest()
        return f"sha256:{h}:salt={salt}"

    def _load(self) -> None:
        cfg: dict[str, Any] = {}
        path = runner.ROOT / "auth.toml"
        if path.exists():
            try:
                with path.open("rb") as f:
                    cfg = tomllib.load(f).get("auth", {}) or {}
            except (tomllib.TOMLDecodeError, OSError):
                cfg = {}
        self.read_scope = str(cfg.get("read_scope", "localhost"))
        self.allowed_origins = [str(o) for o in (cfg.get("allowed_origins") or [])]
        self.secret = (os.environ.get("LOOP_AUTH_SECRET") or str(cfg.get("secret", ""))).encode("utf-8")

        for t in cfg.get("tokens") or []:
            name = str(t.get("name", "")).strip()
            scope = [str(s) for s in (t.get("scope") or [])]
            digest = str(t.get("hash", "")).strip()
            if name and digest:
                self.tokens.append(_Token(name, scope, digest))

        # 環境変数 LOOP_AUTH_TOKENS="name:read,write,execute:PLAIN; name2:read:PLAIN2"
        env = os.environ.get("LOOP_AUTH_TOKENS", "")
        for ent in env.split(";"):
            ent = ent.strip()
            if not ent:
                continue
            parts = ent.split(":")
            if len(parts) < 3:
                continue
            name, scope_s, plain = parts[0].strip(), parts[1].strip(), ":".join(parts[2:]).strip()
            scope = [s.strip() for s in scope_s.split(",") if s.strip()]
            if name and plain:
                self.tokens.append(_Token(name, scope, self._hash_plain(plain, name)))

        # SSE signed token 用の鍵が無いときは、トークンのハッシュ群から導出(再起動毎に安定)
        if not self.secret and self.tokens:
            print("  ! 警告: LOOP_AUTH_SECRET 未設定。SSE 署名鍵をトークンから導出します"
                  "(トークン差し替えで既発行 SSE token が失効)。本番は secret を明示してください。",
                  file=sys.stderr)
            self.secret = hashlib.sha256("|".join(t.hash for t in self.tokens).encode()).digest()

    def has_tokens(self) -> bool:
        return bool(self.tokens)

    def verify_bearer(self, plain: str) -> _Token | None:
        """平文トークン → 一致する _Token。定数時間比較。失敗は None。"""
        for t in self.tokens:
            candidate = self._candidate_hash(plain, t.hash)
            if candidate is not None and hmac.compare_digest(candidate, t.hash):
                return t
        return None

    @staticmethod
    def _candidate_hash(plain: str, stored: str) -> str | None:
        # stored = "sha256:<hex>:salt=<salt>"。salt を取り出して同形ハッシュを作る
        m = re.match(r"^sha256:[0-9a-f]+:salt=(.+)$", stored)
        if not m:
            return None
        salt = m.group(1)
        h = hashlib.sha256((salt + plain).encode("utf-8")).hexdigest()
        return f"sha256:{h}:salt={salt}"


_CONFIG: AuthConfig | None = None


def auth_config() -> AuthConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = AuthConfig()
    return _CONFIG


def reset_config() -> None:
    """テスト用: env / auth.toml を読み直す。"""
    global _CONFIG
    _CONFIG = None


# --- SSE 短命 signed query token(HMAC + expiry。§7.6a) ---

def issue_sse_token(actor: str, ttl: int = _SSE_TOKEN_TTL_SEC) -> str:
    """`<actor>.<exp>.<hmac>` 形の短命トークン。read 主体のみが発行できる前提。"""
    cfg = auth_config()
    exp = int(time.time()) + ttl
    payload = f"{actor}.{exp}"
    sig = hmac.new(cfg.secret or b"loop-local", payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def verify_sse_token(token: str) -> str | None:
    """SSE token を検証して actor を返す。期限切れ/改竄は None。"""
    cfg = auth_config()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    actor, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    payload = f"{actor}.{exp_s}"
    expect = hmac.new(cfg.secret or b"loop-local", payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        return None
    return actor


# --- 監査ログ(§7.7。data/ ではなく engine 側 logs/audit.jsonl) ---

def _audit(record: dict[str, Any]) -> None:
    try:
        logs = runner.ROOT / "logs"
        logs.mkdir(exist_ok=True)
        with (logs / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 監査失敗で本処理を止めない(ベストエフォート追記)


def _classify(path: str, method: str) -> tuple[str, str] | None:
    """(class, scope) を返す。R は None(scope=read だが明示は不要)。W のみ判定。"""
    for pat in _EXEC_PATTERNS:
        if pat.match(path) and method != "GET":
            return ("W", "execute")
    for pat, methods in _WRITE_PATTERNS:
        if pat.match(path) and method in methods:
            return ("W", "write")
    return None


def _is_sse(path: str) -> bool:
    return any(p.match(path) for p in _SSE_PATTERNS)


def _extract_bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return None


def _origin_allowed(request: Request, cfg: AuthConfig) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        # Origin 欠落(非ブラウザ/同一オリジン)はトークン認可済みなら許容しログに残す(§7.5-1)
        return True
    return origin in cfg.allowed_origins


def _read_allowed_without_token(request: Request, cfg: AuthConfig) -> bool:
    if cfg.read_scope == "never":
        return False
    if cfg.read_scope == "always":
        return False
    # "localhost": loopback のみトークン不要
    client = request.client
    host = client.host if client else None
    return host in _LOOPBACK


def _is_loopback(request: Request) -> bool:
    client = request.client
    host = client.host if client else None
    return host in _LOOPBACK


class AuthMiddleware(BaseHTTPMiddleware):
    """到達制御の単一ゲート(§7)。判断・要約・推奨・自動入力は一切しない。

    実装上の方針: route ファイルに Depends を散らさず、ここで横断的に分類・認可・監査する
    (§7.7「ミドルウェアで横断的に差す」)。/api/me と /api/auth/sse-token はここで応答する。
    """

    async def dispatch(self, request: Request, call_next):
        cfg = auth_config()
        path = request.url.path
        method = request.method

        # ヘルパ口(認証メタ)はここで完結。route ファイルを増やさず main.py も触らない
        if path.rstrip("/") == "/api/me":
            return self._handle_me(request, cfg)
        if path.rstrip("/") == "/api/auth/sse-token" and method == "POST":
            return self._handle_sse_token(request, cfg)

        # fail-closed: 非 localhost からの到達は、有効トークンが1つも無ければ全面 401
        if not _is_loopback(request) and not cfg.has_tokens():
            return JSONResponse(
                {"error": "forbidden", "detail": "非localhost到達には auth.toml のトークンが必須(fail-closed)"},
                status_code=403)

        # SSE は EventSource がヘッダを付けられない → query signed token で認可(§7.6a)
        if _is_sse(path) and not self._sse_authorized(request, cfg):
            return JSONResponse({"error": "unauthorized", "detail": "SSE token 不正/期限切れ"}, status_code=401)

        wcls = _classify(path, method)
        actor = self._authenticate(request, cfg)

        if wcls is not None:
            _, needed = wcls
            denied = self._authorize_write(request, cfg, actor, needed)
            if denied is not None:
                _audit({
                    "ts": _now_iso(), "actor": actor or "anonymous",
                    "remote": (request.client.host if request.client else None),
                    "method": method, "path": path, "scope_required": needed,
                    "result": str(denied.status_code),
                    "origin": request.headers.get("origin"),
                })
                return denied

        # 参照(クラス R)の認可: read_scope に従い、非 localhost はトークン要求しうる
        if wcls is None and not _is_sse(path) and path.startswith("/api/"):
            if not _read_allowed_without_token(request, cfg):
                if actor is None:
                    return JSONResponse({"error": "unauthorized", "detail": "read scope のトークンが必要"},
                                        status_code=401)

        response = await call_next(request)

        if wcls is not None:
            _audit({
                "ts": _now_iso(), "actor": actor or "anonymous-local",
                "remote": (request.client.host if request.client else None),
                "method": method, "path": path, "scope_required": wcls[1],
                "result": str(response.status_code),
                "origin": request.headers.get("origin"),
            })
        return response

    # --- 認証/認可の部品 ---

    def _authenticate(self, request: Request, cfg: AuthConfig) -> str | None:
        """Bearer トークンを検証して actor 名。トークン未設定 + loopback は anonymous-local。"""
        plain = _extract_bearer(request)
        if plain:
            tok = cfg.verify_bearer(plain)
            return tok.name if tok else None
        if not cfg.has_tokens() and _is_loopback(request):
            return "anonymous-local"  # P0 互換: ローカル既定は素通し
        return None

    def _scope_of(self, request: Request, cfg: AuthConfig, actor: str | None) -> set[str]:
        if actor == "anonymous-local":
            return {"read", "write", "execute"}  # ローカル既定は全権(従来挙動)
        plain = _extract_bearer(request)
        if plain:
            tok = cfg.verify_bearer(plain)
            if tok:
                return set(tok.scope)
        return set()

    def _authorize_write(self, request: Request, cfg: AuthConfig,
                         actor: str | None, needed: str) -> Response | None:
        """クラス W の認可。失敗時に返すべき Response、成功なら None。"""
        # ローカル + トークン未設定は従来の no-op 素通し(テスト・既定挙動を保つ)
        if actor == "anonymous-local":
            return None
        if actor is None:
            return JSONResponse({"error": "unauthorized", "detail": "トークンが必要です"}, status_code=401)
        if needed not in self._scope_of(request, cfg, actor):
            return JSONResponse({"error": "forbidden", "detail": f"scope '{needed}' が必要"}, status_code=403)
        # CSRF/Origin(§7.5): 認証済みリモート主体にのみ課す
        if not _origin_allowed(request, cfg):
            return JSONResponse({"error": "forbidden", "detail": "Origin 不許可"}, status_code=403)
        if request.headers.get("x-loop-csrf") != "1":
            return JSONResponse({"error": "forbidden", "detail": "X-Loop-CSRF ヘッダ必須"}, status_code=403)
        return None

    def _sse_authorized(self, request: Request, cfg: AuthConfig) -> bool:
        # ローカル + トークン未設定は素通し(従来挙動)
        if not cfg.has_tokens() and _is_loopback(request):
            return True
        token = request.query_params.get("token")
        if token and verify_sse_token(token) is not None:
            return True
        # Bearer 直叩き(curl 等)も read 以上なら許可
        actor = self._authenticate(request, cfg)
        return actor is not None and "read" in self._scope_of(request, cfg, actor)

    # --- ヘルパ口(route を増やさずミドルウェアで応答) ---

    def _handle_me(self, request: Request, cfg: AuthConfig) -> Response:
        """フロントが scope を取得しボタン表示を出し分ける(最終ガードは常にサーバ)。§7.6。"""
        if not _is_loopback(request) and not cfg.has_tokens():
            return JSONResponse({"error": "forbidden"}, status_code=403)
        actor = self._authenticate(request, cfg)
        scope = sorted(self._scope_of(request, cfg, actor)) if actor else []
        return JSONResponse({
            "actor": actor,
            "scope": scope,
            "authenticated": actor is not None,
            "auth_required": cfg.has_tokens(),
        })

    def _handle_sse_token(self, request: Request, cfg: AuthConfig) -> Response:
        """SSE 用の短命 signed query token を発行。read 主体のみ(§7.6a)。"""
        if not _is_loopback(request) and not cfg.has_tokens():
            return JSONResponse({"error": "forbidden"}, status_code=403)
        actor = self._authenticate(request, cfg)
        if actor is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if "read" not in self._scope_of(request, cfg, actor):
            return JSONResponse({"error": "forbidden", "detail": "read scope が必要"}, status_code=403)
        # token 発行も状態を作る POST。リモート主体には write 系と同じ Origin 制約を課す(CSRF 対称性)
        if not _is_loopback(request) and not _origin_allowed(request, cfg):
            return JSONResponse({"error": "forbidden", "detail": "Origin 不許可"}, status_code=403)
        token = issue_sse_token(actor)
        return JSONResponse({"token": token, "expires_in": _SSE_TOKEN_TTL_SEC})
