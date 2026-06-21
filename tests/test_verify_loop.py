# /// script
# requires-python = "==3.12.*"
# dependencies = ["pytest", "pyyaml"]
# ///
"""_verify_revise_loop(run の核心: 決定論ゲート → Verifier → revise/await の有界ループ)の
全経路をモック注入で pin する。_run_attempt と cmd_continue が共有する関数なので、ここが
壊れると初回 run も続行も壊れる。ライブ run では非決定で再現できない revise/handoff/stopped/
contract_update 経路をここで決定論的に固定し、抽出のリグレッションを検出する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import runner  # noqa: E402

CFG = {"loop": {"implementer_revise_rounds": 2}}


class FakeImpl:
    """RoleSession の代役。send された差し戻し/続行プロンプトを記録するだけ。"""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "change.patch").write_text("diff", encoding="utf-8")
    (d / "test-output.txt").write_text("out", encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def _noop_side_effects(monkeypatch):
    # 副作用系(status 書き込み・diff 取得・revise プロンプト生成)は本テストの対象外。
    monkeypatch.setattr(runner, "capture_diff", lambda *a, **k: None)
    monkeypatch.setattr(runner, "write_run_status", lambda *a, **k: None)
    monkeypatch.setattr(runner, "render_revise_prompt", lambda *a, **k: "REVISE PROMPT")


def _seq(values):
    """呼び出しごとに values を順に返す side_effect。最後の値を以降も返し続ける。"""
    box = {"i": 0}

    def _f(*a, **k):
        i = min(box["i"], len(values) - 1)
        box["i"] += 1
        return values[i]

    return _f


def _run(monkeypatch, run_dir, *, verify, judge, drive=None, human=None,
         contract=None, allow_contract_update=False, impl=None):
    monkeypatch.setattr(runner, "run_verify", _seq(verify))
    monkeypatch.setattr(runner, "judge_with_verifier", _seq(judge))
    if drive is not None:
        monkeypatch.setattr(runner, "_drive_implementer", _seq(drive))
    if human is not None:
        monkeypatch.setattr(runner, "await_human", _seq(human))
    if contract is not None:
        monkeypatch.setattr(runner, "apply_contract_update", _seq(contract))
    impl = impl or FakeImpl()
    out = runner._verify_revise_loop(
        {"id": "t"}, impl, run_dir.parent, run_dir, "rid", CFG, "brief",
        {"session_id": "s0"}, 0,
        round_name_fn=lambda r: f"verifier.round{r + 1}.json",
        allow_contract_update=allow_contract_update)
    return out, impl


def test_pass_first_try(monkeypatch, run_dir):
    out, impl = _run(monkeypatch, run_dir,
                     verify=[("pass", 0)], judge=[("pass", {"verdict": "pass"})])
    assert out.final == "pass"
    assert out.test_verdict == "pass" and out.verifier_verdict == "pass"
    assert out.retryable is False and out.stopped is False and out.revise_occurred is False
    assert impl.sent == [], "pass 一発では差し戻さない"
    assert (run_dir / "verifier.round1.json").exists(), "round 別 verifier を残す"


def test_test_fail_floor(monkeypatch, run_dir):
    # 決定論ゲートが fail なら Verifier が pass でも床で fail(combine_verdict)。
    out, _ = _run(monkeypatch, run_dir,
                  verify=[("fail", 1)], judge=[("pass", {"verdict": "pass"})])
    assert out.final == "fail"


def test_revise_then_pass(monkeypatch, run_dir):
    out, impl = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise"}), ("pass", {"verdict": "pass"})],
        drive=[({"session_id": "s1"}, "ok", 0)])
    assert out.final == "pass"
    assert out.revise_occurred is True
    assert impl.sent == ["REVISE PROMPT"], "revise を 1 回 Implementer へ差し戻す"
    assert (run_dir / "verifier.round1.json").exists()
    assert (run_dir / "verifier.round2.json").exists()


def test_revise_exhausted_then_human_none_handoff(monkeypatch, run_dir):
    # revise 上限(2)を使い切り、人間が来ない(None)→ handoff。死角を作らない。
    out, impl = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise"})],
        drive=[({"session_id": "s"}, "ok", 0)],
        human=[(None, 0)])
    assert out.verifier_verdict == "handoff"
    assert out.final == "handoff"
    assert out.revise_occurred is True
    assert len(impl.sent) == 2, "revise を上限回(2)差し戻してから人間へ"


def test_human_directs_then_pass(monkeypatch, run_dir):
    # revise 上限超過 → 人間が続行指示 → Implementer 続行 → 次ラウンドで pass。
    out, impl = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        # round0,1,2 は revise(上限消費)、人間指示後の round は pass
        judge=[("revise", {"verdict": "revise"}), ("revise", {"verdict": "revise"}),
               ("revise", {"verdict": "revise"}), ("pass", {"verdict": "pass"})],
        drive=[({"session_id": "s"}, "ok", 0)],
        human=[("こう直して", 0)])
    assert out.final == "pass"
    # revise 2 回 + 人間指示 1 回 = 3 回 send
    assert impl.sent == ["REVISE PROMPT", "REVISE PROMPT", "こう直して"]


def test_stopped_during_revise(monkeypatch, run_dir):
    out, _ = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise"})],
        drive=[({"session_id": "s"}, "stopped", 0)])
    assert out.stopped is True and out.final == "stopped"


def test_handoff_during_revise(monkeypatch, run_dir):
    out, _ = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise"})],
        drive=[({"session_id": "s"}, "handoff", 0)])
    assert out.verifier_verdict == "handoff" and out.final == "handoff"


def test_timeout_during_revise_is_retryable(monkeypatch, run_dir):
    out, _ = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise"})],
        drive=[(None, "timeout", 0)])
    assert out.final == "timeout" and out.retryable is True


def test_contract_update_applied_when_allowed(monkeypatch, run_dir):
    # allow=True: contract_update を適用 → 同ラウンドで再判定 → pass。
    out, _ = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise", "contract_update": {"accept": ["x"]}}),
               ("pass", {"verdict": "pass"})],
        contract=[{"id": "t", "accept": ["x"]}],
        allow_contract_update=True)
    assert out.final == "pass"
    assert out.task.get("accept") == ["x"], "更新後の task を返す"


def test_contract_update_ignored_when_not_allowed(monkeypatch, run_dir):
    # allow=False(初回 run): contract_update は無視し、通常の revise 経路へ。
    out, impl = _run(
        monkeypatch, run_dir,
        verify=[("pass", 0)],
        judge=[("revise", {"verdict": "revise", "contract_update": {"accept": ["x"]}}),
               ("pass", {"verdict": "pass"})],
        drive=[({"session_id": "s"}, "ok", 0)],
        contract=[{"id": "t", "accept": ["x"]}],
        allow_contract_update=False)
    assert out.final == "pass"
    assert out.task.get("accept") is None, "初回 run は契約を書き換えない"
    assert impl.sent == ["REVISE PROMPT"], "contract_update でなく通常 revise を踏む"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
