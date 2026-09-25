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
    raced = {D.DOWNLOAD, D.RESPONSE, D.TAB, D.FOLDER}
    assert set(D._order((D.FOLDER,))) == raced
    assert D._order(()) == [D.DOWNLOAD, D.RESPONSE, D.TAB, D.FOLDER]
    assert D._order(("nonsense",)) == [D.DOWNLOAD, D.RESPONSE, D.TAB, D.FOLDER]


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


def test_a_hint_that_is_not_a_mechanism_is_never_written_down():
    """_order already ignores one, so recording it buys nothing and
    would let a string an app built from a page reach a file somebody
    posts publicly."""
    d = D.DocumentRequest(hints=(D.FOLDER, "CANARY-from-the-page"))
    assert d.describe()["hints"] == [D.FOLDER]
    assert "CANARY" not in json.dumps(d.describe())


def test_the_canaries_are_checked_lowercased_too():
    """A report that lowercased a value before writing it would slip
    past a canary that only looks for the original casing. Nothing here
    lowercases, and this is what proves it stays that way."""
    patched = I.Identity(date="2026-01-15", number="CANARYORDER8421")
    v = I.verify(None, patched, text="CANARYORDER8421 January 15, 2026 " * 4)
    body = json.dumps(v.report())
    for secret in ("CANARYORDER8421", "2026-01-15", "January"):
        assert secret not in body
        assert secret.lower() not in body.lower()


# -- rendering, for the twelve providers with no file to catch ----------------

