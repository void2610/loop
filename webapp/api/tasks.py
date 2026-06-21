"""TODO(目標契約)の CRUD。§2.1 #9-14。

書き込みは runner.write_task + runner.auto_commit を素通すだけ(file-based contract が正本)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .. import schemas, util
from ..util import runner
from ._deps import err, valid_task_id

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=schemas.TaskListResponse)
def list_tasks(include_archived: bool = False):
    last = {k: schemas.LastRun(**v) for k, v in util.latest_runs().items()}
    tasks = []
    for t in runner.parse_tasks():
        archived = str(t.get("archived", "false")).lower() in ("true", "1")
        if archived and not include_archived:
            continue
        tid = t.get("id")
        tasks.append(schemas.TaskRow(
            id=tid, goal=t.get("goal"), status=t.get("status", "todo"),
            repo=t.get("repo"), archived=archived, last_run=last.get(tid)))
    return schemas.TaskListResponse(
        tasks=tasks, last=last,
        running=(runner.DATA / ".run.lock").exists(),
        generating=(runner.DATA / ".gen.lock").exists())


@router.get("/repos", response_model=schemas.ReposResponse)
def list_repos():
    return schemas.ReposResponse(repos=util.known_repos())


@router.get("/repos/branches", response_model=schemas.BranchesResponse)
def list_branches(repo: str = ""):
    return schemas.BranchesResponse(
        branches=util.repo_branches(repo),
        default=util.repo_default_branch(repo),
    )


@router.get("/tasks/{task_id}", response_model=schemas.TaskDetail)
def task_detail(task_id: str = Depends(valid_task_id)):
    res = runner.read_task(task_id)
    if res is None:
        raise HTTPException(404, err("not_found", f"task not found: {task_id}"))
    fm, body = res
    fields = util.fields_from_fm(task_id, fm, body)
    return schemas.TaskDetail(fields=schemas.TaskFields(**fields), body=body)


@router.post("/tasks", status_code=201, response_model=schemas.TaskIdResult,
             openapi_extra={"x-loop-kind": "A"})
def create_task(inp: schemas.TaskInput):
    tid = util.safe_id(inp.task_id or "")
    if not tid:
        raise HTTPException(400, err("bad_id", "不正な id です(英数字と . _ - のみ、先頭は英数字)。"))
    if (runner.TASKS_DIR / f"{tid}.md").exists():
        raise HTTPException(409, err("exists", f"既に存在します: {tid}"))
    fm = util.fm_from_form(tid, inp.goal, inp.repo, inp.accept, inp.verify,
                           inp.constraints, inp.allowed_tools, inp.max_attempts, inp.status,
                           inp.base_branch, inp.no_pr)
    p = runner.write_task(tid, fm, inp.body)
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} を新規作成")
    return schemas.TaskIdResult(task_id=tid)


@router.put("/tasks/{task_id}", response_model=schemas.TaskIdResult,
            openapi_extra={"x-loop-kind": "A"})
def update_task(inp: schemas.TaskInput, task_id: str = Depends(valid_task_id)):
    fm = util.fm_from_form(task_id, inp.goal, inp.repo, inp.accept, inp.verify,
                           inp.constraints, inp.allowed_tools, inp.max_attempts, inp.status,
                           inp.base_branch, inp.no_pr)
    p = runner.write_task(task_id, fm, inp.body)
    runner.auto_commit(runner.DATA, [p], f"todo: {task_id} を編集")
    return schemas.TaskIdResult(task_id=task_id)


@router.post("/tasks/{task_id}/archive", status_code=204, openapi_extra={"x-loop-kind": "A"})
def archive_task(inp: schemas.ArchiveInput, task_id: str = Depends(valid_task_id)):
    # 削除しない。UI から隠すための archived フラグを立てる/外すだけ(ログは資産)。
    if not runner.set_task_archived(task_id, inp.archived):
        raise HTTPException(404, err("not_found", f"task not found: {task_id}"))
    return Response(status_code=204)
