import asyncio
import io
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import run_result


def line(**overrides):
    return run_result.PREFIX + json.dumps(dict(manual_review=0, failed=0,
            validation_failures=0, new_files=0, **{}) | overrides)


@pytest.mark.parametrize("field", ["manual_review", "failed", "validation_failures"])
def test_any_unresolved_count_requires_attention(field):
    assert run_result.parse(line(**{field: 1}))["attention"]
    assert not run_result.parse(line(new_files=4))["attention"]


@pytest.mark.parametrize("value", ["ordinary output", run_result.PREFIX + "{}",
    run_result.PREFIX + "null", run_result.PREFIX + "broken", line(failed=-1), line(failed=True)])
def test_invalid_or_incomplete_results_are_not_success(value):
    assert run_result.parse(value) is None


def test_result_drops_unexpected_private_fields():
    result = run_result.parse(line(account="synthetic", path="private/example"))
    assert "account" not in result and "path" not in result


def _set_up(install):
    """An install with a venv, which is what the panel will agree to run.

    Only the path is looked at, never the file, so an empty one is
    enough and no interpreter is launched by these tests."""
    exe = install / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    return install


def test_stream_carries_current_counts_and_keeps_exit_code(tmp_path, monkeypatch):
    _set_up(tmp_path)

    class Process:
        def __init__(self, *args, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("ordinary output\n" + line(manual_review=4) + "\n")
        def wait(self, **kwargs): return 0
        def poll(self): return 0
    monkeypatch.setattr(app, "discover_apps", lambda: {"example": {"dir": str(tmp_path)}})
    monkeypatch.setattr(app, "_build_cmd", lambda *args: ["synthetic-command"])
    monkeypatch.setattr(app.subprocess, "Popen", Process)
    async def consume():
        return "".join([part async for part in app.api_run("example", action="all").body_iterator])
    output = asyncio.run(consume())
    assert '"attention": true' in output
    assert '"manual_review": 4' in output
    assert "event: result" in output and "event: done\ndata: 0" in output
    assert run_result.PREFIX not in output
    assert "example" not in app._RUNNING


def test_an_app_that_is_not_set_up_is_told_so_and_never_started(tmp_path,
                                                                monkeypatch):
    """A checkout install with no venv used to run under the panel's own
    interpreter, which has fastapi and nothing else, and died on
    `No module named 'paperpull_core'`. That is a true sentence about the
    wrong interpreter and it tells a tester nothing."""
    started = []
    monkeypatch.setattr(app, "discover_apps", lambda: {"example": {"dir": str(tmp_path)}})
    monkeypatch.setattr(app, "_build_cmd", lambda *args: ["synthetic-command"])
    monkeypatch.setattr(app.subprocess, "Popen",
                        lambda *a, **k: started.append(a) or (_ for _ in ()).throw(
                            AssertionError("should never have started")))
    monkeypatch.setattr(app, "_is_packaged", lambda: False)

    async def consume():
        return "".join([part async for part in
                        app.api_run("example", action="all").body_iterator])

    output = asyncio.run(consume())
    assert not started
    assert "not set up yet" in output
    assert "setup" in output
    assert "RELOAD this page" in output
    assert "event: done\ndata: 1" in output


def test_the_packaged_build_is_never_told_to_run_setup(tmp_path, monkeypatch):
    """It has no venv anywhere and does not need one. Its single bundled
    interpreter carries the core and every app's dependencies."""
    monkeypatch.setattr(app, "_is_packaged", lambda: True)
    assert app.setup_needed({"dir": str(tmp_path)}) == ""


def test_an_install_that_is_set_up_is_not_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_is_packaged", lambda: False)
    _set_up(tmp_path)
    assert app.setup_needed({"dir": str(tmp_path)}) == ""


def test_the_message_names_the_folder_to_open(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_is_packaged", lambda: False)
    said = app.setup_needed({"dir": str(tmp_path)})
    assert str(tmp_path) in said


def test_a_wrong_document_needs_attention_on_its_own():
    """Counted inside manual_review too, but the panel names it, because a
    wrong statement arriving is not the same finding as nothing arriving."""
    assert run_result.parse(line(wrong_document=1))["attention"]
    assert run_result.parse(line())["wrong_document"] == 0


def test_an_app_from_before_the_count_existed_still_reports():
    """Absent is zero, so an install the panel has not refreshed yet still
    shows its run rather than "no run summary"."""
    assert run_result.parse(line()) is not None
    assert run_result.parse(line(wrong_document=-1)) is None
    assert run_result.parse(line(wrong_document="1")) is None


def test_the_panel_names_a_wrong_document():
    src = (Path(app.__file__)).read_text(encoding="utf-8")
    assert "refused as the wrong document" in src