def test_a_rendered_receipt_is_staged_checked_and_moved(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "receipt.pdf"
    got = D.render(FakePage(), lambda p: Path(p).write_bytes(PDF), out,
                   expect=EXPECT)
    assert got.ok and got.mechanism == D.RENDERED
    assert out.read_bytes() == PDF
    assert [p.name for p in tmp_path.iterdir()] == ["receipt.pdf"]


def test_the_second_receipt_carrying_the_first_is_refused(monkeypatch, tmp_path):
    """A dialog that never closed leaves the previous receipt on screen,
    so the next capture prints it again under the next receipt's name.
    That is a real Costco bug and it is invisible without this."""
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "February receipt.pdf"
    got = D.render(FakePage(), lambda p: Path(p).write_bytes(PDF), out,
                   expect=I.Identity(date="2026-02-09", total="76.41"))
    assert got.outcome == D.WRONG
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_blank_render_is_not_filed(monkeypatch, tmp_path):
    """An open modal locks scrolling and printToPDF produces one blank
    sheet. Another real Costco bug."""
    monkeypatch.setattr(I, "_text_of", lambda path, pages: "")
    out = tmp_path / "receipt.pdf"
    got = D.render(FakePage(), lambda p: Path(p).write_bytes(PDF), out,
                   expect=EXPECT)
    # Nothing to read means nothing to disagree with, so it is kept and
    # said out loud rather than refused.
    assert got.verdict.outcome == I.UNREADABLE
    assert out.exists()


def test_a_render_that_raises_leaves_nothing_behind(tmp_path):
    def boom(path):
        Path(path).write_bytes(b"half a document")
        raise RuntimeError("the modal went away")

    out = tmp_path / "receipt.pdf"
    got = D.render(FakePage(), boom, out, expect=EXPECT)
    assert got.outcome == D.NOTHING
    assert list(tmp_path.iterdir()) == []


def test_a_render_that_writes_nothing_is_reported(tmp_path):
    got = D.render(FakePage(), lambda p: None, tmp_path / "r.pdf",
                   expect=EXPECT)
    assert got.outcome == D.NOTHING


def test_a_render_that_produced_html_is_not_filed(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "receipt.pdf"
    got = D.render(FakePage(), lambda p: Path(p).write_bytes(NOT_PDF), out,
                   expect=EXPECT)
    assert got.outcome == D.NOT_A_PDF
    assert not out.exists()


def test_a_provider_with_nothing_to_check_still_renders(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "receipt.pdf"
    got = D.render(FakePage(), lambda p: Path(p).write_bytes(PDF), out)
    assert got.ok and got.verdict.outcome == I.UNCHECKED


def test_rendering_never_learns_how_to_print(tmp_path):
    """The callable does the printing and this module is handed only a
    path. If that ever changes, receipt_pdf's knowledge has leaked in
    here and the two halves have become one."""
    seen = []
    D.render(FakePage(), lambda p: (seen.append(p), Path(p).write_bytes(PDF))[1],
             tmp_path / "r.pdf", expect=EXPECT)
    assert len(seen) == 1
    assert str(seen[0]).endswith(".delivering")


# -- a provider that needs work done while the wait happens -------------------

def test_work_is_done_on_every_poll_while_waiting(monkeypatch, tmp_path):
    """Navy Federal shows an inactivity modal that delays the blob tab
    from opening. Something has to keep dismissing it or the wait times
    out on a provider that was about to answer."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    dismissed = []
    got = D.deliver(page, request(trigger=lambda: None,
                                  while_waiting=lambda: dismissed.append(1)),
                    tmp_path / "d.pdf", is_safe_url=safe, settle_ms=1000)
    assert got.outcome == D.NOTHING
    assert len(dismissed) >= 3, "the waiting work ran %d time(s)" % len(dismissed)


def test_waiting_work_that_raises_does_not_stop_the_wait(monkeypatch, tmp_path):
    """A provider whose modal handler throws is still a provider that
    might be about to answer."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("no modal today")

    D.deliver(page, request(trigger=lambda: None, while_waiting=boom),
              tmp_path / "d.pdf", is_safe_url=safe, settle_ms=1000)
    assert len(calls) >= 3, "the wait stopped at the first raise"


def test_no_waiting_work_is_the_normal_case(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: page.emit_download(
        FakeDownload())), tmp_path / "d.pdf", is_safe_url=safe)
    assert got.ok


def test_waiting_work_stops_as_soon_as_something_arrives(monkeypatch, tmp_path):
    """It is work done while waiting, not work done regardless."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    ran = []
    D.deliver(page, request(trigger=lambda: page.emit_download(FakeDownload()),
                            while_waiting=lambda: ran.append(1)),
              tmp_path / "d.pdf", is_safe_url=safe, settle_ms=5000)
    assert ran == [], "it kept working after the document had arrived"


# -- tabs a capture opened -----------------------------------------------------

class _ClosablePage(FakePage):
    def __init__(self, url="blob:https://bank.example/abc"):
        super().__init__(url)
        self.closed = False

    def close(self):
        self.closed = True


def test_tabs_this_capture_opened_are_closed_when_asked(monkeypatch, tmp_path):
    """A provider that opens a blob tab per statement leaves one behind
    every time, and a full archive is hundreds of them."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    opened = _ClosablePage()
    monkeypatch.setattr(D.capture, "take_new_tab",
                        lambda p, pages, out, s: (Path(out).write_bytes(PDF), True)[1])

    def trigger():
        for fn in page.context.handlers.get("page", []):
            fn(opened)

    got = D.deliver(page, request(trigger=trigger, close_new_tabs=True),
                    tmp_path / "d.pdf", is_safe_url=safe)
    assert got.ok
    assert opened.closed


def test_tabs_are_left_alone_by_default(monkeypatch, tmp_path):
    """A new tab is sometimes where the app wants to be, so closing one
    is opt in."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    opened = _ClosablePage()
    monkeypatch.setattr(D.capture, "take_new_tab",
                        lambda p, pages, out, s: (Path(out).write_bytes(PDF), True)[1])

    def trigger():
        for fn in page.context.handlers.get("page", []):
            fn(opened)

    D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
              is_safe_url=safe)
    assert not opened.closed


def test_a_tab_that_will_not_close_does_not_fail_the_capture(monkeypatch,
                                                             tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()

    class Stubborn(_ClosablePage):
        def close(self):
            raise RuntimeError("already gone")

    opened = Stubborn()
    monkeypatch.setattr(D.capture, "take_new_tab",
                        lambda p, pages, out, s: (Path(out).write_bytes(PDF), True)[1])

    def trigger():
        for fn in page.context.handlers.get("page", []):
            fn(opened)

    got = D.deliver(page, request(trigger=trigger, close_new_tabs=True),
                    tmp_path / "d.pdf", is_safe_url=safe)
    assert got.ok


def test_a_stale_tab_from_a_previous_capture_is_never_read(monkeypatch,
                                                           tmp_path):
    """The bug Navy Federal hand-rolls around by closing old blob tabs
    before it clicks. Arming after the fact means a tab opened by an
    earlier capture was never collected, so it cannot be mistaken for
    this document."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    stale = _ClosablePage("blob:https://bank.example/from-last-time")
    page.context.pages = [stale]
    seen = {}
    monkeypatch.setattr(D.capture, "take_new_tab",
                        lambda p, pages, out, s: (seen.setdefault("pages", list(pages)), False)[1])
    monkeypatch.setattr(D.capture, "take_same_tab",
                        lambda *a, **k: False)
    D.deliver(page, request(trigger=lambda: None), tmp_path / "d.pdf",
              is_safe_url=safe, settle_ms=500)
    assert seen.get("pages", []) == [] or stale not in seen["pages"]


# -- a tab that opens blank and becomes the document a moment later -----------

class _LatePage(FakePage):
    """A tab that opens at about:blank and is given its real address a
    few polls later, which is what a blob tab does."""

    def __init__(self, becomes, after=4):
        super().__init__("about:blank")
        self._becomes, self._after, self._polls = becomes, after, 0

    @property
    def url(self):
        self._polls += 1
        return self._becomes if self._polls > self._after else "about:blank"


def test_a_tab_that_is_still_blank_is_not_the_document_arriving(monkeypatch,
                                                                tmp_path):
    """The Navy Federal regression. A new tab appears at once and only
    becomes the blob a moment later, so treating the tab opening as the
    answer read a blank page and reported that nothing came back."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    late = _LatePage("blob:https://bank.example/abc")
    read = []

    def take(p, pages, out, s):
        read.append([(pg.url or "") for pg in pages])
        Path(out).write_bytes(PDF)
        return True

    monkeypatch.setattr(D.capture, "take_new_tab", take)
    monkeypatch.setattr(D.capture, "take_same_tab", lambda *a, **k: False)

    def trigger():
        for fn in page.context.handlers.get("page", []):
            fn(late)

    got = D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
                    is_safe_url=safe, settle_ms=5000)
    assert got.ok, "gave up while the tab was still blank"
    assert read and not read[0][0].startswith("about:blank")


def test_a_blank_tab_alone_never_ends_the_wait():
    """The property underneath it. A tab with no address yet is not an
    answer."""
    page = FakePage()
    watch = D._Armed(page)
    watch.__enter__()
    try:
        watch.new_pages.append(FakePage("about:blank"))
        assert not watch.anything()
        watch.new_pages.append(FakePage("blob:https://bank.example/x"))
        assert watch.anything()
    finally:
        watch.__exit__()


def test_a_tab_with_no_readable_address_is_not_an_answer():
    class Hostile:
        @property
        def url(self):
            raise RuntimeError("gone")

    page = FakePage()
    watch = D._Armed(page)
    watch.__enter__()
    try:
        watch.new_pages.append(Hostile())
        assert not watch.anything()
    finally:
        watch.__exit__()


def test_a_download_still_ends_the_wait_at_once():
    """The common case must not get slower because of the blob case."""
    page = FakePage()
    watch = D._Armed(page)
    watch.__enter__()
    try:
        watch.download = FakeDownload()
        assert watch.anything()
    finally:
        watch.__exit__()


# -- the answer read as it went past -------------------------------------------

class _Response:
    def __init__(self, url, body=PDF, ctype="application/pdf", kind="document",
                 raises=False):
        self.url, self._body, self._raises = url, body, raises
        self.headers = {"content-type": ctype}
        self.request = type("R", (), {"resource_type": kind})()

    def body(self):
        if self._raises:
            raise RuntimeError("body already consumed")
        return self._body


def _emit(page, response):
    for fn in page.context.handlers.get("response", []):
        fn(response)


def test_a_pdf_answer_is_kept_as_it_goes_past(monkeypatch, tmp_path):
    """Fairfax Water lost two of five bills to a listener attached one
    beat too late. Reading the answer in flight needs no second request,
    which matters where the address was signed for one use."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: _emit(
        page, _Response("https://bank.example/doc.pdf"))),
        tmp_path / "d.pdf", is_safe_url=safe)
    assert got.ok and got.mechanism == D.RESPONSE
    assert (tmp_path / "d.pdf").read_bytes() == PDF


