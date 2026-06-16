# /// script
# requires-python = "==3.12.*"
# dependencies = ["fastapi", "uvicorn[standard]", "jinja2", "python-multipart", "pyyaml"]
# ///
"""run を triage し判断を書き込む編集面(FastAPI + HTMX, localhost)。

§2.5-5 / §7 の唯一の硬い制約: **GUI は判断を生成・要約・推奨・自動入力しない**。
事実要約(runner が作ったもの)と証拠表示まで。判断欄は空で出し、人間が書く。
書き込み先は常に契約ファイル(runs/*.md・review-notes.md)。GUI 独自の権威ストアは持たない。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import loopdb  # noqa: E402
import runner  # noqa: E402

ROOT = runner.ROOT
RUNS = runner.RUNS
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app = FastAPI(title="loop")


def _reindex_and_query(verdict: str | None, reviewed: str | None, task: str | None):
    conn = loopdb.connect(runner.DB)
    loopdb.reindex(conn, RUNS)
    q, params = "SELECT * FROM runs WHERE 1=1", []
    if verdict:
        q += " AND verdict=?"; params.append(verdict)
    if reviewed in ("0", "1"):
        q += " AND reviewed=?"; params.append(int(reviewed))
    if task:
        q += " AND task LIKE ?"; params.append(f"%{task}%")
    q += " ORDER BY started_at DESC, run_id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    verdicts = [r[0] for r in conn.execute("SELECT DISTINCT verdict FROM runs ORDER BY verdict").fetchall()]
    conn.close()
    return rows, verdicts


@app.get("/", response_class=HTMLResponse)
def index(request: Request, verdict: str = "", reviewed: str = "", task: str = ""):
    rows, verdicts = _reindex_and_query(verdict or None, reviewed or None, task or None)
    return templates.TemplateResponse(request, "list.html", {
        "rows": rows, "verdicts": verdicts,
        "f": {"verdict": verdict, "reviewed": reviewed, "task": task},
    })


def _evidence(run_id: str) -> dict:
    d = RUNS / run_id
    out = {}
    for name in ("change.patch", "test-output.txt"):
        p = d / name
        out[name] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
    out["transcript"] = (d / "transcript.jsonl").exists()
    return out


@app.get("/run/{run_id}", response_class=HTMLResponse)
def detail(request: Request, run_id: str):
    md = RUNS / f"{run_id}.md"
    if not md.exists():
        return HTMLResponse(f"run not found: {run_id}", status_code=404)
    text = md.read_text(encoding="utf-8")
    fm = loopdb.parse_front_matter(text)
    summary = ""
    if "## エージェントがやったこと" in text:
        after = text.split("## エージェントがやったこと", 1)[1]
        summary = after.split("\n## ", 1)[0]  # 次の見出し(役割別実行)の手前まで
        summary = "\n".join(l for l in summary.splitlines() if not l.startswith("（")).strip()
    vjson = RUNS / run_id / "verifier.json"
    verifier = None
    if vjson.exists():
        try:
            verifier = json.loads(vjson.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            verifier = None
    return templates.TemplateResponse(request, "detail.html", {
        "run_id": run_id, "fm": fm, "summary": summary, "verifier": verifier,
        "evidence": _evidence(run_id), "judgment": runner.parse_judgment(md),
        "fields": runner.JUDGMENT_FIELDS,
    })


@app.post("/run/{run_id}/judge")
def judge(run_id: str, trust: str = Form(""), risk: str = Form(""),
          checks: str = Form(""), learning: str = Form("")):
    runner.write_judgment(run_id, {"trust": trust, "risk": risk, "checks": checks, "learning": learning},
                          runner.load_config())
    return RedirectResponse(f"/run/{run_id}", status_code=303)


import re  # noqa: E402

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_STATUSES = ["todo", "pass", "fail", "timeout", "handoff"]


def _safe_id(task_id: str) -> str | None:
    task_id = (task_id or "").strip()
    if not task_id or not _SAFE_ID.match(task_id) or task_id.startswith(("_", ".")) or "/" in task_id:
        return None
    return task_id


def _fields_from_fm(task_id: str, fm: dict, body: str) -> dict:
    """front-matter dict → フォーム用フィールド(accept/constraints は行 UI 用にリストのまま)。"""
    tools = fm.get("allowed_tools")
    if isinstance(tools, list):
        tools = ", ".join(tools)
    return {
        "task_id": task_id,
        "goal": fm.get("goal", ""),
        "accept": fm.get("accept") or [],
        "verify": fm.get("verify", "") or "",
        "constraints": fm.get("constraints") or [],
        "allowed_tools": tools or "",
        "max_attempts": fm.get("max_attempts", "") if fm.get("max_attempts") is not None else "",
        "status": fm.get("status", "todo"),
        "body": body,
    }


def _fm_from_form(task_id, goal, accept: list[str], verify, constraints: list[str],
                  allowed_tools, max_attempts, status) -> dict:
    """フォーム入力 → front-matter dict(順序を固定。空フィールドは省く)。"""
    fm: dict = {"id": task_id, "goal": goal.strip("\n")}
    acc = [x.strip() for x in accept if x.strip()]
    if acc:
        fm["accept"] = acc
    if (verify or "").strip():
        fm["verify"] = verify.strip("\n")
    cons = [x.strip() for x in constraints if x.strip()]
    if cons:
        fm["constraints"] = cons
    if (allowed_tools or "").strip():
        fm["allowed_tools"] = allowed_tools.strip()
    if str(max_attempts or "").strip():
        try:
            fm["max_attempts"] = int(max_attempts)
        except ValueError:
            pass
    fm["status"] = status if status in _STATUSES else "todo"
    return fm


def _latest_runs() -> dict:
    """task id → 最新 run {run_id, verdict}(loop.db から。各 run は完了時に upsert 済み)。"""
    last: dict = {}
    try:
        conn = loopdb.connect(runner.DB)
        for r in conn.execute("SELECT task, run_id, verdict FROM runs ORDER BY started_at DESC, run_id DESC"):
            last.setdefault(r["task"], {"run_id": r["run_id"], "verdict": r["verdict"]})
        conn.close()
    except Exception:
        pass
    return last


@app.get("/todo", response_class=HTMLResponse)
def todo_list(request: Request, started: str = ""):
    return templates.TemplateResponse(request, "todo_list.html", {
        "tasks": runner.parse_tasks(), "last": _latest_runs(),
        "running": (runner.DATA / ".run.lock").exists(), "started": started})


@app.get("/todo/new", response_class=HTMLResponse)
def todo_new(request: Request, prompt: str = "", error: str = ""):
    # 既定はプロンプト入力(Claude Code にタスクを考えさせる)
    return templates.TemplateResponse(request, "todo_new.html", {"prompt": prompt, "error": error})


@app.get("/todo/new/manual", response_class=HTMLResponse)
def todo_new_manual(request: Request):
    fields = {"task_id": "", "goal": "", "accept": [], "verify": "", "constraints": [],
              "allowed_tools": "Read, Edit, Write, Grep, Glob, Bash", "max_attempts": "",
              "status": "todo", "body": ""}
    return templates.TemplateResponse(request, "todo_edit.html", {
        "f": fields, "is_new": True, "saved": False, "statuses": _STATUSES})


@app.post("/todo/generate")
def todo_generate(request: Request, prompt: str = Form(""), auto_run: str = Form("")):
    prompt = prompt.strip()
    if not prompt:
        return RedirectResponse("/todo/new", status_code=303)
    obj = runner.generate_task(prompt, runner.load_config())
    if not obj or not obj.get("id") or not obj.get("goal"):
        return templates.TemplateResponse(request, "todo_new.html", {
            "prompt": prompt, "error": "生成に失敗しました(モデル出力が不正)。文言を変えて再試行するか、手動作成へ。"})
    # id を安全化 + 一意化
    base = _safe_id(re.sub(r"[^A-Za-z0-9._-]+", "-", obj["id"]).strip("-.")) or "task"
    tid, n = base, 2
    while (runner.TASKS_DIR / f"{tid}.md").exists():
        tid, n = f"{base}-{n}", n + 1
    fm = _fm_from_form(tid, obj.get("goal", ""), obj.get("accept") or [], obj.get("verify", "") or "",
                       obj.get("constraints") or [], obj.get("allowed_tools", "") or "",
                       obj.get("max_attempts", ""), "todo")
    p = runner.write_task(tid, fm, obj.get("notes", "") or "")
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} をプロンプトから生成")
    if auto_run and not (runner.DATA / ".run.lock").exists():
        subprocess.Popen(["uv", "run", "runner.py", "run", tid], cwd=str(ROOT))
        return RedirectResponse(f"/todo?started={tid}", status_code=303)
    return RedirectResponse(f"/todo/{tid}?generated=1", status_code=303)


@app.get("/todo/{task_id}", response_class=HTMLResponse)
def todo_edit(request: Request, task_id: str, saved: int = 0, generated: int = 0):
    tid = _safe_id(task_id)
    res = runner.read_task(tid) if tid else None
    if res is None:
        return HTMLResponse(f"task not found: {task_id}", status_code=404)
    fm, body = res
    return templates.TemplateResponse(request, "todo_edit.html", {
        "f": _fields_from_fm(tid, fm, body), "is_new": False, "saved": bool(saved),
        "generated": bool(generated), "statuses": _STATUSES})


@app.post("/todo/new")
def todo_create(task_id: str = Form(""), goal: str = Form(""), accept: list[str] = Form([]),
                verify: str = Form(""), constraints: list[str] = Form([]), allowed_tools: str = Form(""),
                max_attempts: str = Form(""), status: str = Form("todo"), body: str = Form("")):
    tid = _safe_id(task_id)
    if not tid:
        return HTMLResponse("不正な id です(英数字と . _ - のみ、先頭は英数字)。", status_code=400)
    if (runner.TASKS_DIR / f"{tid}.md").exists():
        return HTMLResponse(f"既に存在します: {tid}", status_code=409)
    fm = _fm_from_form(tid, goal, accept, verify, constraints, allowed_tools, max_attempts, status)
    p = runner.write_task(tid, fm, body)
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} を新規作成")
    return RedirectResponse(f"/todo/{tid}?saved=1", status_code=303)


@app.post("/todo/{task_id}")
def todo_save(task_id: str, goal: str = Form(""), accept: list[str] = Form([]), verify: str = Form(""),
              constraints: list[str] = Form([]), allowed_tools: str = Form(""), max_attempts: str = Form(""),
              status: str = Form("todo"), body: str = Form("")):
    tid = _safe_id(task_id)
    if not tid:
        return HTMLResponse("invalid id", status_code=400)
    fm = _fm_from_form(tid, goal, accept, verify, constraints, allowed_tools, max_attempts, status)
    p = runner.write_task(tid, fm, body)
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} を編集")
    return RedirectResponse(f"/todo/{tid}?saved=1", status_code=303)


@app.post("/todo/{task_id}/run")
def todo_run(task_id: str):
    tid = _safe_id(task_id)
    if not tid or not (runner.TASKS_DIR / f"{tid}.md").exists():
        return HTMLResponse("no such task", status_code=404)
    if (runner.DATA / ".run.lock").exists():
        return RedirectResponse("/todo?started=busy", status_code=303)
    subprocess.Popen(["uv", "run", "runner.py", "run", tid], cwd=str(ROOT))  # dispatch は種類A
    return RedirectResponse(f"/todo?started={tid}", status_code=303)


@app.post("/todo/{task_id}/delete")
def todo_delete(task_id: str):
    tid = _safe_id(task_id)
    p = runner.TASKS_DIR / f"{tid}.md" if tid else None
    if p and p.exists():
        p.unlink()
        runner.git(runner.DATA, "add", "-A", "--", "tasks")
        runner.git(runner.DATA, "commit", "-q", "-m", f"todo: {tid} を削除")
    return RedirectResponse("/todo", status_code=303)


def _parse_transcript(path: Path) -> list[dict]:
    """セッション JSONL を会話イベント列に畳む(user/assistant のみ。ノイズ行は捨てる)。"""
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") not in ("user", "assistant"):
            continue
        msg = o.get("message", {})
        if not isinstance(msg, dict):
            continue
        ts = (o.get("timestamp") or "")[11:19]
        content = msg.get("content")
        if isinstance(content, str):
            events.append({"cls": "user", "label": "プロンプト", "body": content, "ts": ts})
            continue
        for b in content or []:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                events.append({"cls": "assistant", "label": "アシスタント", "body": b.get("text", ""), "ts": ts})
            elif bt == "thinking":
                events.append({"cls": "think", "label": "思考", "body": b.get("thinking", ""), "ts": ts, "collapse": True})
            elif bt == "tool_use":
                body = json.dumps(b.get("input", {}), ensure_ascii=False, indent=2)
                events.append({"cls": "tool", "label": f"🔧 {b.get('name', 'tool')}", "body": body, "ts": ts,
                               "collapse": len(body) > 600})
            elif bt == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                body = "" if c is None else str(c)
                events.append({"cls": "result", "label": "↩ 結果", "body": body, "ts": ts, "collapse": len(body) > 400})
    return events


@app.get("/run/{run_id}/transcript", response_class=HTMLResponse)
def transcript(request: Request, run_id: str):
    p = RUNS / run_id / "transcript.jsonl"
    if not p.exists():
        return HTMLResponse(f"transcript なし: {run_id}", status_code=404)
    return templates.TemplateResponse(request, "transcript.html", {
        "run_id": run_id, "events": _parse_transcript(p),
    })


@app.get("/run/{run_id}/file/{name}", response_class=PlainTextResponse)
def evidence_file(run_id: str, name: str):
    p = (RUNS / run_id / name).resolve()
    if not str(p).startswith(str((RUNS / run_id).resolve())) or not p.exists():
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


@app.post("/dispatch")
def dispatch():
    # dispatch は種類A。GUI から叩いてよい。バックグラウンドで次の todo を実行。
    subprocess.Popen(["uv", "run", "runner.py", "run"], cwd=str(ROOT))
    return RedirectResponse("/", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
