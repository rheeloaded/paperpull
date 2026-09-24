"""Catching the document, whichever way the provider hands it over.

The property these exist for is the ordering. A document is staged,
checked, and only then moved into place, so a wrong one is deleted
rather than filed. Every other test here is about the interceptor not
being able to make a working provider stop working.

The browser is faked. test_delivery_live.py drives a real one. Both are
needed, because the fakes prove the decisions and only a browser proves
that a download event fires at all.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import delivery as D
from paperpull_core import identity as I

PDF = b"%PDF-1.7\n" + b"x" * 4000
NOT_PDF = b"<html>Your session has expired. Please sign in.</html>" + b" " * 900

# Text a real extraction would find in the document we asked for.
RIGHT = "Order Number 8421997301 January 15, 2026 Total $1,284.55"
WRONG_ONE = "Order Number 8421997999 February 9, 2026 Total $76.41"

EXPECT = I.Identity(date="2026-01-15", total="1284.55", number="8421997301")


# -- fakes ---------------------------------------------------------------------

class FakeDownload:
    def __init__(self, body=PDF):
        self.body = body

    def save_as(self, path):
        Path(path).write_bytes(self.body)


class FakeContext:
    def __init__(self):
        self.handlers = {}

    def on(self, event, fn):
        self.handlers.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        self.handlers.get(event, []).remove(fn)


class FakePage:
    """Enough of a page to arm listeners against and fire once."""

    def __init__(self, url="https://bank.example/documents"):
        self._url = url
        self.context = FakeContext()
        self.handlers = {}
        self.waits = 0

    @property
    def url(self):
        return self._url

    def on(self, event, fn):
        self.handlers.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        self.handlers.get(event, []).remove(fn)

    def wait_for_timeout(self, ms):
        self.waits += 1

    def emit_download(self, download):
        for fn in self.handlers.get("download", []):
            fn(download)


def safe(url):
    return str(url or "").startswith("https://bank.example/")


def patch_text(monkeypatch, text):
    """What pypdf would get out of whatever was staged."""
    monkeypatch.setattr(I, "_text_of", lambda path, pages: text)


def request(**kw):
    kw.setdefault("expect", EXPECT)
    return D.DocumentRequest(**kw)


# -- asking, which needs no trigger and happens first --------------------------

def test_a_url_is_asked_for_before_anything_is_clicked(monkeypatch, tmp_path):
    monkeypatch.setattr(D.capture, "fetch_pdf", lambda p, u, s: PDF)
    patch_text(monkeypatch, RIGHT)
    clicked = []
    out = tmp_path / "doc.pdf"
    got = D.deliver(FakePage(), request(url="https://bank.example/d/1.pdf",
                                        trigger=lambda: clicked.append(1)),
                    out, is_safe_url=safe)
    assert got.ok and got.mechanism == D.ASK
    assert clicked == [], "the trigger fired when asking had already worked"
    assert out.read_bytes() == PDF


def test_when_asking_answers_nothing_the_trigger_still_fires(monkeypatch,
                                                             tmp_path):
    monkeypatch.setattr(D.capture, "fetch_pdf", lambda p, u, s: None)
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    fired = []

    def trigger():
        fired.append(1)
        page.emit_download(FakeDownload())

    got = D.deliver(page, request(url="https://bank.example/d/1.pdf",
                                  trigger=trigger),
                    tmp_path / "doc.pdf", is_safe_url=safe)
    assert fired == [1]
    assert got.ok and got.mechanism == D.DOWNLOAD


# -- the trigger fires exactly once --------------------------------------------

def test_the_trigger_is_never_fired_twice(monkeypatch, tmp_path):
    """Clicking twice on somebody's bank downloads twice, or navigates
    away, or trips a rate limit. Every mechanism is armed before the one
    click instead."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    fired = []
    got = D.deliver(page, request(trigger=lambda: fired.append(1)),
                    tmp_path / "doc.pdf", is_safe_url=safe, settle_ms=500)
    assert fired == [1]
    assert got.outcome == D.NOTHING


