"""A control that could be another document's is never pressed for this one.

Review of the second repair of #36 found four ways the download could
still save a neighbor's PDF under this document's name, each reproduced
in a real browser with invented rows.

The page's Download button hands over every ticked document, and the
guard only counted whether more than one box was ticked. When this row's
box would not tick and another document's box was left ticked, the count
was one, Download was pressed and the other document came back.

One row can hold both documents of a date. It was chosen because it
names this document, and then any View or box in it was tried, and the
other document's View or box was as likely to be first as this one's.

An insert whose label starts with the document's title, "<title> PDF
insert", passed for the document's own link.

A date the lists held one document on was taken as this document's even
when that one document had another title.

Everything here is invented. The rows are list items, table rows and
plain divs, the Download button hands over whichever boxes are ticked,
and the tests drive a real browser, since ticking a box and the name a
link is given are what a fake page gets wrong.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site

ACCOUNT = "Invented Brokerage - 4242"
BROKERAGE = "Brokerage Statement"
RETIREMENT = "Retirement Statement"
SHARED = "2025-11-30"
BOTH = {SHARED: {BROKERAGE, RETIREMENT}}
MINE = "2025-10-31"

# Hands over the boxes ticked when it is pressed, the way a list with a
# Download button would.
DOWNLOAD = ("<button type='button' onclick=\"window.handed = Array.from("
            "document.querySelectorAll('input:checked')).map(b => b.dataset.guid).join(',') || 'nothing'\">"
            "Download</button>")


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture(autouse=True)
def nothing_listed(monkeypatch):
    """Each test says what the lists the page loaded held."""
    monkeypatch.setattr(site, "_LISTED", {})
    monkeypatch.setattr(site, "_LISTED_TITLES", {})


def _guid_of(el):
    return el.evaluate("e => (e.closest('[data-guid]') || e.querySelector('[data-guid]') || e).dataset.guid || ''")


@pytest.fixture
def clicks(monkeypatch):
    """Stands in for the catch. Nothing in a row brings a PDF, so every way
    is tried, and each click is remembered by the document it landed on.
    The page's Download reports which boxes it handed over."""
    got: list = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        if label == "Download":
            el.click()
            got.append(("Download", pg.evaluate("window.handed")))
            return True
        got.append((_guid_of(el), label))
        return False
    monkeypatch.setattr(site, "_catch_pdf", fake)
    return got


def _checked(page, guid):
    return page.evaluate("g => document.querySelector('input[data-guid=' + g + ']').checked", guid)


def _run(page, iso, title=BROKERAGE):
    trace: list = []
    got = site._try_every_way(page, Path("."), iso, Path("unused.pdf"), title, trace)
    return got, trace


# --- the row's box and the page's Download ---------------------------------

BOX_ROWS = ("<ul>"
            "<li><span>11/30/25</span> <input type='checkbox' data-guid='g-theirs' %s> <span>" + RETIREMENT + "</span></li>"
            "<li><span>10/31/25</span> <input type='checkbox' data-guid='g-mine' %s> <span>" + BROKERAGE + "</span></li>"
            "</ul>" + DOWNLOAD)


@pytest.mark.parametrize("theirs, mine", [
    ("checked", "disabled"),                   # this box cannot be ticked, another is
    ("", "disabled"),                          # this box cannot be ticked, none is
    ("checked", "onclick='return false'"),     # the click lands and the box stays clear
    ("", "onclick='return false'"),
])
def test_download_is_pressed_only_when_this_documents_box_is_ticked(page, clicks, monkeypatch, theirs, mine):
    """The first repair counted ticked boxes and pressed Download at one,
    the other document's (second review). Here this row's box never ticks,
    so Download must not be pressed at all."""
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    page.set_content(BOX_ROWS % (theirs, mine))
    got, trace = _run(page, MINE)
    assert not got
    assert [c for c in clicks if c[0] == "Download"] == [], clicks
    notes = [t.get("note") for t in trace]
    assert any(n and n.endswith("so Download was not pressed") for n in notes), notes
    assert _checked(page, "g-theirs") is bool(theirs) and _checked(page, "g-mine") is False


@pytest.mark.parametrize("mine, cleared", [("", True), ("checked", False)])
def test_download_hands_over_this_documents_own_box(page, clicks, monkeypatch, mine, cleared):
    """The positive twin. A box this ticked is cleared again afterwards. A
    box that was already ticked, and alone, is not pressed, and is left as
    it was."""
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    page.set_content(BOX_ROWS % ("", mine))
    got, trace = _run(page, MINE)
    assert got and clicks[-1] == ("Download", "g-mine"), clicks
    assert _checked(page, "g-mine") is not cleared
    assert (trace[-1] == {"note": "this document's box was cleared again"}) is cleared


