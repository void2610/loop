"""REST / SSE / legacy が共有する純関数ユーティリティ。

ここに置くのは「事実の変換」だけ。判断の生成・要約・補完は一切しない(§2.0-1)。
_safe_id・evidence のパストラバーサル防御は移行後も緩めない(§2.4)。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import loopdb  # noqa: E402
import runner  # noqa: E402

ROOT = runner.ROOT
RUNS = runner.RUNS
DATA = runner.DATA
DB = runner.DB

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STATUSES = ["todo", "pass", "fail", "timeout", "handoff"]

# evidence で本文配信を許可するファイル名 allowlist(§2.4-b)
EVIDENCE_ALLOWLIST = (
    "change.patch", "test-output.txt", "verifier.json", "transcript.jsonl",
)
EVIDENCE_ALLOW_SUFFIX = (".stream.jsonl", ".result.json", ".stderr.log")


def safe_id(raw: str | None) -> str | None:
    """task_id / run_id を検証(整形ではなく拒否)。不正なら None。"""
    rid = (raw or "").strip()
    if not rid or not _SAFE_ID.match(rid) or rid.startswith(("_", ".")) or "/" in rid:
        return None
    return rid


def repo_label(raw) -> str:
    """repo 値を短い表示名に。none→no-repo / パス→basename / 登録名→そのまま / 未指定→default。"""
    s = "" if raw is None else str(raw).strip()
    if s == "":
        return "default"
    if s.lower() == "none":
        return "no-repo"
    return Path(s).name if "/" in s else s


def reindex_and_query(verdict: str | None, reviewed: str | None, task: str | None):
    """loop.db を MD から再生成して runs を抽出(使い捨てレンズ)。現 _reindex_and_query。"""
    conn = loopdb.connect(DB)
    loopdb.reindex(conn, RUNS)
    q, params = "SELECT * FROM runs WHERE 1=1", []
    if verdict:
        q += " AND verdict=?"; params.append(verdict)
    if reviewed in ("0", "1"):
        q += " AND reviewed=?"; params.append(int(reviewed))
    if task:
        q += " AND task LIKE ?"; params.append(f"%{task}%")
    q += " ORDER BY started_at DESC, run_id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    verdicts = [r[0] for r in conn.execute(
        "SELECT DISTINCT verdict FROM runs ORDER BY verdict").fetchall()]
    conn.close()
    return rows, verdicts


def latest_runs() -> dict:
    """task id → 最新 run {run_id, verdict}(loop.db から)。現 _latest_runs。"""
    last: dict = {}
    try:
        conn = loopdb.connect(DB)
        for r in conn.execute(
                "SELECT task, run_id, verdict FROM runs ORDER BY started_at DESC, run_id DESC"):
            last.setdefault(r["task"], {"run_id": r["run_id"], "verdict": r["verdict"]})
        conn.close()
    except Exception:
        pass
    return last


def known_repos() -> list[str]:
    cfg = runner.load_config()
    names = list((cfg.get("repos") or {}).keys())
    return names + ["none"]


def read_run_status(run_id: str | None = None) -> dict | None:
    """data/.run.lock(=ロック兼ステータス)を読む。現 _read_run_status に run_id フィルタを追加。

    並列化トラック T で per-run ステータスが runs/<id>/status.json 配列へ分裂しても
    呼び出し側が run_id キーで読めるよう、引数で run_id を受ける契約に固定(§8.1.3)。
    """
    lock = DATA / ".run.lock"
    if not lock.exists():
        return None
    try:
        d = json.loads(lock.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    if run_id is not None and d.get("run_id") != run_id:
        return None
    d.setdefault("phase", "start")
    st = d.get("started_at")
    if st:
        try:
            t = datetime.fromisoformat(st)
            now = datetime.now(t.tzinfo) if t.tzinfo else datetime.now()
            d["elapsed"] = int((now - t).total_seconds())
        except ValueError:
            d["elapsed"] = None
    return d


def fields_from_fm(task_id: str, fm: dict, body: str) -> dict:
    """front-matter dict → フォーム用フィールド(accept/constraints は行 UI 用にリストのまま)。"""
    tools = fm.get("allowed_tools")
    if isinstance(tools, list):
        tools = ", ".join(tools)
    return {
        "task_id": task_id,
        "goal": fm.get("goal", ""),
        "repo": fm.get("repo", "") or "",
        "accept": fm.get("accept") or [],
        "verify": fm.get("verify", "") or "",
        "constraints": fm.get("constraints") or [],
        "allowed_tools": tools or "",
        "max_attempts": fm.get("max_attempts", "") if fm.get("max_attempts") is not None else "",
        "status": fm.get("status", "todo"),
        "body": body,
    }


def fm_from_form(task_id, goal, repo, accept: list[str], verify, constraints: list[str],
                 allowed_tools, max_attempts, status) -> dict:
    """フォーム入力 → front-matter dict(順序を固定。空フィールドは省く)。

    max_attempts は str 受けのまま int 化失敗時に黙って落とす現挙動を維持(契約後方互換)。
    """
    fm: dict = {"id": task_id, "goal": (goal or "").strip("\n")}
    if (repo or "").strip():
        fm["repo"] = repo.strip()
    acc = [x.strip() for x in accept if x.strip()]
    if acc:
        fm["accept"] = acc
    if (verify or "").strip():
        fm["verify"] = verify.strip("\n")
    cons = [x.strip() for x in constraints if x.strip()]
    if cons:
        fm["constraints"] = cons
    if (allowed_tools or "").strip():
        fm["allowed_tools"] = allowed_tools.strip()
    if str(max_attempts or "").strip():
        try:
            fm["max_attempts"] = int(max_attempts)
        except ValueError:
            pass
    fm["status"] = status if status in STATUSES else "todo"
    return fm


def evidence_flags(run_id: str) -> dict:
    """証拠ファイルの存在フラグのみ返す(本文は files エンドポイントで個別取得。§2.2)。"""
    d = RUNS / run_id
    out: dict = {}
    for name in ("change.patch", "test-output.txt"):
        out[name] = (d / name).exists()
    out["transcript"] = (d / "transcript.jsonl").exists()
    return out


def evidence_text(run_id: str) -> dict:
    """証拠ファイル本文を JSON へ詰める(legacy detail 互換)。"""
    d = RUNS / run_id
    out: dict = {}
    for name in ("change.patch", "test-output.txt"):
        p = d / name
        out[name] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
    out["transcript"] = (d / "transcript.jsonl").exists()
    return out


def run_summary(text: str) -> str:
    """runs/<id>.md の `## エージェントがやったこと` を抽出(runner の事実要約。再要約しない)。"""
    if "## エージェントがやったこと" not in text:
        return ""
    after = text.split("## エージェントがやったこと", 1)[1]
    summary = after.split("\n## ", 1)[0]
    return "\n".join(l for l in summary.splitlines() if not l.startswith("（")).strip()


def read_verifier(run_id: str) -> dict | None:
    p = RUNS / run_id / "verifier.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def evidence_file_path(run_id: str, name: str) -> Path | None:
    """パストラバーサル防御 + allowlist を通った証拠ファイルの Path。不正なら None(§2.4-b)。"""
    if safe_id(run_id) is None:
        return None
    if name not in EVIDENCE_ALLOWLIST and not name.endswith(EVIDENCE_ALLOW_SUFFIX):
        return None
    base = (RUNS / run_id).resolve()
    p = (RUNS / run_id / name).resolve()
    if not str(p).startswith(str(base)) or not p.exists():
        return None
    return p


def parse_transcript(path: Path) -> list[dict]:
    """セッション JSONL を会話イベント列に畳む(user/assistant のみ)。REST/SSE/legacy 共有。"""
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") not in ("user", "assistant"):
            continue
        msg = o.get("message", {})
        if not isinstance(msg, dict):
            continue
        ts = (o.get("timestamp") or "")[11:19]
        content = msg.get("content")
        if isinstance(content, str):
            events.append({"cls": "user", "label": "プロンプト", "body": content, "ts": ts})
            continue
        for b in content or []:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                events.append({"cls": "assistant", "label": "アシスタント", "body": b.get("text", ""), "ts": ts})
            elif bt == "thinking":
                events.append({"cls": "think", "label": "思考", "body": b.get("thinking", ""), "ts": ts, "collapse": True})
            elif bt == "tool_use":
                body = json.dumps(b.get("input", {}), ensure_ascii=False, indent=2)
                events.append({"cls": "tool", "label": f"🔧 {b.get('name', 'tool')}", "body": body, "ts": ts,
                               "collapse": len(body) > 600})
            elif bt == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                body = "" if c is None else str(c)
                events.append({"cls": "result", "label": "↩ 結果", "body": body, "ts": ts, "collapse": len(body) > 400})
    return events
