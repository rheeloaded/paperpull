"""The failure file says what a capture did, and a capture waits for a
document that is visibly on its way.

His Pilot on 0.37.0 saved three statements and failed on one (#38). The
failure file he attached showed the run stopping on the statements list
after a capture of about 33 seconds, which is the length of a row found,
clicked and waited on for 25 seconds with nothing arriving. What the click
produced is written only to download-attempt.json, which did not come with
it, and the file listed no newrez.com answer after the page loaded, for the
statement that saved as much as for the one that did not. So the failure
file now carries the capture's steps, how long after the click things
happened, what reached the download folder, and a count of every request
the browser made while it waited, wherever it went. All of it is built from
fixed lists, so nothing off the page reaches it.

The statement that saved took about eleven seconds from the click, which
leaves a 25 second budget little room. A document still visibly on its way
when the budget runs out is now waited for. A download an earlier capture
gave up on is let finish before the next row is looked for, nothing is
clicked while one is still growing, and a PDF that lands after such a
download has gone, or beside another new PDF, is not taken, since the
folder cannot say which of them is this document.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import newrez_docs  # noqa: E402
import newrez_site as site  # noqa: E402

LOAN = "1234567"
MONTHLY = f"https://servicing.newrez.com/servicing/{LOAN}/statements/monthly"
PDF_BYTES = b"%PDF-1.4\n" + b"0" * 2000 + b"\n%%EOF\n"

# The network counts a capture like his might write, with invented values,
# and two fields that must never reach the file.
NETWORK = {
    "provider": {"requests": 3, "fetch_requests": 1, "responses_json": 2, "status_2xx": 2,
                 "finished": 3, "pending": 0},
    "elsewhere": {"requests": 9, "document_requests": 1, "fetch_requests": 4,
                  "status_5xx": 1, "failed": 1, "aborted": 1, "pending": 2,
                  "url": "https://docs.example.test/statement?id=998877"},
    "https://docs.example.test": {"requests": 1},
}

# The trace a capture like his writes, with invented values.
TRACE = [
    {"note": "already on the statements page", "page": "/statements/monthly",
     "url": f"/servicing/{LOAN}/statements/monthly"},
    {"note": "found the row", "date": "2026-08-31", "waited_s": 0, "scrolled": False,
     "url": f"/servicing/{LOAN}/statements/monthly", "controls": 18, "visible": 18,
     "dates_read": ["2026-09-30", "2026-09-30", "2026-08-31", "2026-08-31"],
     "same_date": 2, "chosen": "Statement for August 2026", "chosen_visible": True},
    {"note": "waited for an earlier download to finish", "earlier_download_s": 7,
     "left_unfinished": 0},
    {"note": "clicked", "control": "Statement for August 2026"},
    {"status": 200, "type": "application/json", "url": f"https://servicing.newrez.com/api/x?loan={LOAN}"},
    {"note": "after the click", "url": MONTHLY, "appeared": ["Close", "August 2026 statement"],
     "new_tabs": 0},
    {"note": "waited on a document still on its way", "in_flight_s": 45},
    {"note": "no PDF arrived", "url": f"/servicing/{LOAN}/statements/monthly",
     "download_events": 0, "new_tabs": 0, "arrived_unfinished": 1, "arrived_not_pdf": 0,
     "after_click_s": 71, "in_flight_s": 45, "network": NETWORK},
]


def _failure_text(tmp_path, capture) -> str:
    app = object.__new__(newrez_docs.App)
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.stats = {"mode": "pilot"}
    app.write_failure("capture the document", "the document would not render", capture=capture)
    written = list(app.paths.diagnostics.glob("failure-pilot-*.json"))
    assert len(written) == 1
    return written[0].read_text(encoding="utf-8")


def test_the_failure_file_says_what_the_capture_did_and_nothing_off_the_page(tmp_path):
    text = _failure_text(tmp_path, site.capture_facts(TRACE))
    capture = json.loads(text)["extra"]["capture"]
    assert capture["steps"] == ["stayed on the list", "found the row",
                                "waited for an earlier download", "clicked",
                                "looked after the click", "waited on a document on its way",
                                "no pdf arrived"]
    assert capture["list"] == {"waited_s": 0, "controls": 18, "visible": 18, "same_date": 2,
                               "scrolled": False, "chosen_visible": True}
    assert capture["click"] == {"after_click_s": 71, "in_flight_s": 45, "new_tabs": 0,
                                "download_events": 0, "controls_appeared": 2}
    assert capture["download_folder"] == {"arrived_unfinished": 1, "arrived_not_pdf": 0,
                                          "left_unfinished": 0, "earlier_download_s": 7}
    assert capture["network"]["elsewhere"] == {
        "requests": 9, "document_requests": 1, "fetch_requests": 4, "status_5xx": 1,
        "failed": 1, "aborted": 1, "pending": 2}
    assert capture["network"]["provider"]["responses_json"] == 2
    assert set(capture["network"]) == {"provider", "elsewhere"}
    for leak in (LOAN, "August", "2026-08-31", "servicing", "Close", "api", "example",
                 "998877", "docs"):
        assert leak not in text, leak


def test_a_note_that_is_not_text_is_skipped_rather_than_raising():
    """A note that cannot be looked up in the list is not a step. It used
    to raise inside the code that writes the failure file."""
    facts = site.capture_facts([{"note": ["found the row"]}, {"note": {"a": 1}},
                                {"note": "clicked", "how": ["download folder"]}])
    assert facts == {"steps": ["clicked"]}


# -- the network, counted --------------------------------------------------

class _Req:
    """A request made from `page`, the statements tab when it is None."""

    def __init__(self, url, kind, failure=None, page=None):
        self.url, self.resource_type, self.failure = url, kind, failure
        self.frame = SimpleNamespace(page=page)


class _Res:
    def __init__(self, req, status, headers, body=b""):
        self.request, self.url, self.status, self.headers = req, req.url, status, headers
        self._body = body

    def body(self):
        return self._body


def test_every_request_is_counted_by_where_it_went_and_never_described():
    t = site._Traffic()
    api = _Req(f"https://servicing.newrez.com/api/doc?loan={LOAN}", "fetch")
    vendor = _Req("https://docs.example.test/statement.pdf", "document")
    beacon = _Req("https://metrics.example.test/b", "fetch")
    slow = _Req("https://files.example.test/s", "xhr")
    pixel = _Req("https://metrics.example.test/p.gif", "image")
    for r in (api, vendor, beacon, slow, pixel):
        t.on_request(r)
    t.on_response(_Res(api, 500, {"content-type": "application/json"}))
    t.on_finished(api)
    # a request the browser turns into a download
    t.on_response(_Res(vendor, 200, {"content-type": "application/pdf",
                                     "content-disposition": "attachment; filename=x.pdf"}))
    vendor.failure = "net::ERR_ABORTED"
    t.on_failed(vendor)
    # a request made before the capture listened is not the capture's
    before = _Req("https://metrics.example.test/c", "fetch", failure="net::ERR_FAILED")
    t.on_response(_Res(before, 200, {"content-type": "application/pdf"}))
    t.on_failed(before)
    t.on_response(_Res(beacon, 204, {}))
    t.on_finished(pixel)
    facts = t.facts()
    assert facts["provider"] == dict.fromkeys(site._TRAFFIC_COUNTS, 0) | {
        "requests": 1, "fetch_requests": 1, "responses_json": 1, "status_5xx": 1, "finished": 1}
    assert facts["elsewhere"] == dict.fromkeys(site._TRAFFIC_COUNTS, 0) | {
        "requests": 4, "document_requests": 1, "fetch_requests": 2,
        "responses_pdf": 1, "responses_other": 1, "attachments": 1,
        "status_2xx": 2, "finished": 1, "failed": 1, "aborted": 1,
        "pending": 2, "pending_answered": 1}
    assert not t.tracks(before) and t.tracks(api)
    # a call still waiting could be the document
    assert t.in_flight()
    t.on_finished(beacon)
    t.on_finished(slow)
    assert not t.in_flight()
    assert all(isinstance(v, int) for part in t.facts().values() for v in part.values())


def test_an_image_still_loading_is_not_a_document_on_its_way():
    t = site._Traffic()
    t.on_request(_Req("https://metrics.example.test/p.gif", "image"))
    assert not t.in_flight()
    doc = _Req("https://files.example.test/s", "other")
    t.on_request(doc)
    t.on_response(_Res(doc, 200, {"content-type": "application/octet-stream"}))
    assert t.in_flight(), "a file whose body is still coming is on its way"


def test_another_tabs_requests_are_neither_counted_nor_waited_for():
    """His browser is his, and a call another tab keeps open used to keep
    every capture that gave up waiting its full extra time. A request no
    tab can be named for, a service worker's, is not counted either."""
    other = object()
    t = site._Traffic(ignore={other})
    poll = _Req("https://mail.example.test/poll", "fetch", page=other)
    t.on_request(poll)
    t.on_response(_Res(poll, 200, {"content-type": "application/json"}))

    class _Worker:
        url, resource_type, failure = "https://sw.example.test/x", "fetch", None

        @property
        def frame(self):
            raise RuntimeError("a service worker request has no frame")

    t.on_request(_Worker())
    assert not t.in_flight()
    assert not t.tracks(poll)
    assert all(v == 0 for part in t.facts().values() for v in part.values())
    # the statements tab and a tab the click opened are counted
    t.on_request(_Req("https://docs.example.test/s", "fetch"))
    t.on_request(_Req("https://docs.example.test/tab", "document", page=object()))
    assert t.facts()["elsewhere"]["requests"] == 2 and t.in_flight()


