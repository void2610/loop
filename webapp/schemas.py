"""Pydantic モデル = レスポンス/リクエスト型の唯一の正本(OpenAPI 源)。

入力モデルは extra="forbid"。判断系で勝手なキーを差し込ませない(§2.4 / §2.6)。
出力モデルは整形を入れない(事実とその表示を分離。表示整形はフロント)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import loopdb


class RunRow(BaseModel):
    """loop.db runs 行の射影。COLUMNS と機械的に一致させる(乖離はテストで検出)。"""

    model_config = ConfigDict(extra="allow")

    run_id: str
    task: str | None = None
    verdict: str | None = None
    reviewed: int | None = None
    repo: str | None = None
    started_at: str | None = None


class RunListResponse(BaseModel):
    runs: list[RunRow]
    verdicts: list[str]


class EvidenceFlags(BaseModel):
    model_config = ConfigDict(extra="allow")


class RunDetail(BaseModel):
    run_id: str
    front_matter: dict[str, Any]
    summary: str
    verifier: dict[str, Any] | None
    judgment: dict[str, str]
    judgment_fields: list[list[str]]
    evidence: dict[str, Any]


class EvidenceFileMeta(BaseModel):
    name: str
    size: int
    exists: bool


class EvidenceMeta(BaseModel):
    files: list[EvidenceFileMeta]


class TranscriptEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    cls: str
    label: str
    body: str
    ts: str


class TranscriptResponse(BaseModel):
    events: list[dict[str, Any]]


class LastRun(BaseModel):
    run_id: str
    verdict: str | None = None


class TaskRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    goal: str | None = None
    status: str | None = None
    repo: str | None = None
    last_run: LastRun | None = None


class TaskListResponse(BaseModel):
    tasks: list[TaskRow]
    last: dict[str, LastRun]
    running: bool


class TaskFields(BaseModel):
    task_id: str
    goal: str
    repo: str
    accept: list[str]
    verify: str
    constraints: list[str]
    allowed_tools: str
    max_attempts: str
    status: str
    body: str


class TaskDetail(BaseModel):
    fields: TaskFields
    body: str


class ReposResponse(BaseModel):
    repos: list[str]


class MonitorSnapshot(BaseModel):
    status: dict[str, Any] | None
    recent: list[RunRow]
    unreviewed: int
    pending: int
    phases: list[list[str]]


class LiveRole(BaseModel):
    label: str
    events: list[dict[str, Any]]


class LiveSnapshot(BaseModel):
    run_id: str
    status: dict[str, Any] | None
    active: bool
    roles: list[LiveRole]


class MetaResponse(BaseModel):
    repos: list[str]
    statuses: list[str]
    judgment_fields: list[list[str]]


# --- 入力(書き込み)モデル。extra="forbid" で未知キー拒否 ---

class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = None  # POST 時のみ。PUT は path から取る
    goal: str = ""
    repo: str = ""
    accept: list[str] = []
    verify: str = ""
    constraints: list[str] = []
    allowed_tools: str = ""
    max_attempts: str = ""  # str 受けのまま runner で int 化(後方互換)
    status: str = "todo"
    body: str = ""


class JudgmentInput(BaseModel):
    """判断は trust/risk/checks/learning の4キーのみ。全デフォルト空文字。

    サーバはどのフィールドにも値を合成しない。model_dump() を無変換で write_judgment へ。
    """

    model_config = ConfigDict(extra="forbid")

    trust: str = ""
    risk: str = ""
    checks: str = ""
    learning: str = ""


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = ""
    repo: str = ""
    auto_run: bool = False


class RunStartResult(BaseModel):
    accepted: bool
    reason: str | None = None


class TaskIdResult(BaseModel):
    task_id: str


# --- 分析ダッシュボード(§5)。行形を OpenAPI 正本へ。loop.db は使い捨てレンズ ---
# 集計は事実の提示のみ。SQL の AVG/SUM は空集合で null になりうるので各列は Optional。


class _StatsEnvelope(BaseModel):
    """集計レスポンスの封筒。source/generated_at で loop.db が非 authoritative であることを明示。"""

    generated_at: str
    source: str
    has_more: bool = False


class SummaryRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_runs: int | None = None
    reviewed: int | None = None
    unreviewed: int | None = None
    # 'pass' は予約語のため alias で受ける(出力キーは by_alias=True で 'pass')。
    pass_: int | None = Field(default=None, alias="pass")
    fail: int | None = None
    distinct_skills: int | None = None


class SummaryResponse(_StatsEnvelope):
    rows: list[SummaryRow]


class PassRateRow(BaseModel):
    skill_sha: str | None = None
    pass_rate: float | None = None
    avg_cost: float | None = None
    n: int | None = None


class PassRateResponse(_StatsEnvelope):
    rows: list[PassRateRow]


class VerdictSummaryRow(BaseModel):
    verdict: str | None = None
    n: int | None = None
    unreviewed: int | None = None
    avg_cost: float | None = None
    avg_turns: float | None = None


class VerdictSummaryResponse(_StatsEnvelope):
    rows: list[VerdictSummaryRow]


class GamingSuspectRow(BaseModel):
    run_id: str
    task: str | None = None
    test_verdict: str | None = None
    verifier_verdict: str | None = None
    verifier_confidence: str | None = None
    started_at: str | None = None


class GamingSuspectsResponse(_StatsEnvelope):
    rows: list[GamingSuspectRow]


class CostTimelineRow(BaseModel):
    run_id: str
    started_at: str | None = None
    cost_usd: float | None = None
    turns: int | None = None
    verdict: str | None = None
    skill_sha: str | None = None


class CostTimelineResponse(_StatsEnvelope):
    rows: list[CostTimelineRow]


# RunRow が loopdb.COLUMNS の部分集合であることを起動時に検証(乖離防止。§2.4)
_declared = set(RunRow.model_fields)
_missing = _declared - set(loopdb.COLUMNS) - {"run_id"}
assert not _missing, f"RunRow に loopdb.COLUMNS 外のフィールド: {_missing}"
