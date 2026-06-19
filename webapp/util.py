"""REST / SSE が共有する純関数ユーティリティ。

ここに置くのは「事実の変換」だけ。判断の生成・要約・補完は一切しない(§2.0-1)。
_safe_id・evidence のパストラバーサル防御は移行後も緩めない(§2.4)。
"""

from __future__ import annotations

import json
import re
import sys
import time
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


def norms_view() -> dict:
    """規範記憶のビュー(事実のみ)。repo ごとに conventions.md 生テキスト(=現在の知識)と
    candidates.md の候補配列(承認待ち)を返す。MD が真実(loop.db は介さず直読み)。
    判断(昇格/却下)は生成しない — 候補は status を含めそのまま並べるだけ(§2.6)。"""
    repos = []
    root = runner.NORMS_ROOT
    if root.exists():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            conv = d / "conventions.md"
            rows = []
            for c in runner.parse_candidates(d / "candidates.md"):
                m = re.match(r"candidate-(.+)-\d+$", c["candidate_id"])
                rows.append({
                    "candidate_id": c["candidate_id"], "repo": d.name,
                    "run_id": m.group(1) if m else (c.get("evidence_runs") or [None])[0],
                    "status": c.get("status", "pending"),
                    "observed_friction": c.get("observed_friction", ""),
                    "proposed_norm": c.get("proposed_norm", ""),
                    "drafted_at": c.get("drafted_at"),
                })
            repos.append({
                "name": d.name,
                "conventions": conv.read_text(encoding="utf-8", errors="replace") if conv.exists() else "",
                "has_conventions": conv.exists() and conv.stat().st_size > 0,
                "candidates": rows,
            })
    return {"repos": repos}


