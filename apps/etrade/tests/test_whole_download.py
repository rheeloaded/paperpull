"""Nothing but the document itself is saved under its name, run end to end.

Review of the fifth repair of #36 reproduced four more ways a notice, an
insert or the other document of a date could be pressed and saved as the
document, and two of them ran before the row walk ever looked. A saved
document is marked complete and never tried again, so each one would have
stayed wrong.

The one control of a date that is not a plain View or Download was taken
whenever the lists held one document that day. A "Privacy Notice PDF" link
beside the statement's own link, or beside its title printed as text, was
pressed and saved as the statement.

The row walk read the title as printed only when an element's whole words
were the title, while the row link step reads it anywhere in the row. A
row printing "<title> - October" beside a lone notice link was taken to
print nothing, and the notice was pressed.

A container whose cursor says it is clickable was pressed on its middle
whatever sat inside it, and an insert's View sat there.

A filter chip printing the date counted as a row of that date, so a row
holding this document and the other document's Download passed for a row
holding this document alone.

The same review asked that anything pressed as the document hold nothing
else a press could land on, on every path. A role=button card or a
role=link element can wrap a notice's link, and a press on its middle
lands on whatever is there. Testing that found the mirror case. A span
inside a link was judged on its own words, a bare View or the title,
while a press on it presses the link, an insert's or a notice's.

Everything here is invented. Every test goes through download_bill, the
way a run does, in a real browser, and each page records where every click
truly landed, in the capture phase before any handler runs.
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
ALONE = "2025-10-31"

# Where each click landed, by the data-guid around its target, recorded in
# the capture phase before any handler on the page runs.
LISTENER = ("<script>window.hits = [];"
            "document.addEventListener('click', e => { const g = e.target.closest('[data-guid]');"
            " window.hits.push(g ? g.dataset.guid : e.target.tagName.toLowerCase());"
            " if (!g || g.tagName.toLowerCase() !== 'input') e.preventDefault(); }, true);</script>")


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
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)


def _listed(monkeypatch, iso, titles):
    monkeypatch.setattr(site, "_LISTED", {iso: len(titles)})
    monkeypatch.setattr(site, "_LISTED_TITLES", {iso: set(titles)})


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Stands in for the catch. It presses the element the way the real
    catch does, a click on its middle, and remembers where the press
    landed. A press that lands on a guid in `brings` hands over that
    guid's PDF, written where the download asked for it, so a document
    counts as saved only when a file is there."""
    hits: list = []
    brings: set = set()

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        before = len(pg.evaluate("window.hits"))
        try:
            el.click(timeout=3000)
        except Exception as e:
            hits.append("click failed " + type(e).__name__)
            return False
        landed = pg.evaluate("window.hits")[before:]
        hits.extend(landed)
        handed = [h for h in landed if h in brings]
        if handed:
            Path(out_path).write_bytes(b"%PDF-1.4\n% invented " + handed[0].encode() + b"\n%%EOF\n")
            return True
        return False
    monkeypatch.setattr(site, "_catch_pdf", fake)

    def download(page, iso, title=BROKERAGE):
        out = tmp_path / "Statements" / "document.pdf"
        trace: list = []
        got = site.download_bill(page, tmp_path / "dl", iso, out, title, trace)
        return got, out, trace
    return hits, brings, download


def _refusals(trace):
    return [(t["way"], t["why"]) for t in trace if t.get("note", "").startswith("not sure which")]


def _says_nothing_the_page_said(trace):
    text = json.dumps(trace)
    for leaked in ("Brokerage", "Privacy", "Notice", "October", "Invented", "4242", "g-"):
        assert leaked not in text, (leaked, text)


# --- the one control of a date --------------------------------------------

