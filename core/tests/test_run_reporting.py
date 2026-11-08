import ast
import json
import os
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from paperpull_core import pressing, storage
from paperpull_core.run_reporting import (NEW_LIST_NOTE, PREFIX, lists_what_it_saved,
                                          report_run_result)
from paperpull_core.storage import atomic_write_text, now_iso

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for base in (ROOT / "apps",)
                 for p in base.glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_each_provider_reports_current_run_counts(entry, tmp_path, capsys):
    # Execute the actual summary method, without loading browsers or private configs.
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "write_run_summary")
    scope = {"atomic_write_text": atomic_write_text, "now_iso": now_iso,
             "report_run_result": report_run_result,
             "lists_what_it_saved": lists_what_it_saved, "NEW_LIST_NOTE": NEW_LIST_NOTE}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(entry), "exec"), scope)
    stats = defaultdict(int, started="2026-01-01T00:00:00", mode="all", dates=[], dates_processed=[],
                        new_files=["Statements/synthetic.pdf"], manual_review=2)
    app = SimpleNamespace(stats=stats, args=SimpleNamespace(dry_run=False),
                          paths=SimpleNamespace(root=tmp_path,
                                                run_summary=tmp_path / "run-summary.txt"))
    scope["write_run_summary"](app)
    assert "Statements/synthetic.pdf" in (tmp_path / "new-this-run.txt").read_text()
    stats.update(new_files=[], manual_review=0)
    scope["write_run_summary"](app)
    reports = [json.loads(line[len(PREFIX):]) for line in capsys.readouterr().out.splitlines()
               if line.startswith(PREFIX)]
    assert reports[0]["manual_review"] == 2
    assert reports[1] == {"manual_review": 0, "failed": 0, "validation_failures": 0,
                          "new_files": 0, "name_review": 0, "wrong_document": 0, "alike": 0,
                          "stopped": 0}


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_interrupt_saves_progress_and_returns_nonzero(entry):
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    saved = []
    class FakeApp:
        def __init__(self, args):
            self.stats = {"mode": "all"}
            self.progress = SimpleNamespace(save=lambda **how: saved.append(("progress", how)))
            self.discovery = SimpleNamespace(save=lambda **how: saved.append(("discovery", how)))
        def cmd_run(self, *args, **kwargs): raise KeyboardInterrupt
        def write_run_summary(self): saved.append("summary")
        def close(self): saved.append("closed")
    args = SimpleNamespace(start_date=None, end_date=None, open_browser=False,
                           login=False, discover=False, pilot=False, all=True,
                           pilot_online=False, pilot_instore=False, online=False, instore=False)
    # pressing is a name an app's main reads when it catches a stop at a press.
    scope = {"ONLINE": "Online", "IN_STORE": "In-Store", "App": FakeApp, "pressing": pressing,
             "build_parser": lambda: SimpleNamespace(parse_args=lambda argv: args)}
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(entry), "exec"), scope)
    assert scope["main"]([]) == 130
    # Both stores are saved with leaving=True, so a file another program
    # holds is named in one line rather than raised out of the finally
    # before the result is written (the census below).
    assert saved == [("progress", {"leaving": True}), ("discovery", {"leaving": True}),
                     "summary", "closed"]


def test_a_wrong_document_is_reported_on_its_own_and_said_in_words(capsys):
    """A refused wrong document was counted inside manual_review only, so
    the panel said "needs review" whether nothing had arrived or the wrong
    statement had, and the second puts the run's other files in doubt."""
    report_run_result({"manual_review": 1, "wrong_document": 1, "new_files": []})
    out = capsys.readouterr().out
    result = json.loads(out.split(PREFIX, 1)[1])
    assert result["wrong_document"] == 1
    assert "1 document was refused, since it was not the one asked for" in out


def test_documents_left_unsaved_as_alike_are_reported_on_their_own(capsys):
    """Two documents of one type on one date that a row cannot be bound to
    are left unsaved while the rest of the run goes on, and were only a
    console line. The panel now has the count, and absent is zero."""
    report_run_result({"alike": 2, "new_files": []})
    assert json.loads(capsys.readouterr().out.split(PREFIX, 1)[1])["alike"] == 2
    report_run_result({"new_files": []})
    assert json.loads(capsys.readouterr().out.split(PREFIX, 1)[1])["alike"] == 0


