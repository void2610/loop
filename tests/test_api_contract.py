# /// script
# requires-python = "==3.12.*"
# dependencies = ["fastapi", "uvicorn[standard]", "jinja2", "python-multipart", "pyyaml", "pytest", "httpx"]
# ///
"""P0 API の契約テスト: 書き込みが契約ファイル(MD + git)へ着地すること、
判断系がサーバ側で何も生成しないこと(全空入力→全空セクション)を固定する。

絶対原則の回帰防止に振っている:
- 種類B(判断)はサーバが合成しない(全空入力→全空セクション)。
- 削除エンドポイントは存在せず archive のみ(ログは資産)。
- read 系のパストラバーサル防御 / id 検証は緩めない。
- dispatch は実プロセスを起こさず 404/409 を素直に返す(ここでは Popen をスタブ)。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loopdb  # noqa: E402
import runner  # noqa: E402
from webapp import util  # noqa: E402
from webapp.api import stats as stats_api  # noqa: E402


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """runner / util のパス globals を temp git repo に差し替える。"""
    data = tmp_path / "data"
    (data / "tasks").mkdir(parents=True)
    (data / "runs").mkdir(parents=True)
    (data / "review-notes.md").write_text("# review-notes\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=data, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=data, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=data, check=True)

    for mod in (runner,):
        monkeypatch.setattr(mod, "DATA", data)
        monkeypatch.setattr(mod, "TASKS_DIR", data / "tasks")
        monkeypatch.setattr(mod, "RUNS", data / "runs")
        monkeypatch.setattr(mod, "DB", data / "loop.db")
        monkeypatch.setattr(mod, "REVIEW_NOTES", data / "review-notes.md")
        monkeypatch.setattr(mod, "NORMS_ROOT", data / "repo")
    for attr in ("DATA", "RUNS", "DB"):
        monkeypatch.setattr(util, attr, getattr(runner, attr))
    # stats は `from ..util import DB` で import 時に束縛するので個別に差し替える。
    monkeypatch.setattr(stats_api, "DB", runner.DB)
    return data


@pytest.fixture
def client():
    from webapp.main import app
    return TestClient(app)


# --- テスト用の小道具 ---

def _write_run(data: Path, run_id: str, *, front: str = "task: x\nverdict: pass\n",
               body: str = "\n## エージェントがやったこと\n事実\n") -> Path:
    md = data / "runs" / f"{run_id}.md"
    md.write_text(f"---\n{front}---\n{body}", encoding="utf-8")
    return md


def _git_log(data: Path) -> str:
    return subprocess.run(["git", "log", "--oneline"], cwd=data,
                          capture_output=True, text=True).stdout


# =====================================================================
# tasks: CRUD + archive
# =====================================================================

def test_create_task_writes_md_and_commits(isolated_data, client):
    r = client.post("/api/tasks", json={"task_id": "demo-task", "goal": "デモ目標"})
    assert r.status_code == 201, r.text
    assert r.json()["task_id"] == "demo-task"

    md = isolated_data / "tasks" / "demo-task.md"
    assert md.exists(), "契約ファイルが書かれていない"
    assert "デモ目標" in md.read_text(encoding="utf-8")
    assert "demo-task" in _git_log(isolated_data), "auto_commit されていない"


def test_create_task_duplicate_409(isolated_data, client):
    client.post("/api/tasks", json={"task_id": "dup", "goal": "x"})
    r = client.post("/api/tasks", json={"task_id": "dup", "goal": "y"})
    assert r.status_code == 409


def test_create_task_rejects_bad_id(isolated_data, client):
    r = client.post("/api/tasks", json={"task_id": "../evil", "goal": "x"})
    assert r.status_code == 400


def test_create_task_rejects_unknown_field(isolated_data, client):
    """TaskInput は extra=forbid。未知キーを差し込ませない(§2.4)。"""
    r = client.post("/api/tasks", json={"task_id": "ex", "goal": "g", "secret": 1})
    assert r.status_code == 422


def test_create_task_persists_all_fields(isolated_data, client):
    r = client.post("/api/tasks", json={
        "task_id": "full", "goal": "目標", "repo": "myrepo",
        "accept": ["A1", "  ", "A2"], "verify": "pytest -q",
        "constraints": ["C1"], "allowed_tools": "Read, Bash",
        "max_attempts": "3", "status": "todo"})
    assert r.status_code == 201, r.text
    fm, _ = runner.read_task("full")
    assert fm["goal"] == "目標"
    assert fm["repo"] == "myrepo"
    assert fm["accept"] == ["A1", "A2"], "空文字を落としていない"
    assert fm["verify"] == "pytest -q"
    assert fm["constraints"] == ["C1"]
    assert fm["max_attempts"] == 3, "int 化されていない"


def test_task_detail_roundtrip(isolated_data, client):
    client.post("/api/tasks", json={"task_id": "rt", "goal": "G", "verify": "make test"})
    r = client.get("/api/tasks/rt")
    assert r.status_code == 200, r.text
    f = r.json()["fields"]
    assert f["task_id"] == "rt"
    assert f["goal"] == "G"
    assert f["verify"] == "make test"


def test_task_detail_404(isolated_data, client):
    r = client.get("/api/tasks/nope")
    assert r.status_code == 404


def test_task_detail_bad_id_400(isolated_data, client):
    r = client.get("/api/tasks/_hidden")
    assert r.status_code == 400


def test_update_task_writes_and_commits(isolated_data, client):
    client.post("/api/tasks", json={"task_id": "upd", "goal": "old"})
    r = client.put("/api/tasks/upd", json={"goal": "new", "status": "todo"})
    assert r.status_code == 200, r.text
    fm, _ = runner.read_task("upd")
    assert fm["goal"] == "new"
    assert "upd" in _git_log(isolated_data)


def test_list_tasks_excludes_archived_by_default(isolated_data, client):
    client.post("/api/tasks", json={"task_id": "vis", "goal": "g"})
    client.post("/api/tasks", json={"task_id": "hid", "goal": "g"})
    runner.set_task_archived("hid", True)

    ids = [t["id"] for t in client.get("/api/tasks").json()["tasks"]]
    assert "vis" in ids and "hid" not in ids

    ids_all = [t["id"] for t in client.get("/api/tasks?include_archived=true").json()["tasks"]]
    assert "hid" in ids_all


def test_archive_task_is_reversible_no_delete(isolated_data, client):
    client.post("/api/tasks", json={"task_id": "arc", "goal": "g"})
    md = isolated_data / "tasks" / "arc.md"

    assert client.post("/api/tasks/arc/archive", json={"archived": True}).status_code == 204
    assert md.exists(), "アーカイブは削除ではない(ファイルは残る)"
    assert "archived: true" in md.read_text(encoding="utf-8")

    assert client.post("/api/tasks/arc/archive", json={"archived": False}).status_code == 204
    assert "archived: false" in md.read_text(encoding="utf-8")


def test_archive_task_404(isolated_data, client):
    r = client.post("/api/tasks/ghost/archive", json={"archived": True})
    assert r.status_code == 404


def test_no_delete_endpoint_exists(isolated_data, client):
    """削除を復活させない(ログは資産)。DELETE は許可しない。"""
    assert client.delete("/api/tasks/whatever").status_code in (404, 405)
    assert client.delete("/api/runs/whatever").status_code in (404, 405)


# =====================================================================
# runs: 読み取り / judgment / message / stop / pr / archive
# =====================================================================

def test_run_detail_404(isolated_data, client):
    assert client.get("/api/runs/missing").status_code == 404


def test_run_detail_exposes_empty_judgment_scaffold(isolated_data, client):
    _write_run(isolated_data, "rd")
    r = client.get("/api/runs/rd")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["summary"] == "事実"
    assert set(j["judgment"]) == {"trust", "risk", "checks", "learning"}
    assert all(v == "" for v in j["judgment"].values()), "判断は空で出す(サーバが合成しない)"
    assert [f[0] for f in j["judgment_fields"]] == ["trust", "risk", "checks", "learning"]


def test_runs_list_returns_json(isolated_data, client):
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert "runs" in r.json() and "verdicts" in r.json()


def test_runs_list_reflects_md_and_filters(isolated_data, client):
    _write_run(isolated_data, "p1", front="task: alpha\nverdict: pass\n")
    _write_run(isolated_data, "f1", front="task: beta\nverdict: fail\n")
    rows = client.get("/api/runs").json()["runs"]
    ids = {r["run_id"] for r in rows}
    assert {"p1", "f1"} <= ids

    only_pass = client.get("/api/runs?verdict=pass").json()["runs"]
    assert {r["run_id"] for r in only_pass} == {"p1"}


def test_runs_list_excludes_archived_by_default(isolated_data, client):
    _write_run(isolated_data, "ar", front="task: x\nverdict: pass\narchived: true\n")
    _write_run(isolated_data, "vr", front="task: x\nverdict: pass\n")
    ids = {r["run_id"] for r in client.get("/api/runs").json()["runs"]}
    assert "vr" in ids and "ar" not in ids
    ids_all = {r["run_id"] for r in client.get("/api/runs?include_archived=true").json()["runs"]}
    assert "ar" in ids_all


def test_judgment_extra_field_forbidden(isolated_data, client):
    _write_run(isolated_data, "j1", front="task: x\n")
    r = client.post("/api/runs/j1/judgment", json={"trust": "ok", "evil": "x"})
    assert r.status_code == 422, "extra=forbid が効いていない"


def test_judgment_empty_stays_empty(isolated_data, client):
    """全空入力で判断セクションも全空 = サーバが生成・補完しない(§2.6)。"""
    md = _write_run(isolated_data, "j2")
    r = client.post("/api/runs/j2/judgment", json={})
    assert r.status_code == 204, r.text
    judged = runner.parse_judgment(md)
    assert all(v == "" for v in judged.values()), "サーバが判断を合成した"


def test_judgment_persists_human_text(isolated_data, client):
    """人間が書いた散文はそのまま契約ファイルへ着地する(中継のみ)。"""
    md = _write_run(isolated_data, "j3")
    r = client.post("/api/runs/j3/judgment", json={
        "trust": "信用できる", "risk": "なし", "checks": "境界値テスト", "learning": "学んだ"})
    assert r.status_code == 204, r.text
    judged = runner.parse_judgment(md)
    assert judged["trust"] == "信用できる"
    assert judged["learning"] == "学んだ"
    assert "境界値テスト" in (isolated_data / "review-notes.md").read_text(encoding="utf-8")


def test_judgment_human_verdict_written_to_front_matter(isolated_data, client):
    """human_verdict は人間が verdict を覆すときの構造化シグナル。front-matter に刻まれる。"""
    md = _write_run(isolated_data, "j4", front="task: x\nverdict: pass\n")
    # verdict と同値にして maybe_draft_on_review の起草経路(副作用)を踏まない。
    r = client.post("/api/runs/j4/judgment", json={"human_verdict": "pass"})
    assert r.status_code == 204, r.text
    assert "human_verdict: pass" in md.read_text(encoding="utf-8")


def test_judgment_404_when_run_missing(isolated_data, client):
    r = client.post("/api/runs/ghost/judgment", json={})
    assert r.status_code == 404


def test_archive_run_is_reversible(isolated_data, client):
    md = _write_run(isolated_data, "ra")
    assert client.post("/api/runs/ra/archive", json={"archived": True}).status_code == 204
    assert md.exists()
    assert "archived: true" in md.read_text(encoding="utf-8")
    assert client.post("/api/runs/ra/archive", json={"archived": False}).status_code == 204


def test_archive_run_404(isolated_data, client):
    assert client.post("/api/runs/ghost/archive", json={"archived": True}).status_code == 404


def test_message_appends_inbox(isolated_data, client):
    rd = isolated_data / "runs" / "m1"
    rd.mkdir()
    r = client.post("/api/runs/m1/message", json={"text": "続けて"})
    assert r.status_code == 204, r.text
    lines = (rd / "inbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["text"] == "続けて"


def test_message_rejects_empty(isolated_data, client):
    (isolated_data / "runs" / "m2").mkdir()
    assert client.post("/api/runs/m2/message", json={"text": "  "}).status_code == 400


def test_message_404_when_no_run_dir(isolated_data, client):
    assert client.post("/api/runs/m3/message", json={"text": "x"}).status_code == 404


def test_stop_writes_marker(isolated_data, client):
    rd = isolated_data / "runs" / "s1"
    rd.mkdir()
    assert client.post("/api/runs/s1/stop").status_code == 204
    assert (rd / "stop").exists(), "停止マーカーが置かれていない"


def test_stop_404_when_no_run_dir(isolated_data, client):
    assert client.post("/api/runs/s2/stop").status_code == 404


def test_pr_status_empty_without_pr_url(isolated_data, client):
    """pr_url の無い run は all-None を返す(gh を叩かない)。"""
    _write_run(isolated_data, "pr1", front="task: x\nverdict: pass\n")
    r = client.get("/api/runs/pr1/pr")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["number"] is None and j["url"] is None and j["merged"] is False


# =====================================================================
# evidence: 存在フラグ / 本文配信の allowlist & traversal 防御
# =====================================================================

def test_evidence_meta_reports_sizes(isolated_data, client):
    rd = isolated_data / "runs" / "e1"
    rd.mkdir()
    (rd / "change.patch").write_text("diff", encoding="utf-8")
    files = {f["name"]: f for f in client.get("/api/runs/e1/evidence").json()["files"]}
    assert files["change.patch"]["exists"] and files["change.patch"]["size"] == 4
    assert files["test-output.txt"]["exists"] is False


def test_evidence_file_served_when_allowlisted(isolated_data, client):
    rd = isolated_data / "runs" / "e2"
    rd.mkdir()
    (rd / "change.patch").write_text("PATCH-BODY", encoding="utf-8")
    r = client.get("/api/runs/e2/files/change.patch")
    assert r.status_code == 200
    assert r.text == "PATCH-BODY"


def test_evidence_file_rejects_non_allowlisted(isolated_data, client):
    rd = isolated_data / "runs" / "e3"
    rd.mkdir()
    (rd / "secret.env").write_text("KEY=1", encoding="utf-8")
    r = client.get("/api/runs/e3/files/secret.env")
    assert r.status_code == 404, "allowlist 外は配信しない"


def test_evidence_file_allows_suffix_streams(isolated_data, client):
    rd = isolated_data / "runs" / "e4"
    rd.mkdir()
    (rd / "implementer.stream.jsonl").write_text("{}", encoding="utf-8")
    assert client.get("/api/runs/e4/files/implementer.stream.jsonl").status_code == 200


def test_transcript_404_when_missing(isolated_data, client):
    (isolated_data / "runs" / "t0").mkdir()
    assert client.get("/api/runs/t0/transcript").status_code == 404


def test_transcript_folds_events(isolated_data, client):
    rd = isolated_data / "runs" / "t1"
    rd.mkdir()
    events = [
        {"type": "user", "message": {"content": "やって"}, "timestamp": "2026-06-18T10:00:00Z"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "了解"}]},
         "timestamp": "2026-06-18T10:00:01Z"},
    ]
    (rd / "transcript.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8")
    out = client.get("/api/runs/t1/transcript").json()["events"]
    assert [e["cls"] for e in out] == ["user", "assistant"]
    assert out[0]["body"] == "やって"


# =====================================================================
# meta / monitor / live: 設定の単一ソース & スナップショット
# =====================================================================

def test_meta_exposes_config_single_source(isolated_data, client):
    j = client.get("/api/meta").json()
    assert j["statuses"] == util.STATUSES
    assert [f[0] for f in j["judgment_fields"]] == ["trust", "risk", "checks", "learning"]
    assert "none" in j["repos"]


def test_monitor_snapshot_counts(isolated_data, client):
    _write_run(isolated_data, "mp", front="task: x\nverdict: pass\nreviewed: 0\n")
    client.post("/api/tasks", json={"task_id": "pend", "goal": "g"})
    client.get("/api/runs")  # monitor は reindex しない契約。先に loop.db を作る
    j = client.get("/api/monitor").json()
    assert j["status"] is None, "実行中でなければ status は None"
    assert j["pending"] >= 1, "todo タスクが pending に数えられる"
    assert any(r["run_id"] == "mp" for r in j["recent"])


def test_run_live_no_streams(isolated_data, client):
    (isolated_data / "runs" / "lv").mkdir()
    j = client.get("/api/runs/lv/live").json()
    assert j["active"] is False
    assert j["roles"] == []
    assert j["intervention"] is None


def test_run_live_surfaces_intervention(isolated_data, client):
    rd = isolated_data / "runs" / "lv2"
    rd.mkdir()
    (rd / "intervention.json").write_text(
        json.dumps({"question": "どちらの方針にしますか?"}), encoding="utf-8")
    j = client.get("/api/runs/lv2/live").json()
    assert j["intervention"] == "どちらの方針にしますか?"


# =====================================================================
# dispatch: 実プロセスは起こさない(Popen をスタブ)。404/409/400 を検証
# =====================================================================

@pytest.fixture
def no_popen(monkeypatch):
    """dispatch が subprocess.Popen で claude -p を起こさないようにスタブ。
    呼ばれた引数を記録し、実際の実行を防ぐ(テストでライブ run を起こさない)。"""
    calls = []
    from webapp.api import dispatch as dispatch_api

    def fake_popen(args, *a, **k):
        calls.append(args)
        return None

    # モジュール属性 subprocess.Popen を直接潰すと git の subprocess.run まで巻き込むので、
    # dispatch が参照する `subprocess` 名前だけを Popen のみ持つ namespace に差し替える。
    monkeypatch.setattr(dispatch_api, "subprocess",
                        types.SimpleNamespace(Popen=fake_popen))
    return calls


def test_run_task_404_for_missing(isolated_data, client, no_popen):
    assert client.post("/api/tasks/ghost/run").status_code == 404
    assert no_popen == [], "存在しないタスクで実行を起こさない"


def test_run_task_accepted(isolated_data, client, no_popen):
    client.post("/api/tasks", json={"task_id": "go", "goal": "g"})
    r = client.post("/api/tasks/go/run")
    assert r.status_code == 202, r.text
    assert r.json()["accepted"] is True
    assert no_popen and no_popen[-1][:3] == ["uv", "run", "runner.py"]


def test_run_task_busy_409(isolated_data, client, no_popen):
    client.post("/api/tasks", json={"task_id": "go", "goal": "g"})
    (isolated_data / ".run.lock").write_text("{}", encoding="utf-8")
    r = client.post("/api/tasks/go/run")
    assert r.status_code == 409
    assert r.json()["accepted"] is False and r.json()["reason"] == "busy"
    assert no_popen == [], "busy のとき新たな実行を起こさない"


def test_dispatch_busy_409(isolated_data, client, no_popen):
    (isolated_data / ".run.lock").write_text("{}", encoding="utf-8")
    assert client.post("/api/dispatch").status_code == 409


def test_generate_rejects_empty_prompt(isolated_data, client, no_popen):
    assert client.post("/api/tasks/generate", json={"prompt": "  "}).status_code == 400
    assert no_popen == []


def test_generate_sets_lock_and_spawns(isolated_data, client, no_popen):
    r = client.post("/api/tasks/generate", json={"prompt": "ダウンロードを整理"})
    assert r.status_code == 202, r.text
    assert (isolated_data / ".gen.lock").exists(), "生成中ロックを即時に立てる"
    assert no_popen and "gen" in no_popen[-1]


# =====================================================================
# analytics(stats): loop.db read-only。事実集計のみ。DB 不在で 404
# =====================================================================

def _seed_db(data: Path) -> None:
    _write_run(data, "a1", front=(
        "task: t\nverdict: pass\nreviewed: 1\ncost_usd: 0.5\nturns: 10\n"
        "skill_sha: aaa\nstarted_at: 2026-06-01T00:00:00\n"))
    _write_run(data, "a2", front=(
        "task: t\nverdict: fail\nreviewed: 0\ncost_usd: 0.3\nturns: 7\n"
        "skill_sha: aaa\nstarted_at: 2026-06-02T00:00:00\n"))
    conn = loopdb.connect(data / "loop.db")
    loopdb.reindex(conn, data / "runs")
    conn.close()


def test_analytics_404_without_db(isolated_data, client):
    assert not (isolated_data / "loop.db").exists()
    assert client.get("/api/analytics/summary").status_code == 404


def test_analytics_summary_counts(isolated_data, client):
    _seed_db(isolated_data)
    r = client.get("/api/analytics/summary")
    assert r.status_code == 200, r.text
    j = r.json()
    assert "loop.db" in j["source"], "封筒で非 authoritative を明示"
    row = j["rows"][0]
    assert row["total_runs"] == 2
    assert row["pass"] == 1 and row["fail"] == 1


def test_analytics_verdict_summary(isolated_data, client):
    _seed_db(isolated_data)
    r = client.get("/api/analytics/verdict-summary")
    assert r.status_code == 200, r.text
    verdicts = {row["verdict"]: row["n"] for row in r.json()["rows"]}
    assert verdicts.get("pass") == 1 and verdicts.get("fail") == 1


def test_analytics_cost_timeline_window_and_paging(isolated_data, client):
    _seed_db(isolated_data)
    full = client.get("/api/analytics/cost-timeline").json()["rows"]
    assert [r["run_id"] for r in full] == ["a1", "a2"], "started_at 昇順"

    windowed = client.get("/api/analytics/cost-timeline?since=2026-06-02T00:00:00").json()["rows"]
    assert [r["run_id"] for r in windowed] == ["a2"], "since で範囲を絞る"

    paged = client.get("/api/analytics/cost-timeline?limit=1")
    assert len(paged.json()["rows"]) == 1
    assert paged.json()["has_more"] is True, "limit ぴったりで has_more"


def test_analytics_does_not_synthesize_labels(isolated_data, client):
    """事実集計のみ。危険/要改善などの判断ラベル・推奨キーを足さない(§5)。"""
    _seed_db(isolated_data)
    text = client.get("/api/analytics/summary").text
    for banned in ("危険", "要改善", "推奨", "recommend"):
        assert banned not in text


# =====================================================================
# norms(知識更新エージェント): 閲覧 + 昇格/却下の中継
# =====================================================================

def _write_candidate(data: Path, repo_name: str, cid: str, status: str = "pending") -> Path:
    d = data / "repo" / repo_name
    d.mkdir(parents=True, exist_ok=True)
    cpath = d / "candidates.md"
    with cpath.open("a", encoding="utf-8") as f:
        f.write(f"## {cid}\n- observed_friction: 摩擦の事実\n- proposed_norm: こう振る舞う\n"
                f"- evidence_runs: [run-x]\n- status: {status}\n- drafted_at: 2026-06-18T10:00:00+09:00\n")
    return cpath


def test_norms_empty(isolated_data, client):
    j = client.get("/api/norms").json()
    assert j["repos"] == [] and j["activity"] == []


def test_norms_lists_candidates_and_conventions(isolated_data, client):
    _write_candidate(isolated_data, "git-test", "candidate-run1-1")
    (isolated_data / "repo" / "git-test" / "conventions.md").write_text(
        "# 現在の知識\nルールA を守る\n", encoding="utf-8")
    repo = next(r for r in client.get("/api/norms").json()["repos"] if r["name"] == "git-test")
    assert repo["has_conventions"] and "ルールA" in repo["conventions"]
    c = repo["candidates"][0]
    assert c["candidate_id"] == "candidate-run1-1" and c["status"] == "pending"
    assert c["proposed_norm"] == "こう振る舞う"


def test_norms_activity_drafted(isolated_data, client):
    rd = isolated_data / "runs" / "r-act"
    rd.mkdir()
    (isolated_data / "runs" / "r-act.md").write_text(
        "---\nrepo: git-test\nstarted_at: 2026-06-18T10:00:00\n---\n", encoding="utf-8")
    (rd / "norms.json").write_text(
        json.dumps({"trigger": "revise が発生", "candidates": [{"proposed_norm": "x"}]}), encoding="utf-8")
    a = next(x for x in client.get("/api/norms").json()["activity"] if x["run_id"] == "r-act")
    assert a["outcome"] == "drafted" and a["drafted"] == 1 and a["trigger"] == "revise が発生"


def test_norms_activity_empty_and_failed(isolated_data, client):
    for rid, payload in [
        ("r-empty", {"trigger": "t", "candidates": [], "none_reason": "一般化できず"}),
        ("r-fail", {"trigger": "t", "error": "起草に失敗"})]:
        rd = isolated_data / "runs" / rid
        rd.mkdir()
        (rd / "norms.json").write_text(json.dumps(payload), encoding="utf-8")
    acts = {x["run_id"]: x for x in client.get("/api/norms").json()["activity"]}
    assert acts["r-empty"]["outcome"] == "empty" and acts["r-empty"]["none_reason"] == "一般化できず"
    assert acts["r-fail"]["outcome"] == "failed" and acts["r-fail"]["error"] == "起草に失敗"


def test_norms_promote_writes_conventions(isolated_data, client):
    _write_candidate(isolated_data, "git-test", "candidate-run2-1")
    assert client.post("/api/norms/candidate-run2-1/promote").status_code == 204
    conv = (isolated_data / "repo" / "git-test" / "conventions.md").read_text(encoding="utf-8")
    assert "こう振る舞う" in conv, "proposed_norm が conventions.md へ着地していない"
    repo = next(r for r in client.get("/api/norms").json()["repos"] if r["name"] == "git-test")
    assert repo["candidates"][0]["status"] == "promoted"


def test_norms_reject_sets_status_no_conventions(isolated_data, client):
    _write_candidate(isolated_data, "git-test", "candidate-run3-1")
    assert client.post("/api/norms/candidate-run3-1/reject").status_code == 204
    repo = next(r for r in client.get("/api/norms").json()["repos"] if r["name"] == "git-test")
    assert repo["candidates"][0]["status"] == "rejected"
    assert not (isolated_data / "repo" / "git-test" / "conventions.md").exists()


def test_norms_promote_404_unknown(isolated_data, client):
    assert client.post("/api/norms/candidate-nope-1/promote").status_code == 404


def test_norms_rejects_bad_candidate_id(isolated_data, client):
    assert client.post("/api/norms/evil/promote").status_code == 400


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
