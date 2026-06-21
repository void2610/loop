# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Loop Engineering の計測配管ランナー(v3)。

種類A(メカニクス)はすべてここで全自動化する: dispatch / headless 実行 / 証拠収集 /
自動チェックポイントコミット / run MD 生成 / SQLite upsert / インデックス再生成。
種類B(判断)は決して自動化しない。run MD の「判断」セクションは空のまま出力し、人間が Web 判断フォームで書く。
実行系は claude -p と git worktree(ネイティブ)に委ね、ここは突き合わせ層に徹する。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
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
        cfg = tomllib.load(f)
    # マシン固有の上書き(gitignore)。[repos] の実パス等を公開 repo に晒さないための層。
    local = CONFIG.parent / "loop.local.toml"
    if local.exists():
        with local.open("rb") as f:
            for k, v in tomllib.load(f).items():
                cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def _data_dir() -> Path:
    """契約データ(tasks/runs/review-notes/loop.db)の置き場。別の private git repo にする。
    loop.local.toml [data] dir で host 別パス(例: "data/hosts/<host>")に上書きできる。"""
    try:
        d = load_config().get("data", {}).get("dir", "data")
    except FileNotFoundError:
        d = "data"
    return (ROOT / d).resolve()


# データ系のパスは data_dir 配下に置く(エンジン=公開 repo とは別の git repo)。
DATA = _data_dir()
TASKS_DIR = DATA / "tasks"   # 1 タスク = 1 ファイル(data/tasks/<id>.md、YAML front-matter)
PLANS_DIR = TASKS_DIR / "plans"  # Author 生成の詳細実装プラン(契約の body 外サイドカー: data/tasks/plans/<id>.md)
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


def plan_path(task_id: str) -> Path:
    return PLANS_DIR / f"{task_id}.md"


def write_plan(task_id: str, plan: str) -> Path:
    """Author 生成の実装プランをサイドカーに書く(契約 body は肥らせない)。"""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    p = plan_path(task_id)
    p.write_text(plan.strip() + "\n", encoding="utf-8")
    return p


def read_plan(task_id: str) -> str:
    p = plan_path(task_id)
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


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

# プロンプトの prose 本体は .claude/plugins/loop-roles/templates/*.md に外出し済み。
# Python は動的セクション(条件付き行 / 配列の整形)だけ組み立て、.format() で流す。
TEMPLATES = ROOT / ".claude" / "plugins" / "loop-roles" / "templates"


def _read_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _bullet_section(header: str, items: list, prefix: str = "- ") -> str:
    items = [str(x) for x in (items or []) if str(x).strip()]
    if not items:
        return ""
    return f"\n\n# {header}\n" + "\n".join(f"{prefix}{x}" for x in items)


def render_prompt(task: dict) -> str:
    accept_block = _bullet_section("受け入れ基準(すべて満たすこと)", task.get("accept") or [])
    constraints_block = _bullet_section("制約(違反しないこと)", task.get("constraints") or [])
    verify = task.get("verify")
    verify_block = (
        f"\n\n# 検証\n作業完了後、次のコマンドが exit 0 になることが合格条件です(別プロセスで検証されます): `{verify}`"
        if verify else "")
    return _read_template("task-contract.md").format(
        goal=task["goal"], accept_block=accept_block,
        constraints_block=constraints_block, verify_block=verify_block).rstrip() + "\n"


def render_implementer_prompt(task: dict, context: str, source: str = "Author の実装プラン", brief: str = "") -> str:
    # 役の振る舞いは `.claude/plugins/loop-roles/skills/implementer/SKILL.md` に外出し済み。
    # skill は `disable-model-invocation: true` でモデル自動発火を禁じてあるため、runner から
    # **slash command 形式の user メッセージ**で明示呼び出しする(skill 本文の $ARGUMENTS にここの本文が埋まる)。
    base = render_prompt(task)
    args_parts = [f"## タスク契約\n{base}"]
    if context and context.strip():
        args_parts.append(f"## {source}\n{context}")
    if brief:
        args_parts.append(brief.lstrip("\n"))  # build_norms_brief / build_repo_brief は冒頭に見出し付き
    args_text = "\n\n".join(args_parts)
    return f"/loop-roles:implementer {args_text}"


NEEDS_HUMAN_MARKER = "NEEDS_HUMAN:"


def _needs_human(i_result: dict | None) -> str | None:
    """Implementer のターン最終出力に NEEDS_HUMAN 合図があれば、その質問文を返す(実装中の人間介入トリガ)。"""
    text = (i_result or {}).get("result") or ""
    idx = text.find(NEEDS_HUMAN_MARKER)
    if idx < 0:
        return None
    return text[idx + len(NEEDS_HUMAN_MARKER):].strip() or "続行指示をください。"


def render_revise_prompt(task: dict, verifier_obj: dict | None) -> str:
    """Verifier の差し戻し(revise)を受けた Implementer への追加指示(--resume で前文脈を保持)。"""
    obj = verifier_obj or {}
    reasons = str(obj.get("reasons", "")).strip() or "(理由未記載)"
    changes_block = _bullet_section("要対応", obj.get("required_changes") or [])
    verify = task.get("verify")
    verify_block = (
        f"\n\n# 検証\n修正後、`{verify}` が exit 0 になることを自分で確認してから完了してください。"
        if verify else "")
    return _read_template("revise.md").format(
        reasons=reasons, changes_block=changes_block, verify_block=verify_block).rstrip() + "\n"


def render_verifier_prompt(task: dict, diff_text: str, test_output: str, brief: str = "",
                           human_input: str = "") -> str:
    # 役の振る舞いは `.claude/plugins/loop-roles/skills/verifier/SKILL.md` に外出し済み(disable-model-invocation)。
    # runner からは slash で明示呼び出し → Claude Code が入力レイヤで $ARGUMENTS を skill 本文へ展開する。
    accept = "\n".join(f"- {a}" for a in (task.get("accept") or [])) or "(明示なし)"
    constraints = "\n".join(f"- {c}" for c in (task.get("constraints") or [])) or "(なし)"
    parts = [
        f"## ゴール\n{task['goal']}",
        f"## 受け入れ基準(すべて満たすこと)\n{accept}",
        f"## 制約(違反していないか)\n{constraints}",
        f"## 実装の diff\n```diff\n{diff_text[:6000]}\n```",
        f"## 決定論テストの出力\n{test_output[:4000]}",
    ]
    if human_input.strip():
        parts.append(f"## 人間の介入(承認・決定)\n{human_input.strip()}")
    if brief:
        parts.append(brief.lstrip("\n"))  # build_norms_brief / build_repo_brief は冒頭に見出し付き
    return "/loop-roles:verifier " + "\n\n".join(parts)


# --- git / リポジトリ解決 ---

def _repo_entry(value) -> tuple[str, str]:
    """[repos] の値(パス文字列 or {path, mode} テーブル)を (path, mode) に正規化する。
    mode 既定は 'parallel'(後方互換: 文字列指定は従来どおり worktree 並列)。"""
    if isinstance(value, dict):
        return str(value.get("path", "") or ""), str(value.get("mode", "parallel")).strip().lower()
    return str(value), "parallel"


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
        r, _ = _repo_entry(repos[r])
    p = Path(r).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def repo_mode(repo: Path | None, cfg: dict) -> str:
    """解決済み repo パスの実行モード('serial'|'parallel')。[repos] の mode 指定から引く。

    serial = worktree を作らず repo 本体で 1 本ずつ作業する(Unity 等、worktree 運用に不向きな repo 向け)。
    runner だけがこの違いを意識する(タスク生成・記憶・契約ファイルは不変)。既定は parallel。"""
    if repo is None:
        return "parallel"
    target = repo.resolve()
    for value in (cfg.get("repos", {}) or {}).values():
        path_str, mode = _repo_entry(value)
        if not path_str or mode != "serial":
            continue
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        if p.resolve() == target:
            return "serial"
    return "parallel"


def is_git_repo(path: Path) -> bool:
    return path.is_dir() and git(path, "rev-parse", "--git-dir").returncode == 0


def list_branches(repo: Path) -> list[str]:
    """repo のブランチ候補(ローカル + origin/*、origin/ 接頭は剥がして重複除去)。base_branch 選択用。"""
    if not is_git_repo(repo):
        return []
    # full refname で HEAD symref を弾く(origin/HEAD は short だと "origin" になり擦り抜けるため)。
    out = git(repo, "for-each-ref", "--format=%(refname)\t%(refname:short)", "refs/heads", "refs/remotes")
    names: list[str] = []
    for line in out.stdout.splitlines():
        full, _, short = line.partition("\t")
        if not short or full.endswith("/HEAD"):
            continue
        if short.startswith("origin/"):
            short = short[len("origin/"):]
        if short and short not in names:
            names.append(short)
    return names


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def resolve_base_ref(repo: Path, base_branch: str | None) -> str | None:
    """task の base_branch を worktree/serial の起点 commit-ish に解決する。
    未指定 → None(従来どおり HEAD 起点)。ローカルに在れば そのまま / origin にのみ在れば origin/<branch>。
    どこにも無ければ ValueError(死角を作らず run を fail させる)。"""
    b = (base_branch or "").strip()
    if not b:
        return None
    if git(repo, "rev-parse", "--verify", "--quiet", b).returncode == 0:
        return b
    remote = f"origin/{b}"
    if git(repo, "rev-parse", "--verify", "--quiet", remote).returncode == 0:
        return remote
    raise ValueError(f"base_branch '{b}' が repo に存在しません(ローカル / origin いずれにも無い)")


def add_worktree(repo: Path, run_id: str, base_ref: str | None = None) -> tuple[Path, str]:
    # 対象 repo に依らず loop repo 内の固定ディレクトリに置く(.gitignore 済み)。
    wt = WORKTREES_DIR / run_id
    branch = f"loop/{run_id}"
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    start = base_ref or "HEAD"  # base_branch 指定時はそこを起点に loop/<id> を切る
    with _wt_lock(repo):  # 同一 repo への並行 worktree add を直列化(共有 .git のメタ競合回避)
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(wt), start],
            check=True, capture_output=True, text=True,
        )
    return wt, branch