# -- a capture against a page whose time is invented ---------------------

class _Clock:
    """Seconds that pass only when the page is asked to wait."""

    def __init__(self):
        self.t = 0.0
        self.due: list = []

    def __call__(self):
        return self.t

    def later(self, seconds, fn):
        self.due.append((self.t + seconds, fn))

    def advance(self, seconds):
        end = self.t + seconds
        while True:
            ready = sorted((d for d in self.due if d[0] <= end), key=lambda d: d[0])
            if not ready:
                break
            self.due.remove(ready[0])
            self.t = max(self.t, ready[0][0])
            ready[0][1]()
        self.t = end


class _Ctx:
    def __init__(self):
        self.pages: list = []
        self.handlers: dict = {}

    def on(self, event, fn):
        self.handlers.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        if fn in self.handlers.get(event, []):
            self.handlers[event].remove(fn)

    def fire(self, event, obj):
        for fn in list(self.handlers.get(event, [])):
            fn(obj)


class _Page:
    """A page whose waits move an invented clock, so a capture that waits a
    minute takes no time at all."""

    def __init__(self, clock):
        self.url = MONTHLY
        self.context = _Ctx()
        self.clock = clock

    def on(self, *a):
        pass

    def remove_listener(self, *a):
        pass

    def wait_for_timeout(self, ms):
        self.clock.advance(ms / 1000)


