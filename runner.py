# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Loop Engineering の計測配管ランナー(v3)。

種類A(メカニクス)はすべてここで全自動化する: dispatch / headless 実行 / 証拠収集 /
自動チェックポイントコミット / run MD 生成 / SQLite upsert / インデックス再生成。
種類B(判断)は決して自動化しない。run MD の「判断」セクションは空のまま出力し、人間が nvim で書く。
実行系は claude -p と git worktree(ネイティブ)に委ね、ここは突き合わせ層に徹する。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

import loopdb

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "loop.toml"


def load_config() -> dict:
    with CONFIG.open("rb") as f:
        return tomllib.load(f)


def _data_dir() -> Path:
    """契約データ(TODO/runs/review-notes/loop.db)の置き場。別の private git repo にする。"""
    try:
        with CONFIG.open("rb") as f:
            d = tomllib.load(f).get("data", {}).get("dir", "data")
    except FileNotFoundError:
        d = "data"
    return (ROOT / d).resolve()


# データ系のパスは data_dir 配下に置く(エンジン=公開 repo とは別の git repo)。
DATA = _data_dir()
TASKS_DIR = DATA / "tasks"   # 1 タスク = 1 ファイル(data/tasks/<id>.md、YAML front-matter)
RUNS = DATA / "runs"
DB = DATA / "loop.db"
REVIEW_NOTES = DATA / "review-notes.md"
# worktree は対象 repo に依らずこの loop repo 内に固定配置(.gitignore 済み)。
WORKTREES_DIR = ROOT / ".loop-worktrees"

JUDGMENT_HEADING = "## 判断"

# --- 並列実行の直列化ロック(§4.3 / §4.5) ---
# 同一プロセス内で N 本の run を回す前提のロック群。max_concurrency=1 のときは取得しても
# 競合がないため現状と完全等価。別プロセスワーカー化する場合は file lock へ置き換える。
# RLock: 完了処理ブロック(update_status→upsert_md→auto_commit)を一括で囲みつつ、
# 内側の auto_commit が同じロックを再取得してもデッドロックしないため再入可能にする。
_DATA_COMMIT_LOCK = threading.RLock()       # data/ への書き込み・commit を直列化(index.lock 競合回避)
_WT_LOCKS: dict[str, threading.Lock] = {}   # repo パスごとの worktree 操作ロック
_WT_LOCKS_GUARD = threading.Lock()


def _wt_lock(repo: Path) -> threading.Lock:
    """対象 repo 単位の worktree 操作ロックを返す(同一 repo の並行 add/remove 競合を直列化)。"""
    key = str(repo.resolve())
    with _WT_LOCKS_GUARD:
        return _WT_LOCKS.setdefault(key, threading.Lock())


# --- タスク = 1 ファイル(data/tasks/<id>.md、YAML front-matter) ---

