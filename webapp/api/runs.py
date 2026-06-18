"""run の読み取り系 + 判断書き込み(中継)。§2.1 #1-8。

判断(#6)は JudgmentInput を無変換で runner.write_judgment へ素通す(§2.6)。
サーバ側で trust/risk/checks/learning の補完・要約・LLM 呼び出しを一切しない。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response

from .. import schemas, util
from ..util import runner
from ._deps import err, valid_run_id

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=schemas.RunListResponse)
def list_runs(verdict: str | None = None, reviewed: str | None = None, task: str | None = None,
              include_archived: bool = False):
    rows, verdicts = util.reindex_and_query(verdict or None, reviewed or None, task or None,
                                            include_archived=include_archived)
    return schemas.RunListResponse(runs=[schemas.RunRow(**r) for r in rows], verdicts=verdicts)


@router.post("/runs/{run_id}/archive", status_code=204, openapi_extra={"x-loop-kind": "A"})
def archive_run(inp: schemas.ArchiveInput, run_id: str = Depends(valid_run_id)):
    # run は削除しない(契約=真実の源)。UI 非表示のための archived フラグのみ。
    if not runner.set_run_archived(run_id, inp.archived):
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    return Response(status_code=204)


@router.get("/runs/{run_id}", response_model=schemas.RunDetail)
def run_detail(run_id: str = Depends(valid_run_id)):
    md = util.RUNS / f"{run_id}.md"
    if not md.exists():
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    text = md.read_text(encoding="utf-8")
    fm = util.loopdb.parse_front_matter(text)
    return schemas.RunDetail(
        run_id=run_id, front_matter=fm, summary=util.run_summary(text),
        verifier=util.read_verifier(run_id), judgment=runner.parse_judgment(md),
        judgment_fields=[list(f) for f in runner.JUDGMENT_FIELDS],
        evidence=util.evidence_flags(run_id))


@router.get("/runs/{run_id}/evidence", response_model=schemas.EvidenceMeta)
def run_evidence(run_id: str = Depends(valid_run_id)):
    d = util.RUNS / run_id
    files = []
    for name in ("change.patch", "test-output.txt", "transcript.jsonl", "verifier.json"):
        p = d / name
        ex = p.exists()
        files.append(schemas.EvidenceFileMeta(
            name=name, size=(p.stat().st_size if ex else 0), exists=ex))
    return schemas.EvidenceMeta(files=files)


@router.get("/runs/{run_id}/files/{name}", response_class=PlainTextResponse)
def run_file(name: str, run_id: str = Depends(valid_run_id)):
    p = util.evidence_file_path(run_id, name)
    if p is None:
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


@router.get("/runs/{run_id}/transcript", response_model=schemas.TranscriptResponse)
def run_transcript(run_id: str = Depends(valid_run_id)):
    p = util.RUNS / run_id / "transcript.jsonl"
    if not p.exists():
        raise HTTPException(404, err("not_found", f"transcript なし: {run_id}"))
    return schemas.TranscriptResponse(events=util.parse_transcript(p))


@router.post("/runs/{run_id}/judgment", status_code=204,
             openapi_extra={"x-loop-kind": "A(中継)"})
def put_judgment(inp: schemas.JudgmentInput, run_id: str = Depends(valid_run_id)):
    if not (util.RUNS / f"{run_id}.md").exists():
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    runner.write_judgment(run_id, inp.model_dump(), runner.load_config())  # 無変換素通し
    return Response(status_code=204)


@router.post("/runs/{run_id}/message", status_code=204,
             openapi_extra={"x-loop-kind": "A(中継)"})
def post_message(inp: schemas.MessageInput, run_id: str = Depends(valid_run_id)):
    """awaiting 中の run へ続行指示を渡す。inbox.jsonl に 1 行追記し、runner が同一セッションへ注入する。
    指示文(中身)は人間=種類B。ここは無変換で素通すだけ。"""
    text = (inp.text or "").strip()
    if not text:
        raise HTTPException(400, err("bad_input", "text は必須です"))
    rd = util.RUNS / run_id
    if not rd.is_dir():
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    with (rd / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
    return Response(status_code=204)