class _El:
    """A row's control. It is held as itself, reads back the name it was
    approved under, and counts its presses."""

    def __init__(self, on_click, label="Statement for August 2026"):
        self.on_click, self.label = on_click, label
        self.clicks = 0

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def click(self, timeout=0):
        self.clicks += 1
        self.on_click()

    def element_handle(self, timeout=0):
        return self

    def get_attribute(self, name):
        return "javascript:void(0)" if name == "href" else self.label

    def evaluate(self, js, arg=None):
        assert arg is None and "isConnected" in js, "only the name and row are read"
        return [self.label, "", True]


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(site, "_clock", c)
    monkeypatch.setattr(site, "_ABANDONED", {})
    return c


def _landed(trace):
    return [t for t in trace if t.get("note") == "the PDF landed"]


def _bill(monkeypatch, clock, dl, el, out, iso="2026-08-31",
          title="Mortgage Statement - August 31, 2026"):
    """download_bill on a list already open whose row is `el`."""
    monkeypatch.setattr(site, "_open_list", lambda page, path, trace: True)
    monkeypatch.setattr(site, "_wait_for_control", lambda page, iso, trace: (el, el.label))
    trace: list = []
    ok = site.download_bill(_Page(clock), dl, iso, out, title=title, trace=trace)
    return ok, trace


