"""What a listing notes for Resume, and what Resume does with it.

paperpull_core.listing on its own, with an app that is only an output
folder and a discovery, so each rule can be seen apart from any provider.
Every document app's own Resume, driven through its main after a listing
that stopped, is test_no_resume_is_clean_after_a_list_it_did_not_read.py,
and every receipt app's is
test_no_receipt_resume_is_clean_after_a_list_it_did_not_read.py.
"""
import json
from types import SimpleNamespace

import pytest

from paperpull_core import listing
from paperpull_core.run_reporting import PREFIX, report_run_result


def _app(tmp_path, known=()):
    return SimpleNamespace(
        paths=SimpleNamespace(last_listing=tmp_path / "out" / "last-listing.json"),
        discovery=SimpleNamespace(data={k: {} for k in known}))


def _said(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


# -- what a listing notes ---------------------------------------------------------------

def test_a_listing_is_noted_as_stopped_until_it_is_read_whole(tmp_path):
    app = _app(tmp_path)
    assert listing.last(app) == ""
    listing.started(app)
    assert listing.last(app) == listing.STOPPED
    listing.read_whole(app)
    assert listing.last(app) == listing.COMPLETE
    noted = json.loads(app.paths.last_listing.read_text(encoding="utf-8"))
    assert noted["complete"] is True and noted["at"]


def test_a_listing_that_starts_again_is_stopped_again_until_it_ends(tmp_path):
    """A whole listing before it says nothing about the one running now."""
    app = _app(tmp_path)
    listing.started(app)
    listing.read_whole(app)
    listing.started(app)
    assert listing.last(app) == listing.STOPPED


@pytest.mark.parametrize("body", ["", "not json", "[]", "null", '{"complete": "yes"}', "{}"])
def test_a_note_that_cannot_be_read_is_no_note(tmp_path, body):
    app = _app(tmp_path)
    app.paths.last_listing.parent.mkdir(parents=True)
    app.paths.last_listing.write_text(body, encoding="utf-8")
    assert listing.last(app) == ""


def test_a_note_that_cannot_be_written_never_stops_the_run(tmp_path):
    """The folder it goes in is a file. The listing carries on, and the
    note before it stays as it was."""
    blocker = tmp_path / "out"
    blocker.write_text("a file where the folder would be", encoding="utf-8")
    app = _app(tmp_path)
    listing.started(app)
    listing.read_whole(app)
    assert listing.last(app) == ""


def test_a_note_never_stops_a_listing_whatever_goes_wrong():
    """An app put together without its output folder, as tests that drive
    one part of an app build it."""
    listing.started(SimpleNamespace())
    listing.read_whole(SimpleNamespace(paths=None))


# -- Resume -------------------------------------------------------------------------------

class Process:
    def __init__(self, app=None, reads_whole=False):
        self.handed = []
        self.app, self.reads_whole = app, reads_whole

    def __call__(self, docs):
        self.handed.append(list(docs))
        if self.reads_whole:
            listing.started(self.app)
            listing.read_whole(self.app)


def test_nothing_listed_and_no_listing_read_whole_stops_at_once(tmp_path, capsys):
    app, process = _app(tmp_path), Process()
    with pytest.raises(SystemExit) as stop:
        listing.resume(app, [], process)
    assert stop.value.code == 0 and process.handed == []
    said = _said(capsys)
    assert "Nothing to resume. No Testco documents have been listed yet" in said
    assert "Run Pilot or Run All" in said
    assert "everything in scope is complete" not in said


def test_nothing_listed_after_a_listing_that_stopped_stops_at_once(tmp_path, capsys):
    app, process = _app(tmp_path), Process()
    listing.started(app)
    with pytest.raises(SystemExit):
        listing.resume(app, [], process, noun="statements")
    assert "No Testco statements have been listed yet" in _said(capsys)


def test_a_whole_list_that_held_nothing_is_a_clean_finish(tmp_path, capsys):
    app = _app(tmp_path)
    listing.started(app)
    listing.read_whole(app)
    listing.resume(app, [], Process())
    assert "Nothing to resume - everything in scope is complete." in _said(capsys)


@pytest.mark.parametrize("noted", ["whole", "never"], ids=["read whole", "an install from before"])
def test_everything_done_from_a_whole_list_is_a_clean_finish(tmp_path, capsys, noted):
    app, process = _app(tmp_path, known=["one"]), Process()
    if noted == "whole":
        listing.started(app)
        listing.read_whole(app)
    listing.resume(app, [], process)
    said = _said(capsys)
    assert "Nothing to resume - everything in scope is complete." in said
    assert "stopped before it read" not in said and process.handed == []


def test_everything_known_done_after_a_listing_that_stopped_is_not_finished(tmp_path, capsys):
    app, process = _app(tmp_path, known=["one"]), Process()
    listing.started(app)
    with pytest.raises(SystemExit):
        listing.resume(app, [], process)
    said = _said(capsys)
    assert "The last run stopped before it read Testco's whole list" in said
    assert "Nothing left to resume from the documents listed so far." in said
    assert "This run stops here" in said and process.handed == []
    assert "everything in scope is complete" not in said


def test_what_is_known_is_carried_on_with_and_then_the_run_stops(tmp_path, capsys):
    app, process = _app(tmp_path, known=["one", "two"]), Process()
    listing.started(app)
    with pytest.raises(SystemExit):
        listing.resume(app, ["two"], process)
    assert process.handed == [["two"]]
    said = _said(capsys)
    # Said before anything is taken, and the stop said at the end.
    assert said.index("stopped before it read") < said.index("Resuming: 1 document(s) remaining.")
    assert said.rindex("This run stops here") > said.index("Resuming")


def test_a_resume_that_reads_the_list_whole_itself_finishes_clean(tmp_path, capsys):
    app = _app(tmp_path, known=["one"])
    process = Process(app, reads_whole=True)
    listing.started(app)
    listing.resume(app, ["one"], process)
    assert process.handed == [["one"]]
    assert "This run stops here" not in _said(capsys)


def test_what_is_left_from_a_whole_list_resumes_as_it_always_did(tmp_path, capsys):
    app, process = _app(tmp_path, known=["one"]), Process()
    listing.started(app)
    listing.read_whole(app)
    listing.resume(app, ["one"], process)
    assert process.handed == [["one"]]
    said = _said(capsys)
    assert "Resuming: 1 document(s) remaining." in said and "stopped before" not in said


def test_the_halves_say_first_and_stop_last(tmp_path, capsys):
    """For a Resume that does more than carry on with the list, Anthem's."""
    app = _app(tmp_path, known=["one"])
    listing.started(app)
    assert listing.before_resume(app, "EOBs") is True
    assert "there may be EOBs this app has not seen" in _said(capsys)
    with pytest.raises(SystemExit):
        listing.after_resume(app)
    listing.read_whole(app)
    listing.after_resume(app)
    assert listing.before_resume(app) is False


def test_the_panel_hears_a_run_that_stopped(tmp_path, capsys):
    """Every app writes its result from main's finally, and the stop here is
    the exception in flight there (run_reporting.stopped_early)."""
    app = _app(tmp_path)
    with pytest.raises(SystemExit):
        try:
            listing.resume(app, [], Process())
        finally:
            report_run_result({"new_files": []})
    out = capsys.readouterr().out
    assert json.loads(out.split(PREFIX, 1)[1].splitlines()[0])["stopped"] == 1


# -- a receipt app's Resume, which reads the list again ----------------------------------

def test_a_receipt_resume_reads_the_list_again_after_a_listing_that_stopped(tmp_path, capsys):
    app = _app(tmp_path, known=["one"])
    listing.started(app)
    assert listing.read_again_first(app) is True
    said = _said(capsys)
    assert "The last run did not read Testco's whole list, so Resume reads it" in said
    assert "have been listed yet" not in said


def test_a_receipt_resume_reads_a_list_that_stopped_before_it_found_anything(tmp_path, capsys):
    """Nothing is known, but a listing began and stopped, so the list is
    read, where a new install says that nothing has been listed."""
    app = _app(tmp_path)
    listing.started(app)
    assert listing.read_again_first(app) is True
    assert "have been listed yet" not in _said(capsys)


def test_a_receipt_resume_with_nothing_ever_listed_stops_at_once(tmp_path, capsys):
    app = _app(tmp_path)
    with pytest.raises(SystemExit) as stop:
        listing.read_again_first(app)
    assert stop.value.code == 0
    said = _said(capsys)
    assert "Nothing to resume. No Testco purchases have been listed yet" in said
    assert "Run Pilot or Run All" in said


def test_a_name_that_already_owns_is_not_given_a_second_owner(tmp_path, capsys, monkeypatch):
    """Lowe's list, never Lowe's's list."""
    monkeypatch.setattr(listing, "spec", lambda: SimpleNamespace(provider="Lowe's"))
    app = _app(tmp_path)
    with pytest.raises(SystemExit):
        listing.read_again_first(app)
    listing.started(app)
    listing.read_again_first(app)
    said = _said(capsys)
    assert "no run has read Lowe's list to its end" in said
    assert "did not read Lowe's whole list" in said and "'s's" not in said


@pytest.mark.parametrize("known, noted", [([], "whole"), (["one"], "whole"), (["one"], "never")],
                         ids=["a whole list that held nothing", "a whole list",
                              "an install from before"])
def test_a_receipt_resume_after_a_whole_list_carries_on(tmp_path, capsys, known, noted):
    app = _app(tmp_path, known=known)
    if noted == "whole":
        listing.started(app)
        listing.read_whole(app)
    assert listing.read_again_first(app) is False
    assert _said(capsys) == ""


# -- the mark six receipt apps kept before the note ----------------------------------------

def _old_mark(app):
    mark = app.paths.last_listing.with_name(".discovery-unfinished")
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text("2026-01-20T10:00:00", encoding="utf-8")
    return mark


def test_an_old_mark_and_no_note_is_a_listing_that_stopped(tmp_path):
    """An install whose Discover stopped under a version from before the
    note. Its first Resume reads the list again, as that version's did."""
    app = _app(tmp_path, known=["one"])
    _old_mark(app)
    assert listing.last(app) == listing.STOPPED
    assert listing.read_again_first(app) is True


def test_a_note_says_more_than_an_old_mark(tmp_path):
    app = _app(tmp_path)
    _old_mark(app)
    app.paths.last_listing.write_text('{"complete": true, "at": "2026-01-21T10:00:00"}',
                                      encoding="utf-8")
    assert listing.last(app) == listing.COMPLETE


def test_the_old_mark_goes_once_a_listing_is_noted(tmp_path):
    app = _app(tmp_path)
    mark = _old_mark(app)
    listing.started(app)
    assert not mark.exists()
    listing.read_whole(app)
    assert listing.last(app) == listing.COMPLETE


def test_the_old_mark_stays_when_the_note_cannot_be_written(tmp_path, monkeypatch):
    """The note could not say what the mark said, so the mark still says it."""
    app = _app(tmp_path)
    mark = _old_mark(app)

    def refuse(*_a, **_kw):
        raise OSError("the disk is full")
    monkeypatch.setattr(listing, "atomic_write_json", refuse)
    listing.started(app)
    assert mark.exists() and listing.last(app) == listing.STOPPED
