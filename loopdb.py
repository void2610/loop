"""SQLite インデックス層(ビュー)。

authoritative state を持たない。runs/*.md の front-matter をそのまま列にしただけで、
`reindex()` で MD 全件から完全再生成できる(§2.5-2)。stdlib sqlite3 のみ。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

COLUMNS = [
    "run_id", "task", "verdict", "reviewed", "model", "cost_usd", "turns",
    "duration_ms", "session_id", "repo_sha", "skill_sha", "goal_contract_sha",
    "started_at", "md_path",
    "test_verdict", "verifier_verdict", "verifier_confidence", "repo", "archived",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id            TEXT PRIMARY KEY,
  task              TEXT,
  verdict           TEXT,
  reviewed          INTEGER,
  model             TEXT,
  cost_usd          REAL,
  turns             INTEGER,
  duration_ms       INTEGER,
  session_id        TEXT,
  repo_sha          TEXT,
  skill_sha         TEXT,
  goal_contract_sha TEXT,
  started_at        TEXT,
  md_path           TEXT,
  test_verdict        TEXT,
  verifier_verdict    TEXT,
  verifier_confidence TEXT,
  repo                TEXT,
  archived            INTEGER
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def parse_front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm: dict = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def _coerce(fm: dict, run_id: str, md_path: str) -> dict:
    def num(key, cast):
        v = fm.get(key)
        try:
            return cast(v)
        except (TypeError, ValueError):
            return None

    reviewed = str(fm.get("reviewed", "false")).lower() in ("true", "1")
    return {
        "run_id": run_id,
        "task": fm.get("task"),
        "verdict": fm.get("verdict"),
        "reviewed": 1 if reviewed else 0,
        "model": fm.get("model"),
        "cost_usd": num("cost_usd", float),
        "turns": num("turns", int),
        "duration_ms": num("duration_ms", int),
        "session_id": fm.get("session_id"),
        "repo_sha": fm.get("repo_sha"),
        "skill_sha": fm.get("skill_sha"),
        "goal_contract_sha": fm.get("goal_contract_sha"),
        "started_at": fm.get("started_at"),
        "md_path": md_path,
        "test_verdict": fm.get("test_verdict"),
        "verifier_verdict": fm.get("verifier_verdict"),
        "verifier_confidence": fm.get("verifier_confidence"),
        "repo": fm.get("repo"),
        "archived": 1 if str(fm.get("archived", "false")).lower() in ("true", "1") else 0,
    }


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    placeholders = ",".join("?" for _ in COLUMNS)
    conn.execute(
        f"INSERT OR REPLACE INTO runs ({','.join(COLUMNS)}) VALUES ({placeholders})",
        [row[c] for c in COLUMNS],
    )
    conn.commit()


def upsert_md(conn: sqlite3.Connection, md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    row = _coerce(parse_front_matter(text), md_path.stem, str(md_path.name))
    upsert(conn, row)
    return row


def reindex(conn: sqlite3.Connection, runs_dir: Path) -> int:
    conn.execute("DROP TABLE IF EXISTS runs")
    conn.executescript(SCHEMA)
    n = 0
    for md in sorted(runs_dir.glob("*.md")):
        upsert_md(conn, md)
        n += 1
    return n


def set_reviewed(conn: sqlite3.Connection, run_id: str, reviewed: bool) -> None:
    conn.execute("UPDATE runs SET reviewed=? WHERE run_id=?", (1 if reviewed else 0, run_id))
    conn.commit()
