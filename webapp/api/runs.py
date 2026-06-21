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


@router.get("/runs/{run_id}/pr", response_model=schemas.PrStatus)
def run_pr(run_id: str = Depends(valid_run_id)):
    """awaiting-merge の run の PR 状態を gh で確認。マージ済みなら verdict を pass へ昇格(真の完了)。"""
    st = runner.check_pr_merge(run_id, runner.load_config())
    # PR 未作成(pr_url 無し)では check_pr_merge が {} を返す。None を渡すと merged:bool 検証に
    # 落ちるため、存在するキーだけ渡してモデル既定(merged=False 等)を効かせる。
    keys = ("number", "url", "state", "merged", "ci")
    return schemas.PrStatus(**{k: st[k] for k in keys if st.get(k) is not None})


@router.post("/runs/{run_id}/continue", status_code=202,
             openapi_extra={"x-loop-exec": True})
def continue_run(inp: schemas.MessageInput, run_id: str = Depends(valid_run_id)):
    """完了 run に人間の追加指示を投じて Implementer を resume + Verifier 監査まで走らせる。
    同じ run_id を保ち、stream に continuation marker を追記する。background 実行(SSE で進行を見る)。"""
    import subprocess as _sp
    import yaml as _yaml
    text = (inp.text or "").strip()
    if not text:
        raise HTTPException(400, err("bad_input", "text は必須です"))
    rd = util.RUNS / run_id
    if not rd.is_dir():
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    md = util.RUNS / f"{run_id}.md"
    if not md.exists():
        raise HTTPException(404, err("not_found", f"run md not found: {run_id}"))
    # .run.lock 進行中は弾く(continue は完了 run 用)
    if (runner.DATA / ".run.lock").exists():
        raise HTTPException(409, err("busy", "他の run が進行中です"))
    # 続行の前提を背景プロセス起動前に検証(202 で silent fail させない)。
    # 1) repo 解決 & git repo か / 2) loop/<run_id> ブランチが残っているか(promote 後に削除されると続行不能)。
    try:
        lines, s, e = runner._split_front_matter(md.read_text(encoding="utf-8"))
        fm = (_yaml.safe_load("\n".join(lines[s:e])) or {}) if e else {}
    except (OSError, _yaml.YAMLError):
        fm = {}
    task_id = (fm or {}).get("task")
    if not task_id:
        raise HTTPException(409, err("bad_run_md", "run.md に task が無く続行できません"))
    cfg = runner.load_config()
    task_res = runner.read_task(str(task_id))
    if task_res is None:
        raise HTTPException(409, err("task_missing", f"task が見つかりません: {task_id}"))
    repo = runner.resolve_repo({"repo": (task_res[0] or {}).get("repo")}, cfg)
    if not runner.is_git_repo(repo):
        raise HTTPException(409, err("repo_invalid", f"repo が git 管理下にありません: {repo}"))
    base_ref = f"loop/{run_id}"
    if runner.git(repo, "rev-parse", "--verify", base_ref).returncode != 0:
        raise HTTPException(
            409, err("branch_missing",
                     f"前 run の成果ブランチ {base_ref} が repo に無いため続行できません"
                     " (promote 後の削除など)。新規タスクとして作り直してください。"))
    # Popen 前に「進行中」状態を確定させる(SSE の race 防止)。
    # ここを書かないと、子プロセス起動から worktree 準備までの数秒間、
    # 監視 SSE は前 run の phase=done を見て即 end を流し、live ページが「完了済み」表示で止まる。
    runner._set_fm_key(md, "verdict", "running")
    runner.write_run_status(run_id=run_id, task=str(task_id), repo=str(repo),
                            phase="implementer", verdict=None)
    _sp.Popen(["uv", "run", "runner.py", "continue", run_id, text], cwd=str(util.ROOT))
    return Response(status_code=202)


@router.post("/runs/{run_id}/stop", status_code=204,
             openapi_extra={"x-loop-kind": "A(中継)"})
def stop_run(run_id: str = Depends(valid_run_id)):
    """実行中/awaiting の run に停止マーカーを置く。runner が検知し `stopped` で正常終了
    (ロック解放・worktree 後始末・記録を残す)。awaiting は即時、実行中はターン境界で停止。"""
    rd = util.RUNS / run_id
    if not rd.is_dir():
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    (rd / "stop").write_text("", encoding="utf-8")
    return Response(status_code=204)