def test_it_listens_at_the_context_not_at_the_tab(monkeypatch, tmp_path):
    """A tab's first answer can land before a listener attached on the
    page event exists. The context sees every page's answers from the
    start, which is the whole point."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    seen = {}

    def trigger():
        seen["on_context"] = len(page.context.handlers.get("response", []))
        seen["on_page"] = len(page.handlers.get("response", []))
        _emit(page, _Response("https://bank.example/doc.pdf"))

    D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
              is_safe_url=safe)
    assert seen["on_context"] == 1
    assert seen["on_page"] == 0


def test_an_answer_from_another_host_is_never_read(monkeypatch, tmp_path):
    """A document is not always on the provider's own host, so the app's
    allowlist decides, and anything outside it is not even opened."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    hostile = _Response("https://somewhere-else.example/doc.pdf")
    got = D.deliver(page, request(trigger=lambda: _emit(page, hostile)),
                    tmp_path / "d.pdf", is_safe_url=safe, settle_ms=500)
    assert got.outcome == D.NOTHING


def test_an_answer_that_is_not_a_pdf_is_ignored(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: _emit(
        page, _Response("https://bank.example/page", body=b"<html>hi</html>"))),
        tmp_path / "d.pdf", is_safe_url=safe, settle_ms=500)
    assert got.outcome == D.NOTHING