def test_a_run_with_no_wrong_document_says_nothing_about_it(capsys):
    report_run_result({"new_files": []})
    out = capsys.readouterr().out
    assert "refused" not in out
    assert json.loads(out.split(PREFIX, 1)[1])["wrong_document"] == 0


def _result(out):
    return json.loads(out.split(PREFIX, 1)[1].splitlines()[0])


def test_receipts_saved_under_an_unsure_name_are_counted_on_their_own(capsys):
    """Part of manual_review, so the panel can send the person to Review
    names for those and to the Manual Review folder only for the rest."""
    report_run_result({"manual_review": 3, "name_review": 2, "new_files": []})
    got = _result(capsys.readouterr().out)
    assert got["manual_review"] == 3 and got["name_review"] == 2
    report_run_result({"manual_review": 1, "name_review": 4, "new_files": []})
    assert _result(capsys.readouterr().out)["name_review"] == 1, "never more than manual_review"
    report_run_result({"new_files": []})
    assert _result(capsys.readouterr().out)["name_review"] == 0


def test_a_run_that_finishes_is_not_stopped(capsys):
    report_run_result({"new_files": []})
    assert _result(capsys.readouterr().out)["stopped"] == 0


def test_a_run_leaving_on_an_exception_says_it_stopped(capsys):
    """The quiet stop, SystemExit(0) after a prompt nobody could answer,
    used to report all zeros and read as a clean finish."""
    with pytest.raises(SystemExit):
        try:
            raise SystemExit(0)
        finally:
            report_run_result({"new_files": []})
    out = capsys.readouterr().out
    assert _result(out)["stopped"] == 1
    assert "stopped before it finished" in out


def test_a_rename_that_stops_does_not_point_to_resume(capsys):
    """A Rename that put its files back has just asked for Rename again.
    Resume has nothing of a rename's to carry on with."""
    with pytest.raises(SystemExit):
        try:
            raise SystemExit(1)
        finally:
            report_run_result({"mode": "rename", "new_files": []})
    out = capsys.readouterr().out
    assert _result(out)["stopped"] == 1
    assert "This run stopped before it finished." in out
    assert "Resume" not in out


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_each_provider_reports_a_quiet_stop_as_stopped(entry, capsys):
    """Every app's own main, with a run that stops the way a mid-run
    sign-out stops under the panel. The result it writes on the way out
    has to say so, whatever the exit code is."""
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")

    class FakeApp:
        def __init__(self, args):
            self.stats = {"mode": "all", "new_files": []}
            self.progress = SimpleNamespace(save=lambda **how: None)
            self.discovery = SimpleNamespace(save=lambda **how: None)
        def cmd_run(self, *args, **kwargs): raise SystemExit(0)
        def write_run_summary(self): report_run_result(self.stats)
        def close(self): pass
    args = SimpleNamespace(start_date=None, end_date=None, open_browser=False,
                           login=False, discover=False, pilot=False, all=True,
                           pilot_online=False, pilot_instore=False, online=False, instore=False)
    scope = {"ONLINE": "Online", "IN_STORE": "In-Store", "App": FakeApp, "pressing": pressing,
             "build_parser": lambda: SimpleNamespace(parse_args=lambda argv: args)}
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(entry), "exec"), scope)
    with pytest.raises(SystemExit):
        scope["main"]([])
    assert _result(capsys.readouterr().out)["stopped"] == 1


