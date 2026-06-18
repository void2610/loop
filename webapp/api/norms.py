"""規範記憶(知識更新エージェント)の閲覧 + 昇格/却下の中継。§2.6。

read 系: 現在の知識(conventions.md 生テキスト)/ 候補(candidates.md)/ 起草エージェントの動作履歴(norms.json)。
書き込み: promote / reject は人間=種類B の操作を runner へ素通すだけ。GUI は判断を生成・要約・推奨しない。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .. import schemas, util
from ..util import runner
from ._deps import err

router = APIRouter(tags=["norms"])


def valid_candidate_id(candidate_id: str) -> str:
    """candidate-<run_id>-<n> 形式のみ通す(パストラバーサル防御。整形ではなく拒否。§2.4)。"""
    cid = candidate_id.strip()
    if not cid.startswith("candidate-") or "/" in cid or ".." in cid:
        raise HTTPException(400, err("bad_id", "不正な candidate_id"))
    return cid


@router.get("/norms", response_model=schemas.NormsResponse)
def list_norms():
    view = util.norms_view()
    return schemas.NormsResponse(
        repos=[schemas.NormRepo(**r) for r in view["repos"]],
        activity=[schemas.NormActivity(**a) for a in util.norms_activity()],
        generated_at=datetime.now().isoformat(timespec="seconds"))


@router.post("/norms/{candidate_id}/promote", status_code=204,
             openapi_extra={"x-loop-kind": "A(中継)"})
def promote_norm(candidate_id: str = Depends(valid_candidate_id)):
    # 昇格判断は人間(種類B)。ここは候補の proposed_norm を conventions.md へ着地させる中継のみ。
    if runner.promote_candidate(candidate_id) is None:
        raise HTTPException(404, err("not_found", f"候補が見つかりません: {candidate_id}"))
    return Response(status_code=204)


@router.post("/norms/{candidate_id}/reject", status_code=204,
             openapi_extra={"x-loop-kind": "A(中継)"})
def reject_norm(candidate_id: str = Depends(valid_candidate_id)):
    if not runner.reject_candidate(candidate_id):
        raise HTTPException(404, err("not_found", f"候補が見つかりません: {candidate_id}"))
    return Response(status_code=204)