def remove_worktree(repo: Path, wt: Path) -> None:
    with _wt_lock(repo):  # add と同じ repo ロックで直列化
        git(repo, "worktree", "remove", "--force", str(wt))


# serial repo の「同時 1 本」を担保する実行ロック(run 全体を保持する。worktree 並列とは別系統)。
_SERIAL_LOCKS: dict[str, threading.Lock] = {}
_SERIAL_GUARD = threading.Lock()


def _serial_lock(repo: Path) -> threading.Lock:
    """serial repo の run を同時 1 本に直列化するロック(repo パス単位)。同一プロセス内で有効。"""
    key = str(repo.resolve())
    with _SERIAL_GUARD:
        return _SERIAL_LOCKS.setdefault(key, threading.Lock())


def enter_serial(repo: Path, run_id: str, base_ref: str | None = None) -> tuple[Path, str, str]:
    """serial repo: worktree を作らず repo 本体に loop/<id> ブランチを切って作業する。
    作業ツリーは触らずブランチポインタだけ付け替える(Unity の Library 等を再 import させない)。
    base_ref 指定時はそこを起点に切る(未指定は現在の HEAD 起点)。
    返り値 (workdir=repo, branch, orig_ref)。同時 1 本は呼び出し側の _serial_lock が担保する。"""
    branch = f"loop/{run_id}"
    orig_ref = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    git(repo, "checkout", "-B", branch, *( [base_ref] if base_ref else [] ))
    return repo, branch, orig_ref


def leave_serial(repo: Path, orig_ref: str, run_id: str) -> None:
    """serial run の後始末: 未コミット変更を loop/<id> に退避コミットしてから元ブランチへ戻す。
    worktree の remove --force に相当する「本体を汚さない」保証。成果/中途物は loop/<id> に残る(削除しない)。"""
    git(repo, "add", "-A")
    if git(repo, "diff", "--cached", "--quiet").returncode != 0:
        git(repo, "commit", "-q", "-m", f"loop run {run_id}(中断退避)")
    if orig_ref and orig_ref != "HEAD":  # detached HEAD は元コミット sha を持たないので戻さない
        git(repo, "checkout", orig_ref)


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


def _user_msg(text: str) -> str:
    """stream-json 入力の user メッセージ 1 行。これを stdin に流して 1 ターンを駆動する。"""
    return json.dumps({"type": "user", "message": {"role": "user",
                       "content": [{"type": "text", "text": text}]}}, ensure_ascii=False)


class RoleSession:
    """役割の **永続セッション**(`claude -p --input-format/--output-format stream-json`)。
    唯一の実行機構: one-shot も --resume 再 spawn も廃し、追加指示(revise / 人間介入)は
    すべて send() で同一セッションへ user メッセージとして注入する。
    run_turn() は次の result イベントまで読み、セッションは開いたまま(次の send を待てる)。"""

    def __init__(self, role: str, wt: Path, cfg: dict, run_dir: Path, model: str, tools: list[str],
                 read_only: bool = False, extra_args: list[str] | None = None,
                 resume_session: str | None = None):
        loop = cfg["loop"]
        cmd = [
            "claude", "-p",
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", model,
            "--max-turns", str(loop.get("max_turns", 40)),
            "--max-budget-usd", str(loop["max_budget_usd"]),
            "--permission-mode", loop.get("permission_mode", "default"),
            # 役 skill を Skill ツール経由で呼ぶため、Skill を常時付与(task.allowed_tools での絞り込みから外す)
            "--allowedTools", *tools, "Skill",
        ]
        # 役の振る舞いを skill として注入する。worktree の cwd は対象 repo の checkout で loop engine と別物
        # なので、engine 側の `.claude/plugins/loop-roles/` を --plugin-dir で明示ロードする(--bare 下でも skill は解決される)
        roles_plugin = ROOT / ".claude" / "plugins" / "loop-roles"
        if roles_plugin.exists():
            cmd += ["--plugin-dir", str(roles_plugin)]
        if resume_session:
            cmd += ["--resume", resume_session]
        if read_only:
            cmd += ["--disallowedTools", *WRITE_TOOLS]
        if extra_args:
            cmd += extra_args
        self.role, self.run_dir, self.timeout = role, run_dir, loop["timeout_seconds"]
        self._lines: list[str] = []
        self._sf = (run_dir / f"{role}.stream.jsonl").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=str(wt), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self._closed = False

    def send(self, text: str) -> None:
        """user メッセージを 1 件注入(初回プロンプト・revise 指摘・人間の続行指示すべて共通)。"""
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.write(_user_msg(text) + "\n")
            self.proc.stdin.flush()

    def run_turn(self) -> tuple[dict | None, str]:
        """次の result イベントまで stdout を読む(セッションは開いたまま)。(result, hint) を返す。"""
        killed = {"v": False}

        def _kill():
            killed["v"] = True
            try:
                self.proc.kill()
            except OSError:
                pass

        timer = threading.Timer(self.timeout, _kill)
        timer.start()
        result = None
        try:
            for line in self.proc.stdout:  # イベントが来るたび即ファイルへ(Web がライブ tail)
                self._sf.write(line)
                self._sf.flush()
                self._lines.append(line)
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(o, dict) and o.get("type") == "result":
                    result = o
                    break  # 1 ターン完了。stdin は開いたまま次の send を待てる
        finally:
            timer.cancel()
        if killed["v"]:
            return None, "timeout"
        if result is None:  # stdout が result 無しで尽きた(EOF/クラッシュ)
            (self.run_dir / f"{self.role}.result.raw.txt").write_text("".join(self._lines), encoding="utf-8")
            return None, "error"
        (self.run_dir / f"{self.role}.result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result, ("error" if result.get("is_error") else "ok")

    def close(self) -> None:
        """stdin を閉じてセッション終了(EOF)。stderr を保存。"""
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
        try:
            (self.run_dir / f"{self.role}.stderr.log").write_text(self.proc.stderr.read() or "", encoding="utf-8")
        except (OSError, ValueError):
            pass
        self._sf.close()


def run_role(role: str, prompt: str, wt: Path, cfg: dict, model: str,
             tools: list[str], run_dir: Path,
             extra_args: list[str] | None = None, read_only: bool = False,
             resume_session: str | None = None) -> tuple[dict | None, str]:
    """単発役(1 ターンで完結。Verifier / 単発用)の薄いラッパ。実体は RoleSession。
    1 メッセージ送って 1 ターン読み、stdin を閉じて終了する(= 旧 one-shot と同形だが stream-json IO)。"""
    sess = RoleSession(role, wt, cfg, run_dir, model, tools,
                       read_only=read_only, extra_args=extra_args, resume_session=resume_session)
    try:
        sess.send(prompt)
        return sess.run_turn()
    finally:
        sess.close()


def resolve_tools(value, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        value = [s.strip() for s in value.split(",") if s.strip()]
    return value or fallback


# --- Verifier(別モデル・read-only・構造化出力) ---

VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["pass", "fail", "revise", "handoff"]},
        "criteria": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "met": {"type": "boolean"},
            "evidence": {"type": "string"}}, "required": ["criterion", "met"]}},
        "test_gaming_suspected": {"type": "boolean"},
        "required_changes": {"type": "array", "items": {"type": "string"}},  # revise 時の修正指示
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
    return (v if v in ("pass", "fail", "revise", "handoff") else "handoff"), obj


def combine_verdict(test_verdict: str, verifier_verdict: str) -> str:
    if test_verdict == "fail":
        return "fail"
    if verifier_verdict in ("fail", "handoff"):
        return verifier_verdict
    return "pass"


def _inbox_human_input(run_dir: Path) -> str:
    """この run で人間が Web から送った続行指示/承認(inbox.jsonl)を Verifier へ渡す形に整形する。"""
    inbox = run_dir / "inbox.jsonl"
    if not inbox.exists():
        return ""
    msgs = []
    for line in inbox.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            t = (json.loads(line).get("text") or "").strip()
        except json.JSONDecodeError:
            continue
        if t:
            msgs.append(f"- {t}")
    return "\n".join(msgs)


def judge_with_verifier(task: dict, wt: Path, run_dir: Path, cfg: dict,
                        diff_text: str, test_output: str, brief: str = "") -> tuple[str, dict | None]:
    """Verifier(別モデル・read-only・構造化出力)で判定。handoff の間は冪等に再判定する。
    人間が介入した run では inbox の承認/指示を Verifier に渡す(実装者の自己申告ではなく人間の権威)。"""
    loop, agents = cfg["loop"], cfg["agents"]
    vmax = int(loop.get("verifier_attempts", 3))
    human_input = _inbox_human_input(run_dir)
    verdict, obj = "handoff", None
    for vatt in range(1, vmax + 1):
        print(f"  · Verifier {'判定中' if vatt == 1 else f'再判定 {vatt}/{vmax}'} …")
        v_result, v_hint = run_role(
            "verifier", render_verifier_prompt(task, diff_text, test_output, brief, human_input),
            wt, cfg, agents["verifier_model"], agents["verifier_tools"], run_dir,
            extra_args=["--json-schema", json.dumps(VERIFIER_SCHEMA, ensure_ascii=False)],
            read_only=True)
        verdict, obj = parse_verifier(v_result, v_hint, run_dir)
        if verdict != "handoff":
            break
    return verdict, obj


# --- タスク生成(自然言語 → 目標契約。専用 skill + 構造化出力) ---


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
        "plan": {"type": "string"},  # repo 調査に基づく詳細実装プラン(Explorer 統合。サイドカーに保存)
        "notes": {"type": "string"},
    },
    "required": ["id", "goal", "accept", "plan"],
}