EARLIER = b"%PDF-1.4\nEARLIER" + b"0" * 2000
THIS = b"%PDF-1.4\nTHIS" + b"0" * 2000
DOUBT = "the download folder could not say which download is this one"


def test_a_capture_that_gives_up_counts_what_reached_the_download_folder(tmp_path, clock):
    """A download still being written when the wait ended, and a finished
    file that is not a PDF, are each counted and neither is taken. A
    leftover that was there before the click and is still there is not
    counted as either."""
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "left from before.crdownload").write_bytes(b"")

    def click():
        (dl / "Unconfirmed 1.crdownload").write_bytes(b"%PDF-1.7 part")
        (dl / "statement.html").write_bytes(b"<html>error</html>")

    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(_Page(clock), _El(click), "Download", out, trace, dl) is False
    assert not out.exists()
    gave_up = trace[-1]
    assert gave_up["note"] == "no PDF arrived"
    assert gave_up["arrived_unfinished"] == 1
    assert gave_up["arrived_not_pdf"] == 1
    assert gave_up["earlier_finished"] == 0
    assert gave_up["in_flight_s"] == site.IN_FLIGHT_WAIT_S
    assert gave_up["after_click_s"] == (site.FIRST_WAIT_S + site.LAST_WAIT_S
                                        + site.IN_FLIGHT_WAIT_S)
    facts = site.capture_facts(trace)
    assert facts["steps"] == ["clicked", "looked after the click",
                              "waited on a document on its way", "no pdf arrived"]
    assert facts["download_folder"]["arrived_unfinished"] == 1


def test_a_saved_document_says_how_long_after_the_click_it_landed(tmp_path, clock):
    dl = tmp_path / "dl"
    dl.mkdir()
    page = _Page(clock)
    vendor = _Req("https://docs.example.test/statement", "fetch")

    def click():
        page.context.fire("request", vendor)
        clock.later(4, lambda: page.context.fire("response", _Res(vendor, 200, {"content-type": "application/pdf"})))
        clock.later(4, lambda: page.context.fire("requestfinished", vendor))
        clock.later(4, lambda: (dl / "Monthly Statement.pdf").write_bytes(PDF_BYTES))

    trace = [{"note": "found the row", "waited_s": 3, "controls": 18}]
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(page, _El(click), "Download", out, trace, dl)
    assert out.read_bytes() == PDF_BYTES
    [landed] = _landed(trace)
    assert landed["after_click_s"] == 4
    assert landed["window"] == "first wait" and landed["how"] == "download folder"
    facts = site.landing_facts(trace)
    assert facts["after_click_s"] == 4 and facts["list_waited_s"] == 3
    assert facts["window"] == "first wait" and facts["how"] == "download folder"
    assert facts["network"]["elsewhere"]["responses_pdf"] == 1
    assert facts["network"]["elsewhere"]["finished"] == 1
    # every listener the capture added is gone again
    assert not any(page.context.handlers.values())


def test_a_download_still_being_written_is_waited_for_past_the_budget(tmp_path, clock):
    """Twenty five seconds after the click it is still arriving, and it
    lands at forty. It used to be given up on at twenty five."""
    dl = tmp_path / "dl"
    dl.mkdir()

    def finish():
        (dl / "Unconfirmed 7.crdownload").unlink()
        (dl / "Monthly Statement.pdf").write_bytes(PDF_BYTES)

    def click():
        (dl / "Unconfirmed 7.crdownload").write_bytes(b"%PDF-1.4 part")
        clock.later(40, finish)

    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(_Page(clock), _El(click), "Download", out, trace, dl)
    assert out.read_bytes() == PDF_BYTES
    [landed] = _landed(trace)
    assert landed["window"] == "in flight wait"
    assert landed["after_click_s"] == 40
    assert site.capture_facts(trace)["click"]["in_flight_s"] == 40 - site.FIRST_WAIT_S - site.LAST_WAIT_S