def _split_front_matter(text: str) -> tuple[list[str], int, int]:
    """(lines, fm_start, fm_end) を返す。fm は lines[fm_start:fm_end](--- の内側)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return lines, 0, 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines))
    return lines, 1, end


def parse_tasks() -> list[dict]:
    """data/tasks/*.md を走査し front-matter をタスクとして読む(ファイル名昇順=実行順)。
    `_` や `.` で始まるファイル(テンプレ/隠し)はスキップ。"""
    tasks: list[dict] = []
    if not TASKS_DIR.exists():
        return tasks
    for p in sorted(TASKS_DIR.glob("*.md")):
        if p.name.startswith(("_", ".")):
            continue
        text = p.read_text(encoding="utf-8")
        lines, s, e = _split_front_matter(text)
        if e == 0:
            continue  # front-matter なしはタスクではない
        try:
            data = yaml.safe_load("\n".join(lines[s:e])) or {}
        except yaml.YAMLError as ex:
            print(f"  ! YAML パース失敗(無視) {p.name}: {ex}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("id", p.stem)
        data["_path"] = p
        tasks.append(data)
    return tasks


def next_todo(tasks: list[dict]) -> dict | None:
    for t in tasks:
        if str(t.get("status", "todo")).lower() == "todo":
            return t
    return None


def update_status(task_id: str, new_status: str) -> None:
    target = next((t for t in parse_tasks() if t.get("id") == task_id), None)
    if not target:
        return
    p = target["_path"]
    lines, s, e = _split_front_matter(p.read_text(encoding="utf-8"))
    for k in range(s, e):
        if lines[k].split(":", 1)[0].strip() == "status":
            lines[k] = f"status: {new_status}"
            break
    else:
        lines.insert(e, f"status: {new_status}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _task_dumper():
    """multi-line 文字列を YAML リテラルブロック(|)で出力する SafeDumper。フォーム保存を読みやすく保つ。"""
    class _D(yaml.SafeDumper):
        pass

    def _str(dumper, data):
        style = "|" if "\n" in data else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

    _D.add_representer(str, _str)
    return _D


def read_task(task_id: str) -> tuple[dict, str] | None:
    """タスクファイルを (front-matter dict, body) に分解する(フォーム prefill 用)。"""
    p = TASKS_DIR / f"{task_id}.md"
    if not p.exists():
        return None
    lines, s, e = _split_front_matter(p.read_text(encoding="utf-8"))
    fm = (yaml.safe_load("\n".join(lines[s:e])) or {}) if e else {}
    body = "\n".join(lines[e + 1:]).strip() if e else ""
    return (fm if isinstance(fm, dict) else {}), body


def write_task(task_id: str, fm: dict, body: str = "") -> Path:
    """front-matter dict と body からタスクファイルを書き出す(フォーム保存)。"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    p = TASKS_DIR / f"{task_id}.md"
    dumped = yaml.dump(fm, Dumper=_task_dumper(), allow_unicode=True,
                       sort_keys=False, default_flow_style=False).rstrip("\n")
    text = f"---\n{dumped}\n---\n"
    if body.strip():
        text += f"\n{body.strip()}\n"
    p.write_text(text, encoding="utf-8")
    return p


def goal_contract_sha(task: dict) -> str:
    """目標契約の正規化ハッシュ。skill_sha と並ぶ再現性のキー。"""
    canonical = {k: task.get(k) for k in ("goal", "accept", "constraints", "verify", "allowed_tools", "repo")}
    blob = yaml.safe_dump(canonical, sort_keys=True, allow_unicode=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


# --- プロンプト生成 ---

def render_prompt(task: dict) -> str:
    parts = [
        "あなたは隔離された git worktree 内で作業しています。次のゴールを達成してください。",
        "",
        f"# ゴール\n{task['goal']}",
    ]
    if task.get("accept"):
        parts.append("\n# 受け入れ基準(すべて満たすこと)\n" + "\n".join(f"- {a}" for a in task["accept"]))
    if task.get("constraints"):
        parts.append("\n# 制約(違反しないこと)\n" + "\n".join(f"- {c}" for c in task["constraints"]))
    if task.get("verify"):
        parts.append(
            f"\n# 検証\n作業完了後、次のコマンドが exit 0 になることが合格条件です(別プロセスで検証されます): `{task['verify']}`"
        )
    return "\n".join(parts)


def render_explorer_prompt(task: dict) -> str:
    parts = [
        "あなたは隔離された git worktree 内の Explorer です。**実装はしないでください**。",
        "次のゴールについて、関連ファイル・前提・リスク・推奨アプローチを箇条書きで簡潔に報告してください。",
        f"\n# ゴール\n{task['goal']}",
    ]
    if task.get("accept"):
        parts.append("\n# 受け入れ基準\n" + "\n".join(f"- {a}" for a in task["accept"]))
    if task.get("constraints"):
        parts.append("\n# 制約\n" + "\n".join(f"- {c}" for c in task["constraints"]))
    return "\n".join(parts)


def render_implementer_prompt(task: dict, explorer_findings: str) -> str:
    base = render_prompt(task)
    return base + f"\n\n# 調査メモ(Explorer による事前調査。参考にしてよいが鵜呑みにしない)\n{explorer_findings}"


def render_verifier_prompt(task: dict, diff_text: str, test_output: str) -> str:
    accept = "\n".join(f"- {a}" for a in (task.get("accept") or [])) or "(明示なし)"
    constraints = "\n".join(f"- {c}" for c in (task.get("constraints") or [])) or "(なし)"
    return f"""あなたは独立した受け入れ判定者(Verifier)です。**実装者の自己申告を信じてはいけません。**
受け入れ基準を 1 つずつ、下の diff と検証出力、および worktree 内の実ファイル(Read/Grep/Glob 可)に照らして検証してください。
テストを通すためだけの gaming(本質を解かずテストを書き換える等)や、spec の部分的未達を積極的に疑ってください。
判定はスキーマに従い構造化出力で返してください。

# ゴール
{task['goal']}

# 受け入れ基準(すべて満たすこと)
{accept}

# 制約(違反していないか)
{constraints}

# 実装の diff
```diff
{diff_text[:6000]}
```

# 決定論テストの出力
{test_output[:4000]}
"""


# --- git / リポジトリ解決 ---

def resolve_repo(task: dict, cfg: dict) -> Path | None:
    """タスクの repo 指定を解決する。
    未指定 → [repo].path(デフォルト) / 'none' → None(no-repo) / 登録名 → [repos] のパス / それ以外 → パス。"""
    r = task.get("repo")
    if r is None or str(r).strip() == "":
        r = cfg.get("repo", {}).get("path", ".")
    r = str(r).strip()
    if r.lower() == "none":
        return None
    repos = cfg.get("repos", {})
    if r in repos:
        r = repos[r]
    p = Path(r).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def is_git_repo(path: Path) -> bool:
    return path.is_dir() and git(path, "rev-parse", "--git-dir").returncode == 0


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def add_worktree(repo: Path, run_id: str) -> tuple[Path, str]:
    # 対象 repo に依らず loop repo 内の固定ディレクトリに置く(.gitignore 済み)。
    wt = WORKTREES_DIR / run_id
    branch = f"loop/{run_id}"
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    with _wt_lock(repo):  # 同一 repo への並行 worktree add を直列化(共有 .git のメタ競合回避)
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(wt), "HEAD"],
            check=True, capture_output=True, text=True,
        )
    return wt, branch


def remove_worktree(repo: Path, wt: Path) -> None:
    with _wt_lock(repo):  # add と同じ repo ロックで直列化
        git(repo, "worktree", "remove", "--force", str(wt))


def commit_worktree(wt: Path, message: str) -> bool:
    """worktree のステージ済み変更を loop/<id> ブランチにコミットする。
    remove --force は作業ツリーを破棄するため、ここで commit しないと成果がブランチに残らない。"""
    if git(wt, "diff", "--cached", "--quiet").returncode == 0:
        return False  # 変更なし
    git(wt, "commit", "-q", "-m", message)
    return True


def _status_path(run_id: str) -> Path:
    """各 run の進行ステータスファイル(SSE が配列で集約して読む契約。§4.7)。"""
    return RUNS / run_id / "status.json"


def _merge_json(path: Path, fields: dict) -> dict:
    cur: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8") or "{}")
            if isinstance(loaded, dict):
                cur = loaded
        except (json.JSONDecodeError, OSError):
            cur = {}
    cur.update(fields)
    return cur


def write_run_status(run_id: str, **fields) -> None:
    """各 run の進行状態を runs/<run_id>/status.json(run_id キー)に書く(SSE が配列で読む)。
    N 本同時でも 1 ファイルに混ざらないよう run ごとに分離している(§4.1 / §4.7)。
    互換のため単一 run マーカー data/.run.lock にも現行形のステータスをミラーする。"""
    sp = _status_path(run_id)
    try:
        sp.parent.mkdir(parents=True, exist_ok=True)
        merged = _merge_json(sp, {"run_id": run_id, **fields})
        sp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    except OSError:
        merged = {"run_id": run_id, **fields}
    # .run.lock ミラー: 現行 Web 監視(単一 run 前提)の後方互換。max_concurrency=1 では実質同一。
    lock = DATA / ".run.lock"
    try:
        lock.write_text(json.dumps(_merge_json(lock, merged), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def clear_run_status(run_id: str, verdict: str | None = None) -> None:
    """run 完了時の後処理。status.json を done 化する(SSE が完了を検知できる)。
    .run.lock(claim 兼ミラー)の掃除はここでは行わない — claim の解放は claim を取った
    cmd_run / ワーカープール側の責務(retry を跨いで claim を保持するため)。"""
    sp = _status_path(run_id)
    try:
        if sp.parent.exists():
            sp.write_text(json.dumps(
                {"run_id": run_id, "phase": "done", "verdict": verdict}, ensure_ascii=False),
                encoding="utf-8")
    except OSError:
        pass


def auto_commit(repo: Path, paths: list[Path], message: str) -> None:
    """種類A: チェックポイントコミット。loop.db(ビュー)は .gitignore 済みなので入らない。
    data/ への commit は N 本の run が同時に呼ぶと .git/index.lock 競合で取りこぼすため、
    プロセス内ロックで直列化する(§4.3)。worktree(対象 repo)側は run_id で index が独立なので対象外。"""
    rels = [str(p.relative_to(repo)) for p in paths if p and p.exists()]
    if not rels:
        return
    is_data = repo.resolve() == DATA
    lock = _DATA_COMMIT_LOCK if is_data else contextlib.nullcontext()
    with lock:
        git(repo, "add", *rels)
        if git(repo, "diff", "--cached", "--quiet").returncode == 0:
            return  # 差分なし
        git(repo, "commit", "-q", "-m", message)


# --- headless 実行(役割ごと) ---

# read-only 役割で確実にブロックする変更系ツール。--disallowedTools は allow より優先されるため、
# ユーザー global settings が Bash(*)/Write を許可していても read-only を強制できる。
WRITE_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"]


def run_role(role: str, prompt: str, wt: Path, cfg: dict, model: str,
             tools: list[str], run_dir: Path,
             extra_args: list[str] | None = None, read_only: bool = False) -> tuple[dict | None, str]:
    """役割を1つ headless 実行し {role}.result.json / {role}.stderr.log を保存する。
    read_only=True は変更系ツールを --disallowedTools で禁止(global settings を上書き)。"""
    loop = cfg["loop"]
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",  # 逐次イベントを得てライブ表示する
        "--model", model,
        "--max-turns", str(loop.get("max_turns", 40)),
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--allowedTools", *tools,
    ]
    if read_only:
        cmd += ["--disallowedTools", *WRITE_TOOLS]
    if extra_args:
        cmd += extra_args

    stream_path = run_dir / f"{role}.stream.jsonl"
    err = run_dir / f"{role}.stderr.log"
    proc = subprocess.Popen(cmd, cwd=str(wt), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    killed = {"v": False}

    def _kill():
        killed["v"] = True
        try:
            proc.kill()
        except OSError:
            pass

    timer = threading.Timer(loop["timeout_seconds"], _kill)
    timer.start()
    lines: list[str] = []
    try:
        with stream_path.open("w", encoding="utf-8") as sf:
            for line in proc.stdout:  # イベントが来るたび即ファイルへ(Web がライブ tail する)
                sf.write(line)
                sf.flush()
                lines.append(line)
    finally:
        timer.cancel()
        proc.wait()
    err.write_text(proc.stderr.read() or "", encoding="utf-8")
    if killed["v"]:
        return None, "timeout"

    result = None
    for line in reversed(lines):  # 末尾の result イベント(= 従来の json 出力と同形)を拾う
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and o.get("type") == "result":
            result = o
            break
    if result is None:
        (run_dir / f"{role}.result.raw.txt").write_text("".join(lines), encoding="utf-8")
        return None, "error"
    (run_dir / f"{role}.result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, ("error" if result.get("is_error") else "ok")


def resolve_tools(value, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        value = [s.strip() for s in value.split(",") if s.strip()]
    return value or fallback


# --- Verifier(別モデル・read-only・構造化出力) ---

VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["pass", "fail", "handoff"]},
        "criteria": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "met": {"type": "boolean"},
            "evidence": {"type": "string"}}, "required": ["criterion", "met"]}},
        "test_gaming_suspected": {"type": "boolean"},
        "reasons": {"type": "string"},
        "confidence": {"enum": ["high", "medium", "low"]},
    },
    "required": ["verdict", "reasons", "confidence"],
}


def parse_verifier(result: dict | None, hint: str, run_dir: Path) -> tuple[str, dict | None]:
    """Verifier の構造化出力(result.json の structured_output フィールド)を取り出す。
    判定不能は安全側で handoff(暗黙 pass にしない)。"""
    if hint != "ok" or not result:
        return "handoff", None
    obj = result.get("structured_output")
    if not isinstance(obj, dict):
        return "handoff", None
    (run_dir / "verifier.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    v = obj.get("verdict", "handoff")
    return (v if v in ("pass", "fail", "handoff") else "handoff"), obj


def combine_verdict(test_verdict: str, verifier_verdict: str) -> str:
    if test_verdict == "fail":
        return "fail"
    if verifier_verdict in ("fail", "handoff"):
        return verifier_verdict
    return "pass"


# --- タスク生成(自然言語 → 目標契約。専用 skill + 構造化出力) ---

TASK_AUTHOR_SKILL = ROOT / ".claude" / "skills" / "task-author" / "SKILL.md"

TASK_GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "goal": {"type": "string"},
        "accept": {"type": "array", "items": {"type": "string"}},
        "verify": {"type": "string"},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "allowed_tools": {"type": "string"},
        "max_attempts": {"type": "integer"},
        "notes": {"type": "string"},
    },
    "required": ["id", "goal", "accept"],
}


def generate_task(prompt: str, cfg: dict) -> dict | None:
    """自然言語の依頼を専用 skill 付きで claude -p に渡し、目標契約を構造化出力で得る。
    ファイルへの書き込みは行わない(backend が write_task で決定論的に書く)。"""
    agents, loop = cfg["agents"], cfg["loop"]
    model = agents.get("author_model") or agents["implementer_model"]
    # 「実行せず変換せよ」を明示。これが無いと依頼内容(例: ファイル作成)を実際にやろうとして
    # read-only 拒否 → リトライで turn を空回りし遅くなる。
    # 対象リポジトリは UI で明示選択する(モデルには推定させない)。
    wrapped = ("次の依頼を loop の『目標契約(タスク定義)』に変換し、構造化出力で返してください。"
               "**ファイルの作成・編集・コマンド実行は一切しないでください。設計だけ**です。\n\n# 依頼\n" + prompt)
    cmd = [
        "claude", "-p", wrapped,
        "--output-format", "json",
        "--model", model,
        "--max-turns", "8",  # 設計のみ。空回り防止に小さく
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--disallowedTools", *WRITE_TOOLS,  # 生成は read-only。global settings の Write/Bash を上書き
        "--json-schema", json.dumps(TASK_GEN_SCHEMA, ensure_ascii=False),
    ]
    if TASK_AUTHOR_SKILL.exists():
        cmd += ["--append-system-prompt", TASK_AUTHOR_SKILL.read_text(encoding="utf-8")]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              timeout=loop["timeout_seconds"])
        result = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    obj = result.get("structured_output")
    return obj if isinstance(obj, dict) else None


def _safe_task_id(raw: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (raw or "")).strip("-.")
    return s or "task"


def cmd_gen(prompt: str, auto_run: bool = False, repo: str | None = None) -> int:
    """自然言語の依頼からタスクを生成して data/tasks/ に書き、必要なら実行(background 想定)。
    repo を明示指定したら(空/None 以外)モデル推定を上書きする('default' は repo 省略=デフォルト)。"""
    cfg = load_config()
    DATA.mkdir(parents=True, exist_ok=True)
    print("▶ タスク生成中 …")
    obj = generate_task(prompt, cfg)
    if not isinstance(obj, dict) or not obj.get("id") or not obj.get("goal"):
        print("生成に失敗しました(モデル出力が不正)。")
        return 1
    base = _safe_task_id(obj["id"])
    tid, n = base, 2
    while (TASKS_DIR / f"{tid}.md").exists():
        tid, n = f"{base}-{n}", n + 1
    fm: dict = {"id": tid, "goal": str(obj.get("goal", "")).strip("\n")}
    acc = [str(x).strip() for x in (obj.get("accept") or []) if str(x).strip()]
    if acc:
        fm["accept"] = acc
    verify = str(obj.get("verify", "") or "").strip("\n")
    if verify:
        fm["verify"] = verify
    cons = [str(x).strip() for x in (obj.get("constraints") or []) if str(x).strip()]
    if cons:
        fm["constraints"] = cons
    at = str(obj.get("allowed_tools", "") or "").strip()
    if at:
        fm["allowed_tools"] = at
    ma = obj.get("max_attempts")
    if isinstance(ma, int) and ma > 0:
        fm["max_attempts"] = ma
    fm["status"] = "todo"
    if repo:  # 明示選択を優先(モデル推定を上書き)
        if repo == "default":
            fm.pop("repo", None)
        else:
            fm["repo"] = repo
    p = write_task(tid, fm, str(obj.get("notes", "") or ""))
    auto_commit(DATA, [p], f"todo: {tid} をプロンプトから生成")
    print(f"  · 生成: {tid}")
    if auto_run:
        return cmd_run(tid)
    return 0


# --- 証拠収集 ---

def capture_diff(wt: Path, run_dir: Path) -> None:
    git(wt, "add", "-A")
    diff = git(wt, "diff", "--cached")
    (run_dir / "change.patch").write_text(diff.stdout, encoding="utf-8")


def run_verify(task: dict, wt: Path, run_dir: Path) -> tuple[str, int | None]:
    """検証ゲート(maker と分離)。決定論コマンドの exit code を一次証拠にする。"""
    verify = task.get("verify")
    if not verify:
        (run_dir / "test-output.txt").write_text(
            "verify コマンド未指定 → 決定論テストなし(none)。Verifier の判定に委譲する。\n", encoding="utf-8"
        )
        return "none", None
    proc = subprocess.run(verify, shell=True, cwd=str(wt), capture_output=True, text=True)
    out = f"$ {verify}\n[exit {proc.returncode}]\n\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    (run_dir / "test-output.txt").write_text(out, encoding="utf-8")
    return ("pass" if proc.returncode == 0 else "fail"), proc.returncode


def copy_transcript(result: dict | None, run_dir: Path) -> None:
    if not result or not result.get("session_id"):
        return
    matches = list((Path.home() / ".claude" / "projects").glob(f"**/{result['session_id']}.jsonl"))
    if matches:
        shutil.copy(matches[0], run_dir / "transcript.jsonl")


