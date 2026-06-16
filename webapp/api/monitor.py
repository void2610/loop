"""監視(snapshot + ライブ) + SSE 枠。§2.1 #7-8 と SSE 予約。

SSE は本実装(role別 tail・並行 run 多重化)は WS4。ここは経路と最小1イベントだけ凍結。
per-run ステータスは runs/<id>/status.json を run_id キーで読む契約に固定(§8.1.3)。
SSE は事実イベントの追記専用。判断・要約を一切流さない(§2.3 / §2.6)。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .. import schemas, util
from ..util import runner
from ._deps import valid_run_id

router = APIRouter(tags=["monitor"])

_PHASES = [["explorer", "Explorer"], ["implementer", "Implementer"], ["verifier", "検証/Verifier"]]


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/monitor", response_model=schemas.MonitorSnapshot)
def monitor_snapshot():
    status = util.read_run_status()
    conn = util.loopdb.connect(util.DB)
    recent = [dict(r) for r in conn.execute(
        "SELECT run_id, task, verdict, reviewed, repo, started_at FROM runs "
        "ORDER BY started_at DESC, run_id DESC LIMIT 12")]
    unreviewed = conn.execute("SELECT COUNT(*) FROM runs WHERE reviewed=0").fetchone()[0]
    conn.close()
    pending = sum(1 for t in runner.parse_tasks() if str(t.get("status", "todo")).lower() == "todo")
    return schemas.MonitorSnapshot(
        status=status, recent=[schemas.RunRow(**r) for r in recent],
        unreviewed=unreviewed, pending=pending, phases=_PHASES)


@router.get("/runs/{run_id}/live", response_model=schemas.LiveSnapshot)
def run_live(run_id: str = Depends(valid_run_id)):
    rd = util.RUNS / run_id
    status = util.read_run_status(run_id)
    active = status is not None
    roles = []
    for key, label in (("explorer", "Explorer"), ("implementer", "Implementer"), ("verifier", "Verifier")):
        sp = rd / f"{key}.stream.jsonl"
        if sp.exists() and sp.stat().st_size > 0:
            roles.append(schemas.LiveRole(label=label, events=util.parse_transcript(sp)))
    return schemas.LiveSnapshot(run_id=run_id, status=status, active=active, roles=roles)


@router.get("/stream/monitor")
def stream_monitor():
    """monitor 全体の SSE 枠。event: status / run_done / heartbeat(本実装は WS4)。"""

    async def gen():
        # P0 凍結: 接続直後に現状 status を1本流して経路を確定する
        yield _sse("status", util.read_run_status())
        yield _sse("heartbeat", {"t": 0})
        await asyncio.sleep(0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: str = Depends(valid_run_id)):
    """進行中 run のライブ transcript SSE 枠。event: event / phase / end(本実装は WS4)。"""

    async def gen():
        status = util.read_run_status(run_id)
        yield _sse("phase", {"phase": (status or {}).get("phase", "start")})
        yield _sse("end", {"run_id": run_id})
        await asyncio.sleep(0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
