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
    archived: int | None = None
    started_at: str | None = None


class RunListResponse(BaseModel):
    runs: list[RunRow]
    verdicts: list[str]


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
    archived: bool = False
    last_run: LastRun | None = None


class TaskListResponse(BaseModel):
    tasks: list[TaskRow]
    last: dict[str, LastRun]
    running: bool
    generating: bool = False


class TaskFields(BaseModel):
    task_id: str
    goal: str
    repo: str
    base_branch: str = ""
    no_pr: bool = False
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


class PromptPreview(BaseModel):
    repo: str | None = None
    repo_history_runs: int
    task_contract: str  # render_prompt(task) — goal+accept+constraints+verify
    author_plan: str  # data/tasks/plans/<id>.md(空可)
    constitution: str  # .claude/plugins/loop-roles/constitution.md
    norms: str  # data/repo/<name>/conventions.md(承認済み)
    repo_brief: str  # 過去 run の事実台帳(build_repo_brief)
    implementer_full: str  # 実際に Implementer に渡る全文


class AuthorPromptPreview(BaseModel):
    repo: str | None = None
    inspect: bool  # repo を read-only 調査するか(false なら brief は注入されない)
    repo_history_runs: int
    repo_section: str  # 「## 対象リポジトリ ...」
    request: str  # 「## 依頼 <prompt>」
    constitution: str
    norms: str
    repo_brief: str
    wrapped: str  # /loop-roles:task-author で連結した user メッセージ全文


class AuthorPromptPreviewInput(BaseModel):
    prompt: str
    repo: str = ""


class ReposResponse(BaseModel):
    repos: list[str]


class BranchesResponse(BaseModel):
    branches: list[str]
    default: str | None = None  # remote/HEAD 由来のデフォルトブランチ(空 repo なら None)


class QueueItem(BaseModel):
    id: str | None = None
    goal: str | None = None
    repo: str | None = None


class MonitorSnapshot(BaseModel):
    status: dict[str, Any] | None  # 後方互換: 単一 run ミラー(.run.lock)
    active: list[dict[str, Any]] = []  # 進行中の全 run(phase != done)
    queue: list[QueueItem] = []  # 待機中(status=todo)
    max_concurrency: int = 1
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
    intervention: str | None = None  # awaiting 時、エージェントが詰まった理由(人間への問い)


class MessageInput(BaseModel):
    text: str  # awaiting 中の run へ送る続行指示(人間=種類B の操作判断)


class PrStatus(BaseModel):
    number: int | None = None
    url: str | None = None
    state: str | None = None   # OPEN / MERGED / CLOSED
    merged: bool = False
    ci: str | None = None      # pass / fail / pending / none


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
    base_branch: str = ""
    no_pr: bool = False
    accept: list[str] = []
    verify: str = ""
    constraints: list[str] = []
    allowed_tools: str = ""
    max_attempts: str = ""  # str 受けのまま runner で int 化(後方互換)
    status: str = "todo"
    body: str = ""


class JudgmentInput(BaseModel):
    """判断は単一の自由記述 notes + 任意の human_verdict。全デフォルト空文字。

    サーバはどのフィールドにも値を合成しない。model_dump() を無変換で write_judgment へ。
    human_verdict は人間が verdict を覆すときだけ選ぶ構造化シグナル(空=覆さない)。
    """

    model_config = ConfigDict(extra="forbid")

    notes: str = ""
    human_verdict: str = ""


class ArchiveInput(BaseModel):
    """アーカイブ(UI 非表示)/解除。削除はしない(ログは資産)。"""

    model_config = ConfigDict(extra="forbid")

    archived: bool = True


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = ""
    repo: str = ""
    base_branch: str = ""
    no_pr: bool = False
    auto_run: bool = False


class GenerateAccepted(BaseModel):
    accepted: bool
    gen_id: str  # ライブ transcript SSE と結果スナップショットの URL に使う


class RunStartResult(BaseModel):
    accepted: bool
    reason: str | None = None


class TaskIdResult(BaseModel):
    task_id: str


# --- 規範記憶(知識更新エージェント)。事実の表示のみ。昇格/却下は人間操作の中継(§2.6) ---


class NormCandidate(BaseModel):
    """candidates.md の候補(承認待ちの控え室)。status は pending/promoted/rejected。"""

    candidate_id: str
    repo: str | None = None
    run_id: str | None = None
    status: str
    observed_friction: str = ""
    proposed_norm: str = ""
    drafted_at: str | None = None


class NormRepo(BaseModel):
    name: str
    conventions: str = ""        # conventions.md の生テキスト(= run に注入される現在の知識)
    has_conventions: bool = False
    candidates: list[NormCandidate] = []


class NormActivity(BaseModel):
    """知識更新エージェントが run ごとに起草を試みた記録(runs/<id>/norms.json 由来)。"""

    run_id: str
    repo: str | None = None
    trigger: str = ""
    outcome: str                 # drafted(抽出) / empty(空振り) / failed(出力不正・timeout)
    drafted: int = 0
    none_reason: str | None = None
    error: str | None = None
    started_at: str | None = None


class NormsResponse(BaseModel):
    repos: list[NormRepo]
    activity: list[NormActivity]
    generated_at: str


class ConventionsInput(BaseModel):
    """承認済み知識(conventions.md)の本文。人間が直接編集する(統合・剪定・修正)。"""

    model_config = ConfigDict(extra="forbid")

    text: str = ""


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


# --- Fleet(複数 PC で1つの GUI から全 PC を扱う面)---

class FleetPeer(BaseModel):
    """Fleet を構成する 1 台分の情報。url は Tailnet 経由の Next フロント URL(/api/* を中継)。"""

    name: str             # 表示名・識別子(loop.local.toml [data] dir の host 名と揃える)
    url: str              # 例: "http://shuyamacbook-pro.taila217e5.ts.net:3000"
    is_self: bool = False  # この応答を返した backend 自身であるか


class FleetInfo(BaseModel):
    """GET /api/fleet/peers のレスポンス。peers が空なら Fleet 機能 off(従来通り単一 PC 表示)。"""

    self_name: str | None = None     # 自 host 名(設定が無ければ None)
    peers: list[FleetPeer] = []