# --- run MD 出力(契約の源) ---

def write_run_md(task: dict, run_id: str, verdict: str, result: dict | None,
                 cfg: dict, started_at: str, verify_code: int | None,
                 test_verdict: str = "none", verifier_verdict: str = "handoff",
                 verifier_obj: dict | None = None, roles: dict | None = None,
                 repo: Path | None = None) -> Path:
    repo_sha = git(repo, "rev-parse", "HEAD").stdout.strip() if repo else ""
    skill_sha = git(repo, "rev-parse", "HEAD:.claude/skills").stdout.strip() if repo else ""
    roles = roles or {}

    cost_total = sum(r["total_cost_usd"] for r in roles.values() if r and r.get("total_cost_usd") is not None) or None
    turns_total = sum(r["num_turns"] for r in roles.values() if r and r.get("num_turns") is not None) or None

    fm = {
        "task": task["id"],
        "verdict": verdict,
        "reviewed": "false",
        "repo": str(repo) if repo else "none",
        "test_verdict": test_verdict,
        "verifier_verdict": verifier_verdict,
        "verifier_confidence": (verifier_obj or {}).get("confidence") or None,
        "model": cfg["agents"]["implementer_model"],
        "cost_usd": cost_total if cost_total is not None else (result or {}).get("total_cost_usd"),
        "turns": turns_total if turns_total is not None else (result or {}).get("num_turns"),
        "duration_ms": (result or {}).get("duration_ms"),
        "session_id": (result or {}).get("session_id"),
        "repo_sha": repo_sha or None,
        "skill_sha": skill_sha or None,
        "goal_contract_sha": goal_contract_sha(task),
        "started_at": started_at,
    }
    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm.items() if v is not None)

    # 種類A: 「やったこと」は Implementer 自身の最終出力をそのまま載せる(runner は再要約しない)。
    summary = (result or {}).get("result") or "（最終出力なし。implementer.stderr.log / transcript を参照）"

    evidence = []
    if task.get("verify"):
        ok = {"pass": "全通過", "fail": f"失敗 (exit {verify_code})", "none": "なし"}.get(test_verdict, test_verdict)
        evidence.append(f"- 決定論テスト `{task['verify']}`: {ok} — test-output.txt")
    evidence.append("- diff: change.patch")
    if (RUNS / run_id / "transcript.jsonl").exists():
        evidence.append("- transcript: transcript.jsonl(Implementer セッション)")

    accept = "\n".join(f"- {a}" for a in (task.get("accept") or [])) or "(なし)"

    # 役割別実行テーブル(model は result.json の modelUsage キーから取る)
    role_rows = []
    for r, label in (("explorer", "Explorer"), ("implementer", "Implementer"), ("verifier", "Verifier")):
        d = roles.get(r)
        if d:
            model = next(iter(d.get("modelUsage") or {}), "")
            role_rows.append(f"| {label} | {model} | {d.get('total_cost_usd', '')} | {d.get('num_turns', '')} |")
        else:
            role_rows.append(f"| {label} | — | — | — |")
    role_table = "\n".join(role_rows)

    # Verifier 判定(事実表示。種類B ではない)
    if verifier_obj:
        crit = "\n".join(
            f"  - [{'✓' if c.get('met') else '✗'}] {c.get('criterion', '')} — {c.get('evidence', '')}"
            for c in (verifier_obj.get("criteria") or [])
        ) or "  (基準内訳なし)"
        verifier_block = (
            f"- verdict: {verifier_verdict} / confidence: {verifier_obj.get('confidence', '')}\n"
            f"- test gaming 疑い: {verifier_obj.get('test_gaming_suspected', '')}\n"
            f"- 理由: {verifier_obj.get('reasons', '')}\n"
            f"- 基準ごと:\n{crit}"
        )
    else:
        verifier_block = f"- verdict: {verifier_verdict}(構造化出力なし / 判定不能)"

    body = f"""---
{fm_lines}
---

## 目標契約
{task['goal']}

### 受け入れ基準
{accept}

## エージェントがやったこと
（Implementer の最終出力＝エージェント自身の報告。runner は再要約しない）

{summary}

## 役割別実行
| 役割 | model | cost_usd | turns |
|---|---|---|---|
{role_table}

## Verifier の判定（種類A / 自動。人間の判断ではない）
{verifier_block}

## 証拠
{chr(10).join(evidence)}

{JUDGMENT_HEADING} ← 人間がここだけ書く（種類B / 自動化しない）

### 信用できるか

### 失敗/リスク

### 自動検証に入れるべきチェック

### 学び
"""
    out = RUNS / f"{run_id}.md"
    out.write_text(body, encoding="utf-8")
    return out