def _held(monkeypatch, path: Path) -> list:
    """os.replace refused for `path` as Windows refuses to replace a file
    another program holds open, each try counted, and the pause between
    tries not taken."""
    real = os.replace
    tries = []

    def replace(src, dst, *args, **kwargs):
        if Path(dst) == path:
            tries.append(dst)
            raise PermissionError(13, "The process cannot access the file because it is "
                                  "being used by another process", str(dst))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return tries


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_each_provider_writes_its_result_when_its_run_state_is_held(entry, tmp_path,
                                                                     monkeypatch, capsys):
    """Every app's own main, with a run that stops because another program
    holds progress.json, as Rename stops when its check finds it held. The
    save on the way out waited a second minute and raised PermissionError
    out of the finally, so the person saw a traceback in place of the stop
    and the panel never got the result. Now that save says in one line
    where the file is, does not wait for it again, and the result is
    written."""
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    progress = tmp_path / "progress.json"
    tries = _held(monkeypatch, progress)

    class FakeApp:
        def __init__(self, args):
            self.stats = {"mode": "all", "new_files": []}
            self.progress = storage.JsonStore(progress)
            self.discovery = storage.JsonStore(tmp_path / "discovery.json")
        def cmd_run(self, *args, **kwargs):
            assert not storage.free_to_write(progress, say=lambda *_a: None)
            raise SystemExit(1)
        def write_run_summary(self): report_run_result(self.stats)
        def close(self): pass
    args = SimpleNamespace(start_date=None, end_date=None, open_browser=False,
                           login=False, discover=False, pilot=False, all=True,
                           pilot_online=False, pilot_instore=False, online=False, instore=False)
    scope = {"ONLINE": "Online", "IN_STORE": "In-Store", "App": FakeApp, "pressing": pressing,
             "build_parser": lambda: SimpleNamespace(parse_args=lambda argv: args)}
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(entry), "exec"), scope)
    with pytest.raises(SystemExit) as stop:
        scope["main"]([])
    out = capsys.readouterr().out
    assert stop.value.code == 1
    assert ("  ! %s could not be written, so it keeps what was last saved in it. Close any "
            "program that has it open before the next run." % progress) in out.splitlines()
    assert _result(out)["stopped"] == 1
    assert len(tries) == storage._LOCKED_TRIES + 1, "it waited for the file again on its way out"
    assert (tmp_path / "discovery.json").exists(), "the save after it was never reached"


def discover_with(entry, ends):
    """The app's own main for --discover, against an app whose discovery
    ends the way `ends` says, and what that app was asked to do, in order."""
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    did = []

    class FakeApp:
        def __init__(self, args):
            self.stats = {"mode": "", "new_files": []}
            self.progress = SimpleNamespace(save=lambda **_kw: None)
            self.discovery = SimpleNamespace(save=lambda **_kw: None)
        def cmd_discover(self, *args, **kwargs):
            did.append("discover as %r" % self.stats["mode"])
            ends()
        def write_run_summary(self): did.append("summary")
        def close(self): pass
    args = SimpleNamespace(start_date=None, end_date=None, open_browser=False,
                           login=False, discover=True, pilot=False, all=False,
                           pilot_online=False, pilot_instore=False, online=False, instore=False)
    scope = {"ONLINE": "Online", "IN_STORE": "In-Store", "App": FakeApp,
             "report_run_result": report_run_result, "pressing": pressing,
             "build_parser": lambda: SimpleNamespace(parse_args=lambda argv: args)}
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(entry), "exec"), scope)
    return scope["main"], did


def _stops():
    raise SystemExit(0)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_each_provider_tells_the_panel_how_a_discover_ended(entry, capsys):
    """Discover set no mode, and main writes the run summary, which carries
    the panel's result line, only for a mode, so the panel never heard how a
    Discover ended. One that stopped with its list cut short read "finished,
    check output" as one that read it whole did, and its failure file was
    never offered. Discover downloads nothing, so the run summary and
    new-this-run.txt stay as the last download run wrote them, since
    PaperPull Server hands that list's files on to its plug-ins."""
    main, did = discover_with(entry, lambda: None)
    assert main([]) == 0
    assert _result(capsys.readouterr().out)["stopped"] == 0
    assert did == ["discover as 'discover'"], "a failure file names the command it came from"

    main, did = discover_with(entry, _stops)
    with pytest.raises(SystemExit):
        main([])
    out = capsys.readouterr().out
    assert _result(out)["stopped"] == 1
    assert "stopped before it finished" in out
    assert "press Discover again" in out and "Resume carries on" not in out, (
        "the console sends a stopped Discover to Discover, as the panel does")
    assert did == ["discover as 'discover'"], "and nothing writes the run summary"
