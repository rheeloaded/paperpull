"""Resume reads the lists before it downloads.

The download chooses a document's row by what the lists the page loaded
said, how many documents each date held and their titles. Discovery reads
them. Resume ran no discovery, so every row that did not name its
document was refused, and the app tells a user to press Resume after a
stopped run (#36, review). These drive the command alone, with its
discovery and its downloads stood in for.

Resume carries on only from a list a run read whole, as every document
app's does (paperpull_core.listing). Its own reading of the lists counts,
so lists read whole here let a Resume after a stopped listing finish clean.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_docs
from paperpull_core import listing


def _app(remaining, tmp_path, known=True, whole_when_read=True):
    app = etrade_docs.App.__new__(etrade_docs.App)
    app.stats = {}
    app.args = SimpleNamespace(dry_run=False)
    app.paths = SimpleNamespace(last_listing=tmp_path / "last-listing.json")
    # What an earlier listing left in discovery.json.
    app.discovery = SimpleNamespace(data={"an earlier listing": {}} if known else {})
    calls: list = []

    def discover(quiet=False):
        calls.append(("discover", quiet))
        listing.started(app)
        if whole_when_read:
            listing.read_whole(app)
    app._select = lambda limit=None: list(remaining)
    app._already_done = lambda doc: False
    app.cmd_discover = discover
    app.process = lambda docs, dry_run=False: calls.append(("process", len(docs)))
    return app, calls


def _doc():
    return etrade_docs.Document(title="Invented Statement", category="Statements",
                                date="2025-10-31")


def test_resume_reads_the_lists_before_it_downloads(tmp_path):
    app, calls = _app([_doc()], tmp_path)
    app.cmd_resume()
    assert calls == [("discover", True), ("process", 1)]


def test_resume_with_nothing_left_touches_nothing(tmp_path):
    app, calls = _app([], tmp_path)
    app.cmd_resume()
    assert calls == []


def test_a_resume_that_reads_the_lists_whole_after_a_stopped_listing_finishes_clean(tmp_path):
    app, calls = _app([_doc()], tmp_path)
    listing.started(app)
    app.cmd_resume()
    assert calls == [("discover", True), ("process", 1)]
    assert listing.last(app) == listing.COMPLETE


def test_a_resume_whose_own_reading_stops_short_stops_too(tmp_path, capsys):
    app, calls = _app([_doc()], tmp_path, whole_when_read=False)
    listing.started(app)
    with pytest.raises(SystemExit):
        app.cmd_resume()
    assert calls == [("discover", True), ("process", 1)]
    assert "ETRADE's list was not read to its end" in " ".join(capsys.readouterr().out.split())


def test_resume_with_nothing_ever_listed_stops_and_reads_nothing(tmp_path, capsys):
    app, calls = _app([], tmp_path, known=False)
    with pytest.raises(SystemExit):
        app.cmd_resume()
    assert calls == []
    assert "No ETRADE documents have been listed yet" in " ".join(capsys.readouterr().out.split())