# --- review(種類B への着地。判断そのものは人間が nvim で書く) ---

def set_md_reviewed(md: Path) -> None:
    lines = md.read_text(encoding="utf-8").splitlines()
    for k, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == "reviewed":
            lines[k] = "reviewed: true"
            break
    else:
        if lines and lines[0].strip() == "---":
            lines.insert(1, "reviewed: true")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def judgment_line(md: Path) -> int:
    for i, line in enumerate(md.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith(JUDGMENT_HEADING):
            return i
    return 1


def mark_reviewed(run_id: str, cfg: dict) -> None:
    """種類A: 判断記入後の後処理。reviewed 化 → SQLite upsert → コミット。"""
    md = RUNS / f"{run_id}.md"
    set_md_reviewed(md)
    conn = loopdb.connect(DB)
    loopdb.upsert_md(conn, md)
    conn.close()
    auto_commit(DATA, [md], f"review: {run_id} を reviewed 化")


def unreviewed_runs() -> list[Path]:
    out = []
    for md in sorted(RUNS.glob("*.md")):
        fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8"))
        if str(fm.get("reviewed", "false")).lower() not in ("true", "1"):
            out.append(md)
    return out


# --- 判断の読み書き(GUI フォーム ↔ 契約ファイル。中身は人間が書く) ---

# (フォーム field, MD 箇条書きラベル) の対応。順序は MD の表示順。
JUDGMENT_FIELDS = [
    ("trust", "信用できるか"),
    ("risk", "失敗/リスク"),
    ("checks", "自動検証に入れるべきチェック"),
    ("learning", "学び"),
]


def parse_judgment(md: Path) -> dict:
    """MD の判断セクション(### サブ見出し)から各フィールドの現在値を読む(prefill 用)。
    複数行・複数段落をそのまま保持する。"""
    label_to_key = {label: key for key, label in JUDGMENT_FIELDS}
    values = {key: "" for key, _ in JUDGMENT_FIELDS}
    text = md.read_text(encoding="utf-8")
    if JUDGMENT_HEADING not in text:
        return values
    section = text.split(JUDGMENT_HEADING, 1)[1]
    cur, buf = None, []
    for line in section.splitlines():
        if line.startswith("### "):
            if cur is not None:
                values[cur] = "\n".join(buf).strip()
            cur, buf = label_to_key.get(line[4:].strip()), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        values[cur] = "\n".join(buf).strip()
    return values


def write_judgment(run_id: str, fields: dict, cfg: dict) -> None:
    """種類A: GUI から来た判断を契約ファイルへ書き戻す。中身(fields)は人間が書いたもの。
    判断セクション置換 → review-notes.md 追記 → reviewed 化 → SQLite 再導出 → コミット。
    複数行の散文(学び・判断)を圧縮せずそのまま保持する。"""
    md = RUNS / f"{run_id}.md"
    lines = md.read_text(encoding="utf-8").splitlines()
    head = next((i for i, l in enumerate(lines) if l.startswith(JUDGMENT_HEADING)), len(lines))

    section = [f"{JUDGMENT_HEADING} ← 人間がここだけ書く（種類B / 自動化しない）", ""]
    for key, label in JUDGMENT_FIELDS:
        section.append(f"### {label}")
        section.append("")
        val = (fields.get(key) or "").strip()
        if val:
            section.append(val)
            section.append("")
    md.write_text("\n".join(lines[:head] + section).rstrip() + "\n", encoding="utf-8")

    checks = (fields.get("checks") or "").strip()
    if checks:
        day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        cl = checks.splitlines()
        entry = f"- {day} {run_id}: {cl[0]}\n" + "".join(f"  {x}\n" for x in cl[1:])
        with REVIEW_NOTES.open("a", encoding="utf-8") as f:
            f.write(entry)

    set_md_reviewed(md)
    conn = loopdb.connect(DB)
    loopdb.upsert_md(conn, md)
    conn.close()
    auto_commit(DATA, [md, REVIEW_NOTES], f"review: {run_id} 判断を記入し reviewed 化")


# --- コマンド ---

def _run_attempt(task: dict, run_id: str, cfg: dict, started_at: str) -> tuple[str, bool]:
    """1 試行(Explorer→Implementer→決定論テスト→Verifier)。(final, retryable) を返す。
    retryable=True は「実装が timeout/error で確定しなかった」= run 全体を再試行する価値がある状態。
    Verifier の handoff(判定不能)は read-only のまま内部で再判定する(冪等で安全)。"""
    loop, agents = cfg["loop"], cfg["agents"]
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    repo = resolve_repo(task, cfg)
    no_repo = repo is None
    if not no_repo and not is_git_repo(repo):
        (run_dir / "test-output.txt").write_text(f"NG: repo が git リポジトリではありません: {repo}\n", encoding="utf-8")
        write_run_status(run_id=run_id, task=task["id"], repo=str(repo),
                         started_at=started_at, phase="verifier", verdict=None)
        md = write_run_md(task, run_id, "fail", None, cfg, started_at, None,
                          "none", "handoff", None, {}, repo=None)
        with _DATA_COMMIT_LOCK:  # 完了処理(task status / loop.db / commit)を一括で直列化(§4.3)
            update_status(task["id"], "fail")
            conn = loopdb.connect(DB); loopdb.upsert_md(conn, md); conn.close()
            auto_commit(DATA, [md, run_dir, task.get("_path")], f"run: {run_id} → fail(repo 不正)")
        clear_run_status(run_id, "fail")
        print(f"  · repo が不正: {repo} → fail")
        return "fail", False

    if no_repo:  # どのリポジトリにも属さないタスク: git なしの一時作業ディレクトリ
        wt, branch = WORKTREES_DIR / run_id, None
        wt.mkdir(parents=True, exist_ok=True)
    else:
        wt, branch = add_worktree(repo, run_id)
    repo_label = str(repo) if repo else "none"
    try:
        # 1) Explorer(read-only、失敗は致命でない)
        write_run_status(run_id=run_id, task=task["id"], repo=repo_label,
                         started_at=started_at, phase="explorer")
        print("  · Explorer 調査中 …")
        e_result, _ = run_role("explorer", render_explorer_prompt(task), wt, cfg,
                               agents["explorer_model"], agents["explorer_tools"], run_dir, read_only=True)
        explorer_findings = (e_result or {}).get("result") or "(Explorer 出力なし)"

        # 2) Implementer(read-write、ここが本作業)
        write_run_status(run_id=run_id, phase="implementer")
        print("  · Implementer 実装中 …")
        i_tools = resolve_tools(task.get("allowed_tools"), agents["implementer_tools"])
        i_result, i_hint = run_role("implementer", render_implementer_prompt(task, explorer_findings),
                                    wt, cfg, agents["implementer_model"], i_tools, run_dir)
        copy_transcript(i_result, run_dir)   # 主トランスクリプトは Implementer セッション
        if no_repo:
            (run_dir / "change.patch").write_text("（no-repo タスク: git diff なし。証拠は test-output と transcript)\n", encoding="utf-8")
        else:
            capture_diff(wt, run_dir)

        verifier_obj = None
        retryable = False
        if i_hint == "timeout":
            final, test_verdict, verifier_verdict, vcode = "timeout", "none", "handoff", None
            retryable = True
        elif i_hint == "error":
            final, test_verdict, verifier_verdict, vcode = "fail", "none", "handoff", None
            retryable = True
        else:
            # 3) 決定論テスト(証拠)
            write_run_status(run_id=run_id, phase="verifier")
            test_verdict, vcode = run_verify(task, wt, run_dir)   # "pass"/"fail"/"none"
            # 4) Verifier(別モデル、read-only、構造化出力)。handoff の間は再判定(冪等で安全)。
            vmax = int(loop.get("verifier_attempts", 3))
            diff_text = (run_dir / "change.patch").read_text(encoding="utf-8", errors="replace")
            tp = run_dir / "test-output.txt"
            test_output = tp.read_text(encoding="utf-8", errors="replace") if tp.exists() else "(なし)"
            verifier_verdict = "handoff"
            for vatt in range(1, vmax + 1):
                print(f"  · Verifier {'判定中' if vatt == 1 else f'再判定 {vatt}/{vmax}'} …")
                v_result, v_hint = run_role(
                    "verifier", render_verifier_prompt(task, diff_text, test_output),
                    wt, cfg, agents["verifier_model"], agents["verifier_tools"], run_dir,
                    extra_args=["--json-schema", json.dumps(VERIFIER_SCHEMA, ensure_ascii=False)],
                    read_only=True)
                verifier_verdict, verifier_obj = parse_verifier(v_result, v_hint, run_dir)
                if verifier_verdict != "handoff":
                    break
            final = combine_verdict(test_verdict, verifier_verdict)

        # remove --force の前にコミットして成果を loop/<id> ブランチに残す(repo タスクのみ)。
        committed = commit_worktree(wt, f"loop run {run_id} → {final}") if not no_repo else False

        roles = {}
        for r in ("explorer", "implementer", "verifier"):
            p = run_dir / f"{r}.result.json"
            roles[r] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

        md = write_run_md(task, run_id, final, i_result, cfg, started_at, vcode,
                          test_verdict, verifier_verdict, verifier_obj, roles, repo=repo)
        # 完了処理(task status 書換 / loop.db upsert / data/ commit)を 1 ブロックで直列化(§4.3)。
        # N 本が同時にここへ来ても data/ の index.lock 競合や loop.db 書込み競合を避ける。
        with _DATA_COMMIT_LOCK:
            update_status(task["id"], final)
            conn = loopdb.connect(DB)
            loopdb.upsert_md(conn, md)
            conn.close()
            auto_commit(DATA, [md, run_dir, task.get("_path")], f"run: {run_id} → {final}")

        print(f"  · test={test_verdict} / verifier={verifier_verdict} / final={final}")
        if no_repo:
            print(f"  · run MD: {md.relative_to(DATA)}(no-repo)")
        else:
            branch_note = f"branch {branch} に成果をコミット" if committed else f"branch {branch}(変更なし)"
            print(f"  · run MD: {md.relative_to(DATA)} / {branch_note}")
        return final, retryable
    finally:
        clear_run_status(run_id, locals().get("final"))  # status.json を done 化(.run.lock ミラーも掃除)
        if no_repo:
            shutil.rmtree(wt, ignore_errors=True)
        else:
            remove_worktree(repo, wt)


def _run_task_to_completion(task: dict, cfg: dict) -> str:
    """1 タスクを確定まで担当する(=1 ジョブの単位。§4.4-a)。再試行込みで最終 verdict を返す。
    claim 機構を持たない: claim は呼び出し側(cmd_run / ワーカープール)の責務。"""
    now = datetime.now(timezone.utc).astimezone()
    # 同日リトライでの run_id 衝突を避けるため時刻まで含める。再試行は -retryN を付ける。
    base = f"{now:%Y-%m-%d-%H%M%S}-{task['id']}"
    started_at = now.isoformat(timespec="seconds")
    # 実装が timeout/error で確定しなかったときだけ run 全体を再試行(冪等タスク前提)。
    # 決定済みの pass/fail/handoff は再試行しない。非冪等タスクは task に max_attempts: 1 を指定。
    max_attempts = int(task.get("max_attempts") or cfg["loop"].get("max_attempts", 2))

    final = "fail"
    for attempt in range(1, max_attempts + 1):
        run_id = base if attempt == 1 else f"{base}-retry{attempt}"
        print(f"▶ run: {run_id}" + ("" if attempt == 1 else f"(再試行 {attempt}/{max_attempts})"))
        final, retryable = _run_attempt(task, run_id, cfg, started_at)
        if not retryable:
            break
        if attempt == max_attempts:
            print(f"  · 再試行上限({max_attempts})到達 → final={final} で確定。")
            break
        print(f"  · 実装が確定せず({final})。新しい worktree で run 全体を再試行します …")
    return final


def _warn_same_verifier(cfg: dict) -> None:
    agents = cfg["agents"]
    if agents["verifier_model"] == agents["implementer_model"]:
        print("  ! 警告: verifier_model が implementer_model と同一。別モデルにすべき(記事の Sub-agents の肝)。")


def _run_serial(task_id: str | None, cfg: dict) -> int:
    """max_concurrency=1 の直列実行。.run.lock の O_EXCL atomic claim で従来挙動を完全維持する。"""
    # 単一オペレータ前提の atomic claim。/dispatch 連打などの同時実行で
    # 同一タスクを2プロセスが拾い branch 衝突するのを防ぐ。
    lock = DATA / ".run.lock"
    try:
        os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        print("別の run が進行中です(data/.run.lock)。完了を待つか、残留なら削除してください。")
        return 1
    try:
        if task_id:  # 特定タスクを指定実行(Web の「実行」ボタン)
            task = next((t for t in parse_tasks() if t.get("id") == task_id), None)
            if not task:
                print(f"タスクが見つかりません: {task_id}")
                return 1
        else:
            task = next_todo(parse_tasks())
        if not task:
            print("実行可能な todo タスクがありません(data/tasks/)。")
            return 0
        _warn_same_verifier(cfg)
        _run_task_to_completion(task, cfg)
    finally:
        lock.unlink(missing_ok=True)
    return 0


def _claim_next(cfg: dict, handled: set[str], guard: threading.Lock) -> dict | None:
    """todo の先頭から、この invocation でまだ拾っていない最初のタスクを atomic に claim する。
    .run.lock(O_EXCL)が単一プロセスで担っていた「同一タスクの二重 claim 防止」を N 並行間で再現する
    (§4.2 の claim を in-process に縮約)。`handled` は揮発キャッシュで authoritative ではない
    (真実は tasks/*.md の status)。一度 claim したタスクはこの実行内では二度と拾わない
    = 1 job = 1 task を確定まで担当(§4.4-a)。"""
    with guard:
        for t in parse_tasks():
            if t["id"] in handled:
                continue
            if str(t.get("status", "todo")).lower() != "todo":
                continue
            handled.add(t["id"])
            return t
        return None


def _run_parallel(task_id: str | None, cfg: dict, max_concurrency: int) -> int:
    """max_concurrency>1 の並列実行。in-process claim + ThreadPool で N 本同時に回す。
    claude -p は subprocess 委譲なので GIL を待たず並行する(§4.6)。"""
    _warn_same_verifier(cfg)
    if task_id:  # 単一タスク指定。別タスクとは並行可だが、同一タスクの二重起動だけは防ぐ。
        # max_concurrency>1 では全体 .run.lock を持たないため、ここは task 単位の atomic claim
        # (.run-<id>.lock の O_EXCL)で「同じタスクを2プロセスが同時実行」だけを排除する(§4.4-a)。
        tlock = DATA / f".run-{_safe_task_id(task_id)}.lock"
        try:
            os.close(os.open(str(tlock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            print(f"このタスクは既に実行中です({tlock.name})。完了待ち、または残留なら削除してください。")
            return 1
        try:
            task = next((t for t in parse_tasks() if t.get("id") == task_id), None)
            if not task:
                print(f"タスクが見つかりません: {task_id}")
                return 1
            _run_task_to_completion(task, cfg)
        finally:
            tlock.unlink(missing_ok=True)
            (DATA / ".run.lock").unlink(missing_ok=True)  # 単一 run 後方互換マーカーを掃除
        return 0

    print(f"▶ 並列実行(max_concurrency={max_concurrency})。todo を順に claim します …")
    handled: set[str] = set()  # この実行で claim 済みのタスク id(再 claim 防止。揮発)
    guard = threading.Lock()

    def _worker() -> None:
        while True:
            task = _claim_next(cfg, handled, guard)
            if task is None:
                return
            try:
                _run_task_to_completion(task, cfg)
            except Exception as ex:  # 1 ジョブの失敗を他ワーカーへ波及させない(§4.4-e)
                print(f"  ! run 失敗(隔離) {task['id']}: {ex!r}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        for f in [pool.submit(_worker) for _ in range(max_concurrency)]:
            f.result()
    (DATA / ".run.lock").unlink(missing_ok=True)  # 全 run 完了 → 単一 run 後方互換マーカーを掃除
    return 0


def cmd_run(task_id: str | None = None) -> int:
    cfg = load_config()
    DATA.mkdir(parents=True, exist_ok=True)
    REVIEW_NOTES.touch(exist_ok=True)
    # デフォルト 1 = 従来の単一直列(.run.lock)と完全等価。N へ上げるのは loop.toml の明示宣言のみ。
    max_concurrency = max(1, int(cfg["loop"].get("max_concurrency", 1)))
    if max_concurrency == 1:
        return _run_serial(task_id, cfg)
    return _run_parallel(task_id, cfg, max_concurrency)


def cmd_reindex() -> int:
    conn = loopdb.connect(DB)
    n = loopdb.reindex(conn, RUNS)
    conn.close()
    print(f"reindex 完了: {n} 件の run MD から loop.db を再生成しました。")
    return 0


def cmd_review() -> int:
    import os
    cfg = load_config()
    pending = unreviewed_runs()
    if not pending:
        print("未レビューの run はありません。")
        return 0
    md = pending[0]
    run_id = md.stem
    editor = os.environ.get("EDITOR", "nvim")
    print(f"▶ review: {run_id}（残り {len(pending)} 件）")
    print(f"  · {editor} で判断セクションを開きます。保存して閉じると reviewed 化 + コミットします。")
    subprocess.run([editor, f"+{judgment_line(md)}", str(md)])
    mark_reviewed(run_id, cfg)
    print(f"  · {run_id}: reviewed:true / SQLite upsert / コミット 完了")
    return 0


def cmd_status() -> int:
    mds = sorted(RUNS.glob("*.md"))
    if not mds:
        print("run がまだありません。")
        return 0
    print(f"{'run':<40} {'verdict':<9} {'rev':<4} {'cost':>7} {'turns':>6}")
    print("-" * 72)
    for md in mds:
        fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8"))
        cost = fm.get("cost_usd", "")
        cost = f"${float(cost):.3f}" if cost else ""
        rev = "✓" if str(fm.get("reviewed", "false")).lower() in ("true", "1") else "·"
        print(f"{md.stem:<40} {fm.get('verdict', '?'):<9} {rev:<4} {cost:>7} {fm.get('turns', ''):>6}")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        return cmd_run(sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd == "gen":
        rest = sys.argv[3:]
        repo = rest[rest.index("--repo") + 1] if "--repo" in rest and rest.index("--repo") + 1 < len(rest) else None
        return cmd_gen(sys.argv[2] if len(sys.argv) > 2 else "", "--run" in rest, repo)
    table = {"reindex": cmd_reindex, "review": cmd_review, "status": cmd_status}
    if cmd in table:
        return table[cmd]()
    print(f"unknown command: {cmd}\nusage: runner.py [run [task_id]|gen <prompt> [--run]|review|reindex|status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