def test_everything_is_armed_before_the_trigger(monkeypatch, tmp_path):
    """The listener has to exist before the click, or the event it was
    listening for has already happened."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    seen = {}

    def trigger():
        seen["download"] = len(page.handlers.get("download", []))
        seen["page"] = len(page.context.handlers.get("page", []))
        page.emit_download(FakeDownload())

    D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
              is_safe_url=safe)
    assert seen["download"] == 1
    assert seen["page"] == 1


def test_a_trigger_that_raises_is_reported_not_raised(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("the control went away")

    got = D.deliver(FakePage(), request(trigger=boom), tmp_path / "d.pdf",
                    is_safe_url=safe)
    assert got.outcome == D.NOTHING
    assert not got.ok


# -- the ordering this module exists for ---------------------------------------

def test_a_wrong_document_never_reaches_the_destination(monkeypatch, tmp_path):
    """The whole point. The capture helpers write to the path they are
    given, so if that path were the final one the wrong document would
    be in the archive before anything asked."""
    patch_text(monkeypatch, WRONG_ONE)
    page = FakePage()
    out = tmp_path / "January statement.pdf"
    got = D.deliver(page, request(trigger=lambda: page.emit_download(
        FakeDownload())), out, is_safe_url=safe)
    assert got.outcome == D.WRONG
    assert not got.ok
    assert not out.exists(), "a refused document was written anyway"


def test_and_nothing_is_left_behind_when_it_is_refused(monkeypatch, tmp_path):
    patch_text(monkeypatch, WRONG_ONE)
    page = FakePage()
    out = tmp_path / "doc.pdf"
    D.deliver(page, request(trigger=lambda: page.emit_download(FakeDownload())),
              out, is_safe_url=safe)
    assert list(tmp_path.iterdir()) == [], "a staging file was left on disk"


def test_the_right_document_is_moved_into_place(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    out = tmp_path / "doc.pdf"
    got = D.deliver(page, request(trigger=lambda: page.emit_download(
        FakeDownload())), out, is_safe_url=safe)
    assert got.ok and out.read_bytes() == PDF
    assert [p.name for p in tmp_path.iterdir()] == ["doc.pdf"]


def test_without_strict_a_refused_document_is_written_and_still_reported(
        monkeypatch, tmp_path):
    """For a migration that wants the finding without the refusal yet."""
    patch_text(monkeypatch, WRONG_ONE)
    page = FakePage()
    out = tmp_path / "doc.pdf"
    got = D.deliver(page, request(trigger=lambda: page.emit_download(
        FakeDownload())), out, is_safe_url=safe, strict=False)
    assert out.exists()
    assert got.verdict.outcome == I.REFUSED


def test_an_error_page_with_a_plausible_size_is_refused(monkeypatch, tmp_path):
    """A site answering an expired link with HTML still produces a file."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    out = tmp_path / "doc.pdf"
    got = D.deliver(page, request(trigger=lambda: page.emit_download(
        FakeDownload(NOT_PDF))), out, is_safe_url=safe)
    assert got.outcome == D.NOT_A_PDF
    assert not out.exists()


def test_a_document_with_nothing_to_check_against_is_still_saved(
        monkeypatch, tmp_path):
    """Most providers supply nothing today. Every one of them has to
    keep working exactly as it does."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    out = tmp_path / "doc.pdf"
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.emit_download(FakeDownload())),
        out, is_safe_url=safe)
    assert got.ok
    assert got.verdict.outcome == I.UNCHECKED


# -- reading the race ----------------------------------------------------------

def test_a_new_tab_is_read_when_no_download_fired(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    monkeypatch.setattr(D.capture, "take_new_tab",
                        lambda p, pages, out, s: (Path(out).write_bytes(PDF), True)[1])
    def trigger():
        for fn in page.context.handlers.get("page", []):
            fn(FakePage("https://bank.example/view/1"))
    got = D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
                    is_safe_url=safe)
    assert got.ok and got.mechanism == D.TAB


def test_this_tab_becoming_the_document_is_caught(monkeypatch, tmp_path):
    """PG&E moves the tab itself rather than opening one, and from
    outside that looks exactly like nothing happening."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    monkeypatch.setattr(D.capture, "take_same_tab",
                        lambda p, start, out, tr, s: (Path(out).write_bytes(PDF), True)[1])
    got = D.deliver(page, request(trigger=lambda: None), tmp_path / "d.pdf",
                    is_safe_url=safe, settle_ms=500)
    assert got.ok and got.mechanism == D.TAB


def test_the_watched_folder_is_the_last_resort(monkeypatch, tmp_path):
    """Twelve apps attach to a browser the user launched, where no
    download event ever fires and the browser saves the file itself."""
    patch_text(monkeypatch, RIGHT)
    dl = tmp_path / "dl"
    dl.mkdir()
    page = FakePage()
    monkeypatch.setattr(D.capture, "take_new_pdf",
                        lambda d, before, out: (Path(out).write_bytes(PDF), True)[1])
    def trigger():
        (dl / "statement.pdf").write_bytes(PDF)
    got = D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
                    is_safe_url=safe, dl_dir=dl)
    assert got.ok and got.mechanism == D.FOLDER
    assert D.FOLDER in got.armed


def test_a_hint_moves_a_mechanism_first_and_removes_none():
    assert D._order((D.FOLDER,))[0] == D.FOLDER
    assert set(D._order((D.FOLDER,))) == {D.DOWNLOAD, D.TAB, D.FOLDER}
    assert D._order(()) == [D.DOWNLOAD, D.TAB, D.FOLDER]
    assert D._order(("nonsense",)) == [D.DOWNLOAD, D.TAB, D.FOLDER]