def generate_task(prompt: str, cfg: dict, repo_path: Path | None = None) -> dict | None:
    """自然言語の依頼を専用 skill 付きで claude -p に渡し、目標契約を構造化出力で得る。
    ファイルへの書き込みは行わない(backend が write_task で決定論的に書く)。
    repo_path 指定時は、その repo 内を cwd にして read-only(Read/Grep/Glob)で実構成を調べさせ、
    その repo で実際に exit 0 になる verify を書かせる(repo を見ずに当て推量させない)。"""
    agents, loop = cfg["agents"], cfg["loop"]
    model = agents.get("author_model") or agents["implementer_model"]
    inspect = repo_path is not None and repo_path.is_dir()
    # 役定義は task-author skill(disable-model-invocation: true)に外出し済み。
    # runner は slash で明示呼び出しし、依頼と repo 文脈を $ARGUMENTS に詰める。
    parts = [f"## 依頼\n{prompt}"]
    if inspect:
        parts.insert(0, f"## 対象リポジトリ\nあなたは `{repo_path}` の中で read-only(Read/Grep/Glob)で実行されています。実構成を調べてから `verify`/`accept`/`plan` を書いてください。")
        # 憲法(最優先)+ 承認済み規範(手続き的記憶)+ 過去 run の事実(検証済みコマンド等)。優先順位は 憲法 > 規範 > 事実。
        brief = build_constitution_brief() + build_norms_brief(repo_path, cfg) + build_repo_brief(repo_path, int(loop.get("repo_history_runs", 8)))
        if brief.strip():
            parts.append(brief.lstrip("\n"))
    wrapped = "/loop-roles:task-author " + "\n\n".join(parts)
    cmd = [
        "claude", "-p", wrapped,
        "--output-format", "json",
        "--model", model,
        "--max-turns", "12" if inspect else "8",  # repo 調査ぶん少し増やす。設計のみで空回り防止に小さく
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--allowedTools", "Read", "Grep", "Glob",  # 生成は read-only 調査のみ
        "--disallowedTools", *WRITE_TOOLS,  # global settings の Write/Bash を上書きして read-only 強制
        "--json-schema", json.dumps(TASK_GEN_SCHEMA, ensure_ascii=False),
        "--plugin-dir", str(ROOT / ".claude" / "plugins" / "loop-roles"),
    ]
    cwd = str(repo_path) if inspect else str(ROOT)
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
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


def cmd_gen(prompt: str, auto_run: bool = False, repo: str | None = None,
           base_branch: str | None = None, no_pr: bool = False) -> int:
    """自然言語の依頼からタスクを生成して data/tasks/ に書き、必要なら実行(background 想定)。
    repo を明示指定したら(空/None 以外)モデル推定を上書きする('default' は repo 省略=デフォルト)。
    base_branch 指定時は起点ブランチとして契約に書く(空=現在の HEAD 起点)。
    no_pr=True は promote(PR 提出)を抑止するフラグを契約に書く(ローカル検証用)。"""
    cfg = load_config()
    DATA.mkdir(parents=True, exist_ok=True)
    # 生成中であることを Web が決定論的に検出するためのロック(完了で必ず外す)。
    gen_lock = DATA / ".gen.lock"
    gen_lock.write_text(prompt[:300], encoding="utf-8")
    tid = None
    try:
        print("▶ タスク生成中 …")
        # 選択 repo を実パスへ解決して author に read-only 調査させる(repo='default'/none/未指定は調査なし)。
        repo_path = None
        if repo and repo != "default":
            repo_path = resolve_repo({"repo": repo}, cfg)
        if repo_path is not None:
            print(f"  · repo を調査(read-only): {repo_path}")
        obj = generate_task(prompt, cfg, repo_path)
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
            # YAML が int を unquoted で書くと TaskFields(str) が pydantic v2 strict で 500 になる。
            # 境界で str 化して MD 上は常に quoted("1" 等)で書き出す。
            fm["max_attempts"] = str(ma)
        fm["status"] = "todo"
        if repo:  # 明示選択を優先(モデル推定を上書き)
            if repo == "default":
                fm.pop("repo", None)
            else:
                fm["repo"] = repo
        if (base_branch or "").strip():
            fm["base_branch"] = base_branch.strip()
        if no_pr:
            fm["no_pr"] = True
        p = write_task(tid, fm, str(obj.get("notes", "") or ""))
        paths = [p]
        plan = str(obj.get("plan", "") or "").strip()
        if plan:  # 詳細プランは body 外のサイドカーへ(契約を肥らせない / Web 編集と独立)
            paths.append(write_plan(tid, plan))
            print(f"  · 実装プランを生成: {plan_path(tid).relative_to(DATA)}")
        auto_commit(DATA, paths, f"todo: {tid} をプロンプトから生成")
        print(f"  · 生成: {tid}")
    finally:
        gen_lock.unlink(missing_ok=True)  # 生成中表示は必ず解除
    if auto_run and tid:
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

def _reindex_md(md: Path) -> None:
    """単一 run MD を SQLite へ再導出する(connect→upsert→close)。"""
    conn = loopdb.connect(DB)
    loopdb.upsert_md(conn, md)
    conn.close()


def build_repo_brief(repo: Path | None, limit: int = 8) -> str:
    """過去 run(同一 repo)の**客観的事実だけ**を集めた簡潔なブリーフ(種類A)。
    人間の判断(学び / review-notes / ## 判断)は含めない=メタループ用。
    内容: 過去に exit0 で通った検証コマンド / 過去の失敗の事実 / 直近 run の verdict 台帳。
    run を回すほど蓄積し、その repo に対する新インスタンスの習熟が上がる。"""
    if not repo or limit <= 0:
        return ""
    try:
        conn = loopdb.connect(DB)
        rows = conn.execute(
            "SELECT run_id, verdict FROM runs WHERE repo=? AND COALESCE(archived,0)=0 "
            "ORDER BY started_at DESC, run_id DESC LIMIT ?", (str(repo), limit)).fetchall()
        conn.close()
    except Exception:
        return ""
    verified: list[str] = []
    failures: list[tuple[str, str]] = []
    ledger: list[str] = []
    for r in rows:
        rid, verdict = r["run_id"], (r["verdict"] or "")
        ledger.append(f"- `{rid}`: {verdict}")
        tp = RUNS / rid / "test-output.txt"
        if not tp.exists():
            continue
        lines = tp.read_text(encoding="utf-8", errors="replace").splitlines()
        cmd = lines[0][2:].strip() if lines and lines[0].startswith("$ ") else ""
        if not cmd:
            continue
        exit0 = any(l.strip() == "[exit 0]" for l in lines[:3])
        if exit0:
            if cmd not in verified:
                verified.append(cmd)
        elif verdict == "fail":
            ess = [l.strip() for l in lines
                   if any(k in l.lower() for k in ("error", "assert", "fail", "exception"))][:2]
            failures.append((cmd, " / ".join(x[:120] for x in ess)))
    parts = []
    if verified:
        parts.append("## 過去に通った検証コマンド(再利用候補)\n" + "\n".join(f"- `{c}`" for c in verified[:5]))
    if failures:
        parts.append("## 過去の失敗(同じ轍を踏まない)\n" + "\n".join(f"- `{c}`: {e}" for c, e in failures[:4] if c))
    if ledger:
        parts.append("## 直近 run\n" + "\n".join(ledger))
    if not parts:
        return ""
    return ("\n\n# この repo の過去 run からの事実(参考。現状の repo を優先し鵜呑みにしない。人間の判断は含まない)\n"
            + "\n\n".join(parts))


# --- 規範記憶(手続き的記憶。事実ブリーフとは別系統。種類A の注入 + 起草 / 昇格は人間=種類B) ---
# 構造: data/repo/<name>/conventions.md(承認済み・注入される) + candidates.md(候補・注入されない控え室)。
# 真実は MD。loop.db の norm_candidates は派生(reindex で完全再生成)。

NORMS_ROOT = DATA / "repo"


def _safe_repo_name(raw: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (raw or "")).strip("-.")
    return s or "repo"


def repo_norm_name(repo: Path, cfg: dict) -> str:
    """規範を格納する repo 名。[repos] レジストリに同一パスがあればその登録名を、無ければ basename を使う
    (既存のタスク repo 解決と整合させ、規範を repo 単位で分離する)。"""
    target = repo.resolve()
    for name, path in (cfg.get("repos", {}) or {}).items():
        p = Path(str(path)).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        try:
            if p.resolve() == target:
                return _safe_repo_name(name)
        except OSError:
            continue
    return _safe_repo_name(repo.name)


def norms_paths(repo: Path, cfg: dict) -> tuple[Path, Path]:
    """(conventions.md, candidates.md) のパスを返す。"""
    d = NORMS_ROOT / repo_norm_name(repo, cfg)
    return d / "conventions.md", d / "candidates.md"


def build_constitution_brief() -> str:
    """人間が書く憲法(.claude/plugins/loop-roles/constitution.md)を最優先で注入する(種類A・自動)。
    役定義ツリー配下なので skill_sha に含まれ、どの憲法版で run したかが再現性ログに残る。
    最優先・エージェント不可侵。存在しなければ何も注入しない(常時オンで分岐を増やさない)。"""
    path = ROOT / ".claude" / "plugins" / "loop-roles" / "constitution.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return ""
    return ("\n\n# 憲法(最優先・不可侵)\n"
            "これは人間が定めた最上位の規範です。以下の設計規範・事実ブリーフや個別タスク指示と矛盾する場合も、"
            "この憲法を最優先で守ってください。\n\n" + text)


def build_norms_brief(repo: Path | None, cfg: dict) -> str:
    """承認済み規範(conventions.md)を注入する手続き的記憶(種類A)。
    人間が candidates.md から昇格させたものだけ。候補(candidates.md)は絶対に注入しない。
    優先順位は 憲法(constitution.md) > これ > 過去 run の事実ブリーフ。"""
    if repo is None:
        return ""
    conv, _ = norms_paths(repo, cfg)
    if not conv.exists():
        return ""
    text = conv.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return ""
    return ("\n\n# このリポジトリの設計規範(人間が承認済み)\n"
            "これは人間が承認した手続き的記憶です。上の『憲法』には劣後しますが、"
            "下の『過去 run からの事実』よりは優先してください。"
            "(優先順位: 憲法 > この規範 > 過去 run の事実)\n\n" + text)


