"""実行起動系(claude -p を subprocess.Popen)。§2.1 #15-17。x-loop-exec: RCE 露出点。

これらは localhost 固定の安全装置を外さない(認証層は WS6)。runner の .run.lock
直列化を尊重し、busy は 409 で素直に返す(API 側に lock を持ち込まない)。
"""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from .. import schemas, util
from ..util import runner
from ._deps import err, valid_task_id

router = APIRouter(tags=["dispatch"])

_EXEC = {"x-loop-exec": True, "x-loop-kind": "A"}


def _busy() -> bool:
    return (runner.DATA / ".run.lock").exists()


@router.post("/tasks/{task_id}/run", status_code=202,
             response_model=schemas.RunStartResult, openapi_extra=_EXEC)
def run_task(task_id: str = Depends(valid_task_id)):
    if not (runner.TASKS_DIR / f"{task_id}.md").exists():
        raise HTTPException(404, err("not_found", f"no such task: {task_id}"))
    if _busy():
        return JSONResponse(schemas.RunStartResult(accepted=False, reason="busy").model_dump(),
                            status_code=409)
    subprocess.Popen(["uv", "run", "runner.py", "run", task_id], cwd=str(util.ROOT))
    return schemas.RunStartResult(accepted=True)


@router.post("/tasks/generate", status_code=202, openapi_extra=_EXEC)
def generate_task(inp: schemas.GenerateInput):
    if not inp.prompt.strip():
        raise HTTPException(400, err("bad_input", "prompt は必須です"))
    args = ["uv", "run", "runner.py", "gen", inp.prompt.strip()]
    if inp.repo.strip():
        args += ["--repo", inp.repo.strip()]
    if inp.base_branch.strip():
        args += ["--base-branch", inp.base_branch.strip()]
    if inp.auto_run:
        args.append("--run")
    # 生成中ロックを即時に立てる(背景プロセスが lock を作るまでの race を避ける)。cmd_gen が完了で外す。
    runner.DATA.mkdir(parents=True, exist_ok=True)
    (runner.DATA / ".gen.lock").write_text(inp.prompt.strip()[:300], encoding="utf-8")
    subprocess.Popen(args, cwd=str(util.ROOT))
    return {"accepted": True}


@router.post("/dispatch", status_code=202,
             response_model=schemas.RunStartResult, openapi_extra=_EXEC)
def dispatch():
    if _busy():
        return JSONResponse(schemas.RunStartResult(accepted=False, reason="busy").model_dump(),
                            status_code=409)
    subprocess.Popen(["uv", "run", "runner.py", "run"], cwd=str(util.ROOT))
    return schemas.RunStartResult(accepted=True)
