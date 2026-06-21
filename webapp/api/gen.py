"""タスク生成(Author)のライブ transcript + 結果スナップショット。

設計: cmd_gen が data/gen/<gen_id>/ に author.stream.jsonl をライブ追記する。
- /api/gen/<gen_id>/stream: stream-json を tail して event/end を SSE 配信(run 用と同じ形)。
- /api/gen/<gen_id>/snapshot: gen.json(完了 or 失敗のスナップ)+ 既蓄積イベントを返す。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import util
from ..util import runner

router = APIRouter(tags=["gen"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
# stream.jsonl が この秒数以上更新されず gen.json も無ければ「kill された残骸」と判定する。
_STALE_SECONDS = 30


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _gen_dir(gen_id: str) -> Path:
    # 軽い path traversal ガード(/ や .. を含む id は拒否)
    if "/" in gen_id or ".." in gen_id or not gen_id:
        raise HTTPException(400, {"error": "bad_id", "message": "invalid gen_id"})
    return runner.DATA / "gen" / gen_id


@router.get("/gen")
def list_gens(limit: int = 30):
    """data/gen/<id>/ を新しい順に。各 entry に status / task_id / error / 開始時刻を載せる。"""
    base = runner.DATA / "gen"
    if not base.exists():
        return {"generations": []}
    entries: list[dict] = []
    try:
        ids = sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True)
    except OSError:
        ids = []
    now = time.time()
    for gen_id in ids[:limit]:
        d = base / gen_id
        result: dict | None = None
        rp = d / "gen.json"
        if rp.exists():
            try:
                result = json.loads(rp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result = None
        if result:
            status = result.get("status") or "fail"
            task_id = result.get("task_id")
            error = result.get("error")
        else:
            # gen.json なし → 実行中 or kill された残骸を mtime で判定する
            sp = d / "author.stream.jsonl"
            if sp.exists() and now - sp.stat().st_mtime <= _STALE_SECONDS:
                status, task_id, error = "running", None, None
            else:
                age = int(now - sp.stat().st_mtime) if sp.exists() else None
                status, task_id = "fail", None
                error = f"aborted (no result, stream silent {age}s)" if age is not None else "aborted (no stream)"
        entries.append({
            "gen_id": gen_id,
            "status": status,
            "task_id": task_id,
            "error": error,
            # gen_id 命名規約 "YYYY-MM-DD-HHMMSS-gen" から started_at を導出。
            "started_at": gen_id[:17] if len(gen_id) >= 17 else None,
        })
    return {"generations": entries}


@router.get("/gen/{gen_id}/snapshot")
def gen_snapshot(gen_id: str):
    """完了/失敗の結果(gen.json)と既蓄積の transcript event 配列。SSE 接続前の初期化用。"""
    d = _gen_dir(gen_id)
    if not d.exists():
        raise HTTPException(404, {"error": "not_found", "message": f"gen not found: {gen_id}"})
    sp = d / "author.stream.jsonl"
    events = util.parse_transcript(sp) if sp.exists() else []
    result_path = d / "gen.json"
    result: dict | None = None
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = None
    return {"gen_id": gen_id, "events": events, "result": result}


@router.get("/gen/{gen_id}/stream")
async def stream_gen(request: Request, gen_id: str):
    """Author のライブ transcript SSE。author.stream.jsonl を tail して event/end を配信。"""
    d = _gen_dir(gen_id)

    async def gen():
        sent = 0
        beat = 0
        # ディレクトリが出来るまで少し待つ(POST 直後の race を吸収)
        for _ in range(20):
            if d.exists():
                break
            await asyncio.sleep(0.2)
        while True:
            if await request.is_disconnected():
                return
            sp = d / "author.stream.jsonl"
            if sp.exists() and sp.stat().st_size > 0:
                try:
                    events = util.parse_transcript(sp)
                except OSError:
                    events = []
                if len(events) > sent:
                    for ev in events[sent:]:
                        yield _sse("event", {**ev, "role": "author"})
                    sent = len(events)
            # gen.json があれば完了 → result を end に載せて終了
            result_path = d / "gen.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    result = {"status": "fail", "error": "result_read_failed"}
                yield _sse("end", {"gen_id": gen_id, "result": result})
                return
            # stream が一定時間更新なし = kill された残骸 → fail で end を出して終了
            if sp.exists():
                age = time.time() - sp.stat().st_mtime
                if age > _STALE_SECONDS:
                    yield _sse("end", {
                        "gen_id": gen_id,
                        "result": {"status": "fail", "task_id": None,
                                   "error": f"aborted (no result, stream silent {int(age)}s)"},
                    })
                    return
            beat += 1
            yield _sse("heartbeat", {"t": beat})
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