# --- 規範候補(candidates.md)の読み書き。MD が真実、loop.db は派生 ---

def _norm_oneline(s: str) -> str:
    """候補フィールドを単一行に畳む(`- key: value` 形式を壊さない)。"""
    return " ".join(str(s or "").split()).strip()


def parse_candidates(path: Path) -> list[dict]:
    """candidates.md を候補ブロック(## candidate-...)の配列に分解する。"""
    if not path.exists():
        return []
    out: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## candidate-"):
            if cur is not None:
                out.append(cur)
            cur = {"candidate_id": line[3:].strip(), "evidence_runs": [], "status": "pending"}
        elif cur is not None and line.lstrip().startswith("- ") and ":" in line:
            k, v = line.lstrip()[2:].split(":", 1)
            k, v = k.strip(), v.strip()
            if k == "evidence_runs":
                cur[k] = [x.strip() for x in v.strip("[]").split(",") if x.strip()]
            elif k in ("observed_friction", "proposed_norm", "status", "drafted_at"):
                cur[k] = v
    if cur is not None:
        out.append(cur)
    return out


def _render_candidate(cid: str, observed: str, norm: str, evidence: list[str], drafted_at: str) -> str:
    ev = ", ".join(evidence)
    return (f"## {cid}\n"
            f"- observed_friction: {_norm_oneline(observed)}\n"
            f"- proposed_norm: {_norm_oneline(norm)}\n"
            f"- evidence_runs: [{ev}]\n"
            f"- status: pending\n"
            f"- drafted_at: {drafted_at}\n")


def set_candidate_status(path: Path, candidate_id: str, new_status: str) -> bool:
    """candidates.md の指定候補ブロックの status 行を書き換える。"""
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    in_block, changed = False, False
    for i, line in enumerate(lines):
        if line.startswith("## candidate-"):
            in_block = (line[3:].strip() == candidate_id)
        elif in_block and line.lstrip().startswith("- status:"):
            lines[i] = "- status: " + new_status
            changed = True
            in_block = False
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


# --- 規範候補の起草(種類A・自動。read-only・構造化出力。確定権は与えない) ---

NORMS_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {"type": "array", "items": {"type": "object", "properties": {
            "observed_friction": {"type": "string"},  # 観察された摩擦の事実
            "proposed_norm": {"type": "string"},       # 一般化された振る舞い規範(「〜する」)
        }, "required": ["observed_friction", "proposed_norm"]}},
        "none_reason": {"type": "string"},  # 候補なしのときの理由(可観測性)
    },
    "required": ["candidates"],
}


def _run_summary_for_norms(run_id: str, repo: Path) -> str:
    """起草エージェントへ渡す構造化サマリ(front-matter + diff + 差し戻し理由)。
    生 transcript も人間の review-notes も渡さない(poisoning と種類B 侵食を防ぐ)。"""
    md = RUNS / f"{run_id}.md"
    md_text = md.read_text(encoding="utf-8") if md.exists() else ""
    fm = loopdb.parse_front_matter(md_text) if md_text else {}
    keys = ("task", "verdict", "test_verdict", "verifier_verdict", "verifier_confidence")
    head = "\n".join(f"- {k}: {fm[k]}" for k in keys if fm.get(k))

    goal_block = ""
    if "## 目標契約" in md_text:
        goal = md_text.split("## 目標契約", 1)[1].split("##", 1)[0].strip()
        goal_block = f"\n\n# 目標契約\n{goal[:1500]}"

    verifier_block = ""
    vj = RUNS / run_id / "verifier.json"
    if vj.exists():
        try:
            obj = json.loads(vj.read_text(encoding="utf-8"))
            rc = [str(c) for c in (obj.get("required_changes") or [])]
            verifier_block = ("\n\n# Verifier の指摘(差し戻し/判定理由)\n"
                              f"- reasons: {_norm_oneline(obj.get('reasons', ''))[:800]}\n"
                              + ("- required_changes:\n" + "\n".join(f"  - {c}" for c in rc) if rc else ""))
        except json.JSONDecodeError:
            pass

    diff_block = ""
    patch = RUNS / run_id / "change.patch"
    if patch.exists():
        diff_block = ("\n\n# 実装の diff(抜粋)\n```diff\n"
                      + patch.read_text(encoding="utf-8", errors="replace")[:5000] + "\n```")

    return _read_template("norm-summary.md").format(
        run_id=run_id, head=head, goal_block=goal_block,
        verifier_block=verifier_block, diff_block=diff_block).rstrip() + "\n"


def draft_norm_candidates(run_id: str, repo: Path, cfg: dict, trigger: str) -> dict | None:
    """摩擦 run から規範候補を起草する(read-only・構造化出力)。ファイルは書かない。
    backend(maybe_draft_norms)が candidates.md へ決定論的に追記する(generate_task と同じ分業)。"""
    loop, agents = cfg["loop"], cfg["agents"]
    model = agents.get("author_model") or agents["implementer_model"]
    summary = _run_summary_for_norms(run_id, repo)
    # 役定義は norm-drafter skill(disable-model-invocation: true)に外出し済み。
    # runner は slash で明示呼び出しし、トリガー / 摩擦サマリを $ARGUMENTS に詰める。
    prompt = f"/loop-roles:norm-drafter ## トリガー\n{trigger}\n\n{summary}"
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--max-turns", "8",
        "--max-budget-usd", str(loop["max_budget_usd"]),
        "--permission-mode", loop.get("permission_mode", "default"),
        "--allowedTools", "Read", "Grep", "Glob",
        "--disallowedTools", *WRITE_TOOLS,  # global settings を上書きして read-only 強制(起草のみ)
        "--json-schema", json.dumps(NORMS_DRAFT_SCHEMA, ensure_ascii=False),
        "--plugin-dir", str(ROOT / ".claude" / "plugins" / "loop-roles"),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True,
                              timeout=loop["timeout_seconds"])
        result = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None
    obj = result.get("structured_output")
    return obj if isinstance(obj, dict) else None


