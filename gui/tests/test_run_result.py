import asyncio
import io
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import run_result


# The mark a run is given, which its result line carries.
MARK = "0123456789abcdef" * 2


def line(**overrides):
    return run_result.PREFIX + MARK + " " + json.dumps(dict(manual_review=0, failed=0,
            validation_failures=0, new_files=0, **{}) | overrides)


@pytest.mark.parametrize("field", ["manual_review", "failed", "validation_failures"])
def test_any_unresolved_count_requires_attention(field):
    assert run_result.parse(line(**{field: 1}), MARK)["attention"]
    assert not run_result.parse(line(new_files=4), MARK)["attention"]


@pytest.mark.parametrize("value", ["ordinary output", run_result.PREFIX + MARK + " {}",
    run_result.PREFIX + MARK + " null", run_result.PREFIX + MARK + " broken", line(failed=-1),
    line(failed=True)])
def test_invalid_or_incomplete_results_are_not_success(value):
    assert run_result.parse(value, MARK) is None


def test_result_drops_unexpected_private_fields():
    result = run_result.parse(line(account="synthetic", path="private/example"), MARK)
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
            # The real core marks its line with the mark the panel gave it.
            mark = kwargs["env"][run_result.MARK_ENV]
            self.stdout = io.StringIO("ordinary output\n" + line(manual_review=4).replace(MARK, mark)
                                      + "\n")
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
    interpreter, which had fastapi and nothing else, and died on
    `No module named 'paperpull_core'`. That is a true sentence about the
    wrong interpreter and it tells a tester nothing. It still is, until
    setup-all has given that interpreter what an app needs."""
    started = []
    monkeypatch.setattr(app, "discover_apps", lambda: {"example": {"dir": str(tmp_path)}})
    monkeypatch.setattr(app, "_build_cmd", lambda *args: ["synthetic-command"])
    monkeypatch.setattr(app.subprocess, "Popen",
                        lambda *a, **k: started.append(a) or (_ for _ in ()).throw(
                            AssertionError("should never have started")))
    monkeypatch.setattr(app, "_is_packaged", lambda: False)
    monkeypatch.setattr(app, "_runs_apps", lambda: False)

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


def test_the_message_names_setup_all_and_the_folder_it_is_in(tmp_path, monkeypatch):
    """setup-all builds the one environment every provider shares (#65),
    where the message used to send each provider to a setup of its own."""
    monkeypatch.setattr(app, "_is_packaged", lambda: False)
    monkeypatch.setattr(app, "_runs_apps", lambda: False)
    said = app.setup_needed({"dir": str(tmp_path)})
    assert "  1. Open  %s\n" % app.HERE.parent in said
    assert "setup-all.%s" % ("bat" if sys.platform == "win32" else "command") in said


def test_an_app_with_no_venv_runs_once_setup_all_has_filled_the_panels_own(tmp_path,
                                                                           monkeypatch):
    """In a checkout an app with no venv of its own runs on the panel's
    interpreter, gui/.venv, which setup-all builds for every app."""
    monkeypatch.setattr(app, "_is_packaged", lambda: False)
    monkeypatch.setattr(app, "_runs_apps", lambda: True)
    assert app.setup_needed({"dir": str(tmp_path)}) == ""
    assert app._python_for(tmp_path) == sys.executable


def test_whether_the_panels_interpreter_can_run_an_app_is_asked_of_a_new_process(
        tmp_path, monkeypatch):
    """The naming page puts the core on the panel's own path, so the panel
    could import it while no app run started by the panel could. A package
    only on the panel's path does not count, and one on the path every run
    inherits does."""
    folder = tmp_path / "only-here"
    (folder / "pp_only_on_this_path").mkdir(parents=True)
    (folder / "pp_only_on_this_path" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(app, "APP_NEEDS", ("pp_only_on_this_path",))
    monkeypatch.setattr(app, "_RUNS_APPS", {})
    monkeypatch.syspath_prepend(str(folder))
    import importlib.util
    assert importlib.util.find_spec("pp_only_on_this_path") is not None
    assert app._runs_apps() is False
    monkeypatch.setenv("PYTHONPATH", str(folder))
    assert app._runs_apps() is True


def test_the_answer_is_asked_again_only_once_the_packages_change(monkeypatch):
    """A page lists every app, and setup-all can finish while it is open."""
    asked, stamp = [], [1]
    monkeypatch.setattr(app, "_RUNS_APPS", {})
    monkeypatch.setattr(app, "_packages_stamp", lambda: stamp[0])
    monkeypatch.setattr(app.subprocess, "run",
                        lambda *a, **k: asked.append(a) or app.subprocess.CompletedProcess(a, 0))
    assert app._runs_apps() and app._runs_apps()
    assert len(asked) == 1
    stamp[0] = 2
    assert app._runs_apps()
    assert len(asked) == 2


def test_a_wrong_document_needs_attention_on_its_own():
    """Counted inside manual_review too, but the panel names it, because a
    wrong statement arriving is not the same finding as nothing arriving."""
    assert run_result.parse(line(wrong_document=1), MARK)["attention"]
    assert run_result.parse(line(), MARK)["wrong_document"] == 0


def test_an_app_from_before_the_count_existed_still_reports():
    """Absent is zero, so an install the panel has not refreshed yet still
    shows its run rather than "no run summary"."""
    assert run_result.parse(line(), MARK) is not None
    assert run_result.parse(line(wrong_document=-1), MARK) is None
    assert run_result.parse(line(wrong_document="1"), MARK) is None


def test_the_panel_names_a_wrong_document():
    assert "refused as the wrong document" in app.HTML


def test_documents_left_unsaved_as_alike_are_counted_but_need_no_attention():
    """Documents of one type on one date are left unsaved while the rest
    of the run goes on. They are listed again on every run and never
    saved, so a run that counted them would need a look for good. The
    count is carried, and only another count makes the run one to look at."""
    alike = run_result.parse(line(alike=2), MARK)
    assert alike["alike"] == 2 and alike["attention"] is False
    assert run_result.parse(line(alike=2, failed=1), MARK)["attention"]
    assert run_result.parse(line(), MARK)["alike"] == 0
    assert run_result.parse(line(alike=-1), MARK) is None
    assert run_result.parse(line(alike="2"), MARK) is None
    assert "left unsaved, sharing a type and date" in app.HTML


def test_a_run_that_stopped_needs_attention_and_is_named():
    """A mid-run sign-out under the panel ends with exit code 0 and all
    zero counts, which used to read as a clean finish."""
    assert run_result.parse(line(stopped=1), MARK)["attention"]
    assert run_result.parse(line(), MARK)["stopped"] == 0
    assert run_result.parse(line(stopped=-1), MARK) is None
    assert "Stopped before finishing" in app.HTML


def test_a_discover_that_stopped_offers_to_check_again():
    """Discover tells the panel how it ended. Continue downloads, and
    somebody who asked only to see what the provider has is offered Check
    again for a Discover that stopped, never Continue."""
    js = (Path(app.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "const downloads = ['pilot', 'all', 'resume'].includes(RUN.action)" in js
    assert "const recheck = RUN.action === 'discover';" in js
    assert "recheck ? 'Check again when you are ready'" in js
    assert 'data-action="discover"' in js and "Check again</button>" in js


def test_a_resume_only_a_listing_carries_on_from_is_carried_to_the_panel():
    """A Resume that stopped because no run read the list to its end says
    so, and the panel offers Get new documents rather than Continue, which
    would stop the same way again (#124). An app from before it sends no
    count, which reads as no such stop."""
    stop = run_result.parse(line(stopped=1, list_not_read=1), MARK)
    assert stop["list_not_read"] == 1 and stop["stopped"] == 1
    assert run_result.parse(line(stopped=1), MARK)["list_not_read"] == 0
    assert run_result.parse(line(list_not_read=-1), MARK) is None
    assert run_result.parse(line(list_not_read="1"), MARK) is None