def test_download_is_not_pressed_when_the_ticked_boxes_cannot_be_counted(page, clicks, monkeypatch):
    """A count that failed used to read as nothing ticked."""
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    monkeypatch.setattr(site, "_TICKED_JS", "() => { throw new Error('invented') }")
    page.set_content(BOX_ROWS % ("checked", ""))
    got, trace = _run(page, MINE)
    assert not got and [c for c in clicks if c[0] == "Download"] == []
    assert {"note": "the ticked boxes could not be counted, so Download was not pressed", "ticked": -1} in trace
    assert _checked(page, "g-mine") is False


def test_download_is_not_pressed_when_the_page_has_two(page, clicks, monkeypatch):
    """A Download button in each row means the first one found could be
    another row's. The box is not even ticked."""
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    page.set_content((BOX_ROWS % ("", "")) + DOWNLOAD)
    got, trace = _run(page, MINE)
    assert not got and [c for c in clicks if c[0] == "Download"] == []
    assert {"note": "no single Download button on the page, so none was pressed", "buttons": 2} in trace
    assert _checked(page, "g-mine") is False


class _LateBox:
    """A box whose tick raises and still lands, as a click that times out
    after the page took it would."""

    def __init__(self):
        self.state, self.presses = "clear", 0

    def evaluate(self, _js):
        return self.state

    def click(self, timeout=None):
        self.presses += 1
        self.state = "ticked" if self.state == "clear" else "clear"
        if self.presses == 1:
            raise TimeoutError("invented")


def test_a_tick_that_raised_is_not_trusted_and_is_cleared(page, clicks):
    """The reviewer asked that the tick raise nothing. The page shows one
    ticked box, the count would say one, and Download must still not be
    pressed, and the box that did tick is cleared."""
    page.set_content("<input type='checkbox' data-guid='g-other' checked>" + DOWNLOAD)
    box = _LateBox()
    trace: list = []
    assert not site._tick_and_download(page, box, Path("."), Path("unused.pdf"), trace)
    assert clicks == []
    assert trace[0] == {"note": "checkbox click failed, so Download was not pressed", "error": "TimeoutError"}
    assert box.state == "clear" and box.presses == 2


# --- a row that holds both documents of a date -----------------------------

TWO_BOXES = ("<ul><li><span>11/30/25</span> "
             "<input type='checkbox' data-guid='g-theirs'> <a href='#' data-guid='g-theirs'>" + RETIREMENT + "</a> "
             "<input type='checkbox' data-guid='g-mine'> <a href='#' data-guid='g-mine'>" + BROKERAGE + "</a>"
             "</li></ul>" + DOWNLOAD)

TWO_VIEWS = ("<ul><li><span>11/30/25</span> "
             "<span data-guid='g-mine-title'>" + BROKERAGE + "</span> <a href='#' data-guid='g-mine'>View</a> "
             "<span data-guid='g-theirs-title'>%s</span> <a href='#' data-guid='g-theirs'>View</a>"
             "</li></ul>")


@pytest.mark.parametrize("titles, why", [
    (BOTH, "the row names another document of this date"),
    ({}, "the row holds more than one box"),
])
def test_a_row_with_both_documents_and_a_box_each_ticks_neither(page, clicks, monkeypatch, titles, why):
    """The first repair ticked the row's first box, the other document's,
    and pressed Download (second review). Only this document's own name
    may be pressed."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", titles)
    page.set_content(TWO_BOXES)
    got, trace = _run(page, SHARED)
    assert not got
    assert clicks == [("g-mine", BROKERAGE)], clicks
    assert not _checked(page, "g-mine") and not _checked(page, "g-theirs")
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert row["holds_only_this_document"] is False and row["why_not"] == why
    assert trace[-1] == {"note": "only this document's own name was pressed, since the row may hold another document",
                         "why": why, "names_pressed": 1, "left_alone": 3}


@pytest.mark.parametrize("theirs, titles, why", [
    (RETIREMENT, BOTH, "the row names another document of this date"),
    # The page prints the other title differently from the lists, so only
    # the two Views say the row holds two documents.
    ("Retirement Summary", BOTH, "the row repeats a control"),
    # No list was read, as in a resume, so nothing says what else the date holds.
    (RETIREMENT, {}, "the lists did not say this row holds this document alone"),
])
def test_a_row_with_both_documents_and_a_view_each_presses_only_the_name(page, clicks, monkeypatch,
                                                                         theirs, titles, why):
    """The first repair tried this document's name, then every View in the
    row, and saved the other document's (second review)."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", titles)
    page.set_content(TWO_VIEWS % theirs)
    got, trace = _run(page, SHARED)
    assert not got
    assert [g for g, _label in clicks] == ["g-mine-title"], clicks
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert row["why_not"] == why
    # What goes into download-attempt.json says none of it.
    text = json.dumps(trace)
    for leaked in ("Brokerage", "Retirement", "Summary", "11/30", "g-mine", "g-theirs"):
        assert leaked not in text, (leaked, text)


