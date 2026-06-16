"""api_router: 各 module の `router` を自動収集して /api 配下にまとめる。

新エンドポイント追加で main.py を触らせない設計。webapp/api/ に *.py を足し
module-level の `router`(APIRouter)を定義すれば自動で /api 配下に載る。
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter

api_router = APIRouter(prefix="/api")

for _mod in pkgutil.iter_modules(__path__):
    if _mod.name.startswith("_"):
        continue
    _m = importlib.import_module(f"{__name__}.{_mod.name}")
    _r = getattr(_m, "router", None)
    if isinstance(_r, APIRouter):
        api_router.include_router(_r)
