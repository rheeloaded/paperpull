"""A run's own lines name what the person can press where they are.

Technical details and the live line under a run show what a run prints, and
the panel's buttons are Get new documents, Try the newest few, Check what's
there and Continue. Lines naming Pilot, Run All, Discover and Resume there
send somebody to a button that does not exist on the page. In a terminal
those are the commands, so they stay. The mark the panel gives a run is
what tells the two apart, as run_reporting.not_signed_in has it.
"""
from types import SimpleNamespace

import pytest

from paperpull_core import listing, run_reporting
from paperpull_core.run_reporting import MARK_ENV, report_run_result


def _app(tmp_path, known=()):
    return SimpleNamespace(
        paths=SimpleNamespace(last_listing=tmp_path / "out" / "last-listing.json"),
        discovery=SimpleNamespace(data={k: {} for k in known}))


class Process:
    def __call__(self, remaining):
        self.handed = list(remaining)


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setenv(MARK_ENV, "a" * 32)


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.delenv(MARK_ENV, raising=False)


def _said(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


def test_a_whole_run_goes_by_its_button_under_the_panel(tmp_path, panel, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(listing, "scoped", lambda _a: False)
    assert listing._whole_run(app) == "Get new documents or Try the newest few"
    monkeypatch.setattr(listing, "scoped", lambda _a: True)
    assert listing._whole_run(app) == "Get new documents or Try the newest few, with All dates chosen"


def test_a_whole_run_keeps_its_flags_name_in_a_terminal(tmp_path, terminal, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(listing, "scoped", lambda _a: False)
    assert listing._whole_run(app) == "Pilot or Run All"


def test_nothing_left_says_continue_under_the_panel(tmp_path, capsys, panel):
    app = _app(tmp_path)
    listing.started(app)
    listing.read_whole(app)
    listing.resume(app, [], Process())
    said = _said(capsys)
    assert "Nothing to continue. Everything in these dates is saved." in said
    assert "resume" not in said.lower() and "scope" not in said


def test_carrying_on_says_continue_under_the_panel(tmp_path, capsys, panel):
    app = _app(tmp_path, known=["one", "two"])
    listing.started(app)
    listing.read_whole(app)
    listing.resume(app, ["one"], Process())
    assert "Continuing with 1 document left." in _said(capsys)
    listing.resume(app, ["one", "two"], Process())
    assert "Continuing with 2 documents left." in _said(capsys)


def test_carrying_on_keeps_its_name_in_a_terminal(tmp_path, capsys, terminal):
    app = _app(tmp_path, known=["one"])
    listing.started(app)
    listing.read_whole(app)
    listing.resume(app, ["one"], Process())
    assert "Resuming: 1 document(s) remaining." in _said(capsys)


def _stopped_summary(mode="", whole_run=""):
    """report_run_result as a run on its way out on an exception calls it."""
    try:
        raise run_reporting.ListNotRead(whole_run) if whole_run else RuntimeError("a stop")
    except (run_reporting.ListNotRead, RuntimeError):
        report_run_result({"mode": mode})


def test_a_stopped_run_says_continue_under_the_panel(capsys, panel):
    _stopped_summary()
    said = _said(capsys)
    assert "Continue carries on from where it stopped" in said and "Resume" not in said


def test_a_stopped_run_says_resume_in_a_terminal(capsys, terminal):
    _stopped_summary()
    assert "Resume carries on from where it stopped" in _said(capsys)


def test_a_stopped_check_names_its_own_button_under_the_panel(capsys, panel):
    _stopped_summary(mode="discover")
    said = _said(capsys)
    assert "Check what's there downloads nothing" in said and "Discover" not in said and "Resume" not in said


def test_a_list_not_read_names_the_buttons_under_the_panel(capsys, panel):
    _stopped_summary(whole_run="Get new documents or Try the newest few")
    said = _said(capsys)
    assert "Continue would only stop here again, so run Get new documents or Try the newest few" in said
    assert "Resume" not in said


@pytest.mark.parametrize("n, words", [(1, "1 document was refused, since it was not the one asked for"),
                                      (3, "3 documents were refused, since each was not the one asked for")])
def test_a_refused_document_is_counted_in_words(capsys, n, words):
    report_run_result({"wrong_document": n, "manual_review": n})
    assert words in _said(capsys)
