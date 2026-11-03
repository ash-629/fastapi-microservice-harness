import json

import pytest
from harness import cli, hooks


@pytest.fixture
def task(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness/task.json").write_text(json.dumps({"active": True, "scope": "affected"}))
    return tmp_path


def receipt(task, status="PASS", scope="affected"):
    data = {
        "status": status,
        "fingerprint": cli.fingerprint(),
        "checks": [{"name": c, "status": "PASS"} for c in hooks.REQUIRED[scope]],
    }
    (task / ".harness/latest.json").write_text(json.dumps(data))


def test_failed_receipt_cannot_pass_stop(task):
    receipt(task, status="FAIL")
    assert hooks.handle("Stop", {}, task)["decision"] == "block"


def test_quick_does_not_satisfy_affected(task):
    receipt(task, scope="quick")
    assert hooks.handle("Stop", {}, task)["decision"] == "block"


def test_current_complete_receipt_finishes_task(task):
    receipt(task)
    assert hooks.handle("Stop", {}, task) == {}
    assert hooks.read_json(task / ".harness/task.json")["active"] is False


def test_changed_source_blocks_and_continuation_is_bounded(task):
    receipt(task)
    (task / "changed.py").write_text("x=1")
    assert hooks.handle("Stop", {}, task)["decision"] == "block"
    assert "decision" not in hooks.handle("Stop", {"stop_hook_active": True}, task)


def test_consultation_not_forced_to_run_tests(tmp_path):
    assert hooks.handle("Stop", {}, tmp_path) == {}


def test_post_tool_marks_task_dirty(task):
    hooks.handle("PostToolUse", {}, task)
    assert hooks.read_json(task / ".harness/task.json")["dirty"] is True