def maybe_draft_norms(run_id: str, repo: Path | None, cfg: dict, trigger: str) -> None:
    """摩擦 run の規範候補を起草し candidates.md へ追記する(種類A)。conventions.md には絶対に書かない。
    空振り・失敗は黙って握り潰さず run のログ(norms.json)と stdout に残す(可観測性)。"""
    if repo is None or not repo.is_dir():  # repo が無い/stale(別マシンの run 等)なら起草しない
        return
    run_dir = RUNS / run_id
    log = run_dir / "norms.json"
    obj = draft_norm_candidates(run_id, repo, cfg, trigger)
    if not isinstance(obj, dict):
        try:
            log.write_text(json.dumps({"trigger": trigger, "error": "起草に失敗(出力不正/timeout)"},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        print("  · 規範候補: 起草に失敗(出力不正)→ candidates.md は変更なし")
        return
    cands = [c for c in (obj.get("candidates") or []) if isinstance(c, dict) and c.get("proposed_norm")]
    try:
        log.write_text(json.dumps({"trigger": trigger, **obj}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    if not cands:
        reason = _norm_oneline(obj.get("none_reason", "")) or "一般化できる規範なし"
        print(f"  · 規範候補: 抽出できず({reason})")
        return
    _, cpath = norms_paths(repo, cfg)
    drafted_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with _DATA_COMMIT_LOCK:  # 並行 run の candidates.md 追記・loop.db 書込みを直列化
        cpath.parent.mkdir(parents=True, exist_ok=True)
        existing = len([c for c in parse_candidates(cpath) if c["candidate_id"].startswith(f"candidate-{run_id}-")])
        conn = loopdb.connect(DB)
        rname = repo_norm_name(repo, cfg)
        blocks = []
        for i, c in enumerate(cands, start=existing + 1):
            cid = f"candidate-{run_id}-{i}"
            blocks.append(_render_candidate(cid, c.get("observed_friction", ""), c["proposed_norm"], [run_id], drafted_at))
            loopdb.upsert_norm_candidate(conn, {
                "candidate_id": cid, "repo": rname, "run_id": run_id, "status": "pending",
                "observed_friction": _norm_oneline(c.get("observed_friction", "")),
                "proposed_norm": _norm_oneline(c["proposed_norm"]), "drafted_at": drafted_at,
            })
        conn.close()
        with cpath.open("a", encoding="utf-8") as f:
            if cpath.stat().st_size == 0:
                f.write(f"# {rname} の規範候補(昇格待ちの控え室。run には注入されない)\n\n")
            f.write("\n".join(blocks))
        auto_commit(DATA, [cpath], f"norms: {run_id} から規範候補 {len(cands)} 件を起草(pending)")
    print(f"  · 規範候補: {len(cands)} 件を candidates.md に起草(pending / 昇格は人間)")


def reindex_norms() -> int:
    """全 repo の candidates.md を走査して loop.db の norm_candidates を再生成する(派生・非 authoritative)。"""
    conn = loopdb.connect(DB)
    loopdb.clear_norm_candidates(conn)
    n = 0
    if NORMS_ROOT.exists():
        for cpath in sorted(NORMS_ROOT.glob("*/candidates.md")):
            rname = cpath.parent.name
            for c in parse_candidates(cpath):
                m = re.match(r"candidate-(.+)-\d+$", c["candidate_id"])
                loopdb.upsert_norm_candidate(conn, {
                    "candidate_id": c["candidate_id"], "repo": rname,
                    "run_id": m.group(1) if m else None, "status": c.get("status", "pending"),
                    "observed_friction": c.get("observed_friction", ""),
                    "proposed_norm": c.get("proposed_norm", ""), "drafted_at": c.get("drafted_at"),
                })
                n += 1
    conn.close()
    return n


def _finalize_run(task: dict, run_id: str, run_dir: Path, md: Path, final: str, commit_msg: str) -> None:
    """run 確定の後処理(§4.3): task status 書換 / loop.db upsert / data commit を 1 ブロックで直列化。
    N 本が同時にここへ来ても data/ の index.lock 競合や loop.db 書込み競合を避ける。"""
    with _DATA_COMMIT_LOCK:
        update_status(task["id"], final)
        _reindex_md(md)
        auto_commit(DATA, [md, run_dir, task.get("_path")], commit_msg)


def _compute_skill_sha(repo: Path | None) -> str:
    """run の再現性キー。engine 側 `loop-roles` プラグイン(役定義の本体)を主として、
    target repo の `.claude/skills/`(あればプロジェクト固有の知識)を併記する。
    どちらも無ければ空。両方あるときは合成 hash(SQL group-by 用の単一キー)。"""
    parts: list[str] = []
    p = git(ROOT, "rev-parse", "HEAD:.claude/plugins/loop-roles")
    if p.returncode == 0 and p.stdout.strip():
        parts.append(p.stdout.strip())
    if repo:
        t = git(repo, "rev-parse", "HEAD:.claude/skills")
        if t.returncode == 0 and t.stdout.strip():
            parts.append(t.stdout.strip())
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def write_run_md(task: dict, run_id: str, verdict: str, result: dict | None,
                 cfg: dict, started_at: str, verify_code: int | None,
                 test_verdict: str = "none", verifier_verdict: str = "handoff",
                 verifier_obj: dict | None = None, roles: dict | None = None,
                 repo: Path | None = None, pr_url: str | None = None) -> Path:
    repo_sha = git(repo, "rev-parse", "HEAD").stdout.strip() if repo else ""
    skill_sha = _compute_skill_sha(repo)
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
        "pr_url": pr_url or None,
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
    for r, label in (("implementer", "Implementer"), ("verifier", "Verifier")):
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

{JUDGMENT_HEADING} ← 人間がここだけ書く（種類B / 自動化しない・自由記述）
"""
    out = RUNS / f"{run_id}.md"
    out.write_text(body, encoding="utf-8")
    return out


# --- review(種類B。判断そのものは人間が Web 判断フォームで書く) ---

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


def _set_fm_key(path: Path, key: str, value: str) -> None:
    """front-matter の key 行を value に書き換える(無ければ追加)。"""
    lines, s, e = _split_front_matter(path.read_text(encoding="utf-8"))
    if e == 0:
        return
    for k in range(s, e):
        if lines[k].split(":", 1)[0].strip() == key:
            lines[k] = f"{key}: {value}"
            break
    else:
        lines.insert(e, f"{key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _clear_fm_key(path: Path, key: str) -> None:
    """front-matter から key 行を削除する(無ければ何もしない)。"""
    lines, s, e = _split_front_matter(path.read_text(encoding="utf-8"))
    if e == 0:
        return
    kept = [l for i, l in enumerate(lines) if not (s <= i < e and l.split(":", 1)[0].strip() == key)]
    if len(kept) != len(lines):
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def set_task_archived(task_id: str, archived: bool) -> bool:
    """タスクをアーカイブ/解除(削除しない=ログは資産)。front-matter の archived を立てる。"""
    t = next((x for x in parse_tasks() if x.get("id") == task_id), None)
    if not t:
        return False
    _set_fm_key(t["_path"], "archived", "true" if archived else "false")
    verb = "アーカイブ" if archived else "アーカイブ解除"
    auto_commit(DATA, [t["_path"]], f"todo: {task_id} を{verb}")
    return True


def set_run_archived(run_id: str, archived: bool) -> bool:
    """run をアーカイブ/解除(削除しない)。run MD の archived を立て SQLite を再導出。"""
    md = RUNS / f"{run_id}.md"
    if not md.exists():
        return False
    _set_fm_key(md, "archived", "true" if archived else "false")
    _reindex_md(md)
    verb = "アーカイブ" if archived else "アーカイブ解除"
    auto_commit(DATA, [md], f"run: {run_id} を{verb}")
    return True


def _repo_from_run_md(md: Path) -> Path | None:
    """run MD の front-matter の repo(絶対パス文字列)を Path に戻す('none' は None)。"""
    fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8")) if md.exists() else {}
    r = str(fm.get("repo", "") or "").strip()
    if not r or r.lower() == "none":
        return None
    return Path(r)


def maybe_draft_on_review(run_id: str, cfg: dict) -> None:
    """トリガー3(人間レビューで verdict が覆った): run MD front-matter の human_verdict が
    runner の verdict と食い違うとき、規範候補を起草する(種類A の起草 / 覆し判断は人間=種類B)。
    human_verdict は人間が Web 判断フォームで任意に選ぶ構造化シグナル(無ければ何もしない)。"""
    md = RUNS / f"{run_id}.md"
    if not md.exists():
        return
    fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8"))
    human = str(fm.get("human_verdict", "") or "").strip()
    if not human or human == str(fm.get("verdict", "") or "").strip():
        return
    repo = _repo_from_run_md(md)
    try:
        maybe_draft_norms(run_id, repo, cfg,
                          f"人間レビューで verdict が覆った(runner={fm.get('verdict')} → human={human})")
    except Exception as ex:
        print(f"  · 規範候補: 起草中に例外(無視) {ex!r}")


# --- 判断の読み書き(GUI フォーム ↔ 契約ファイル。中身は人間が書く) ---

# 判断は単一の自由記述欄(notes)。GUI は判断を生成しないので、入力面は最小限の1欄に保つ。
JUDGMENT_FIELDS = [("notes", "判断(自由記述)")]


def parse_judgment(md: Path) -> dict:
    """MD の判断セクション(## 判断 以降の自由記述)を notes として読む(prefill 用)。
    複数行・複数段落をそのまま保持する。"""
    values = {"notes": ""}
    text = md.read_text(encoding="utf-8")
    if JUDGMENT_HEADING not in text:
        return values
    section = text.split(JUDGMENT_HEADING, 1)[1]
    # 1 行目は見出しの残り(「← 人間が…」)なので落とし、以降を自由記述本文とする。
    values["notes"] = "\n".join(section.splitlines()[1:]).strip()
    return values


def write_judgment(run_id: str, fields: dict, cfg: dict) -> None:
    """種類A: GUI から来た判断を契約ファイルへ書き戻す。中身(notes)は人間が書いた自由記述。
    判断セクション置換 → review-notes.md 追記 → reviewed 化 → SQLite 再導出 → コミット。
    複数行の散文を圧縮せずそのまま保持する。"""
    md = RUNS / f"{run_id}.md"
    lines = md.read_text(encoding="utf-8").splitlines()
    head = next((i for i, l in enumerate(lines) if l.startswith(JUDGMENT_HEADING)), len(lines))

    notes = (fields.get("notes") or "").strip()
    section = [f"{JUDGMENT_HEADING} ← 人間がここだけ書く（種類B / 自動化しない・自由記述）", ""]
    if notes:
        section += [notes, ""]
    md.write_text("\n".join(lines[:head] + section).rstrip() + "\n", encoding="utf-8")

    # human_verdict: 人間が verdict を覆すときだけ front-matter に刻む構造化シグナル(空=覆さない)。
    # 不正値は無視(GUI の select が pass/fail/revise/handoff のみ送る)。覆しは maybe_draft_on_review が拾う。
    hv = (fields.get("human_verdict") or "").strip()
    if hv in ("pass", "fail", "revise", "handoff"):
        _set_fm_key(md, "human_verdict", hv)
    else:
        _clear_fm_key(md, "human_verdict")

    if notes:  # 種類B の R&D ログとして review-notes.md に全文を蓄積する。
        day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        nl = notes.splitlines()
        entry = f"- {day} {run_id}: {nl[0]}\n" + "".join(f"  {x}\n" for x in nl[1:])
        with REVIEW_NOTES.open("a", encoding="utf-8") as f:
            f.write(entry)

    set_md_reviewed(md)
    _reindex_md(md)
    auto_commit(DATA, [md, REVIEW_NOTES], f"review: {run_id} 判断を記入し reviewed 化")
    maybe_draft_on_review(run_id, cfg)


# --- PR promotion(run=pass 後: PR 作成 → CI/Copilot が green になるまで Implementer 差し戻し) ---
# merge は人間(種類B)。loop は green & Copilot-clean まで持っていって handoff で止める。

COPILOT_BOT = "copilot-pull-request-reviewer[bot]"


def _gh(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def _gh_json(args: list[str], cwd: Path, default):
    p = _gh(args, cwd)
    try:
        return json.loads(p.stdout) if p.stdout.strip() else default
    except json.JSONDecodeError:
        return default


def _repo_slug(repo: Path) -> str:
    return _gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], repo).stdout.strip()


def _default_branch(repo: Path) -> str:
    return _gh(["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"], repo).stdout.strip() or "main"


def open_pr(repo: Path, branch: str, title: str, body: str, base: str | None = None) -> tuple[int | None, str]:
    """branch を push して PR を作る。既存 PR があればそれを返す。base 未指定はデフォルトブランチ。"""
    git(repo, "push", "-u", "origin", branch)
    base = (base or "").strip() or _default_branch(repo)
    p = _gh(["pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body], repo)
    if p.returncode == 0:
        url = p.stdout.strip().splitlines()[-1]
        num = url.rstrip("/").split("/")[-1]
        return (int(num) if num.isdigit() else None), url
    o = _gh_json(["pr", "view", branch, "--json", "number,url"], repo, {})  # 既存 PR
    return o.get("number"), o.get("url", "")


def request_copilot(repo: Path, slug: str, pr: int) -> None:
    _gh(["api", "-X", "POST", f"repos/{slug}/pulls/{pr}/requested_reviewers",
         "-f", f"reviewers[]={COPILOT_BOT}"], repo)


def wait_ci(repo: Path, pr: int, timeout: int) -> None:
    """CI チェックの pending が無くなるまで待つ(タイムアウトで打ち切り)。"""
    deadline = time.monotonic() + timeout
    grace = time.monotonic() + 30  # チェック未生成の初動猶予
    while True:
        checks = _gh_json(["pr", "checks", str(pr), "--json", "name,bucket"], repo, [])
        if checks and not any(c.get("bucket") == "pending" for c in checks):
            return
        if not checks and time.monotonic() > grace:
            return  # CI 無し
        if time.monotonic() > deadline:
            return
        time.sleep(10)


def collect_ci_failures(repo: Path, pr: int) -> list[dict]:
    fails = []
    for c in _gh_json(["pr", "checks", str(pr), "--json", "name,bucket,link"], repo, []):
        if c.get("bucket") != "fail":
            continue
        m = re.search(r"runs/(\d+)", c.get("link", ""))
        log = ""
        if m:
            lp = _gh(["run", "view", m.group(1), "--log-failed"], repo, timeout=120)
            log = "\n".join(lp.stdout.splitlines()[-40:])
        fails.append({"name": c.get("name"), "log": log})
    return fails


def wait_copilot(repo: Path, slug: str, pr: int, timeout: int) -> bool:
    """Copilot のレビュー投稿(state≠PENDING)が出るまで待つ。"""
    deadline = time.monotonic() + timeout
    while True:
        states = _gh_json(["api", f"repos/{slug}/pulls/{pr}/reviews",
                           "--jq", f'[.[]|select(.user.login=="{COPILOT_BOT}")|.state]'], repo, [])
        if any(s != "PENDING" for s in states):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(10)


def collect_review_threads(repo: Path, slug: str, pr: int) -> list[dict]:
    """Copilot の未解決 reviewThread を集める(pr-review-fix と同じ isResolved=false 基準)。"""
    owner, name = slug.split("/", 1)
    q = ('{repository(owner:"%s",name:"%s"){pullRequest(number:%d){reviewThreads(first:100){'
         'nodes{id isResolved path line comments(first:1){nodes{author{login} body}}}}}}}') % (owner, name, pr)
    data = _gh_json(["api", "graphql", "-f", f"query={q}"], repo, {})
    nodes = (((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get("reviewThreads", {}).get("nodes", [])
    out = []
    for n in nodes:
        if n.get("isResolved"):
            continue
        cs = (n.get("comments") or {}).get("nodes") or []
        c = cs[0] if cs else {}
        author = ((c.get("author") or {}).get("login") or "")
        if "copilot" not in author.lower():
            continue
        out.append({"id": n.get("id"), "path": n.get("path"), "line": n.get("line"), "body": c.get("body", "")})
    return out


def resolve_thread(repo: Path, thread_id: str) -> None:
    q = 'mutation{resolveReviewThread(input:{threadId:"%s"}){thread{isResolved}}}' % thread_id
    _gh(["api", "graphql", "-f", f"query={q}"], repo)


def render_promote_fix_prompt(ci_fails: list[dict], threads: list[dict]) -> str:
    parts = ["提出した PR の CI または Copilot レビューで問題が見つかりました。あなたはこの worktree で実装を続けています。"
             "下記をすべて解消し、再度テストを通してから完了してください。"]
    if ci_fails:
        parts.append("\n# CI 失敗")
        for f in ci_fails:
            parts.append(f"## {f['name']}\n```\n{f['log'][:1500]}\n```")
    if threads:
        parts.append("\n# Copilot レビュー指摘(未解決)")
        for t in threads:
            parts.append(f"- `{t['path']}:{t.get('line')}`: {t['body'][:500]}")
    return "\n".join(parts)


def promote_run(task: dict, run_id: str, run_dir: Path, repo: Path, wt: Path,
                branch: str, cfg: dict, session_id: str | None) -> dict:
    """run=pass の成果を PR 化し、CI + Copilot が green になるまで Implementer を --resume で回す。
    merge はしない(green & clean → 人間が merge)。"""
    loop, agents = cfg["loop"], cfg["agents"]
    i_tools = resolve_tools(task.get("allowed_tools"), agents["implementer_tools"])
    slug = _repo_slug(repo)
    title = f"{task['id']}: {str(task.get('goal', '')).strip().splitlines()[0][:60]}"
    body = f"loop run `{run_id}` の成果(Verifier 監査 pass)。\n\n🤖 loop により自動生成。**merge は人間が判断**。"
    pr, url = open_pr(repo, branch, title, body, base=(task.get("base_branch") or "").strip() or None)
    if not pr:
        return {"state": "error", "detail": "PR 作成に失敗"}
    request_copilot(repo, slug, pr)

    rounds = int(loop.get("promote_rounds", 3))
    ci_to = int(loop.get("ci_timeout_seconds", 1800))
    cop_to = int(loop.get("copilot_timeout_seconds", 600))
    ci_fails: list[dict] = []
    threads: list[dict] = []
    state, rnd = "green", 0
    for rnd in range(rounds + 1):
        wait_ci(repo, pr, ci_to)
        wait_copilot(repo, slug, pr, cop_to)
        ci_fails = collect_ci_failures(repo, pr)
        threads = collect_review_threads(repo, slug, pr)
        (run_dir / f"promote.round{rnd + 1}.json").write_text(
            json.dumps({"ci_fail": [f["name"] for f in ci_fails], "threads": threads},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    · promote round {rnd + 1}: CI fail={len(ci_fails)} / Copilot 未解決={len(threads)}")
        if not ci_fails and not threads:
            state = "green"
            break
        if rnd >= rounds:
            state = "exhausted"
            break
        run_role("implementer", render_promote_fix_prompt(ci_fails, threads), wt, cfg,
                 agents["implementer_model"], i_tools, run_dir, resume_session=session_id)
        git(wt, "add", "-A")  # commit_worktree はステージ済み前提
        if not commit_worktree(wt, f"loop promote {run_id} round {rnd + 1}"):
            print("    · promote: 修正による変更なし → 打ち切り(handoff)")
            state = "no-change"
            break
        git(repo, "push", "origin", branch)
        for t in threads:  # 対応したスレッドを resolve(再レビューで再提起され得る)
            if t.get("id"):
                resolve_thread(repo, t["id"])
        request_copilot(repo, slug, pr)
    return {"state": state, "pr_url": url, "pr_number": pr, "rounds": rnd + 1,
            "ci_fail": [f["name"] for f in ci_fails], "copilot_unresolved": len(threads)}


def _pr_ci_state(rollup: list) -> str:
    if not rollup:
        return "none"
    if any(c.get("status") != "COMPLETED" for c in rollup):
        return "pending"
    if any(c.get("conclusion") not in ("SUCCESS", "NEUTRAL", "SKIPPED", None) for c in rollup):
        return "fail"
    return "pass"


def check_pr_merge(run_id: str, cfg: dict) -> dict:
    """awaiting-merge の run の PR 状態を gh で確認。**マージ済みなら verdict を pass へ昇格(真の完了)**。
    返り値: {number, url, state(OPEN/MERGED/CLOSED), merged, ci}。PR が無ければ {}。"""
    md = RUNS / f"{run_id}.md"
    if not md.exists():
        return {}
    fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8"))
    pr_url = str(fm.get("pr_url") or "").strip()
    if not pr_url:
        return {}
    m = re.search(r"/pull/(\d+)", pr_url)
    repo = _repo_from_run_md(md)
    if not m or repo is None or not repo.is_dir():
        return {"url": pr_url}
    pr = int(m.group(1))
    o = _gh_json(["pr", "view", str(pr), "--json", "state,url,mergedAt,statusCheckRollup"], repo, {})
    state = o.get("state", "")
    merged = state == "MERGED" or bool(o.get("mergedAt"))
    if merged and str(fm.get("verdict")) == "awaiting-merge":
        with _DATA_COMMIT_LOCK:  # PR マージ = 真の完了 → pass へ昇格(種類A)
            _set_fm_key(md, "verdict", "pass")
            _reindex_md(md)
            auto_commit(DATA, [md], f"merge: {run_id} の PR #{pr} がマージ済み → pass 確定")
        print(f"  · {run_id}: PR #{pr} マージ済み → verdict=pass(真の完了)")
    return {"number": pr, "url": o.get("url") or pr_url, "state": state,
            "merged": merged, "ci": _pr_ci_state(o.get("statusCheckRollup") or [])}


def cmd_merges() -> int:
    """awaiting-merge の全 run の PR を確認し、マージ済みを pass へ昇格させる sweep(headless 用)。"""
    cfg = load_config()
    conn = loopdb.connect(DB)
    rows = conn.execute(
        "SELECT run_id FROM runs WHERE verdict='awaiting-merge' AND COALESCE(archived,0)=0").fetchall()
    conn.close()
    if not rows:
        print("awaiting-merge(PR マージ待ち)の run はありません。")
        return 0
    for r in rows:
        st = check_pr_merge(r["run_id"], cfg)
        print(f"  · {r['run_id']}: PR {st.get('state', '?')} / merged={st.get('merged')} / ci={st.get('ci')}")
    return 0


# --- 人間介入(awaiting): 止まった run へ Web から続行指示を渡す ---

STOP_SIGNAL = "__STOP__"  # await_human がこの文字列を返したら人間が UI から停止を要求


def _stop_requested(run_dir: Path) -> bool:
    """Web の停止ボタンが置く stop マーカーの有無。検知したら run は `stopped` で正常終了する。"""
    return (run_dir / "stop").exists()


def await_human(run_id: str, run_dir: Path, question: str, cfg: dict, seen: int) -> tuple[str | None, int]:
    """run を awaiting にし、人間の続行指示を inbox.jsonl から待つ(Web が POST で 1 行追記する)。
    seen = 既に消費した inbox 行数。新しい行が来たらその text を返す。
    停止要求 → (STOP_SIGNAL, seen)。intervention_timeout_seconds で打ち切り → (None, seen)(handoff へ)。"""
    timeout = int(cfg["loop"].get("intervention_timeout_seconds", 1800))
    inbox = run_dir / "inbox.jsonl"
    (run_dir / "intervention.json").write_text(
        json.dumps({"question": question}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_run_status(run_id=run_id, phase="awaiting")
    print(f"  · awaiting: 人間の続行指示を待機(最大 {timeout}s)。Web の run 詳細から送信してください。")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _stop_requested(run_dir):
            (run_dir / "intervention.json").unlink(missing_ok=True)
            return STOP_SIGNAL, seen
        if inbox.exists():
            rows = [l for l in inbox.read_text(encoding="utf-8").splitlines() if l.strip()]
            if len(rows) > seen:
                try:
                    text = (json.loads(rows[seen]).get("text") or "").strip()
                except json.JSONDecodeError:
                    text = ""
                (run_dir / "intervention.json").unlink(missing_ok=True)
                return (text or None), seen + 1
        time.sleep(2)
    (run_dir / "intervention.json").unlink(missing_ok=True)
    return None, seen


def _drive_implementer(impl: "RoleSession", run_id: str, run_dir: Path, cfg: dict,
                       inbox_seen: int) -> tuple[dict | None, str, int]:
    """直前に送ったメッセージに対する Implementer のターンを回す。
    **実装中**に NEEDS_HUMAN(方針疑問/権限不足)が出たら await_human で解決し同一セッションで続行。
    通常完了したターンの (i_result, hint, inbox_seen) を返す。hint=ok/timeout/error/handoff/stopped。"""
    while True:
        i_result, i_hint = impl.run_turn()
        copy_transcript(i_result, run_dir)
        if i_hint in ("timeout", "error"):
            return i_result, i_hint, inbox_seen
        if _stop_requested(run_dir):  # ターン境界での停止検知(実行中 run の停止)
            return i_result, "stopped", inbox_seen
        question = _needs_human(i_result)
        if not question:
            return i_result, "ok", inbox_seen  # 通常完了 → 呼び出し側でゲート + Verifier へ
        print("  · Implementer が NEEDS_HUMAN(実装中の判断/権限)→ 人間待ち")
        human, inbox_seen = await_human(run_id, run_dir, question, cfg, inbox_seen)
        if human == STOP_SIGNAL:
            return i_result, "stopped", inbox_seen
        if human is None:
            return i_result, "handoff", inbox_seen  # 人間来ず → handoff
        print("  · 人間の回答を受領 → Implementer 続行 …")
        write_run_status(run_id=run_id, phase="implementer")
        impl.send(human)


# --- コマンド ---

def _run_attempt(task: dict, run_id: str, cfg: dict, started_at: str) -> tuple[str, bool]:
    """1 試行(Author プラン → Implementer → 決定論ゲート → Verifier → revise ループ)。
    (final, retryable) を返す。retryable=True は「実装が timeout/error で確定しなかった」= run 全体を再試行する価値がある状態。
    Verifier の handoff は read-only のまま再判定(冪等)。revise は Implementer を --resume で差し戻し(有界)。"""
    loop, agents = cfg["loop"], cfg["agents"]
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    repo = resolve_repo(task, cfg)
    if not is_git_repo(repo):
        (run_dir / "test-output.txt").write_text(f"NG: repo が git リポジトリではありません: {repo}\n", encoding="utf-8")
        write_run_status(run_id=run_id, task=task["id"], repo=str(repo),
                         started_at=started_at, phase="verifier", verdict=None)
        md = write_run_md(task, run_id, "fail", None, cfg, started_at, None,
                          "none", "handoff", None, {}, repo=repo)
        _finalize_run(task, run_id, run_dir, md, "fail", f"run: {run_id} → fail(repo 不正)")
        clear_run_status(run_id, "fail")
        print(f"  · repo が不正: {repo} → fail")
        return "fail", False

    # base_branch 指定があれば worktree/serial の起点をそこへ(未指定は従来どおり HEAD)。無効 ref は run を fail。
    try:
        base_ref = resolve_base_ref(repo, task.get("base_branch"))
    except ValueError as ex:
        (run_dir / "test-output.txt").write_text(f"NG: {ex}\n", encoding="utf-8")
        write_run_status(run_id=run_id, task=task["id"], repo=str(repo),
                         started_at=started_at, phase="verifier", verdict=None)
        md = write_run_md(task, run_id, "fail", None, cfg, started_at, None,
                          "none", "handoff", None, {}, repo=repo)
        _finalize_run(task, run_id, run_dir, md, "fail", f"run: {run_id} → fail(base_branch 不正)")
        clear_run_status(run_id, "fail")
        print(f"  · {ex} → fail")
        return "fail", False

    # serial repo は worktree を作らず本体で 1 本ずつ作業する(Unity 等の worktree 不向き repo)。
    # 同一 serial repo の同時実行はロックで直列化(他 repo / parallel worktree は並行のまま)。
    serial = repo_mode(repo, cfg) == "serial"
    lock = _serial_lock(repo) if serial else None
    if lock:
        lock.acquire()
    try:
        if serial:
            wt, branch, orig_ref = enter_serial(repo, run_id, base_ref)
        else:
            wt, branch, orig_ref = (*add_worktree(repo, run_id, base_ref), None)
    except BaseException:
        if lock:
            lock.release()
        raise
    repo_label = str(repo)
    try:
        i_tools = resolve_tools(task.get("allowed_tools"), agents["implementer_tools"])
        verifier_obj = None
        retryable = False
        stopped = False  # 人間が UI から停止を要求したか(→ verdict=stopped で正常終了)
        revise_occurred = False  # 摩擦トリガー: revise 差し戻しが起きたか(規範候補の起草条件)
        test_verdict, verifier_verdict, vcode = "none", "handoff", None
        final = "fail"

        # 1) 事前情報: Author 生成の実装プラン(生成時に repo を read-only 調査済み)+ 規範(承認済み)+ 過去 run の事実。
        impl_context = read_plan(task.get("id", ""))
        # 注入順 = 優先順位: 憲法(constitution.md・最優先)→ 承認済み規範(手続き的記憶)→ 過去 run の事実。
        brief = build_constitution_brief() + build_norms_brief(repo, cfg) + build_repo_brief(repo, int(loop.get("repo_history_runs", 8)))

        # 2) Implementer = 永続セッション。**実装中**の判断/権限不足は NEEDS_HUMAN で人間へ(_drive_implementer)。
        #    **実装後**の欠陥は Verifier の責務(revise で自動修正)。handoff→人間は最後の安全網。
        write_run_status(run_id=run_id, task=task["id"], repo=repo_label,
                         started_at=started_at, phase="implementer")
        print("  · Implementer 実装中 …")
        impl = RoleSession("implementer", wt, cfg, run_dir, agents["implementer_model"], i_tools)
        i_result, inbox_seen = None, 0
        try:
            impl.send(render_implementer_prompt(task, impl_context, "Author の実装プラン(repo 調査済み)", brief))
            i_result, i_hint, inbox_seen = _drive_implementer(impl, run_id, run_dir, cfg, inbox_seen)
            if i_hint == "timeout":
                final, retryable = "timeout", True
            elif i_hint == "error":
                final, retryable = "fail", True
            elif i_hint == "handoff":  # 実装中の問いに人間が応答せず確定不能
                final, verifier_verdict = "handoff", "handoff"
            elif i_hint == "stopped":  # 人間が UI から停止
                final, stopped = "stopped", True
            else:
                # 3-5) 実装完了 → 決定論ゲート → Verifier 監査 →(欠陥なら revise を自動注入)を有界ループ。
                revise_max = int(loop.get("implementer_revise_rounds", 2))
                rounds = 0
                while True:
                    capture_diff(wt, run_dir)
                    write_run_status(run_id=run_id, phase="verifier")
                    test_verdict, vcode = run_verify(task, wt, run_dir)   # "pass"/"fail"/"none"(床)
                    diff_text = (run_dir / "change.patch").read_text(encoding="utf-8", errors="replace")
                    tp = run_dir / "test-output.txt"
                    test_output = tp.read_text(encoding="utf-8", errors="replace") if tp.exists() else "(なし)"
                    verifier_verdict, verifier_obj = judge_with_verifier(task, wt, run_dir, cfg, diff_text, test_output, brief)
                    if verifier_obj is not None:  # 各ラウンドの判断を証拠として残す(最終 verifier.json とは別)
                        (run_dir / f"verifier.round{rounds + 1}.json").write_text(
                            json.dumps(verifier_obj, ensure_ascii=False, indent=2), encoding="utf-8")
                    if verifier_verdict in ("pass", "fail"):
                        break
                    # 実装後の欠陥(revise・回数内): Verifier の指摘を自動で差し戻す(人間不要)
                    if verifier_verdict == "revise" and rounds < revise_max:
                        rounds += 1
                        revise_occurred = True
                        print(f"  · Verifier が差し戻し(revise {rounds}/{revise_max})→ Implementer 再実装 …")
                        write_run_status(run_id=run_id, phase="implementer")
                        impl.send(render_revise_prompt(task, verifier_obj))
                        i_result, i_hint, inbox_seen = _drive_implementer(impl, run_id, run_dir, cfg, inbox_seen)
                        if i_hint in ("timeout", "error"):
                            final, retryable = ("timeout" if i_hint == "timeout" else "fail"), True
                            break
                        if i_hint == "handoff":
                            verifier_verdict = "handoff"
                            break
                        if i_hint == "stopped":
                            final, stopped = "stopped", True
                            break
                        continue
                    # 最後の安全網: revise 上限超過 / Verifier handoff → 人間へ(主経路ではない)
                    question = ((verifier_obj or {}).get("reasons")
                                or "自動判定では確証できません。続行指示をください。")
                    human, inbox_seen = await_human(run_id, run_dir, question, cfg, inbox_seen)
                    if human == STOP_SIGNAL:
                        final, stopped = "stopped", True
                        break
                    if human is None:
                        verifier_verdict = "handoff"
                        break
                    print("  · 人間の続行指示を受領 → Implementer 続行 …")
                    write_run_status(run_id=run_id, phase="implementer")
                    impl.send(human)
                    i_result, i_hint, inbox_seen = _drive_implementer(impl, run_id, run_dir, cfg, inbox_seen)
                    if i_hint in ("timeout", "error"):
                        final, retryable = ("timeout" if i_hint == "timeout" else "fail"), True
                        break
                    if i_hint == "handoff":
                        verifier_verdict = "handoff"
                        break
                    if i_hint == "stopped":
                        final, stopped = "stopped", True
                        break
                    rounds = 0  # 人間が方向を与えた = 新フェーズ。revise カウンタをリセット
                if not retryable and not stopped:
                    final = combine_verdict(test_verdict, verifier_verdict)
        finally:
            impl.close()
        session_id = (i_result or {}).get("session_id")

        # remove --force の前にコミットして成果を loop/<id> ブランチに残す。
        committed = commit_worktree(wt, f"loop run {run_id} → {final}")

        # 6) promote: pass なら PR 化し CI + Copilot が green になるまで Implementer を差し戻し(種類A)。
        #    task.no_pr=true は PR を出さず loop/<id> ブランチのまま留める(ローカル検証用)。
        promote_info = None
        no_pr = str(task.get("no_pr", "")).lower() in ("true", "1", "yes")
        if final == "pass" and loop.get("promote_on_pass") and committed and not no_pr:
            write_run_status(run_id=run_id, phase="promote")
            print("  · promote: PR 提出 → CI/Copilot 対応 …")
            promote_info = promote_run(task, run_id, run_dir, repo, wt, branch, cfg, session_id)
            (run_dir / "promote.json").write_text(
                json.dumps(promote_info, ensure_ascii=False, indent=2), encoding="utf-8")
            if promote_info.get("state") == "green":
                final = "awaiting-merge"  # 真の完了は人間の PR マージ後。check_pr_merge が pass へ昇格させる
            else:  # green にできず → 人間へ(死角を作らない)
                final = "handoff"
            print(f"  · promote: {promote_info.get('state')} / PR {promote_info.get('pr_url')}")

        roles = {}
        for r in ("implementer", "verifier"):
            p = run_dir / f"{r}.result.json"
            roles[r] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

        md = write_run_md(task, run_id, final, i_result, cfg, started_at, vcode,
                          test_verdict, verifier_verdict, verifier_obj, roles, repo=repo,
                          pr_url=(promote_info or {}).get("pr_url"))
        _finalize_run(task, run_id, run_dir, md, final, f"run: {run_id} → {final}")

        # 摩擦のある run でだけ規範候補を起草する(種類A)。毎 run ではない。昇格は人間(種類B)。
        if not retryable:
            triggers = []
            if revise_occurred:
                triggers.append("Implementer の revise 差し戻しが発生(required_changes)")
            if verifier_verdict == "handoff":
                triggers.append("Verifier が handoff(自動判定では確証できず)")
            if triggers:
                try:
                    maybe_draft_norms(run_id, repo, cfg, " / ".join(triggers))
                except Exception as ex:  # 起草の失敗を run 確定に波及させない
                    print(f"  · 規範候補: 起草中に例外(無視) {ex!r}")

        print(f"  · test={test_verdict} / verifier={verifier_verdict} / final={final}")
        branch_note = f"branch {branch} に成果をコミット" if committed else f"branch {branch}(変更なし)"
        print(f"  · run MD: {md.relative_to(DATA)} / {branch_note}")
        return final, retryable
    finally:
        clear_run_status(run_id, locals().get("final"))  # status.json を done 化(.run.lock ミラーも掃除)
        try:
            if serial:
                leave_serial(repo, orig_ref, run_id)  # 退避コミット → 元ブランチへ戻す(本体を汚さない)
            else:
                remove_worktree(repo, wt)
        finally:
            if lock:
                lock.release()


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
    nc = reindex_norms()  # 規範候補(candidates.md)も MD から派生インデックスを再生成
    print(f"reindex 完了: run MD {n} 件 / 規範候補 {nc} 件から loop.db を再生成しました。")
    return 0


def _find_candidate(candidate_id: str) -> tuple[Path, dict] | None:
    """全 repo の candidates.md を走査して candidate_id を持つ (candidates_path, 候補dict) を返す。"""
    if not NORMS_ROOT.exists():
        return None
    for cpath in sorted(NORMS_ROOT.glob("*/candidates.md")):
        for c in parse_candidates(cpath):
            if c["candidate_id"] == candidate_id:
                return cpath, c
    return None


def write_conventions(repo_name: str, text: str) -> Path:
    """承認済み知識(conventions.md)を人間の編集で上書きする(種類B の中継=統合・剪定・修正)。
    promote は追記専用なので、重複・陳腐化した規範を磨き込む更新口はここ。中身は人間が書く(生成しない)。"""
    d = NORMS_ROOT / _safe_repo_name(repo_name)
    conv = d / "conventions.md"
    body = text if (text == "" or text.endswith("\n")) else text + "\n"
    with _DATA_COMMIT_LOCK:
        d.mkdir(parents=True, exist_ok=True)
        conv.write_text(body, encoding="utf-8")
        auto_commit(DATA, [conv], f"norms: {_safe_repo_name(repo_name)} の conventions.md を人間が編集")
    return conv


def reject_candidate(candidate_id: str) -> bool:
    """規範候補を reject(人間=種類B の操作の中継。CLI / Web 共用)。見つからねば False。"""
    found = _find_candidate(candidate_id)
    if not found:
        return False
    cpath, c = found
    with _DATA_COMMIT_LOCK:
        set_candidate_status(cpath, c["candidate_id"], "rejected")
        reindex_norms()
        auto_commit(DATA, [cpath], f"norms: {c['candidate_id']} を reject")
    return True


def promote_candidate(candidate_id: str) -> Path | None:
    """規範候補を conventions.md へ昇格(人間=種類B の操作の中継。CLI / Web 共用)。返り値=conventions.md パス。
    文言の統合・上書き・剪定は人間が conventions.md を直接編集して行う。見つからねば None。"""
    found = _find_candidate(candidate_id)
    if not found:
        return None
    cpath, c = found
    conv = cpath.parent / "conventions.md"
    promoted_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    ev = ", ".join(c.get("evidence_runs", []))
    block = (f"\n## (昇格: {c['candidate_id']} — 見出し/文言は人間が調整)\n"
             f"{c.get('proposed_norm', '')}\n"
             f"- evidence_runs: [{ev}]\n"
             f"- promoted_at: {promoted_at}\n")
    with _DATA_COMMIT_LOCK:
        conv.parent.mkdir(parents=True, exist_ok=True)
        if not conv.exists() or conv.stat().st_size == 0:
            conv.write_text(f"# {cpath.parent.name} の設計規範(承認済み・run に注入される)\n\n"
                            "> 人間が candidates.md から昇格させた規範のみ。憲法(constitution.md)に劣後する。\n",
                            encoding="utf-8")
        with conv.open("a", encoding="utf-8") as f:
            f.write(block)
        set_candidate_status(cpath, c["candidate_id"], "promoted")
        reindex_norms()
        auto_commit(DATA, [conv, cpath], f"norms: {c['candidate_id']} を conventions.md へ昇格")
    return conv


def cmd_norms(rest: list[str]) -> int:
    """規範記憶の昇格配管(種類B の人間作業の補助のみ。規範文の生成・要約・推奨はしない)。
    usage: norms [list] | promote <id> | reject <id> | draft <run_id> [--reason <text>]"""
    cfg = load_config()
    action = rest[0] if rest else "list"

    if action == "list":
        rows = []
        if NORMS_ROOT.exists():
            for cpath in sorted(NORMS_ROOT.glob("*/candidates.md")):
                for c in parse_candidates(cpath):
                    if c.get("status", "pending") == "pending":
                        rows.append((cpath.parent.name, c))
        if not rows:
            print("pending な規範候補はありません(摩擦 run が出ると起草されます)。")
            return 0
        print(f"pending な規範候補 {len(rows)} 件(昇格は人間: norms promote/reject <id>):\n")
        for rname, c in rows:
            print(f"● {c['candidate_id']}  [{rname}]")
            print(f"    摩擦: {c.get('observed_friction', '')}")
            print(f"    規範案: {c.get('proposed_norm', '')}")
            print(f"    evidence: {c.get('evidence_runs', [])}\n")
        return 0

    if action in ("promote", "reject"):
        if len(rest) < 2:
            print(f"usage: norms {action} <candidate_id>")
            return 2
        if action == "reject":
            if not reject_candidate(rest[1]):
                print(f"候補が見つかりません: {rest[1]}")
                return 1
            print(f"  · {rest[1]} を rejected にしました。")
            return 0
        conv = promote_candidate(rest[1])
        if conv is None:
            print(f"候補が見つかりません: {rest[1]}")
            return 1
        print(f"  · {rest[1]} を promoted にし conventions.md へ追記しました。"
              f"文言調整は {conv.relative_to(DATA)} を直接編集してください。")
        return 0

    if action == "draft":
        if len(rest) < 2:
            print("usage: norms draft <run_id> [--reason <text>]")
            return 2
        run_id = rest[1]
        md = RUNS / f"{run_id}.md"
        if not md.exists():
            print(f"run が見つかりません: {run_id}")
            return 1
        reason = rest[rest.index("--reason") + 1] if "--reason" in rest and rest.index("--reason") + 1 < len(rest) else "人間が手動で起草を要求(レビュー時の摩擦)"
        repo = _repo_from_run_md(md)
        maybe_draft_norms(run_id, repo, cfg, reason)
        return 0

    print(f"unknown norms action: {action}\nusage: norms [list] | promote <id> | reject <id> | draft <run_id> [--reason <text>]")
    return 2


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
        def _opt(flag: str) -> str | None:
            return rest[rest.index(flag) + 1] if flag in rest and rest.index(flag) + 1 < len(rest) else None
        return cmd_gen(sys.argv[2] if len(sys.argv) > 2 else "", "--run" in rest,
                       _opt("--repo"), _opt("--base-branch"), "--no-pr" in rest)
    if cmd == "norms":
        return cmd_norms(sys.argv[2:])
    table = {"reindex": cmd_reindex, "status": cmd_status, "merges": cmd_merges}
    if cmd in table:
        return table[cmd]()
    print("unknown command: {}\nusage: runner.py [run [task_id]|gen <prompt> [--run]|reindex|status|merges|"
          "norms [list|promote <id>|reject <id>|draft <run_id>]]".format(cmd), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
