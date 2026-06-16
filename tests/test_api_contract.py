# /// script
# requires-python = "==3.12.*"
# dependencies = ["fastapi", "uvicorn[standard]", "jinja2", "python-multipart", "pyyaml", "pytest", "httpx"]
# ///
"""P0 API の契約テスト: 書き込みが契約ファイル(MD + git)へ着地すること、
判断系がサーバ側で何も生成しないこと(全空入力→全空セクション)を固定する。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import runner  # noqa: E402
from webapp import util  # noqa: E402


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
    for attr in ("DATA", "RUNS", "DB"):
        monkeypatch.setattr(util, attr, getattr(runner, attr))
    return data


@pytest.fixture
def client():
    from webapp.main import app
    return TestClient(app)


def test_create_task_writes_md_and_commits(isolated_data, client):
    r = client.post("/api/tasks", json={"task_id": "demo-task", "goal": "デモ目標"})
    assert r.status_code == 201, r.text
    assert r.json()["task_id"] == "demo-task"

    md = isolated_data / "tasks" / "demo-task.md"
    assert md.exists(), "契約ファイルが書かれていない"
    assert "デモ目標" in md.read_text(encoding="utf-8")

    log = subprocess.run(["git", "log", "--oneline"], cwd=isolated_data,
                         capture_output=True, text=True).stdout
    assert "demo-task" in log, "auto_commit されていない"


def test_create_task_duplicate_409(isolated_data, client):
    client.post("/api/tasks", json={"task_id": "dup", "goal": "x"})
    r = client.post("/api/tasks", json={"task_id": "dup", "goal": "y"})
    assert r.status_code == 409


def test_create_task_rejects_bad_id(isolated_data, client):
    r = client.post("/api/tasks", json={"task_id": "../evil", "goal": "x"})
    assert r.status_code == 400


def test_judgment_extra_field_forbidden(isolated_data, client):
    (isolated_data / "runs" / "r1.md").write_text("---\ntask: x\n---\n", encoding="utf-8")
    r = client.post("/api/runs/r1/judgment", json={"trust": "ok", "evil": "x"})
    assert r.status_code == 422, "extra=forbid が効いていない"


def test_judgment_empty_stays_empty(isolated_data, client):
    """全空入力で判断セクションも全空 = サーバが生成・補完しない(§2.6)。"""
    md = isolated_data / "runs" / "r2.md"
    md.write_text("---\ntask: x\nverdict: pass\n---\n\n## エージェントがやったこと\n事実\n", encoding="utf-8")
    r = client.post("/api/runs/r2/judgment", json={})
    assert r.status_code == 204, r.text
    judged = runner.parse_judgment(md)
    assert all(v == "" for v in judged.values()), "サーバが判断を合成した"


def test_runs_list_returns_json(isolated_data, client):
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert "runs" in r.json() and "verdicts" in r.json()
