"""API 共通の依存(id 検証など)。整形ではなく拒否(§2.4)。"""

from __future__ import annotations

from fastapi import HTTPException

from .. import util


def err(code: str, msg: str) -> dict:
    return {"error": code, "detail": msg}


def valid_run_id(run_id: str) -> str:
    rid = util.safe_id(run_id)
    if rid is None:
        raise HTTPException(400, detail=err("bad_id", "不正な run_id"))
    return rid


def valid_task_id(task_id: str) -> str:
    tid = util.safe_id(task_id)
    if tid is None:
        raise HTTPException(400, detail=err("bad_id", "不正な task_id"))
    return tid
