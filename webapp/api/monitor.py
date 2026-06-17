"""監視(snapshot + ライブ) + SSE。§2.1 #7-8 と SSE 本実装。

per-run ステータスは run_id キーで読む契約(util.read_run_status(run_id))に固定(§8.1.3)。
SSE は事実イベントの追記専用。判断・要約を一切流さない(§2.3 / §2.6)。
方式: ファイル(.run.lock / runs/<id>/<role>.stream.jsonl / runs/*.md)を一定間隔で観測し、
差分(新 transcript 行・phase 変化・新 run 出現)だけを push する。claude -p の stream は
ファイルへ逐次書かれるので、それを tail して near-real-time に配信する。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .. import schemas, util
from ..util import runner
from ._deps import valid_run_id

router = APIRouter(tags=["monitor"])

_PHASES = [["implementer", "Implementer"], ["verifier", "検証/Verifier"]]
_ROLES = ("implementer", "verifier")
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/monitor", response_model=schemas.MonitorSnapshot)
def monitor_snapshot():
    status = util.read_run_status()
    conn = util.loopdb.connect(util.DB)
    recent = [dict(r) for r in conn.execute(
        "SELECT run_id, task, verdict, reviewed, repo, started_at FROM runs "
        "WHERE COALESCE(archived,0)=0 ORDER BY started_at DESC, run_id DESC LIMIT 12")]
    unreviewed = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE reviewed=0 AND COALESCE(archived,0)=0").fetchone()[0]
    conn.close()
    pending = sum(1 for t in runner.parse_tasks()
                  if str(t.get("status", "todo")).lower() == "todo"
                  and str(t.get("archived", "false")).lower() not in ("true", "1"))
    return schemas.MonitorSnapshot(
        status=status, recent=[schemas.RunRow(**r) for r in recent],
        unreviewed=unreviewed, pending=pending, phases=_PHASES)


@router.get("/runs/{run_id}/live", response_model=schemas.LiveSnapshot)
def run_live(run_id: str = Depends(valid_run_id)):
    rd = util.RUNS / run_id
    status = util.read_run_status(run_id)
    active = status is not None
    roles = []
    for key, label in (("implementer", "Implementer"), ("verifier", "Verifier")):
        sp = rd / f"{key}.stream.jsonl"
        if sp.exists() and sp.stat().st_size > 0:
            roles.append(schemas.LiveRole(label=label, events=util.parse_transcript(sp)))
    return schemas.LiveSnapshot(run_id=run_id, status=status, active=active, roles=roles)


def _run_ids() -> set[str]:
    return {p.stem for p in util.RUNS.glob("*.md")} if util.RUNS.exists() else set()


@router.get("/stream/monitor")
async def stream_monitor(request: Request):
    """monitor 全体の SSE。status 変化 / 新 run 出現(run_done)/ heartbeat を継続配信。"""

    async def gen():
        last_status = None  # 直近に送った status の JSON 文字列(変化検出用)
        known = _run_ids()  # 既知の run。初回スナップショットは run_done にしない
        beat = 0
        # 接続直後に現状を1本(フロントの「未接続」を即解消)
        cur = util.read_run_status()
        last_status = json.dumps(cur, ensure_ascii=False, sort_keys=True)
        yield _sse("status", cur)
        while True:
            if await request.is_disconnected():
                return
            cur = util.read_run_status()
            snap = json.dumps(cur, ensure_ascii=False, sort_keys=True)
            if snap != last_status:
                last_status = snap
                yield _sse("status", cur)
            now = _run_ids()
            for rid in sorted(now - known):
                yield _sse("run_done", {"run_id": rid})
            known = now
            beat += 1
            yield _sse("heartbeat", {"t": beat})
            await asyncio.sleep(2)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/runs/{run_id}/stream")
async def stream_run(request: Request, run_id: str = Depends(valid_run_id)):
    """進行中 run のライブ transcript SSE。role別 stream.jsonl を tail して event/phase/end を配信。"""
    rd = util.RUNS / run_id

    async def gen():
        counts = {r: 0 for r in _ROLES}  # role ごとに送信済みイベント数(差分のみ push)
        last_phase = None
        beat = 0
        while True:
            if await request.is_disconnected():
                return
            status = util.read_run_status(run_id)
            phase = (status or {}).get("phase")
            if phase and phase != last_phase:
                last_phase = phase
                yield _sse("phase", {"phase": phase})
            for role in _ROLES:
                sp = rd / f"{role}.stream.jsonl"
                if not (sp.exists() and sp.stat().st_size > 0):
                    continue
                try:
                    events = util.parse_transcript(sp)
                except OSError:
                    continue
                if len(events) > counts[role]:
                    for ev in events[counts[role]:]:
                        yield _sse("event", {**ev, "role": role})
                    counts[role] = len(events)
            # 終了判定: 進行ステータスが消え(.run.lock 解放)run MD が出ている = 完了
            if status is None and (util.RUNS / f"{run_id}.md").exists():
                yield _sse("end", {"run_id": run_id})
                return
            beat += 1
            yield _sse("heartbeat", {"t": beat})
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