def test_a_request_still_waiting_for_its_answer_is_waited_for(tmp_path, clock):
    """Nothing in the download folder yet, only a request made by the
    click that has not been answered. It is answered at thirty seconds
    with the file, which lands in the folder."""
    dl = tmp_path / "dl"
    dl.mkdir()
    page = _Page(clock)
    vendor = _Req("https://docs.example.test/statement", "fetch")

    def answer():
        page.context.fire("response", _Res(vendor, 200, {"content-type": "application/pdf"}))
        page.context.fire("requestfinished", vendor)
        (dl / "Monthly Statement.pdf").write_bytes(PDF_BYTES)

    def click():
        page.context.fire("request", vendor)
        clock.later(30, answer)

    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(page, _El(click), "Download", out, trace, dl)
    [landed] = _landed(trace)
    assert landed["window"] == "in flight wait" and landed["after_click_s"] == 30


def test_nothing_on_its_way_is_not_waited_for(tmp_path, clock):
    """A click that started nothing gives up when the budget ends, and
    another site's image does not keep it waiting."""
    dl = tmp_path / "dl"
    dl.mkdir()
    page = _Page(clock)

    def click():
        page.context.fire("request", _Req("https://metrics.example.test/p.gif", "image"))

    trace = []
    assert site._catch_pdf(page, _El(click), "Download", tmp_path / "s.pdf", trace, dl) is False
    assert trace[-1]["after_click_s"] == site.FIRST_WAIT_S + site.LAST_WAIT_S
    assert trace[-1]["in_flight_s"] == 0
    assert trace[-1]["network"]["elsewhere"]["pending"] == 1


def test_a_download_an_earlier_capture_left_finishes_before_the_row_is_looked_for(
        tmp_path, clock, monkeypatch):
    """The capture before gave up while its download was still being
    written. It finishes two seconds into this capture, before the row is
    looked for, and so is part of the picture taken before the click. This
    statement's own file arrives three seconds after the click and is the
    one saved."""
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Unconfirmed 5.crdownload").write_bytes(b"%PDF-1.4 earl")

    def earlier_finishes():
        (dl / "Unconfirmed 5.crdownload").unlink()
        (dl / "Monthly Statement.pdf").write_bytes(EARLIER)

    clock.later(2, earlier_finishes)
    el = _El(lambda: clock.later(3, lambda: (dl / "Monthly Statement (1).pdf").write_bytes(THIS)))
    out = tmp_path / "s.pdf"
    ok, trace = _bill(monkeypatch, clock, dl, el, out)
    assert ok and out.read_bytes() == THIS
    assert (dl / "Monthly Statement.pdf").read_bytes() == EARLIER, "the earlier one is left alone"
    waited = [t for t in trace if t.get("note") == "waited for an earlier download to finish"]
    assert waited and waited[0]["earlier_download_s"] == 2 and waited[0]["left_unfinished"] == 0
    # the wait comes before the row is looked for, and nothing sits between
    # the row being found and the press
    assert site.capture_facts(trace)["steps"][:2] == ["waited for an earlier download", "clicked"]


def test_a_pdf_that_lands_after_an_earlier_download_finished_is_not_taken(tmp_path, clock):
    """A download the capture before gave up on stalled, so it was taken as
    abandoned and the click was made. It finishes two seconds after the
    click, under the name every statement gets. It used to be saved as
    this statement. The folder cannot say which download it is, so neither
    file is taken and the statement is asked for again on the next run."""
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Unconfirmed 5.crdownload").write_bytes(b"%PDF-1.4 earl")

    def earlier_finishes():
        (dl / "Unconfirmed 5.crdownload").unlink()
        (dl / "Monthly Statement.pdf").write_bytes(EARLIER)

    def click():
        clock.later(2, earlier_finishes)
        clock.later(3, lambda: (dl / "Monthly Statement (1).pdf").write_bytes(THIS))

    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(_Page(clock), _El(click), "Download", out, trace, dl) is False
    assert not out.exists()
    assert (dl / "Monthly Statement.pdf").read_bytes() == EARLIER, "left where it landed"
    [doubt] = [t for t in trace if t.get("note") == DOUBT]
    assert doubt["earlier_finished"] == 1 and doubt["new_pdfs"] == 1
    assert doubt["after_click_s"] == 2
    facts = site.capture_facts(trace)
    assert facts["steps"][-1] == "folder could not tell which download"
    assert facts["download_folder"] == {"earlier_finished": 1, "new_pdfs": 1}


