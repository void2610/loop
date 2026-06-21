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
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .. import schemas, util
from ..util import runner
from ._deps import valid_run_id

router = APIRouter(tags=["monitor"])

_PHASES = [["implementer", "Implementer"], ["verifier", "検証/Verifier"]]
_ROLES = ("implementer", "verifier")
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
# Last-Event-ID から role 単位の再開位置を引く。EventSource は直近 1 個しか送らないため
# 受け取った role だけ進めて、もう一方は 0 から差分読みで自然同期する(seek 状態が無いと毎回 0)。
_LEID_RE = re.compile(r"^(implementer|verifier):(\d+)$")
_LEID_END_RE = re.compile(r"^end:(\d+)-(\d+)$")


def _sse(event: str, data, eid: str | None = None) -> str:
    """SSE フレーム。eid を入れると EventSource が `Last-Event-ID` に保持し、再接続時に
    自動でリクエストヘッダに付ける(過去 event 全部の重送防止)。"""
    head = f"id: {eid}\n" if eid else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
    queue = util.run_queue()
    active = util.active_runs()
    max_concurrency = max(1, int(runner.load_config()["loop"].get("max_concurrency", 1)))
    return schemas.MonitorSnapshot(
        status=status, active=active,
        queue=[schemas.QueueItem(**q) for q in queue], max_concurrency=max_concurrency,
        recent=[schemas.RunRow(**r) for r in recent],
        unreviewed=unreviewed, pending=len(queue), phases=_PHASES)


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
    intervention = None  # awaiting 中だけ存在(runner が intervention.json を置く)
    ip = rd / "intervention.json"
    if ip.exists():
        try:
            intervention = (json.loads(ip.read_text(encoding="utf-8")).get("question") or "").strip() or None
        except (json.JSONDecodeError, OSError):
            intervention = None
    return schemas.LiveSnapshot(run_id=run_id, status=status, active=active, roles=roles, intervention=intervention)


def _run_ids() -> set[str]:
    return {p.stem for p in util.RUNS.glob("*.md")} if util.RUNS.exists() else set()


@router.get("/stream/monitor")
async def stream_monitor(request: Request):
    """monitor 全体の SSE。status 変化 / 新 run 出現(run_done)/ heartbeat を継続配信。"""

    async def gen():
        last_status = None  # 直近に送った status の JSON 文字列(変化検出用)
        known = _run_ids()  # 既知の run。初回スナップショットは run_done にしない
        beat = 0
        # 接続直後に現状を1本(フロントの「未接続」を即解消)。{runs:[...]} で全 active を供給する。
        cur = {"runs": util.active_runs()}
        last_status = json.dumps(cur, ensure_ascii=False, sort_keys=True)
        yield _sse("status", cur)
        while True:
            if await request.is_disconnected():
                return
            cur = {"runs": util.active_runs()}
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
    """進行中 run のライブ transcript SSE。role別 stream.jsonl を tail して event/phase/end を配信。
    Last-Event-ID で接続単位の重送を防ぐ(role:N で role 別 index、end:i-v で完了済み再接続を即終端)。"""
    rd = util.RUNS / run_id
    md = util.RUNS / f"{run_id}.md"

    leid = request.headers.get("last-event-id") or ""
    # end 済みで再接続してきた場合は即終端(過去 event を流し直さない)
    if _LEID_END_RE.match(leid) or (leid.startswith("end:") and not _LEID_RE.match(leid)):
        async def end_only():
            yield _sse("end", {"run_id": run_id}, eid=leid or "end:0-0")
        return StreamingResponse(end_only(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def gen():
        counts: dict[str, int] = {r: 0 for r in _ROLES}  # role 別 送信済み event index
        pos: dict[str, int] = {r: 0 for r in _ROLES}  # role 別 ファイル seek 位置
        # Last-Event-ID で受け取った role は「N まで送信済み」として扱い、現状ファイルを全読みして
        # 残り(=N+1 件目以降の蓄積分)を即送信、その後 pos=末尾 で差分のみ tail に移る。
        # event 数とファイル行数は 1:1 対応しないため、seek 位置は「全読みのあと末尾」に確定させる必要がある。
        m = _LEID_RE.match(leid)
        if m:
            r0 = m.group(1)
            counts[r0] = int(m.group(2)) + 1
            sp = rd / f"{r0}.stream.jsonl"
            if sp.exists() and sp.stat().st_size > 0:
                try:
                    ev_all = util.parse_transcript(sp)
                except OSError:
                    ev_all = []
                # 既送信(counts[r0] 件)を skip して残りを即吐く。次の tick は pos=末尾 から差分のみ。
                for ev in ev_all[counts[r0]:]:
                    yield _sse("event", {**ev, "role": r0}, eid=f"{r0}:{counts[r0]}")
                    counts[r0] += 1
                pos[r0] = sp.stat().st_size

        last_phase = None
        beat = 0
        while True:
            if await request.is_disconnected():
                return
            status = util.read_run_status(run_id)
            phase = (status or {}).get("phase")
            if phase and phase != last_phase and phase != "done":
                last_phase = phase
                yield _sse("phase", {"phase": phase})
            for role in _ROLES:
                sp = rd / f"{role}.stream.jsonl"
                if not (sp.exists() and sp.stat().st_size > 0):
                    continue
                try:
                    new_events, new_pos = util.parse_transcript_from(sp, pos[role])
                except OSError:
                    continue
                pos[role] = new_pos
                for ev in new_events:
                    yield _sse("event", {**ev, "role": role}, eid=f"{role}:{counts[role]}")
                    counts[role] += 1
            # 終了判定: phase=done が一次根拠。fallback として status 消失 + run.md verdict 最終値。
            done = (status is not None and phase == "done") or (
                status is None and md.exists() and util._md_verdict_is_final(md))
            if done:
                yield _sse("end", {"run_id": run_id},
                           eid=f"end:{counts['implementer']}-{counts['verifier']}")
                return
            beat += 1
            yield _sse("heartbeat", {"t": beat})
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