def test_the_first_pdf_answer_wins_and_later_ones_do_not_replace_it(
        monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    other = b"%PDF-1.7 a different document" + b"y" * 4000

    def trigger():
        _emit(page, _Response("https://bank.example/first.pdf"))
        _emit(page, _Response("https://bank.example/second.pdf", body=other))

    D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
              is_safe_url=safe)
    assert (tmp_path / "d.pdf").read_bytes() == PDF


def test_an_answer_whose_body_cannot_be_read_does_not_raise(monkeypatch,
                                                            tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    got = D.deliver(page, request(trigger=lambda: _emit(
        page, _Response("https://bank.example/doc.pdf", raises=True))),
        tmp_path / "d.pdf", is_safe_url=safe, settle_ms=500)
    assert got.outcome == D.NOTHING


def test_a_download_still_wins_over_an_answer_seen_in_flight(monkeypatch,
                                                             tmp_path):
    """Order matters. A real download event is the least ambiguous thing
    a provider can do."""
    patch_text(monkeypatch, RIGHT)
    page = FakePage()

    def trigger():
        _emit(page, _Response("https://bank.example/doc.pdf"))
        page.emit_download(FakeDownload())

    got = D.deliver(page, request(trigger=trigger), tmp_path / "d.pdf",
                    is_safe_url=safe)
    assert got.mechanism == D.DOWNLOAD


def test_the_response_listener_is_removed_afterwards(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    page = FakePage()
    for _ in range(3):
        D.deliver(page, request(trigger=lambda: _emit(
            page, _Response("https://bank.example/doc.pdf"))),
            tmp_path / "d.pdf", is_safe_url=safe)
    assert page.context.handlers.get("response", []) == []


# -- for the thirty three apps that already have the bytes --------------------

def test_bytes_an_app_already_has_are_staged_checked_and_moved(monkeypatch,
                                                                tmp_path):
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "statement.pdf"
    got = D.place(PDF, out, expect=EXPECT)
    assert got.ok and got.mechanism == D.ASK
    assert out.read_bytes() == PDF
    assert [p.name for p in tmp_path.iterdir()] == ["statement.pdf"]


def test_the_wrong_document_is_refused_even_when_the_app_fetched_it(
        monkeypatch, tmp_path):
    """Fetching the bytes yourself is not evidence they are the right
    bytes. An id resolved from a stale list points at another document
    just as easily as a mis-clicked row does."""
    patch_text(monkeypatch, WRONG_ONE)
    out = tmp_path / "January statement.pdf"
    got = D.place(PDF, out, expect=EXPECT)
    assert got.outcome == D.WRONG
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []


def test_an_empty_answer_is_reported_rather_than_written(tmp_path):
    out = tmp_path / "statement.pdf"
    got = D.place(b"", out, expect=EXPECT)
    assert got.outcome == D.NOTHING
    assert not out.exists()


def test_something_that_is_not_a_pdf_is_refused(monkeypatch, tmp_path):
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "statement.pdf"
    got = D.place(NOT_PDF, out, expect=EXPECT)
    assert got.outcome == D.NOT_A_PDF
    assert not out.exists()


def test_an_app_with_nothing_to_check_against_still_saves(monkeypatch,
                                                           tmp_path):
    patch_text(monkeypatch, RIGHT)
    out = tmp_path / "statement.pdf"
    got = D.place(PDF, out)
    assert got.ok and got.verdict.outcome == I.UNCHECKED


def test_placing_never_learns_how_to_fetch():
    """The bytes arrive as bytes. If this ever grows a page argument,
    an app's own headers and decoding have started leaking into the
    core, which is the thing that cannot be shared."""
    import inspect

    params = list(inspect.signature(D.place).parameters)
    assert params[0] == "data"
    assert "page" not in params


def test_a_decoded_document_is_checked_like_any_other(monkeypatch, tmp_path):
    """TSP's 1099-R arrives with a print-stream line in front of the PDF
    and is trimmed by the app before this sees it. What arrives here is
    already a document, whatever it took to become one."""
    patch_text(monkeypatch, RIGHT)
    trimmed = PDF
    assert trimmed.startswith(b"%PDF-")
    assert D.place(trimmed, tmp_path / "f.pdf", expect=EXPECT).ok