def test_an_earlier_download_still_growing_means_nothing_is_clicked(tmp_path, clock, monkeypatch):
    """An earlier download is still being written when the thirty second
    wait ends, and finishes two seconds later, before this statement's own
    file would have. The statement is not clicked, so neither can be
    mistaken for the other, and it is left for the next run."""
    dl = tmp_path / "dl"
    dl.mkdir()
    part = dl / "Unconfirmed 6.crdownload"
    part.write_bytes(b"x")
    grows_until = site.EARLIER_WAIT_S + 1
    for s in range(1, grows_until + 1):
        clock.later(s, lambda s=s: part.write_bytes(b"x" * (s + 1)))

    def finish():
        part.unlink()
        (dl / "Monthly Statement.pdf").write_bytes(EARLIER)

    clock.later(grows_until + 1, finish)
    el = _El(lambda: clock.later(3, lambda: (dl / "Monthly Statement (1).pdf").write_bytes(THIS)))
    out = tmp_path / "s.pdf"
    ok, trace = _bill(monkeypatch, clock, dl, el, out)
    assert ok is False and el.clicks == 0 and not out.exists()
    facts = site.capture_facts(trace)
    assert facts["steps"] == ["earlier download still being written"]
    assert facts["download_folder"] == {"earlier_download_s": site.EARLIER_WAIT_S, "left_unfinished": 1}
    clock.advance(10)
    assert (dl / "Monthly Statement.pdf").read_bytes() == EARLIER, "and it is left where it lands"


def test_a_1098_is_not_saved_from_a_download_that_may_be_an_earlier_one(tmp_path, clock, monkeypatch):
    """A 1098 has no date inside to check, so the download folder is the
    only thing that can refuse it. A stalled statement download finishes
    after the 1098's click and is not taken as the 1098."""
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Unconfirmed 8.crdownload").write_bytes(b"%PDF-1.4 stat")

    def earlier_finishes():
        (dl / "Unconfirmed 8.crdownload").unlink()
        (dl / "Monthly Statement.pdf").write_bytes(EARLIER)

    def click():
        clock.later(2, earlier_finishes)
        clock.later(4, lambda: (dl / "Form 1098.pdf").write_bytes(THIS))

    el = _El(click, label="Form 1098 for 2025")
    out = tmp_path / "t.pdf"
    ok, trace = _bill(monkeypatch, clock, dl, el, out, iso="2025-12-31",
                      title="Tax Document - December 31, 2025")
    assert ok is False and el.clicks == 1 and not out.exists()
    steps = site.capture_facts(trace)["steps"]
    assert steps == ["waited for an earlier download", "clicked", "folder could not tell which download"]


def test_two_new_pdfs_at_once_are_neither_taken(tmp_path, clock):
    """Two PDFs landing together cannot be told apart by the folder."""
    dl = tmp_path / "dl"
    dl.mkdir()

    def both():
        (dl / "Monthly Statement.pdf").write_bytes(EARLIER)
        (dl / "Monthly Statement (1).pdf").write_bytes(THIS)

    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(_Page(clock), _El(lambda: clock.later(3, both)), "Download",
                           out, trace, dl) is False
    assert not out.exists()
    [doubt] = [t for t in trace if t.get("note") == DOUBT]
    assert doubt["new_pdfs"] == 2 and doubt["earlier_finished"] == 0


