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

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
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

JUDGMENT_HEADING = "## 判断"


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
    canonical = {k: task.get(k) for k in ("goal", "accept", "constraints", "verify", "allowed_tools")}
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


# --- git ---

def repo_root(cfg: dict) -> Path:
    return (ROOT / cfg["repo"]["path"]).resolve()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def add_worktree(repo: Path, run_id: str) -> tuple[Path, str]:
    wt = repo.parent / ".loop-worktrees" / run_id
    branch = f"loop/{run_id}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(wt), "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return wt, branch


def remove_worktree(repo: Path, wt: Path) -> None:
    git(repo, "worktree", "remove", "--force", str(wt))


def commit_worktree(wt: Path, message: str) -> bool:
    """worktree のステージ済み変更を loop/<id> ブランチにコミットする。
    remove --force は作業ツリーを破棄するため、ここで commit しないと成果がブランチに残らない。"""
    if git(wt, "diff", "--cached", "--quiet").returncode == 0:
        return False  # 変更なし
    git(wt, "commit", "-q", "-m", message)
    return True


def auto_commit(repo: Path, paths: list[Path], message: str) -> None:
    """種類A: チェックポイントコミット。loop.db(ビュー)は .gitignore 済みなので入らない。"""
    rels = [str(p.relative_to(repo)) for p in paths if p and p.exists()]
    if not rels:
        return
    git(repo, "add", *rels)
    staged = git(repo, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        return  # 差分なし
    git(repo, "commit", "-q", "-m", message)


# --- headless 実行(役割ごと) ---

def run_role(role: str, prompt: str, wt: Path, cfg: dict, model: str,
             tools: list[str], run_dir: Path,
             extra_args: list[str] | None = None) -> tuple[dict | None, str]:
    """役割を1つ headless 実行し {role}.result.json / {role}.stderr.log を保存する。"""
    loop = cfg["loop"]
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(loop.get("max_turns", 40)),
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--allowedTools", *tools,
    ]
    if extra_args:
        cmd += extra_args
    err = run_dir / f"{role}.stderr.log"
    try:
        proc = subprocess.run(cmd, cwd=str(wt), capture_output=True, text=True,
                              timeout=loop["timeout_seconds"])
    except subprocess.TimeoutExpired as e:
        err.write_text(e.stderr if isinstance(e.stderr, str) else "", encoding="utf-8")
        return None, "timeout"
    err.write_text(proc.stderr or "", encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        (run_dir / f"{role}.result.raw.txt").write_text(proc.stdout or "", encoding="utf-8")
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
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(loop.get("max_turns", 40)),
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--allowedTools", "Read", "Grep", "Glob",
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
                 verifier_obj: dict | None = None, roles: dict | None = None) -> Path:
    repo = repo_root(cfg)
    repo_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    skill_sha = git(repo, "rev-parse", "HEAD:.claude/skills").stdout.strip()
    roles = roles or {}

    cost_total = sum(r["total_cost_usd"] for r in roles.values() if r and r.get("total_cost_usd") is not None) or None
    turns_total = sum(r["num_turns"] for r in roles.values() if r and r.get("num_turns") is not None) or None

    fm = {
        "task": task["id"],
        "verdict": verdict,
        "reviewed": "false",
        "test_verdict": test_verdict,
        "verifier_verdict": verifier_verdict,
        "verifier_confidence": (verifier_obj or {}).get("confidence") or None,
        "model": cfg["agents"]["implementer_model"],
        "cost_usd": cost_total if cost_total is not None else (result or {}).get("total_cost_usd"),
        "turns": turns_total if turns_total is not None else (result or {}).get("num_turns"),
        "duration_ms": (result or {}).get("duration_ms"),
        "session_id": (result or {}).get("session_id"),
        "repo_sha": repo_sha,
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
    repo = repo_root(cfg)
    wt, branch = add_worktree(repo, run_id)
    try:
        # 1) Explorer(read-only、失敗は致命でない)
        print("  · Explorer 調査中 …")
        e_result, _ = run_role("explorer", render_explorer_prompt(task), wt, cfg,
                               agents["explorer_model"], agents["explorer_tools"], run_dir)
        explorer_findings = (e_result or {}).get("result") or "(Explorer 出力なし)"

        # 2) Implementer(read-write、ここが本作業)
        print("  · Implementer 実装中 …")
        i_tools = resolve_tools(task.get("allowed_tools"), agents["implementer_tools"])
        i_result, i_hint = run_role("implementer", render_implementer_prompt(task, explorer_findings),
                                    wt, cfg, agents["implementer_model"], i_tools, run_dir)
        copy_transcript(i_result, run_dir)   # 主トランスクリプトは Implementer セッション
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
                    extra_args=["--json-schema", json.dumps(VERIFIER_SCHEMA, ensure_ascii=False)])
                verifier_verdict, verifier_obj = parse_verifier(v_result, v_hint, run_dir)
                if verifier_verdict != "handoff":
                    break
            final = combine_verdict(test_verdict, verifier_verdict)

        # remove --force の前にコミットして成果を loop/<id> ブランチに残す。
        committed = commit_worktree(wt, f"loop run {run_id} → {final}")

        roles = {}
        for r in ("explorer", "implementer", "verifier"):
            p = run_dir / f"{r}.result.json"
            roles[r] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

        md = write_run_md(task, run_id, final, i_result, cfg, started_at, vcode,
                          test_verdict, verifier_verdict, verifier_obj, roles)
        update_status(task["id"], final)

        conn = loopdb.connect(DB)
        loopdb.upsert_md(conn, md)
        conn.close()

        auto_commit(DATA, [md, run_dir, task.get("_path")], f"run: {run_id} → {final}")

        print(f"  · test={test_verdict} / verifier={verifier_verdict} / final={final}")
        branch_note = f"branch {branch} に成果をコミット" if committed else f"branch {branch}(変更なし)"
        print(f"  · run MD: {md.relative_to(DATA)} / {branch_note}")
        return final, retryable
    finally:
        remove_worktree(repo, wt)


def cmd_run(task_id: str | None = None) -> int:
    import os
    cfg = load_config()
    DATA.mkdir(parents=True, exist_ok=True)
    REVIEW_NOTES.touch(exist_ok=True)

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

        agents = cfg["agents"]
        if agents["verifier_model"] == agents["implementer_model"]:
            print("  ! 警告: verifier_model が implementer_model と同一。別モデルにすべき(記事の Sub-agents の肝)。")

        now = datetime.now(timezone.utc).astimezone()
        # 同日リトライでの run_id 衝突を避けるため時刻まで含める。再試行は -retryN を付ける。
        base = f"{now:%Y-%m-%d-%H%M%S}-{task['id']}"
        started_at = now.isoformat(timespec="seconds")
        # 実装が timeout/error で確定しなかったときだけ run 全体を再試行(冪等タスク前提)。
        # 決定済みの pass/fail/handoff は再試行しない。非冪等タスクは task に max_attempts: 1 を指定。
        max_attempts = int(task.get("max_attempts") or cfg["loop"].get("max_attempts", 2))

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
    finally:
        lock.unlink(missing_ok=True)
    return 0


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
    table = {"reindex": cmd_reindex, "review": cmd_review, "status": cmd_status}
    if cmd in table:
        return table[cmd]()
    print(f"unknown command: {cmd}\nusage: runner.py [run [task_id]|review|reindex|status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
