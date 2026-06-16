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
TODO = DATA / "TODO.md"
RUNS = DATA / "runs"
DB = DATA / "loop.db"
REVIEW_NOTES = DATA / "review-notes.md"

JUDGMENT_HEADING = "## 判断"


# --- TODO.md パース(```yaml フェンスブロック = 1 タスク) ---

def parse_tasks() -> list[dict]:
    if not TODO.exists():
        return []
    lines = TODO.read_text(encoding="utf-8").splitlines()
    tasks: list[dict] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("```") and "yaml" in stripped:
            inner_start = i + 1
            j = inner_start
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            block = "\n".join(lines[inner_start:j])
            try:
                data = yaml.safe_load(block) or {}
            except yaml.YAMLError as e:
                print(f"  ! YAML パース失敗(無視): {e}", file=sys.stderr)
                data = {}
            if isinstance(data, dict) and data.get("id"):
                data["_inner_start"] = inner_start
                data["_inner_end"] = j
                tasks.append(data)
            i = j + 1
        else:
            i += 1
    return tasks


def next_todo(tasks: list[dict]) -> dict | None:
    for t in tasks:
        if str(t.get("status", "todo")).lower() == "todo":
            return t
    return None


def update_status(task_id: str, new_status: str) -> None:
    tasks = parse_tasks()
    target = next((t for t in tasks if t.get("id") == task_id), None)
    if not target:
        return
    lines = TODO.read_text(encoding="utf-8").splitlines()
    inner_start, inner_end = target["_inner_start"], target["_inner_end"]
    for k in range(inner_start, inner_end):
        if lines[k].split(":", 1)[0].strip() == "status":
            indent = lines[k][: len(lines[k]) - len(lines[k].lstrip())]
            lines[k] = f"{indent}status: {new_status}"
            break
    else:
        lines.insert(inner_start, f"status: {new_status}")
    TODO.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    rels = [str(p.relative_to(repo)) for p in paths if p.exists()]
    if not rels:
        return
    git(repo, "add", *rels)
    staged = git(repo, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        return  # 差分なし
    git(repo, "commit", "-q", "-m", message)


# --- headless 実行 ---

def run_claude(prompt: str, wt: Path, cfg: dict, task: dict, run_dir: Path) -> tuple[dict | None, str]:
    loop = cfg["loop"]
    model = task.get("model") or loop["model"]
    tools = task.get("allowed_tools")
    if isinstance(tools, str):
        tools = [s.strip() for s in tools.split(",") if s.strip()]
    tools = tools or loop["default_allowed_tools"]

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(loop["max_turns"]),
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--allowedTools", *tools,
    ]
    stderr_log = run_dir / "stderr.log"
    try:
        proc = subprocess.run(
            cmd, cwd=str(wt), capture_output=True, text=True, timeout=loop["timeout_seconds"],
        )
    except subprocess.TimeoutExpired as e:
        stderr_log.write_text(e.stderr if isinstance(e.stderr, str) else "", encoding="utf-8")
        return None, "timeout"

    stderr_log.write_text(proc.stderr or "", encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        (run_dir / "result.raw.txt").write_text(proc.stdout or "", encoding="utf-8")
        return None, "error"
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, ("error" if result.get("is_error") else "ok")


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
            "verify コマンド未指定。決定論で二値判定できないため handoff。\n", encoding="utf-8"
        )
        return "handoff", None
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
                 cfg: dict, started_at: str, verify_code: int | None) -> Path:
    repo = repo_root(cfg)
    repo_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    skill_sha = git(repo, "rev-parse", "HEAD:.claude/skills").stdout.strip()

    fm = {
        "task": task["id"],
        "verdict": verdict,
        "reviewed": "false",
        "model": (result or {}).get("model") or task.get("model") or cfg["loop"]["model"],
        "cost_usd": (result or {}).get("total_cost_usd"),
        "turns": (result or {}).get("num_turns"),
        "duration_ms": (result or {}).get("duration_ms"),
        "session_id": (result or {}).get("session_id"),
        "repo_sha": repo_sha,
        "skill_sha": skill_sha or None,
        "goal_contract_sha": goal_contract_sha(task),
        "started_at": started_at,
    }
    fm_lines = "\n".join(f"{k}: {v}" for k, v in fm.items() if v is not None)

    # 種類A: 「やったこと」はエージェント自身の最終出力をそのまま載せる(runner は再要約しない)。
    summary = (result or {}).get("result") or "（最終出力なし。stderr.log / transcript を参照）"

    evidence = []
    if task.get("verify"):
        ok = "全通過" if verdict == "pass" else f"失敗 (exit {verify_code})"
        evidence.append(f"- 検証 `{task['verify']}`: {ok} — test-output.txt")
    evidence.append("- diff: change.patch")
    if (RUNS / run_id / "transcript.jsonl").exists():
        evidence.append("- transcript: transcript.jsonl")

    accept = "\n".join(f"- {a}" for a in (task.get("accept") or [])) or "(なし)"

    body = f"""---
{fm_lines}
---

## 目標契約
{task['goal']}

### 受け入れ基準
{accept}

## エージェントがやったこと
（claude -p の最終出力＝エージェント自身の報告。runner は再要約しない）

{summary}

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

def cmd_run() -> int:
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
        task = next_todo(parse_tasks())
        if not task:
            print("実行可能な todo タスクがありません(TODO.md)。")
            return 0

        now = datetime.now(timezone.utc).astimezone()
        # 同日リトライでの run_id 衝突(過去 run の上書き)を避けるため時刻まで含める。
        run_id = f"{now:%Y-%m-%d-%H%M%S}-{task['id']}"
        run_dir = RUNS / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        started_at = now.isoformat(timespec="seconds")

        print(f"▶ run: {run_id}")
        repo = repo_root(cfg)
        wt, branch = add_worktree(repo, run_id)
        try:
            print("  · claude -p 実行中 …")
            result, hint = run_claude(render_prompt(task), wt, cfg, task, run_dir)
            copy_transcript(result, run_dir)
            capture_diff(wt, run_dir)

            if hint == "timeout":
                verdict, vcode = "timeout", None
            elif hint == "error":
                verdict, vcode = "fail", None
            else:
                verdict, vcode = run_verify(task, wt, run_dir)

            # remove --force の前にコミットして成果を loop/<id> ブランチに残す。
            committed = commit_worktree(wt, f"loop run {run_id} → {verdict}")

            md = write_run_md(task, run_id, verdict, result, cfg, started_at, vcode)
            update_status(task["id"], verdict)

            conn = loopdb.connect(DB)
            loopdb.upsert_md(conn, md)
            conn.close()

            auto_commit(DATA, [md, run_dir, TODO], f"run: {run_id} → {verdict}")

            print(f"  · verdict: {verdict}")
            print(f"  · run MD: {md.relative_to(DATA)}（判断は未記入 / reviewed:false）")
            branch_note = f"branch {branch} に成果をコミット" if committed else f"branch {branch}(変更なし)"
            print(f"  · SQLite upsert 済 / data へ自動コミット済 / {branch_note}")
        finally:
            remove_worktree(repo, wt)
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
    table = {"run": cmd_run, "reindex": cmd_reindex, "review": cmd_review, "status": cmd_status}
    if cmd in table:
        return table[cmd]()
    print(f"unknown command: {cmd}\nusage: runner.py [run|review|reindex|status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
