# /// script
# requires-python = ">=3.12"
# dependencies = ["duckdb"]
# ///
"""DuckDB 分析レンズ(ビュー、状態なし)。

loop.db(SQLite)を attach し、queries/*.sql を実行する。authoritative state は持たない。
ad-hoc は `uv run stats.py "<SQL>"`、canned は引数なしで queries/*.sql を全実行。
クエリ内では SQLite の `runs` テーブルを `runs` ビューとして直接参照できる。
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent


def _db_path() -> Path:
    try:
        with (ROOT / "loop.toml").open("rb") as f:
            d = tomllib.load(f).get("data", {}).get("dir", "data")
    except FileNotFoundError:
        d = "data"
    return (ROOT / d / "loop.db").resolve()


DB = _db_path()


def make_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    try:
        con.execute("INSTALL sqlite; LOAD sqlite;")
    except duckdb.Error:
        pass
    con.execute(f"ATTACH '{DB}' AS src (TYPE sqlite);")
    con.execute("CREATE VIEW runs AS SELECT * FROM src.runs;")
    return con


def run_sql(con: duckdb.DuckDBPyConnection, sql: str) -> None:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    widths = [max(len(c), *(len(_fmt(r[i])) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(_fmt(v).ljust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} rows)\n")


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4f}"
    return "" if v is None else str(v)


def main() -> int:
    if not DB.exists():
        print("loop.db がありません。先に `uv run runner.py reindex` を実行してください。", file=sys.stderr)
        return 1
    con = make_con()
    if len(sys.argv) > 1:  # ad-hoc
        run_sql(con, sys.argv[1])
        return 0
    sqls = sorted((ROOT / "queries").glob("*.sql"))
    if not sqls:
        print("queries/*.sql がありません。")
        return 0
    for q in sqls:
        print(f"### {q.name}")
        run_sql(con, q.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
