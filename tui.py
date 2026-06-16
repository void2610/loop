# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml", "textual>=0.60"]
# ///
"""run を triage するための読み取り専用 TUI(ビュー)。

§2.5-4 / §7 を厳守: 判断・学び・review-notes は GUI で書かない。GUI は loop.db とファイルを
読むだけで、判断対象に速く着地するためのナビゲーションに徹する。要約・採点・「推奨判断」は出さない。
書き込みの権威は常に MD(nvim 側)。'e' で nvim に着地し、後処理(reviewed 化・コミット・upsert)は
runner ヘルパが行う。
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Markdown

import loopdb
import runner

DB = runner.DB
RUNS = runner.RUNS

COLUMNS = [("run", 38), ("verdict", 9), ("rev", 4), ("cost", 8), ("turns", 6), ("skill", 10)]


class LoopTUI(App):
    CSS = """
    DataTable { width: 60%; height: 1fr; }
    Markdown { width: 40%; height: 1fr; border-left: solid $accent; padding: 0 1; }
    """
    BINDINGS = [
        ("e", "edit", "判断を書く(nvim)"),
        ("u", "toggle_unreviewed", "未レビューのみ"),
        ("r", "reindex", "再インデックス"),
        ("q", "quit", "終了"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.unreviewed_only = False
        self.rows: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(cursor_type="row")
            yield Markdown("run を選択してください。")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label, width in COLUMNS:
            table.add_column(label, width=width, key=label)
        self._reindex()
        self.load_rows()

    def _reindex(self) -> None:
        conn = loopdb.connect(DB)
        loopdb.reindex(conn, RUNS)
        conn.close()

    def load_rows(self) -> None:
        conn = loopdb.connect(DB)
        q = "SELECT * FROM runs"
        if self.unreviewed_only:
            q += " WHERE reviewed=0"
        q += " ORDER BY started_at DESC, run_id DESC"
        self.rows = conn.execute(q).fetchall()
        conn.close()

        table = self.query_one(DataTable)
        table.clear()
        for r in self.rows:
            cost = f"${r['cost_usd']:.3f}" if r["cost_usd"] is not None else ""
            rev = "✓" if r["reviewed"] else "·"
            skill = (r["skill_sha"] or "")[:8]
            table.add_row(r["run_id"], r["verdict"] or "?", rev, cost,
                          str(r["turns"] or ""), skill, key=r["run_id"])
        flt = " [未レビューのみ]" if self.unreviewed_only else ""
        self.title = f"loop — {len(self.rows)} runs{flt}"
        if self.rows:
            self.show_detail(self.rows[0]["run_id"])
        else:
            self.query_one(Markdown).update("(該当 run なし)")

    def show_detail(self, run_id: str) -> None:
        md = RUNS / f"{run_id}.md"
        if md.exists():
            self.query_one(Markdown).update(md.read_text(encoding="utf-8"))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            self.show_detail(event.row_key.value)

    def _selected_run(self) -> str | None:
        table = self.query_one(DataTable)
        if not self.rows:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return key.value if key else None

    def action_edit(self) -> None:
        run_id = self._selected_run()
        if not run_id:
            return
        import os
        md = RUNS / f"{run_id}.md"
        editor = os.environ.get("EDITOR", "nvim")
        with self.suspend():
            __import__("subprocess").run([editor, f"+{runner.judgment_line(md)}", str(md)])
        runner.mark_reviewed(run_id, runner.load_config())  # reviewed 化 + commit + upsert(種類A)
        self._reindex()
        self.load_rows()

    def action_toggle_unreviewed(self) -> None:
        self.unreviewed_only = not self.unreviewed_only
        self.load_rows()

    def action_reindex(self) -> None:
        self._reindex()
        self.load_rows()


if __name__ == "__main__":
    LoopTUI().run()
