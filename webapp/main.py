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
        summary = after.split("## 証拠", 1)[0]
        summary = "\n".join(l for l in summary.splitlines() if not l.startswith("（")).strip()
    return templates.TemplateResponse(request, "detail.html", {
        "run_id": run_id, "fm": fm, "summary": summary,
        "evidence": _evidence(run_id), "judgment": runner.parse_judgment(md),
        "fields": runner.JUDGMENT_FIELDS,
    })


@app.post("/run/{run_id}/judge")
def judge(run_id: str, trust: str = Form(""), risk: str = Form(""),
          checks: str = Form(""), learning: str = Form("")):
    runner.write_judgment(run_id, {"trust": trust, "risk": risk, "checks": checks, "learning": learning},
                          runner.load_config())
    return RedirectResponse(f"/run/{run_id}", status_code=303)


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