def test_a_notice_pdf_beside_the_documents_own_link_is_never_saved(page, run, monkeypatch):
    """His row shape, a table row. The document's own link reads its title
    and nothing that makes it a document control by its words, and a notice
    link beside it says "Privacy Notice PDF", which does. When the
    document's own link brought nothing, the notice was the one control of
    the date and was pressed and saved as the statement (review, R1)."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>%s</td>"
                     "<td><a href='#' data-guid='g-mine'>%s</a></td>"
                     "<td><a href='#' data-guid='g-notice'>Privacy Notice PDF</a></td>"
                     "</tr></tbody></table>%s" % (ACCOUNT, BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, out, trace = download(page, ALONE)
    assert "g-notice" not in hits, hits
    assert not got and not out.exists()
    assert hits and set(hits) == {"g-mine"}, hits
    assert ("control", "the one control of this date may be for something else") in _refusals(trace), trace
    _says_nothing_the_page_said(trace)


@pytest.mark.parametrize("shape", ["li", "div"])
def test_a_notice_pdf_beside_the_title_printed_as_text_is_never_saved(page, run, monkeypatch, shape):
    """The title is printed as plain text and the notice is the only
    control with "PDF" in it. The one control step pressed it before the
    row walk, which would have refused it, ever looked (review, R2)."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    tag, outer = ("li", "ul") if shape == "li" else ("div", "div")
    page.set_content("<%s><%s><span>10/31/25</span> <span data-guid='g-title'>%s</span> "
                     "<a href='#' data-guid='g-notice'>Privacy Notice PDF</a></%s></%s>%s"
                     % (outer, tag, BROKERAGE, tag, outer, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, out, trace = download(page, ALONE)
    assert "g-notice" not in hits, hits
    assert not got and not out.exists()
    assert hits == ["g-title"], hits
    _says_nothing_the_page_said(trace)


@pytest.mark.parametrize("beside, pressed", [("", ["g-doc"]),
                                             ("<a href='#' data-guid='g-notice'>Privacy Notice</a>", [])],
                         ids=["alone", "beside a notice"])
def test_the_one_control_of_a_row_that_names_nothing_is_taken_only_alone(page, run, monkeypatch,
                                                                         beside, pressed):
    """The positive twin. The row prints neither the title nor any other
    name for it, and its one control is "Statement PDF", the document's
    own link under another name, so it is still taken. With a notice
    beside it either could be the document's, so neither is pressed."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<div id='rows'><div class='doc'><span>10/31/25</span> <span>%s</span> "
                     "<a href='#' data-guid='g-doc'>Statement PDF</a> %s</div></div>%s"
                     % (ACCOUNT, beside, LISTENER))
    hits, brings, download = run
    brings.update({"g-doc", "g-notice"})
    got, out, trace = download(page, ALONE)
    assert hits == pressed, hits
    assert got is bool(pressed) and out.exists() is bool(pressed)
    _says_nothing_the_page_said(trace)


# --- the title printed inside longer words ---------------------------------

def test_a_row_that_prints_the_title_inside_longer_words_keeps_its_notice_unpressed(page, run, monkeypatch):
    """The row prints "<title> - October", so it prints the title, and its
    one link is a notice. The row link step reads the title anywhere in the
    row, the row walk read it only as an element's whole words, took the
    row to print nothing and pressed the notice as the document's link
    under another name (review, R7)."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <span>%s - October</span> "
                     "<a href='#' data-guid='g-notice'>Privacy Notice</a></li></ul>%s" % (BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, out, trace = download(page, ALONE)
    assert hits == [], hits
    assert not got and not out.exists()
    assert {"note": "nothing in the row may be pressed for this document", "left_alone": 1} in trace, trace
    _says_nothing_the_page_said(trace)


# --- a clickable container -------------------------------------------------

def test_a_clickable_container_over_an_insert_is_never_pressed(page, run, monkeypatch):
    """A container whose cursor starts here holds this document's View and
    an insert's, marked as an insert only by its label. The container read
    "View View", a bare action, and a press on its middle landed on the
    insert, which was saved as the statement (review, R3)."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <span data-guid='g-title'>%s</span> "
                     "<div style='cursor:pointer;display:inline-block;text-align:center'>"
                     "<span data-guid='g-view'>View</span><br>"
                     "<a href='#' data-guid='g-insert' aria-label='View insert' "
                     "style='display:inline-block;padding:20px 60px'>View</a></div></li></ul>%s"
                     % (BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-insert")
    got, out, trace = download(page, ALONE)
    assert "g-insert" not in hits, hits
    assert not got and not out.exists()
    assert hits == ["g-title", "g-view"], hits
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert [c for c in row["candidates"] if c.get("holds_another")] == \
        [{"kind": "pointer", "insert": False, "left_out": True, "holds_another": True,
          "inside_another": False}], row
    _says_nothing_the_page_said(trace)


# --- something inside a link is that link ----------------------------------

@pytest.mark.parametrize("link", [
    # a span reading View inside a link labeled as an insert
    "<a href='#' data-guid='g-insert' aria-label='View insert'><span>View</span></a>",
    # the title in a span inside a link labeled as an insert
    "<a href='#' data-guid='g-insert' aria-label='%s insert'><span>%s</span></a>" % (BROKERAGE, BROKERAGE),
    # the title in a span inside a link that runs on past it to a notice
    "<a href='#' data-guid='g-insert'><span>%s</span> PDF Privacy Notice</a>" % BROKERAGE,
], ids=["view in an insert", "title in an insert", "title in a notice"])
def test_what_sits_inside_an_insert_or_notice_link_is_never_pressed(page, run, monkeypatch, link):
    """A press on anything inside a link is a press on that link. The row
    walk took a span inside a link as a candidate of its own and judged it
    on the span's words alone, a bare View or the title, so a press on it
    handed over the insert or the notice the link around it stood for."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <span data-guid='g-title'>%s</span> %s</li></ul>%s"
                     % (BROKERAGE, link, LISTENER))
    hits, brings, download = run
    brings.add("g-insert")
    got, out, trace = download(page, ALONE)
    assert "g-insert" not in hits, hits
    assert not got and not out.exists()
    assert hits == ["g-title"], hits
    _says_nothing_the_page_said(trace)


def test_the_title_inside_the_documents_own_link_is_still_pressed(page, run, monkeypatch):
    """The positive twin. The title in a span inside the document's own
    link, which names the document by its label, presses that link."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <a href='#' data-guid='g-mine' aria-label='%s PDF for %s'>"
                     "<span>%s</span></a></li></ul>%s" % (BROKERAGE, ACCOUNT, BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-mine")
    got, out, trace = download(page, ALONE)
    assert got and b"g-mine" in out.read_bytes()
    assert hits == ["g-mine"], hits


# --- how many rows carry the date -------------------------------------------

CHIP = "<ul class='chips'><li><span>11/30/25</span></li></ul>"
# A row of the date that is none of the listed documents, a notice with a
# View of its own.
NOTICE_ROW = ("<ul><li><span>11/30/25</span> <span>Privacy Notice</span> "
              "<a href='#' data-guid='g-notice'>View</a></li></ul>")


def _doc_row(guid, title, button):
    return ("<tr><td>11/30/25</td><td><a href='#' data-guid='%s'>%s</a></td>"
            "<td><button data-guid='%s'>Download statement</button></td></tr>" % (guid, title, button))


@pytest.mark.parametrize("beside", [CHIP, NOTICE_ROW], ids=["chip", "notice row"])
def test_a_chip_that_prints_the_date_does_not_make_a_shared_row_look_alone(page, run, monkeypatch, beside):
    """The lists held two documents on the date and one row carries this
    document's link beside a Download that could be the other's. A filter
    chip printing the date counted as a second row, so the row passed for
    one holding this document alone and its Download was pressed and
    saved (review, R6). A notice row of the same date with its own View
    is not one of the listed documents either."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content(beside + "<table><tbody>%s</tbody></table>%s"
                     % (_doc_row("g-mine", BROKERAGE, "g-theirs"), LISTENER))
    hits, brings, download = run
    brings.add("g-theirs")
    got, out, trace = download(page, SHARED)
    assert "g-theirs" not in hits, hits
    assert not got and not out.exists()
    assert hits and set(hits) == {"g-mine"}, hits
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert row["why_not"] == "fewer rows carry this date than the lists held documents"
    assert (row["carrying_the_date"], row["rows_with_a_document_control"]) == (2, 1), row
    _says_nothing_the_page_said(trace)


def test_a_chip_does_not_stop_a_row_of_its_own_from_using_its_download(page, run, monkeypatch):
    """The positive twin. Each document of the date has a row of its own,
    so the row naming this document holds it alone, chip or no chip, and
    its Download is used when its own link brings nothing."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content(CHIP + "<table><tbody>%s%s</tbody></table>%s"
                     % (_doc_row("g-theirs", RETIREMENT, "g-theirs-download"),
                        _doc_row("g-mine", BROKERAGE, "g-mine-download"), LISTENER))
    hits, brings, download = run
    brings.update({"g-mine-download", "g-theirs-download"})
    got, out, trace = download(page, SHARED)
    assert got and b"g-mine-download" in out.read_bytes()
    assert "g-theirs" not in hits and "g-theirs-download" not in hits, hits
    assert hits[-1] == "g-mine-download", hits
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert row["holds_only_this_document"] is True and row["rows_with_a_document_control"] == 2


# --- anything pressed as the document holds nothing else --------------------

def test_a_named_control_holding_a_notice_is_never_pressed_whole(page, run, monkeypatch):
    """A card named for the document, a role=button element, wraps a
    notice's icon link. The one control step took the card as the named
    control and a press on its middle landed on the notice."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<div id='rows'><div class='doc'><span>10/31/25</span> "
                     "<div role='button' tabindex='0' data-guid='g-card' aria-label='%s PDF' "
                     "style='display:inline-block;text-align:center'>%s<br>"
                     "<a href='#' data-guid='g-notice' aria-label='Privacy Notice' "
                     "style='display:inline-block;width:160px;height:60px'></a></div></div></div>%s"
                     % (BROKERAGE, BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, out, trace = download(page, ALONE)
    assert "g-notice" not in hits, hits
    assert not got and not out.exists()
    assert ("control", "the control holds something else that could be pressed") in _refusals(trace), trace
    _says_nothing_the_page_said(trace)


def test_a_named_row_link_holding_a_notice_is_never_pressed_whole(page, run, monkeypatch):
    """His row shape with the document's link drawn as a role=link element
    that wraps a notice's link. The row link step took it by its name, and
    a press on its middle landed on the notice."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>%s</td><td>"
                     "<div role='link' tabindex='0' data-guid='g-mine' aria-label='%s PDF for %s' "
                     "style='display:inline-block;text-align:center'>%s<br>"
                     "<a href='#' data-guid='g-notice' aria-label='Privacy Notice' "
                     "style='display:inline-block;width:160px;height:60px'></a></div>"
                     "</td></tr></tbody></table>%s" % (ACCOUNT, BROKERAGE, ACCOUNT, BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, out, trace = download(page, ALONE)
    assert "g-notice" not in hits, hits
    assert not got and not out.exists()
    assert {"note": "a link naming this document holds something else that could be pressed, "
                    "so it was passed over"} in trace, trace
    _says_nothing_the_page_said(trace)


def test_a_view_link_holding_a_notice_is_never_pressed_whole(page, run, monkeypatch):
    """The only row of a date of one document, which prints no title. Its
    View is a role=link element wrapping a notice's icon link. A bare View
    may be the document's, and the row link step pressed it on its middle,
    which landed on the notice."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>%s</td><td>"
                     "<div role='link' tabindex='0' data-guid='g-view' "
                     "style='display:inline-block;text-align:center'>View<br>"
                     "<a href='#' data-guid='g-notice' aria-label='Privacy Notice' "
                     "style='display:inline-block;width:160px;height:60px'></a></div>"
                     "</td></tr></tbody></table>%s" % (ACCOUNT, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, out, trace = download(page, ALONE)
    assert "g-notice" not in hits, hits
    assert not got and not out.exists()
    assert ("row link", "the control holds something else that could be pressed") in _refusals(trace), trace
    _says_nothing_the_page_said(trace)