def test_a_leftover_the_browser_kept_is_waited_on_once(tmp_path, clock, monkeypatch):
    """A browser keeps an interrupted download's file so it can resume it.
    Such a leftover used to cost five seconds before every capture. It is
    waited on once, and it is still watched, so the second statement is
    saved without waiting."""
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Unconfirmed 9.crdownload").write_bytes(b"%PDF-1.4 part")
    first = _El(lambda: clock.later(3, lambda: (dl / "Monthly Statement.pdf").write_bytes(THIS)))
    ok, trace = _bill(monkeypatch, clock, dl, first, tmp_path / "a.pdf")
    assert ok
    assert site.capture_facts(trace)["download_folder"]["earlier_download_s"] == site.EARLIER_STILL_S
    second = _El(lambda: clock.later(3, lambda: (dl / "Monthly Statement (1).pdf").write_bytes(EARLIER)),
                 label="Statement for July 2026")
    ok, trace = _bill(monkeypatch, clock, dl, second, tmp_path / "b.pdf", iso="2026-07-31",
                      title="Mortgage Statement - July 31, 2026")
    assert ok and (tmp_path / "b.pdf").read_bytes() == EARLIER
    assert site.capture_facts(trace)["steps"][0] == "clicked"


def test_a_row_that_changes_while_the_press_is_tried_is_not_pressed_through_the_page(tmp_path, clock):
    """A control named only "View" takes its date from its row. The
    ordinary press could not reach it, and while it tried, the row became
    July's. The press through the page is not made."""

    class _Stuck(_El):
        def __init__(self):
            super().__init__(lambda: None, label="View")
            self.row = "August 2026"
            self.through_the_page = 0

        def click(self, timeout=0):
            self.row = "July 2026"
            raise TimeoutError("something lies over it")

        def evaluate(self, js, arg=None):
            if arg is None:
                return [self.label, self.row, True]
            self.through_the_page += 1
            return True

    el = _Stuck()
    trace = []
    assert site._catch_pdf(_Page(clock), el, "View", tmp_path / "s.pdf", trace, tmp_path,
                           check=lambda: site._still_the_one(el, "2026-08-31", "View")) is False
    assert el.through_the_page == 0
    [refused] = [t for t in trace if t.get("note") == "the row changed, so it was not pressed through the DOM"]
    assert refused["why"] == "it no longer carries this date"


def test_a_pdf_another_tab_is_sent_is_not_this_document(tmp_path, clock):
    """A newrez.com PDF that another tab of his browser asks for while this
    capture waits is not this document, and a call that tab keeps open does
    not keep the capture waiting."""
    dl = tmp_path / "dl"
    dl.mkdir()
    page = _Page(clock)
    other = object()
    page.context.pages = [page, other]
    held = _Req("https://mail.example.test/poll", "fetch", page=other)
    pdf = _Req("https://servicing.newrez.com/api/document", "fetch", page=other)

    def click():
        page.context.fire("request", held)
        page.context.fire("request", pdf)
        page.context.fire("response", _Res(pdf, 200, {"content-type": "application/pdf"}, PDF_BYTES))

    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(page, _El(click), "Download", out, trace, dl) is False
    assert not out.exists()
    gave_up = trace[-1]
    assert gave_up["in_flight_s"] == 0
    assert gave_up["network"]["provider"]["requests"] == 0
    assert gave_up["network"]["elsewhere"]["requests"] == 0


# -- the journal line for a saved document --------------------------------

