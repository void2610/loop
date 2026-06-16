"""現行 Jinja UI(8ページ)を /legacy prefix へ退避(無改造で機能温存)。

§8.1.6: Jinja は P4 完了まで /legacy/* で温存。撤去はこのファイルと templates/ の削除のみ。
判断は人間入力を契約ファイルへ中継するだけ(GUI は生成・要約・推奨・自動入力しない)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import util
from .util import runner

router = APIRouter(prefix="/legacy")

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["repo_label"] = util.repo_label
# legacy テンプレ内のリンクを /legacy 配下へ寄せる
templates.env.globals["base"] = "/legacy"

ROOT = util.ROOT
RUNS = util.RUNS


@router.get("/", response_class=HTMLResponse)
def index(request: Request, verdict: str = "", reviewed: str = "", task: str = ""):
    rows, verdicts = util.reindex_and_query(verdict or None, reviewed or None, task or None)
    return templates.TemplateResponse(request, "list.html", {
        "rows": rows, "verdicts": verdicts,
        "f": {"verdict": verdict, "reviewed": reviewed, "task": task},
    })


@router.get("/run/{run_id}", response_class=HTMLResponse)
def detail(request: Request, run_id: str):
    md = RUNS / f"{run_id}.md"
    if not md.exists():
        return HTMLResponse(f"run not found: {run_id}", status_code=404)
    text = md.read_text(encoding="utf-8")
    fm = util.loopdb.parse_front_matter(text)
    return templates.TemplateResponse(request, "detail.html", {
        "run_id": run_id, "fm": fm, "summary": util.run_summary(text),
        "verifier": util.read_verifier(run_id), "evidence": util.evidence_text(run_id),
        "judgment": runner.parse_judgment(md), "fields": runner.JUDGMENT_FIELDS,
    })


@router.post("/run/{run_id}/judge")
def judge(run_id: str, trust: str = Form(""), risk: str = Form(""),
          checks: str = Form(""), learning: str = Form("")):
    runner.write_judgment(run_id, {"trust": trust, "risk": risk, "checks": checks, "learning": learning},
                          runner.load_config())
    return RedirectResponse(f"/legacy/run/{run_id}", status_code=303)


@router.get("/monitor", response_class=HTMLResponse)
def monitor(request: Request):
    status = util.read_run_status()
    conn = util.loopdb.connect(util.DB)
    recent = [dict(r) for r in conn.execute(
        "SELECT run_id, task, verdict, reviewed, repo, started_at FROM runs "
        "ORDER BY started_at DESC, run_id DESC LIMIT 12")]
    unreviewed = conn.execute("SELECT COUNT(*) FROM runs WHERE reviewed=0").fetchone()[0]
    conn.close()
    pending = sum(1 for t in runner.parse_tasks() if str(t.get("status", "todo")).lower() == "todo")
    return templates.TemplateResponse(request, "monitor.html", {
        "status": status, "recent": recent, "unreviewed": unreviewed, "pending": pending,
        "phases": [("explorer", "Explorer"), ("implementer", "Implementer"), ("verifier", "検証/Verifier")]})


@router.get("/monitor/live/{run_id}", response_class=HTMLResponse)
def monitor_live(request: Request, run_id: str):
    if "/" in run_id or ".." in run_id:
        return HTMLResponse("bad request", status_code=400)
    rd = RUNS / run_id
    if not rd.is_dir():
        return HTMLResponse(f"run not found: {run_id}", status_code=404)
    status = util.read_run_status()
    active = bool(status and status.get("run_id") == run_id)
    roles = []
    for key, label in (("explorer", "Explorer"), ("implementer", "Implementer"), ("verifier", "Verifier")):
        sp = rd / f"{key}.stream.jsonl"
        if sp.exists() and sp.stat().st_size > 0:
            roles.append({"label": label, "events": util.parse_transcript(sp)})
    return templates.TemplateResponse(request, "monitor_live.html", {
        "run_id": run_id, "status": status, "active": active, "roles": roles})


@router.get("/todo", response_class=HTMLResponse)
def todo_list(request: Request, started: str = "", generating: int = 0):
    return templates.TemplateResponse(request, "todo_list.html", {
        "tasks": runner.parse_tasks(), "last": util.latest_runs(),
        "running": (runner.DATA / ".run.lock").exists(), "started": started,
        "generating": bool(generating)})


@router.get("/todo/new", response_class=HTMLResponse)
def todo_new(request: Request, prompt: str = "", error: str = ""):
    return templates.TemplateResponse(request, "todo_new.html", {
        "prompt": prompt, "error": error, "repos": util.known_repos()})


@router.get("/todo/new/manual", response_class=HTMLResponse)
def todo_new_manual(request: Request):
    fields = {"task_id": "", "goal": "", "repo": "", "accept": [], "verify": "", "constraints": [],
              "allowed_tools": "Read, Edit, Write, Grep, Glob, Bash", "max_attempts": "",
              "status": "todo", "body": ""}
    return templates.TemplateResponse(request, "todo_edit.html", {
        "f": fields, "is_new": True, "saved": False, "statuses": util.STATUSES, "repos": util.known_repos()})


@router.post("/todo/generate")
def todo_generate(prompt: str = Form(""), auto_run: str = Form(""), repo: str = Form("")):
    if not prompt.strip():
        return RedirectResponse("/legacy/todo/new", status_code=303)
    args = ["uv", "run", "runner.py", "gen", prompt.strip()]
    if repo.strip():
        args += ["--repo", repo.strip()]
    if auto_run:
        args.append("--run")
    subprocess.Popen(args, cwd=str(ROOT))
    return RedirectResponse("/legacy/todo?generating=1", status_code=303)


@router.get("/todo/{task_id}", response_class=HTMLResponse)
def todo_edit(request: Request, task_id: str, saved: int = 0, generated: int = 0):
    tid = util.safe_id(task_id)
    res = runner.read_task(tid) if tid else None
    if res is None:
        return HTMLResponse(f"task not found: {task_id}", status_code=404)
    fm, body = res
    return templates.TemplateResponse(request, "todo_edit.html", {
        "f": util.fields_from_fm(tid, fm, body), "is_new": False, "saved": bool(saved),
        "generated": bool(generated), "statuses": util.STATUSES, "repos": util.known_repos()})


@router.post("/todo/new")
def todo_create(task_id: str = Form(""), goal: str = Form(""), repo: str = Form(""),
                accept: list[str] = Form([]), verify: str = Form(""), constraints: list[str] = Form([]),
                allowed_tools: str = Form(""), max_attempts: str = Form(""), status: str = Form("todo"),
                body: str = Form("")):
    tid = util.safe_id(task_id)
    if not tid:
        return HTMLResponse("不正な id です(英数字と . _ - のみ、先頭は英数字)。", status_code=400)
    if (runner.TASKS_DIR / f"{tid}.md").exists():
        return HTMLResponse(f"既に存在します: {tid}", status_code=409)
    fm = util.fm_from_form(tid, goal, repo, accept, verify, constraints, allowed_tools, max_attempts, status)
    p = runner.write_task(tid, fm, body)
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} を新規作成")
    return RedirectResponse(f"/legacy/todo/{tid}?saved=1", status_code=303)


@router.post("/todo/{task_id}")
def todo_save(task_id: str, goal: str = Form(""), repo: str = Form(""), accept: list[str] = Form([]),
              verify: str = Form(""), constraints: list[str] = Form([]), allowed_tools: str = Form(""),
              max_attempts: str = Form(""), status: str = Form("todo"), body: str = Form("")):
    tid = util.safe_id(task_id)
    if not tid:
        return HTMLResponse("invalid id", status_code=400)
    fm = util.fm_from_form(tid, goal, repo, accept, verify, constraints, allowed_tools, max_attempts, status)
    p = runner.write_task(tid, fm, body)
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} を編集")
    return RedirectResponse(f"/legacy/todo/{tid}?saved=1", status_code=303)


@router.post("/todo/{task_id}/run")
def todo_run(task_id: str):
    tid = util.safe_id(task_id)
    if not tid or not (runner.TASKS_DIR / f"{tid}.md").exists():
        return HTMLResponse("no such task", status_code=404)
    if (runner.DATA / ".run.lock").exists():
        return RedirectResponse("/legacy/todo?started=busy", status_code=303)
    subprocess.Popen(["uv", "run", "runner.py", "run", tid], cwd=str(ROOT))
    return RedirectResponse(f"/legacy/todo?started={tid}", status_code=303)


@router.post("/todo/{task_id}/delete")
def todo_delete(task_id: str):
    tid = util.safe_id(task_id)
    p = runner.TASKS_DIR / f"{tid}.md" if tid else None
    if p and p.exists():
        p.unlink()
        runner.git(runner.DATA, "add", "-A", "--", "tasks")
        runner.git(runner.DATA, "commit", "-q", "-m", f"todo: {tid} を削除")
    return RedirectResponse("/legacy/todo", status_code=303)


@router.get("/run/{run_id}/transcript", response_class=HTMLResponse)
def transcript(request: Request, run_id: str):
    p = RUNS / run_id / "transcript.jsonl"
    if not p.exists():
        return HTMLResponse(f"transcript なし: {run_id}", status_code=404)
    return templates.TemplateResponse(request, "transcript.html", {
        "run_id": run_id, "events": util.parse_transcript(p),
    })


@router.get("/run/{run_id}/file/{name}", response_class=PlainTextResponse)
def evidence_file(run_id: str, name: str):
    p = (RUNS / run_id / name).resolve()
    if not str(p).startswith(str((RUNS / run_id).resolve())) or not p.exists():
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


@router.post("/dispatch")
def dispatch():
    subprocess.Popen(["uv", "run", "runner.py", "run"], cwd=str(ROOT))
    return RedirectResponse("/legacy/", status_code=303)
