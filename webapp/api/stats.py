"""分析ダッシュボード API(§5)。loop.db 直読み(sqlite3, read-only)。

絶対原則: 事実の集計提示のみ。判断(種類B)を生成しない。閾値超過に「危険」「要改善」等の
ラベル・推奨・序列・自動要約を一切付けない。API は生値を返し、整形(% 表示等)はフロント。
LLM 呼び出しはこの経路に存在しない(import も持たない)。

loop.db は MD 派生の使い捨てインデックス(authoritative=runs/*.md)。read-only で開き、
ダッシュボード経路では一切書き込まない。封筒(envelope)の source でその位置づけを明示する。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ._deps import err
from ..util import ROOT, DB
from ..schemas import (
    CostTimelineResponse,
    GamingSuspectsResponse,
    PassRateResponse,
    SummaryResponse,
    VerdictSummaryResponse,
)

router = APIRouter(tags=["stats"])

# canned SQL の単一定義元(queries/*.sql)。クエリ文字列を Python へコピペしない(§5.2)。
_QUERIES = ROOT / "queries"

# 行レベルに started_at を持つ系のみ。集計系(pass-rate/verdict)は全期間固定(§5.4)。
_BASE_RUNS = "SELECT * FROM runs"

# 新規 SQL は CLI 資産(queries/*.sql)と二重化しないよう、行レベル素の SELECT のみここで定義。
_COST_TIMELINE_SQL = (
    "SELECT run_id, started_at, cost_usd, turns, verdict, skill_sha "
    "FROM runs WHERE started_at IS NOT NULL ORDER BY started_at ASC"
)
_SUMMARY_SQL = (
    "SELECT COUNT(*) AS total_runs, "
    "SUM(reviewed) AS reviewed, "
    "SUM(CASE WHEN reviewed=0 THEN 1 ELSE 0 END) AS unreviewed, "
    "SUM(CASE WHEN verdict='pass' THEN 1 ELSE 0 END) AS pass, "
    "SUM(CASE WHEN verdict='fail' THEN 1 ELSE 0 END) AS fail, "
    "COUNT(DISTINCT skill_sha) AS distinct_skills "
    "FROM runs"
)


def _connect_ro() -> sqlite3.Connection:
    """loop.db を read-only で開く(分析は観測であって統制ではない。§5.2)。

    DB 不在(未 reindex)時は immutable URI が失敗するため明示的に 404 を返す。
    """
    if not DB.exists():
        raise HTTPException(404, err("no_db", "loop.db がありません(reindex 前)"))
    uri = f"file:{DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _read_query(name: str) -> str:
    """queries/<name>.sql を読む(canned の単一定義元)。"""
    p = _QUERIES / f"{name}.sql"
    return p.read_text(encoding="utf-8")


def _to_jsonable(v: Any) -> Any:
    """Decimal 等を素の float へ。丸めや「%」整形はしない(API は生値。§5.3)。"""
    if isinstance(v, (int, float, str)) or v is None:
        return v
    return float(v)


def _fetch(conn: sqlite3.Connection, sql: str, params: list | None = None) -> list[dict]:
    cur = conn.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [{c: _to_jsonable(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def _with_window(
    base_sql: str,
    since: str | None,
    until: str | None,
    limit: int | None,
    offset: int | None,
) -> tuple[str, list]:
    """canned SQL を改変せずサブクエリでラップし、started_at 範囲 + ページングを安全注入(§5.4)。

    文字列連結でのパラメータ注入は禁止。値は sqlite のプレースホルダ(?)で渡す。
    """
    clauses, params = [], []
    if since:
        clauses.append("started_at >= ?")
        params.append(since)
    if until:
        clauses.append("started_at <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM ({base_sql.rstrip().rstrip(';')}) AS sub{where}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset or 0]
    return sql, params


def _envelope(model_cls: type, rows: list[dict], *, limit: int | None = None):
    """rows(SQL 由来 dict)を型付き応答モデルへ。Pydantic が行を各 Row 型へ検証する(§2.4)。"""
    return model_cls(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        source="loop.db (derived index; authoritative=runs/*.md)",
        rows=rows,
        has_more=(limit is not None and len(rows) == limit),
    )


def _query_simple(model_cls: type, name: str):
    """集計系 canned クエリ(期間フィルタなし=全期間固定。§5.4)。"""
    conn = _connect_ro()
    try:
        return _envelope(model_cls, _fetch(conn, _read_query(name)))
    finally:
        conn.close()


@router.get("/analytics/pass-rate-by-skill", response_model=PassRateResponse)
def pass_rate_by_skill() -> PassRateResponse:
    return _query_simple(PassRateResponse, "pass_rate_by_skill")


@router.get("/analytics/verdict-summary", response_model=VerdictSummaryResponse)
def verdict_summary() -> VerdictSummaryResponse:
    return _query_simple(VerdictSummaryResponse, "verdict_summary")


@router.get("/analytics/summary", response_model=SummaryResponse)
def summary() -> SummaryResponse:
    conn = _connect_ro()
    try:
        return _envelope(SummaryResponse, _fetch(conn, _SUMMARY_SQL))
    finally:
        conn.close()


@router.get("/analytics/gaming-suspects", response_model=GamingSuspectsResponse)
def gaming_suspects(
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> GamingSuspectsResponse:
    conn = _connect_ro()
    try:
        sql, params = _with_window(_read_query("gaming_suspects"), since, until, limit, offset)
        return _envelope(GamingSuspectsResponse, _fetch(conn, sql, params), limit=limit)
    finally:
        conn.close()


@router.get("/analytics/cost-timeline", response_model=CostTimelineResponse)
def cost_timeline(
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> CostTimelineResponse:
    conn = _connect_ro()
    try:
        sql, params = _with_window(_COST_TIMELINE_SQL, since, until, limit, offset)
        return _envelope(CostTimelineResponse, _fetch(conn, sql, params), limit=limit)
    finally:
        conn.close()