def _one_page_pdf(path: Path) -> None:
    """A blank one page PDF that pypdf opens."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out) + b" " * 4000)


def test_the_journal_says_how_each_saved_document_arrived(tmp_path, monkeypatch):
    """The failure file carries the journal, so a run that saves one and
    fails the next shows how long the good one took. His showed only that
    it was saved."""
    from types import SimpleNamespace
    app = object.__new__(newrez_docs.App)
    app.args = SimpleNamespace(apply=False, redownload=False)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 1000, "owner": ""}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.index_csv = storage.CsvFile(app.paths.document_index_csv, storage.DOCUMENT_INDEX_COLUMNS)
    app._dl_dir = tmp_path / "dl"
    app.stats = {"mode": "pilot", "manual_review": 0, "new_files": [], "dates": [],
                 "statements": 0, "tax_documents": 0, "insurance_documents": 0, "other": 0,
                 "validation_failures": 0, "duplicate_filenames": 0, "failed": 0}
    app.check_session = lambda page: None
    monkeypatch.setattr(newrez_docs.site, "goto_documents", lambda page: True)

    def fake_download(page, dl_dir, iso, out_path, title="", trace=None):
        _one_page_pdf(Path(out_path))
        trace.append({"note": "found the row", "waited_s": 2})
        trace.append({"note": "the PDF landed", "how": "download folder", "window": "last wait",
                      "after_click_s": 12, "network": NETWORK})
        return True

    monkeypatch.setattr(newrez_docs.site, "download_bill", fake_download)
    doc = newrez_docs.Document(title="Tax Document - December 31, 2025",
                               category="Tax Document", summary="Tax Document", date="2025-12-31")
    app.download_one(SimpleNamespace(url=MONTHLY), doc, "2025-12-31 Newrez Tax Document.pdf")
    entries = app.journal.report()["entries"]
    [saved] = [e for e in entries if e.get("outcome") == "saved the document"]
    assert saved["facts"]["after_click_s"] == 12
    assert saved["facts"]["window"] == "last wait"
    assert saved["facts"]["how"] == "download folder"
    assert saved["facts"]["list_waited_s"] == 2
    assert saved["facts"]["network"]["elsewhere"]["pending"] == 2
    assert "example" not in json.dumps(entries)


# -- words -----------------------------------------------------------------

def test_every_step_the_capture_writes_has_public_words():
    """A note that is not in the list is dropped from the file, so a new
    one added to the capture without words here would go missing. And
    words the failure file will not accept would be dropped there."""
    import inspect
    import re
    src = "".join(inspect.getsource(f) for f in (
        site._open_list, site._wait_for_control, site._year_for_row, site.download_bill,
        site._catch_pdf, site._earlier_downloads_settled))
    written = set(re.findall(r'"note": "([^"]+)"', src))
    written |= set(re.findall(r'_note\(trace, "([^"]+)"', src))
    written |= set(re.findall(r'else "([^"]+)"', src))
    assert len(written) >= 30, written
    assert not written - set(site._CAPTURE_STEPS), written - set(site._CAPTURE_STEPS)
    from paperpull_core.failure import _STEP_RE
    for words in list(site._CAPTURE_STEPS.values()) + list(site._CAPTURE_WINDOWS) \
            + list(site._CAPTURE_HOWS) + list(site._CHECK_WHYS) + list(site.STATEMENT_VERDICTS) \
            + list(site._PICKER_STATES) + list(site._PICKER_REFUSALS) + list(site._WALK_OUTCOMES):
        assert _STEP_RE.match(words), words
    # every word a year step or a walk can end on is one of the fixed words
    year_src = inspect.getsource(site._year_picker) + inspect.getsource(site._picker_refusal)
    assert set(re.findall(r'return "([a-z ]+)"\n', year_src)) <= set(site._PICKER_REFUSALS)
    states = set(re.findall(r'out\.state(?:, out\.\w+)? = "([a-z ]+)"', year_src))
    assert states and states <= set(site._PICKER_STATES), states
    assert set(re.findall(r'return "([a-z ]+)", picker\n', inspect.getsource(site._choose_year))) \
        <= set(site._WALK_OUTCOMES) | {"chose", "already chosen"}
    # the words a capture names its wait and its way by are all allowed
    windows = set(re.findall(r'ended\([^,]+, "([^"]+)"\)', src))
    hows = set(re.findall(r'ended\("([^"]+)"', src)) | set(re.findall(r'return "([a-z ]+)"\n', src))
    assert windows and windows <= set(site._CAPTURE_WINDOWS), windows
    assert hows and hows <= set(site._CAPTURE_HOWS), hows
    # and every reason the control is not the one approved is one of the words
    whys = set(re.findall(r'return "([a-z ]+)"\n', inspect.getsource(site._still_the_one)))
    assert whys == set(site._CHECK_WHYS), whys
    # a section of the failure file holds at most twenty fields
    parts = {}
    for name, part in list(site._CAPTURE_COUNTS.items()) + list(site._CAPTURE_FLAGS.items()):
        parts.setdefault(part, []).append(name)
    assert all(len(names) <= 18 for names in parts.values()), parts
    assert len(site._TRAFFIC_COUNTS) <= 20
