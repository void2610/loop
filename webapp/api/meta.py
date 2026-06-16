"""メタ情報(repos / statuses / judgment_fields)。loop.toml→API の一本道。§1.6。

フロントにラベルや status 許可集合をハードコードさせない。設定の単一ソースは Python。
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import schemas, util
from ..util import runner

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=schemas.MetaResponse)
def meta():
    return schemas.MetaResponse(
        repos=util.known_repos(), statuses=util.STATUSES,
        judgment_fields=[list(f) for f in runner.JUDGMENT_FIELDS])
