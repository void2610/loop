"""タスク生成(Author)のライブ transcript + 結果スナップショット。

設計: cmd_gen が data/gen/<gen_id>/ に author.stream.jsonl をライブ追記する。
- /api/gen/<gen_id>/stream: stream-json を tail して event/end を SSE 配信(run 用と同じ形)。
- /api/gen/<gen_id>/snapshot: gen.json(完了 or 失敗のスナップ)+ 既蓄積イベントを返す。
"""

from __future__ import annotations

import asyncio
import json
import re
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
# Author が Explore sub-agent などで token を大量消費中は数十秒 silent もあるので余裕を持つ。
_STALE_SECONDS = 180


def _sse(event: str, data: Any, eid: str | None = None) -> str:
    """SSE フレーム。eid を入れると EventSource が `Last-Event-ID` で再接続時に持ち回す。"""
    head = f"id: {eid}\n" if eid else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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


@router.post("/gen/{gen_id}/stop", status_code=204)
def gen_stop(gen_id: str):
    """gen_dir/stop ファイルを置く → cmd_gen の watcher が subprocess を kill して gen.json に
    status:"stopped" を書く(/api/gen 一覧と SSE end イベントで反映される)。"""
    d = _gen_dir(gen_id)
    if not d.exists():
        raise HTTPException(404, {"error": "not_found", "message": f"gen not found: {gen_id}"})
    (d / "stop").write_text("", encoding="utf-8")
    from fastapi import Response as _R
    return _R(status_code=204)


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
    """Author のライブ transcript SSE。author.stream.jsonl を tail して event/end を配信。
    Last-Event-ID で再接続時の重送を防ぐ(int 単調 index、"end" で完了済み再接続を即終端)。"""
    d = _gen_dir(gen_id)
    if not d.exists():
        raise HTTPException(404, {"error": "not_found", "message": f"gen not found: {gen_id}"})

    leid = request.headers.get("last-event-id") or ""

    # end 済みの再接続: gen.json から result を再構成して即 end(過去 event を流し直さない)
    if leid == "end":
        result_path = d / "gen.json"
        result: dict = {"status": "fail", "error": "result_read_failed"}
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

        async def end_only():
            yield _sse("end", {"gen_id": gen_id, "result": result}, eid="end")
        return StreamingResponse(end_only(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def gen():
        sent = 0
        pos = 0  # author.stream.jsonl の seek 位置(差分のみ JSON decode)
        beat = 0
        # 受け取った Last-Event-ID(N)分は送信済みとして扱い、ファイル全読みで残りを即吐く。
        # event 数とファイル行数は 1:1 対応しないため、seek は「全読みのあと末尾」に確定させる。
        m = re.match(r"^(\d+)$", leid)
        replay: list[dict] = []
        if m:
            sent = int(m.group(1)) + 1
            sp0 = d / "author.stream.jsonl"
            if sp0.exists() and sp0.stat().st_size > 0:
                try:
                    ev_all = util.parse_transcript(sp0)
                except OSError:
                    ev_all = []
                replay = list(ev_all[sent:])
                pos = sp0.stat().st_size
        for ev in replay:
            yield _sse("event", {**ev, "role": "author"}, eid=str(sent))
            sent += 1

        while True:
            if await request.is_disconnected():
                return
            sp = d / "author.stream.jsonl"
            if sp.exists() and sp.stat().st_size > 0:
                try:
                    new_events, pos = util.parse_transcript_from(sp, pos)
                except OSError:
                    new_events = []
                for ev in new_events:
                    yield _sse("event", {**ev, "role": "author"}, eid=str(sent))
                    sent += 1
            # gen.json があれば完了 → result を end に載せて終了
            result_path = d / "gen.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    result = {"status": "fail", "error": "result_read_failed"}
                yield _sse("end", {"gen_id": gen_id, "result": result}, eid="end")
                return
            # stream が一定時間更新なし = kill された残骸 → fail で end を出して終了
            if sp.exists():
                age = time.time() - sp.stat().st_mtime
                if age > _STALE_SECONDS:
                    yield _sse("end", {
                        "gen_id": gen_id,
                        "result": {"status": "fail", "task_id": None,
                                   "error": f"aborted (no result, stream silent {int(age)}s)"},
                    }, eid="end")
                    return
            beat += 1
            yield _sse("heartbeat", {"t": beat})
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
