"""A stop at a press ends the run the way it says it does, in every app that
presses through paperpull_core.pressing.

pressing.stop_run saves the run's progress, says why the run stopped and
has the app write its failure file with the stop's facts, through the app's
own write_failure(..., extra=facts). Twelve apps whose fallback press now
goes through pressing.press_once had a write_failure that took no extra, so
a stop there would have ended the run on a TypeError, with nothing said in
the run's own words and no failure file written. The census beside this one
reads only that main() catches the stop, and the browser tests call each
capture by itself, so neither could see it.

Each app's own main is run here with a made-up config and no browser, and
its run stops at a press the moment it starts. Every word here is made up.
"""
import ast
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import listing, pressing
from paperpull_core.run_reporting import PREFIX, ListNotRead, report_run_result

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_docs.py")) + sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


def presses_through_pressing(app: Path) -> bool:
    for path in sorted(app.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "pressing"
                    and node.attr in ("click", "check", "press_once")):
                return True
    return False


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(("_", ".")) and entry_of(d)
              and presses_through_pressing(d))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def test_every_app_that_presses_through_pressing_is_here():
    """Not vacuous. American Express, Vanguard, ADP, whose View statement
    goes through press_once, the twelve whose fallback press does, and
    M&T, whose year headings are pressed in their frame through
    pressing.click, found by what their code calls."""
    assert {d.name for d in APPS} >= {
        "amex", "vanguard", "adp", "amfam", "applecard", "att", "etrade", "golden1",
        "newrez", "pge", "sba", "smud", "statefarm", "wellsfargo", "mtb"}


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_stop_at_a_press_is_said_and_written_down(app, tmp_path, monkeypatch, capsys):
    mod = load(app)
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    import playwright.sync_api as sync_api

    def no_browser(*_args, **_kwargs):
        raise AssertionError("nothing here starts a browser")
    monkeypatch.setattr(sync_api, "sync_playwright", no_browser)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))

    def stops_at_a_press(self, *_args, **_kwargs):
        raise pressing.Covered(
            "press a control", "something on the page is over the control",
            ["Something on the page covers the control for this document, so nothing was "
             "pressed.", pressing.AGAIN],
            {"verdict": "covered", "error": "timeout"}, after_a_press=True)
    monkeypatch.setattr(mod.App, "cmd_run", stops_at_a_press)
    capsys.readouterr()
    with pytest.raises(SystemExit) as ended:
        mod.main(["--config", str(cfg), "--all", "--yes"])
    said = " ".join(capsys.readouterr().out.split())
    assert ended.value.code == 0, said[-1500:]
    assert "!! Something on the page covers the control for this document" in said, said[-1500:]
    written = sorted((tmp_path / "out").rglob("failure-*.json"))
    assert len(written) == 1, sorted(p.name for p in (tmp_path / "out").rglob("*"))
    report = json.loads(written[0].read_text(encoding="utf-8"))
    assert report["step"] == "press a control"
    assert report["reason"] == "something on the page is over the control"
    assert report["extra"]["verdict"] == "covered"


# -- a stop that leaves the list unread, stop_run on its own ----------------------------
#
# Simmons, Bilt, First Horizon and Coinbase's card statements read their list
# again for each document and stop the run with a pressing.Stop when it will
# not read. stop_run left on a plain SystemExit, so the panel offered
# Continue, which read the same list for its first document and stopped
# there again (#124). Every app's own main is driven with such a stop in
# test_every_app_stops_when_its_list_stops_while_it_downloads.py.

class Run:
    """A run that only saves, writes and remembers what it was asked."""

    def __init__(self, tmp_path, mode="all", scope=None, failure_raises=False):
        self.paths = SimpleNamespace(last_listing=tmp_path / "out" / "last-listing.json")
        self.args = SimpleNamespace(**dict([scope])) if scope else SimpleNamespace()
        self.stats = {"mode": mode, "failure_files": ["an earlier document's file"]}
        self.saved, self.written, self.surveys = [], [], []
        self.progress = SimpleNamespace(save=lambda **kw: self.saved.append(kw))
        self.failure_raises = failure_raises

    def write_failure(self, step, reason, extra=None):
        if self.failure_raises:
            raise OSError("the diagnostics folder is a file")
        self.written.append((step, reason, extra))

    def write_survey(self):
        self.surveys.append(True)