def test_a_row_of_its_own_on_a_shared_date_may_use_its_view(page, clicks, monkeypatch):
    """The positive twin. Each document of the date has its own row, which
    prints its title and a View. The row naming this document holds it
    alone, so its View is tried, and the other row's never."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", BOTH)
    page.set_content("<ul>"
                     "<li><span>11/30/25</span> <span>%s</span> <a href='#' data-guid='g-theirs'>View</a></li>"
                     "<li><span>11/30/25</span> <span>%s</span> <a href='#' data-guid='g-mine'>View</a></li>"
                     "</ul>" % (RETIREMENT, BROKERAGE))
    got, trace = _run(page, SHARED)
    assert [g for g, _label in clicks] == ["", "g-mine"], clicks
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert row["holds_only_this_document"] is True and "why_not" not in row


def test_a_row_naming_another_document_never_has_that_link_tried(page, clicks, monkeypatch):
    """The row holds this document's View and the other document's own
    link. Neither the View nor that link is tried."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", BOTH)
    page.set_content("<ul><li><span>11/30/25</span> <span data-guid='g-mine-title'>%s</span> "
                     "<a href='#' data-guid='g-mine'>View</a> <a href='#' data-guid='g-theirs'>%s</a></li></ul>"
                     % (BROKERAGE, RETIREMENT))
    got, _trace = _run(page, SHARED)
    assert not got and [g for g, _label in clicks] == ["g-mine-title"], clicks


def test_a_row_with_two_boxes_on_a_date_of_one_document_ticks_neither(page, clicks, monkeypatch):
    """Even where the lists held one document on the date, a row with two
    boxes cannot say which is this document's."""
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    page.set_content("<ul><li><span>10/31/25</span> <input type='checkbox' data-guid='g-other'> "
                     "<input type='checkbox' data-guid='g-mine'> <span>%s</span></li></ul>%s"
                     % (BROKERAGE, DOWNLOAD))
    got, trace = _run(page, MINE)
    assert not got and [c for c in clicks if c[0] == "Download"] == []
    assert not _checked(page, "g-other") and not _checked(page, "g-mine")


def test_a_row_that_prints_another_date_presses_only_the_name(page, clicks, monkeypatch):
    """A list item that prints two dates may hold two documents."""
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    page.set_content("<ul><li><span>10/31/25</span> <span data-guid='g-mine-title'>%s</span> "
                     "<span>09/15/25</span> <a href='#' data-guid='g-other'>View</a></li></ul>" % BROKERAGE)
    got, trace = _run(page, MINE)
    assert not got and [g for g, _label in clicks] == ["g-mine-title"], clicks
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert row["why_not"] == "the row prints another date"


def test_a_table_row_that_prints_another_date_is_not_taken_by_its_date(page, monkeypatch):
    monkeypatch.setattr(site, "_LISTED", {MINE: 1})
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>Posted 09/15/25</td>"
                     "<td><a href='#' data-guid='g-other'>View</a></td></tr></tbody></table>")
    trace: list = []
    assert site._row_link_for(page, MINE, BROKERAGE, trace) == (None, "")
    assert trace[-1]["why"] == "the row prints another date"


# --- an insert named after the document ------------------------------------

def test_an_insert_named_after_the_document_is_never_tried(page, clicks, monkeypatch):
    """"<title> PDF insert" starts the way the document's own link does, so
    it counted as the title (second review)."""
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    page.set_content("<ul><li><span>05/31/25</span> "
                     "<a href='#' data-guid='g-insert' aria-label='%s PDF insert'>Insert</a> "
                     "<a href='#' data-guid='g-doc'>%s</a></li></ul>" % (BROKERAGE, BROKERAGE))
    _run(page, "2025-05-31")
    assert clicks and all(g != "g-insert" for g, _label in clicks), clicks
    assert clicks[0][0] == "g-doc"


