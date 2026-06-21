# /// script
# requires-python = "==3.12.*"
# dependencies = ["pytest"]
# ///
"""loopdb(SQLite インデックス層)の不変条件テスト。

絶対原則 §1.2 / §2.5 の回帰防止: loop.db は派生で、reindex で MD 全件から
完全再生成できる(rm loop.db && reindex で壊れない)。さらに COLUMNS / SCHEMA /
_coerce の三重定義がドリフトしていないことを固定する(列を1つ足し忘れたら検出)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loopdb  # noqa: E402


def _write_run(runs: Path, run_id: str, front: str) -> None:
    (runs / f"{run_id}.md").write_text(f"---\n{front}---\n\n本文\n", encoding="utf-8")


@pytest.fixture
def runs_dir(tmp_path):
    d = tmp_path / "runs"
    d.mkdir()
    _write_run(d, "a1", "task: t\nverdict: pass\nreviewed: 1\ncost_usd: 0.5\nturns: 10\n")
    _write_run(d, "a2", "task: t\nverdict: fail\nreviewed: 0\ncost_usd: 0.3\nturns: 7\n")
    _write_run(d, "a3", "task: u\nverdict: pass\narchived: true\n")
    return d


def _all_rows(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY run_id")]


def test_coerce_keys_match_columns():
    """_coerce が返すキー集合が COLUMNS と一致(列の足し忘れ/余りを検出)。"""
    row = loopdb._coerce({}, "x", "x.md")
    assert set(row) == set(loopdb.COLUMNS)


def test_schema_columns_match_columns(tmp_path):
    """SQLite テーブルの実列が COLUMNS と順序込みで一致(SCHEMA とのドリフト検出)。"""
    conn = loopdb.connect(tmp_path / "loop.db")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(runs)")]
    conn.close()
    assert cols == loopdb.COLUMNS


def test_reindex_counts_and_coerces(runs_dir, tmp_path):
    conn = loopdb.connect(tmp_path / "loop.db")
    n = loopdb.reindex(conn, runs_dir)
    assert n == 3
    rows = {r["run_id"]: r for r in _all_rows(conn)}
    assert rows["a1"]["verdict"] == "pass" and rows["a1"]["reviewed"] == 1
    assert rows["a1"]["cost_usd"] == 0.5 and rows["a1"]["turns"] == 10
    assert rows["a2"]["reviewed"] == 0
    assert rows["a3"]["archived"] == 1
    conn.close()


def test_reindex_is_idempotent(runs_dir, tmp_path):
    """同一 conn で reindex を繰り返しても件数・内容が不変(冪等)。"""
    conn = loopdb.connect(tmp_path / "loop.db")
    loopdb.reindex(conn, runs_dir)
    first = _all_rows(conn)
    loopdb.reindex(conn, runs_dir)
    loopdb.reindex(conn, runs_dir)
    assert _all_rows(conn) == first
    conn.close()


def test_reindex_full_regeneration_after_unlink(runs_dir, tmp_path):
    """rm loop.db && reindex で壊れず同一行集合を再生成できる(§1.2 の不変条件)。"""
    db = tmp_path / "loop.db"
    conn = loopdb.connect(db)
    loopdb.reindex(conn, runs_dir)
    before = _all_rows(conn)
    conn.close()

    db.unlink()
    assert not db.exists()
    conn = loopdb.connect(db)
    loopdb.reindex(conn, runs_dir)
    assert _all_rows(conn) == before
    conn.close()


def test_reindex_reflects_md_changes(runs_dir, tmp_path):
    """MD が真実: 行の更新・削除も reindex で MD に追従する。"""
    conn = loopdb.connect(tmp_path / "loop.db")
    loopdb.reindex(conn, runs_dir)
    assert len(_all_rows(conn)) == 3

    (runs_dir / "a3.md").unlink()
    _write_run(runs_dir, "a2", "task: t\nverdict: pass\n")  # fail → pass に書き換え
    loopdb.reindex(conn, runs_dir)
    rows = {r["run_id"]: r for r in _all_rows(conn)}
    assert set(rows) == {"a1", "a2"}
    assert rows["a2"]["verdict"] == "pass"
    conn.close()


def test_parse_front_matter_flat_scalars():
    """loop.db index は stdlib 縛りの flat パーサ(クォート無しスカラ前提)。"""
    fm = loopdb.parse_front_matter("---\ntask: t\nverdict: pass\n---\nbody")
    assert fm == {"task": "t", "verdict": "pass"}
    assert loopdb.parse_front_matter("no front matter") == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