def list_stop(list_unread=True):
    return pressing.Stop("find the document", "the documents list stopped", [
        "The documents list stopped before this document was saved, since it answered 500.",
        "Nothing was pressed."], {"rows": 0}, list_unread=list_unread)


def ended(run, stop, capsys):
    """How stop_run leaves, with the result line and the words main's
    finally says on the way out, as the panel reads them."""
    with pytest.raises(SystemExit) as left:
        try:
            pressing.stop_run(run, stop)
        finally:
            report_run_result({"new_files": []})
    out = capsys.readouterr().out
    return (left.value, json.loads(out.split(PREFIX, 1)[1].splitlines()[0]),
            " ".join(out.split(PREFIX, 1)[0].split()))


@pytest.mark.parametrize("scope,whole_run", [
    (None, "Pilot or Run All"), (("year", 2026), "Pilot or Run All with no year or dates set")])
def test_a_stop_that_leaves_the_list_unread_has_the_panel_offer_a_run_that_lists(
        tmp_path, capsys, scope, whole_run):
    run = Run(tmp_path, scope=scope)
    listing.started(run)
    listing.read_whole(run)
    left, result, said = ended(run, list_stop(), capsys)
    assert isinstance(left, ListNotRead) and left.code == 0 and left.whole_run == whole_run
    assert listing.last(run) == listing.STOPPED
    assert run.saved == [{"backup": True}]
    # A file of its own, though an earlier document wrote the run's one.
    assert run.written == [("find the document", "the documents list stopped", {"rows": 0})]
    assert said.startswith("!! The documents list stopped before this document was saved")
    assert ("Nothing was pressed. Everything saved so far is kept. Look at the browser "
            "window, then run %s, either of which reads the list first." % whole_run) in said
    assert result["stopped"] == 1 and result["list_not_read"] == 1
    assert "Resume would only stop here again" in said and "Resume carries on" not in said


def test_a_stop_without_it_is_continued_as_before(tmp_path, capsys):
    run = Run(tmp_path)
    listing.started(run)
    listing.read_whole(run)
    left, result, said = ended(run, list_stop(list_unread=False), capsys)
    assert type(left) is SystemExit and left.code == 0
    assert listing.last(run) == listing.COMPLETE
    assert run.written == [("find the document", "the documents list stopped", {"rows": 0})]
    assert "reads the list first" not in said
    assert result["stopped"] == 1 and "list_not_read" not in result
    assert "Resume carries on from where it stopped" in said


def test_the_listing_is_noted_before_anything_that_can_go_wrong(tmp_path):
    run = Run(tmp_path, failure_raises=True)
    listing.started(run)
    listing.read_whole(run)
    with pytest.raises(OSError):
        pressing.stop_run(run, list_stop())
    assert listing.last(run) == listing.STOPPED


@pytest.mark.parametrize("mode", ["diagnose", "record"])
def test_diagnose_and_record_take_it_as_any_stop(tmp_path, capsys, mode):
    """Neither downloads, so neither lists anything a download reads again.
    The listing is left as the last download run noted it."""
    run = Run(tmp_path, mode=mode)
    listing.started(run)
    listing.read_whole(run)
    with pytest.raises(SystemExit) as left:
        pressing.stop_run(run, list_stop())
    assert type(left.value) is SystemExit and left.value.code == 0
    assert listing.last(run) == listing.COMPLETE
    assert run.written == []
    assert run.surveys == ([True] if mode == "diagnose" else [])
    assert "reads the list first" not in capsys.readouterr().out