def test_a_row_link_named_after_the_document_that_is_an_insert_is_passed_over(page):
    page.set_content("<table><tbody><tr><td>05/31/25</td>"
                     "<td><a href='#' data-guid='g-insert' aria-label='%s PDF insert'>Insert</a></td>"
                     "<td><a href='#' data-guid='g-doc'>%s</a></td></tr></tbody></table>" % (BROKERAGE, BROKERAGE))
    el, label = site._row_link_for(page, "2025-05-31", BROKERAGE, [])
    assert el is not None and _guid_of(el) == "g-doc" and label == BROKERAGE


def test_a_control_named_after_the_document_that_is_an_insert_is_passed_over(page, monkeypatch):
    """The document's own link here is not a control by its words, so the
    insert was the only control that named it, and was taken."""
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    page.set_content("<div><span>05/31/25</span> "
                     "<a href='#' data-guid='g-insert' aria-label='%s PDF insert'>PDF</a> "
                     "<a href='#' data-guid='g-doc'>%s</a></div>" % (BROKERAGE, BROKERAGE))
    el, _name = site._control_for(page, "2025-05-31", BROKERAGE, [])
    assert el is None or _guid_of(el) != "g-insert"


def test_a_document_whose_title_is_an_insert_name_is_still_found(page):
    """The title is taken out before the words are judged, so a document
    listed as "Client Relationship Summary" still gets its own link."""
    title = "Client Relationship Summary"
    page.set_content("<table><tbody><tr><td>05/31/25</td>"
                     "<td><a href='#' data-guid='g-crs' aria-label='%s PDF for %s'>%s</a></td>"
                     "</tr></tbody></table>" % (title, ACCOUNT, title))
    el, label = site._row_link_for(page, "2025-05-31", title, [])
    assert el is not None and _guid_of(el) == "g-crs" and label == title


def test_an_account_named_like_an_insert_does_not_hide_the_document(page, clicks, monkeypatch):
    """The account a link names after "PDF for" is not what the link hands
    over, so the document's own link is still found and still tried."""
    label = "%s PDF for Client Reserve - 4242" % BROKERAGE
    page.set_content("<table><tbody><tr><td>05/31/25</td><td>Client Reserve - 4242</td>"
                     "<td><a href='#' data-guid='g-doc' aria-label='%s'>%s</a></td></tr></tbody></table>"
                     % (label, BROKERAGE))
    el, _label = site._row_link_for(page, "2025-05-31", BROKERAGE, [])
    assert el is not None and _guid_of(el) == "g-doc"
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    _run(page, "2025-05-31")
    assert clicks and clicks[0][0] == "g-doc", clicks


# --- one document on the date, but another one -----------------------------

ONE_VIEW = {"tr": "<table><tbody><tr><td>05/31/25</td><td><a href='#' data-guid='g-other'>View</a></td></tr></tbody></table>",
            "li": "<ul><li><span>05/31/25</span> <a href='#' data-guid='g-other'>View</a></li></ul>",
            "div": "<div><span>05/31/25</span> <a href='#' data-guid='g-other'>View</a></div>"}


def _take(page, shape, clicks):
    if shape == "tr":
        el, _label = site._row_link_for(page, "2025-05-31", BROKERAGE, [])
        return _guid_of(el) if el is not None else ""
    if shape == "div":
        el, _label = site._control_for(page, "2025-05-31", BROKERAGE, [])
        return _guid_of(el) if el is not None else ""
    _run(page, "2025-05-31")
    return clicks[0][0] if clicks else ""


@pytest.mark.parametrize("shape", ["tr", "li", "div"])
@pytest.mark.parametrize("listed, taken", [({"Annual Fee Notice"}, ""), ({BROKERAGE}, "g-other")])
def test_a_date_of_one_document_is_this_documents_only_when_the_titles_agree(page, clicks, monkeypatch,
                                                                            shape, listed, taken):
    """The lists held one document on the date. When that one was another
    title, the only row of the date is not this document's (second
    review), and when it was this title, it is."""
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    monkeypatch.setattr(site, "_LISTED_TITLES", {"2025-05-31": listed})
    page.set_content(ONE_VIEW[shape])
    assert _take(page, shape, clicks) == taken


# --- the address a trace may carry ------------------------------------------

def test_an_address_part_made_of_letters_alone_is_masked_when_it_looks_like_a_token():
    """Only digits were counted, so a token of letters kept its place in
    the trace (second review)."""
    assert site.mask_href("https://us.etrade.com/docs/QkVSVEVORURUT0tFTg/view") == "etrade:/docs/#/view"
    assert site.mask_href("https://us.etrade.com/docs/" + "q" * 35 + "/view") == "etrade:/docs/#/view"
    assert site.mask_href("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems?RequestID=1") == \
        "etrade:/etaz/api/adsal/accountdocs/v2/searchItems?RequestID"