def norms_activity(limit: int = 200) -> list[dict]:
    """知識更新(規範起草)エージェントの動作履歴: runs/<id>/norms.json を新しい順に集約する。
    起草が走った run のみ存在し、抽出(drafted)・空振り(empty/none_reason)・失敗(failed/error)を可観測にする。
    再要約はしない(norms.json に runner が残した事実をそのまま運ぶ)。"""
    out: list[dict] = []
    if not RUNS.exists():
        return out
    for nj in RUNS.glob("*/norms.json"):
        run_id = nj.parent.name
        try:
            obj = json.loads(nj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cands = obj.get("candidates") or []
        err = obj.get("error")
        outcome = "failed" if err else ("drafted" if cands else "empty")
        repo, started = None, None
        md = RUNS / f"{run_id}.md"
        if md.exists():
            fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8", errors="replace"))
            repo, started = repo_label(fm.get("repo")), fm.get("started_at")
        out.append({
            "run_id": run_id, "repo": repo, "trigger": obj.get("trigger", ""),
            "outcome": outcome, "drafted": len(cands),
            "none_reason": obj.get("none_reason") or None, "error": err, "started_at": started,
        })
    out.sort(key=lambda r: (r.get("started_at") or "", r["run_id"]), reverse=True)
    return out[:limit]


def repo_label(raw) -> str:
    """repo 値を短い表示名に。none→no-repo / パス→basename / 登録名→そのまま / 未指定→default。"""
    s = "" if raw is None else str(raw).strip()
    if s == "":
        return "default"
    if s.lower() == "none":
        return "no-repo"
    return Path(s).name if "/" in s else s


def reindex_and_query(verdict: str | None, reviewed: str | None, task: str | None,
                      include_archived: bool = False):
    """loop.db を MD から再生成して runs を抽出(使い捨てレンズ)。既定でアーカイブ済みは除外。"""
    conn = loopdb.connect(DB)
    loopdb.reindex(conn, RUNS)
    q, params = "SELECT * FROM runs WHERE 1=1", []
    if not include_archived:
        q += " AND COALESCE(archived,0)=0"
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


def repo_branches(repo: str | None) -> list[str]:
    """repo 指定(登録名 / 'default' / パス)を解決してブランチ候補を返す。none/未知は空。"""
    r = (repo or "").strip()
    if r.lower() == "none":
        return []
    cfg = runner.load_config()
    path = runner.resolve_repo({} if r in ("", "default") else {"repo": r}, cfg)
    if path is None:
        return []
    return runner.list_branches(path)


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
    _add_elapsed(d)
    return d


def _add_elapsed(d: dict) -> dict:
    """status dict に started_at からの経過秒 elapsed を付ける(欠損/不正は None)。"""
    st = d.get("started_at")
    if st:
        try:
            t = datetime.fromisoformat(st)
            now = datetime.now(t.tzinfo) if t.tzinfo else datetime.now()
            d["elapsed"] = int((now - t).total_seconds())
        except ValueError:
            d["elapsed"] = None
    return d


def _stale_after_seconds() -> int:
    """run が「無更新ならもう死んでいる」と判定する上限秒。
    どの待機フェーズ(implementer turn / awaiting / CI / Copilot)の合計よりも長く取り、
    legit な待機 run を誤って隠さない。中断・SIGKILL で done 化されなかった status を落とすためだけに使う。"""
    loop = runner.load_config().get("loop", {})
    return (int(loop.get("timeout_seconds", 1800))
            + int(loop.get("intervention_timeout_seconds", 1800))
            + int(loop.get("ci_timeout_seconds", 1800))
            + int(loop.get("copilot_timeout_seconds", 600)) + 300)


def active_runs() -> list[dict]:
    """進行中(phase != done)の全 run の status.json を集約して返す(N 本同時の監視用)。
    真実は各 runs/<id>/status.json。完了は clear_run_status が phase=done にする。
    SIGKILL 等で done 化されず残った status は、run ディレクトリの無更新時間で stale 判定して除く(削除はしない)。"""
    out: list[dict] = []
    if not RUNS.exists():
        return out
    stale_after = _stale_after_seconds()
    now = time.time()
    for sp in RUNS.glob("*/status.json"):
        try:
            d = json.loads(sp.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(d, dict) or not d.get("run_id"):
            continue
        if str(d.get("phase") or "").lower() == "done":
            continue
        try:  # run ディレクトリ内の最新更新が閾値より古ければ死んだ run とみなす
            newest = max((p.stat().st_mtime for p in sp.parent.iterdir() if p.is_file()),
                         default=sp.stat().st_mtime)
        except OSError:
            newest = 0
        if now - newest > stale_after:
            continue
        out.append(_add_elapsed(d))
    out.sort(key=lambda r: str(r.get("started_at") or ""))
    return out


def run_queue() -> list[dict]:
    """待機キュー(status=todo・未アーカイブのタスク)を next_todo と同じ並びで返す。"""
    q: list[dict] = []
    for t in runner.parse_tasks():
        if str(t.get("status", "todo")).lower() != "todo":
            continue
        if str(t.get("archived", "false")).lower() in ("true", "1"):
            continue
        q.append({"id": t.get("id"), "goal": t.get("goal"), "repo": t.get("repo")})
    return q


def fields_from_fm(task_id: str, fm: dict, body: str) -> dict:
    """front-matter dict → フォーム用フィールド(accept/constraints は行 UI 用にリストのまま)。"""
    tools = fm.get("allowed_tools")
    if isinstance(tools, list):
        tools = ", ".join(tools)
    return {
        "task_id": task_id,
        "goal": fm.get("goal", ""),
        "repo": fm.get("repo", "") or "",
        "base_branch": fm.get("base_branch", "") or "",
        "no_pr": str(fm.get("no_pr", "")).lower() in ("true", "1", "yes"),
        "accept": fm.get("accept") or [],
        "verify": fm.get("verify", "") or "",
        "constraints": fm.get("constraints") or [],
        "allowed_tools": tools or "",
        "max_attempts": fm.get("max_attempts", "") if fm.get("max_attempts") is not None else "",
        "status": fm.get("status", "todo"),
        "body": body,
    }


def fm_from_form(task_id, goal, repo, accept: list[str], verify, constraints: list[str],
                 allowed_tools, max_attempts, status, base_branch="", no_pr=False) -> dict:
    """フォーム入力 → front-matter dict(順序を固定。空フィールドは省く)。

    max_attempts は str 受けのまま int 化失敗時に黙って落とす現挙動を維持(契約後方互換)。
    """
    fm: dict = {"id": task_id, "goal": (goal or "").strip("\n")}
    if (repo or "").strip():
        fm["repo"] = repo.strip()
    if (base_branch or "").strip():
        fm["base_branch"] = base_branch.strip()
    if no_pr:  # PR を出さない(ローカル検証用)。既定 false は省略してMDを汚さない
        fm["no_pr"] = True
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
    """証拠ファイル本文を JSON へ詰める。"""
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


# Claude Code のスラッシュコマンド呼び出しが付ける機械的エンベロープ。中身(command-args)が実プロンプト。
_CMD_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_CMD_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
_CMD_TAG_RE = re.compile(r"</?command-(?:message|name|args)>")


def _unwrap_command(text: str) -> tuple[str, str | None]:
    """`<command-args>` で包まれたプロンプトから実中身と起動スキル名を取り出す(markdown が壊れないよう envelope を剥がす)。"""
    nm = _CMD_NAME_RE.search(text)
    name = nm.group(1).strip() if nm else None
    m = _CMD_ARGS_RE.search(text)
    if m:
        rest = text[m.end():].strip()
        inner = m.group(1).strip()
        return (f"{inner}\n\n{rest}" if rest else inner), name
    return _CMD_TAG_RE.sub("", text), name


def parse_transcript(path: Path) -> list[dict]:
    """セッション JSONL を会話イベント列に畳む(user/assistant のみ)。REST/SSE 共有。"""
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
            body, skill = _unwrap_command(content)
            label = f"プロンプト · {skill}" if skill else "プロンプト"
            events.append({"cls": "user", "label": label, "body": body, "ts": ts})
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