def test_a_wrong_hint_still_finds_the_document(monkeypatch, tmp_path):
    """An app that believes it is folder-first and is wrong still gets
    its document, because a hint reorders and never restricts."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    got = D.deliver(page, request(hints=(D.FOLDER,),
                                  trigger=lambda: page.emit_download(
                                      FakeDownload())),
                    tmp_path / "d.pdf", is_safe_url=safe)
    assert got.ok and got.mechanism == D.DOWNLOAD


# -- it may never take a working run down --------------------------------------

def test_a_page_that_refuses_every_listener_does_not_raise(tmp_path):
    class Hostile:
        url = "https://bank.example/x"

        def on(self, *a, **k):
            raise RuntimeError("no")

        @property
        def context(self):
            raise RuntimeError("no")

        def wait_for_timeout(self, ms):
            raise RuntimeError("no")

    got = D.deliver(Hostile(), request(trigger=lambda: None),
                    tmp_path / "d.pdf", is_safe_url=safe)
    assert got.outcome == D.NOTHING


def test_a_capture_helper_that_raises_is_survived(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("the tab went away")

    monkeypatch.setattr(D.capture, "take_new_tab", boom)
    monkeypatch.setattr(D.capture, "take_same_tab", boom)
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: None), tmp_path / "d.pdf",
                    is_safe_url=safe, settle_ms=500)
    assert got.outcome == D.NOTHING


def test_listeners_are_removed_afterwards(monkeypatch, tmp_path):
    """A run captures hundreds of documents. Leaking a listener per
    document is a slow leak that only shows on a full archive."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    for _ in range(5):
        D.deliver(page, request(trigger=lambda: page.emit_download(
            FakeDownload())), tmp_path / "d.pdf", is_safe_url=safe)
    assert page.handlers.get("download", []) == []
    assert page.context.handlers.get("page", []) == []


def test_the_wait_uses_the_browser_clock_not_a_sleep(monkeypatch, tmp_path):
    """Playwright's sync API dispatches events only while the thread is
    inside a Playwright call. A sleep here means the download listener
    never fires and every provider looks like it answered nothing. This
    has been shipped wrong before."""
    page = FakePage()
    D.deliver(page, request(trigger=lambda: None), tmp_path / "d.pdf",
              is_safe_url=safe, settle_ms=1000)
    assert page.waits > 0, "nothing waited inside a Playwright call"


# -- the guard stays with the app ----------------------------------------------

def test_the_allowlist_is_the_apps_and_is_never_guessed(monkeypatch, tmp_path):
    """Fairfax Water serves from docsight.net and Golden 1 from a
    vendor, so a document is not always on the provider's host and this
    module must not decide which hosts are allowed."""
    seen = []
    monkeypatch.setattr(D.capture, "fetch_pdf",
                        lambda p, u, s: (seen.append(s), None)[1])
    D.deliver(FakePage(), request(url="https://docsight.net/d/1.pdf"),
              tmp_path / "d.pdf", is_safe_url=safe)
    assert seen and seen[0] is safe


# -- what a reader is told -----------------------------------------------------

def test_a_refusal_says_something_is_capturing_the_wrong_document(
        monkeypatch, tmp_path):
    patch_text(monkeypatch, WRONG_ONE)
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: page.emit_download(
        FakeDownload())), tmp_path / "d.pdf", is_safe_url=safe)
    said = " ".join(D.summarize(got.report()))
    assert "wrong document" in said


def test_nothing_arriving_names_what_was_watched(monkeypatch, tmp_path):
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: None), tmp_path / "d.pdf",
                    is_safe_url=safe, settle_ms=500)
    said = " ".join(D.summarize(got.report()))
    assert "nothing came back" in said
    assert "download" in said and "tab" in said


def test_summarizing_something_that_is_not_a_report_is_empty():
    assert D.summarize(None) == []
    assert D.summarize("saved") == []


# -- the canary, because this report travels in a failure file ----------------

def test_no_path_or_url_reaches_the_report(monkeypatch, tmp_path):
    patch_text(monkeypatch, "Order CANARY8421997301 January 15, 2026")
    page = FakePage("https://bank.example/CANARYSESSION")
    out = tmp_path / "CANARYNAME January statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        url="https://bank.example/d/CANARYDOC.pdf",
        expect=I.Identity(number="CANARY8421997301"),
        trigger=lambda: page.emit_download(FakeDownload())),
        out, is_safe_url=safe)
    body = json.dumps(got.report())
    for secret in ("CANARY", "bank.example", str(tmp_path), "statement.pdf"):
        assert secret not in body, secret
    assert got.report()["outcome"] in (D.SAVED, D.WRONG, D.NOTHING)
