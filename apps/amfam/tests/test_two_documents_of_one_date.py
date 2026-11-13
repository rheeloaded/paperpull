"""Two documents of one date, and a control that could not be read.

The Wells Fargo app kept one document per date and pressed the first
control of the date, whatever it fetched (fixed there in 240a473e), and
American Family's statements code has the same shape. Discovery kept one
document for each bill and date, named Tax Document or Account Statement
after the first control of that date it could read, and _statement_controls
passed over a control it could not read as if it were not there. The
download pressed the first control carrying the date. So when a 1099 and a
statement share a date only the first of them is ever found. And when the
1099 could not be read while the page was surveyed, the date was recorded
as the statement, the download pressed the 1099, and it was filed as the
statement. Nothing checks which document a saved file is.

The Wells Fargo repair ended three rounds of reviews that each found a new
wrong save by reading each control twice, the old way and with care, and
filing it only where the two agree. Here the old way is this app's own
reading, its row rule that already refuses a list among them, and the
careful one reads the same row leaving out every other document control's
words and dates, and takes a control's kind from its own words and then
the nearest words around it. Where the two disagree the control is counted
and left for a person. Each shape below is in this app's words. A shape the
code before got right is held to the same answer.

Everything here is invented, and it drives a real browser, since what a
read of an element answers and where a press lands are what a fake page
gets wrong. Each page records where every click truly landed, in the
capture phase, by the data-guid around the click's target. A stalled read
is Playwright's own TimeoutError, raised by testkit.stall_reads.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amfam_docs as app_mod
import amfam_site as site
from paperpull_core.testkit import receipt_app, stall_reads, text_pdf

BASE = "https://myaccount.amfam.com"
DAY = "2026-01-31"
STATEMENT = "Account Statement - January 31, 2026"
TAX = "Tax Document - January 31, 2026"

# Every read discovery and the download make of a control, the element
# itself and then what it says, so a stalled control answers none of them.
STALLED = {"locator": ("element_handle",),
           "handle": ("get_attribute", "inner_text", "evaluate", "is_visible")}

UNREAD = "a document control on the page could not be read"
TWO_ROWS = "more than one row of this date holds this kind of document"
NONE_OF_THIS_KIND = "no control of this date is this kind of document"
NOT_THE_SAME = "the control was not the same when read again"

# Where each click landed, by the data-guid around its target.
LISTENER = ("<script>window.hits = [];"
            "document.addEventListener('click', e => { const g = e.target.closest('[data-guid]');"
            " window.hits.push(g ? g.dataset.guid : e.target.tagName.toLowerCase());"
            " e.preventDefault(); }, true);</script>")

STATEMENT_ROW = ("<div data-guid='r-statement'><span>Statement date 01/31/2026</span> "
                 "<span>Billing statement</span> "
                 "<button data-guid='g-statement'>View bill</button></div>")
TAX_ROW = ("<div data-guid='r-tax'><span>Issued 01/31/2026</span> <span>Form 1099-INT</span> "
           "<button data-guid='g-tax'>Download 1099-INT</button></div>")
# A second statement of the same day, printing the same words.
TWIN_ROW = ("<div data-guid='r-twin'><span>Statement date 01/31/2026</span> "
            "<span>Billing statement</span> "
            "<button data-guid='g-twin'>View bill</button></div>")
# One statement offered twice, the way many statement lists do.
VIEW_AND_DOWNLOAD_ROW = ("<div data-guid='r-statement'><span>Statement date 01/31/2026</span> "
                         "<span>Billing statement</span> "
                         "<button data-guid='g-view'>View bill</button> "
                         "<button data-guid='g-download'>Download PDF</button></div>")
OTHER_DAY_ROW = ("<div data-guid='r-older'><span>Statement date 12/31/2025</span> "
                 "<span>Billing statement</span> "
                 "<button data-guid='g-older'>View bill</button></div>")


def _page(*rows):
    """A list of rows, the way Billing & Payments draws statements."""
    return "<div data-cy='statements'>%s</div>%s" % ("".join(rows), LISTENER)


def _blocks(*blocks):
    """A page laid out in blocks of its own."""
    return "<div>%s</div>%s" % ("".join(blocks), LISTENER)


def _marked(guid, words, date):
    """One row of a statements list the way the tester's recording shows it
    (#45), a link with no address marked statementPDF beside the row's
    words, which say what it is."""
    return ("<div data-cy='statementRow' data-guid='r-%s'><div><div><span>%s %s</span></div>"
            "<div><a data-cy='statementPDF' title='View statement' data-guid='%s'><span>PDF</span></a>"
            "</div></div></div>" % (guid, words, date, guid))


MARKED_STATEMENT = _marked("g-statement", "Statement date", "01/31/2026")
MARKED_TAX = _marked("g-tax", "Form 1099-INT", "01/31/2026")


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        driver.stop()
        pytest.skip("no browser to drive, %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser, monkeypatch):
    """A blank tab the page is set into, rather than one opened at
    myaccount.amfam.com, with nothing to expand or scroll and no bills.
    Nothing it asks for leaves this machine."""
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg, view=None: True)
    monkeypatch.setattr(site, "scroll_full_page", lambda pg, *a, **k: None)
    pg = browser.new_page()
    pg.context.route("**/*", lambda r: r.abort())
    yield pg
    pg.close()


@pytest.fixture
def presses(monkeypatch):
    """Stands in for the catch. It presses the element the way the real
    catch does, remembers where the press landed, and saves a PDF that
    names the control it came from."""
    hits: list = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        before = len(pg.evaluate("window.hits"))
        try:
            el.click(timeout=3000)
        except Exception as e:
            hits.append("click failed " + type(e).__name__)
            return False
        landed = pg.evaluate("window.hits")[before:]
        hits.extend(landed)
        Path(out_path).write_bytes(b"%PDF-1.4\n% " + ",".join(landed).encode() + b"\n%%EOF\n")
        return bool(landed)
    monkeypatch.setattr(site, "_catch_pdf", fake)
    return hits


def _download(page, tmp_path, title, iso=DAY):
    trace: list = []
    saved = site.download_bill(page, tmp_path, iso, tmp_path / "saved.pdf", title=title, trace=trace)
    return saved, trace


def _refusals(trace):
    return [t.get("why") for t in trace if "why" in t]


def _found(docs):
    return sorted((d.date_text, d.kind, d.title) for d in docs)


# --- two kinds of document on one date ---------------------------------------

@pytest.mark.parametrize("rows", [(TAX_ROW, STATEMENT_ROW), (STATEMENT_ROW, TAX_ROW),
                                  (MARKED_TAX, MARKED_STATEMENT), (MARKED_STATEMENT, MARKED_TAX)],
                         ids=["tax form first", "statement first",
                              "marked, tax form first", "marked, statement first"])
def test_a_statement_and_a_tax_form_of_one_date_are_both_found(page, rows):
    """The statement was never found once the 1099 came first, and the 1099
    never once the statement did, in rows of words or in the rows of
    statementPDF links the tester's page draws."""
    page.set_content(_page(*rows))
    assert _found(site.collect_download_docs(page)) == [
        (DAY, "statement", STATEMENT), (DAY, "tax", TAX)]


@pytest.mark.parametrize("rows", [(TAX_ROW, STATEMENT_ROW), (STATEMENT_ROW, TAX_ROW),
                                  (MARKED_TAX, MARKED_STATEMENT), (MARKED_STATEMENT, MARKED_TAX)],
                         ids=["tax form first", "statement first",
                              "marked, tax form first", "marked, statement first"])
@pytest.mark.parametrize("title, guid", [(STATEMENT, "g-statement"), (TAX, "g-tax")],
                         ids=["the statement", "the tax form"])
def test_each_document_of_the_date_is_pressed_for_its_own_kind(page, presses, tmp_path, rows, title, guid):
    """The download asked for a date alone and pressed the first control
    carrying it, so whichever came first was saved under both names."""
    page.set_content(_page(*rows))
    saved, trace = _download(page, tmp_path, title)
    assert saved and presses == [guid], (presses, trace)
    assert guid.encode() in (tmp_path / "saved.pdf").read_bytes()


# --- a control that could not be read ----------------------------------------

@pytest.mark.parametrize("rows, stalled, kept, guid", [
    ((TAX_ROW, STATEMENT_ROW), "g-tax", STATEMENT, "g-statement"),
    ((STATEMENT_ROW, TAX_ROW), "g-statement", TAX, "g-tax"),
], ids=["the 1099 unread", "the statement unread"])
def test_a_control_unread_during_discovery_is_not_saved_as_another(page, presses, tmp_path,
                                                                  rows, stalled, kept, guid):
    """The case the audit read. The first control of the date could not be
    read while the page was surveyed, so the date was recorded as the other
    document. Once it answered again, the download pressed it, the first
    control carrying the date, and filed it under the other's name."""
    page.set_content(_page(*rows))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {stalled}, **STALLED)
        docs = site.collect_download_docs(page)
    assert [d.title for d in docs] == [kept]
    saved, trace = _download(page, tmp_path, kept)
    assert saved and presses == [guid], (presses, trace)
    assert guid.encode() in (tmp_path / "saved.pdf").read_bytes()


def test_a_control_still_unread_at_the_download_keeps_the_other_unpressed(page, presses, tmp_path, monkeypatch):
    """The 1099 still does not answer when the statement is fetched. It was
    passed over as if it were not on the page, which left the statement as
    the only control of its date and kind. A control that could not be read
    may be a second statement of the day, so nothing is pressed, and the
    reason is written in words of the app's own."""
    page.set_content(_page(TAX_ROW, STATEMENT_ROW))
    stall_reads(monkeypatch, {"g-tax"}, **STALLED)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [UNREAD], trace
    assert not (tmp_path / "saved.pdf").exists()
    said = json.dumps(trace)
    assert "1099" not in said and "statement" not in said.lower(), said


def test_an_unread_control_lends_no_other_control_its_date_or_kind(page, monkeypatch):
    """A control that would not answer is counted and left for the next run.
    The documents around it are named from their own controls only."""
    page.set_content(_page(TAX_ROW, STATEMENT_ROW, OTHER_DAY_ROW))
    stall_reads(monkeypatch, {"g-tax"}, **STALLED)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [("2025-12-31", "statement", "Account Statement - December 31, 2025"),
                            (DAY, "statement", STATEMENT)]
    assert docs.unread == 1


def test_a_marked_link_whose_mark_cannot_be_read_is_counted_as_unread(page, monkeypatch):
    """Whether a link is marked statementPDF was read with its failure taken
    as no mark, and a link that showed only PDF was then no control of a
    statement at all, passed over without a word. Only that read stalls,
    and every other read of the link answers."""
    page.set_content(_page(MARKED_TAX, MARKED_STATEMENT))
    stall_reads(monkeypatch, {"g-tax"}, locator=(), handle=("evaluate",), scripts=(site._MARKED_JS,))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unread == 1


# --- two rows of one date and kind ---------------------------------------------

def test_two_statements_of_one_date_are_refused_rather_than_taken_as_one(page, presses, tmp_path):
    """Two statements of the same day, in rows that print the same words.
    The first was saved as the day's statement and the second was never
    asked for. Nothing on the page tells them apart, so neither is guessed
    at."""
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_discovery_records_two_rows_of_one_date_once_and_says_so(page):
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW, TAX_ROW))
    docs = site.collect_download_docs(page)
    assert sorted((d.title, d.rows) for d in docs) == [(STATEMENT, 2), (TAX, 1)]


def test_view_and_download_in_one_row_are_one_document(page, presses, tmp_path):
    """Two controls in one row fetch one document, so the row is not
    refused as two. The first of them is pressed, as it always was."""
    page.set_content(_page(VIEW_AND_DOWNLOAD_ROW))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_document_alone_on_its_date_is_saved_as_before(page, presses, tmp_path):
    page.set_content(_page(STATEMENT_ROW, OTHER_DAY_ROW))
    saved, trace = _download(page, tmp_path, "Account Statement - December 31, 2025", iso="2025-12-31")
    assert saved and presses == ["g-older"], (presses, trace)


# --- what the download is asked for, and when the page moves -------------------

def test_a_title_that_names_no_kind_presses_nothing(page, presses, tmp_path):
    """The kind is read back out of the title discovery wrote. A title it
    did not write says nothing about the kind, so nothing is guessed."""
    page.set_content(_page(STATEMENT_ROW))
    saved, trace = _download(page, tmp_path, "")
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["the title does not say which kind of document it is"], trace


def test_a_page_whose_controls_cannot_be_counted_presses_nothing(page, presses, tmp_path, monkeypatch):
    """The page's controls would not even be counted, so what any of them
    fetches cannot be told, and nothing is pressed."""
    page.set_content(_page(STATEMENT_ROW))
    stall_reads(monkeypatch, {"g-statement"}, locator=("count",))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [UNREAD], trace


def test_the_element_read_is_the_one_pressed_when_another_row_is_drawn_above(page, presses, tmp_path,
                                                                            monkeypatch):
    """The statement is the first control when the page is read, and the
    page then draws the 1099 above it. This app holds each control as the
    element itself (the review of the Bill details change), so the element
    read again and pressed is the statement, wherever the page moved it."""
    page.set_content(_page(STATEMENT_ROW, TAX_ROW))
    real = site._survey

    def then_redrawn(pg, *a, **k):
        found = real(pg, *a, **k)
        pg.evaluate("() => { const t = document.querySelector('[data-guid=r-tax]');"
                    " t.parentNode.insertBefore(t, t.parentNode.firstChild); }")
        return found
    monkeypatch.setattr(site, "_survey", then_redrawn)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_the_element_read_again_is_the_one_pressed(page, tmp_path, monkeypatch):
    """The page draws a 1099 row above the statement just as the press is
    made. The element read again is what is pressed, never whatever stands
    at its place among the controls by then."""
    page.set_content(_page(STATEMENT_ROW, OTHER_DAY_ROW))
    hits: list = []

    def drawn_above_then_pressed(pg, el, label, out_path, trace=None, dl_dir=None):
        pg.evaluate("row => document.querySelector('[data-cy=statements]')"
                    ".insertAdjacentHTML('afterbegin', row)", TAX_ROW)
        before = len(pg.evaluate("window.hits"))
        el.click(timeout=3000)
        hits.extend(pg.evaluate("window.hits")[before:])
        Path(out_path).write_bytes(b"%PDF-1.4\n%%EOF\n")
        return True
    monkeypatch.setattr(site, "_catch_pdf", drawn_above_then_pressed)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and hits == ["g-statement"], (hits, trace)


def test_a_row_drawn_again_between_the_look_and_the_press_is_not_trusted(page, presses, tmp_path, monkeypatch):
    """The list is drawn again, with the same words, after the page was
    read. The element read has left the page, and the one in its place is
    one the look never saw, so nothing is pressed."""
    page.set_content(_page(STATEMENT_ROW))
    real = site._survey

    def then_redrawn(pg, *a, **k):
        found = real(pg, *a, **k)
        pg.evaluate("() => { const b = document.querySelector('[data-cy=statements]');"
                    " b.innerHTML = b.innerHTML; }")
        return found
    monkeypatch.setattr(site, "_survey", then_redrawn)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NOT_THE_SAME], trace


def test_a_control_that_left_the_page_is_never_pressed(page, presses, tmp_path, monkeypatch):
    """The list is drawn again after the page was read. The control names
    its own date, so read off the page it says what it said on it. It has
    left the page all the same, so nothing is pressed, neither it nor the
    copy drawn in its place."""
    page.set_content(_page("<div data-guid='r-statement'><span>Billing statement</span> "
                           "<button data-guid='g-statement'>View bill for January 31, 2026</button></div>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]
    real = site._survey

    def then_redrawn(pg, *a, **k):
        found = real(pg, *a, **k)
        pg.evaluate("() => { const b = document.querySelector('[data-cy=statements]');"
                    " b.innerHTML = b.innerHTML; }")
        return found
    monkeypatch.setattr(site, "_survey", then_redrawn)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NOT_THE_SAME], trace


def test_a_control_that_will_not_answer_its_second_read_is_not_pressed(page, presses, tmp_path, monkeypatch):
    """The page was read whole, then the control chosen does not answer when
    it is read again as the element that will be pressed."""
    page.set_content(_page(STATEMENT_ROW))
    real = site._survey

    def then_stalled(pg, *a, **k):
        found = real(pg, *a, **k)
        stall_reads(monkeypatch, {"g-statement"}, locator=(), handle=STALLED["handle"])
        return found
    monkeypatch.setattr(site, "_survey", then_stalled)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NOT_THE_SAME], trace


def test_a_control_whose_readings_part_before_the_press_is_not_pressed(page, presses, tmp_path, monkeypatch):
    """The page was read and the statement's two readings agreed. Then its
    row came to name a 1099 as well. Its name, date and row are as before,
    but read again its readings disagree, so it is not pressed."""
    page.set_content(_page(STATEMENT_ROW))
    real = site._survey

    def then_changed(pg, *a, **k):
        found = real(pg, *a, **k)
        pg.evaluate("() => { document.querySelector('[data-guid=r-statement] span:nth-child(2)')"
                    ".textContent = 'Billing statement and Form 1099-INT'; }")
        return found
    monkeypatch.setattr(site, "_survey", then_changed)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NOT_THE_SAME], trace


# --- a whole run ----------------------------------------------------------------
#
# The app's own discovery and download, the way a run calls them, so the
# title discovery writes is the one the download is handed. Each press saves
# a real PDF that names the control it came from, and what the run filed is
# read back out of the folders.

def _fake_catch(pg, el, label, out_path, trace=None, dl_dir=None):
    before = len(pg.evaluate("window.hits"))
    el.click(timeout=3000)
    landed = pg.evaluate("window.hits")[before:]
    Path(out_path).write_bytes(text_pdf(["pressed " + ",".join(landed)]))
    return bool(landed)


def _app_in(page, tmp_path):
    app = receipt_app(app_mod, tmp_path)
    app._context, app._work_page, app._dl_dir = page.context, page, tmp_path / "downloads"
    # The tab is this test's own, so the check that it is on American
    # Family's site (tabs.on_its_site) is stood in for too.
    app._on_its_site = lambda: page
    return app


@pytest.fixture
def run(page, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "_catch_pdf", _fake_catch)
    return _app_in(page, tmp_path)


def _filed(app):
    """Each folder the run saved into, and the controls its PDFs came from."""
    out: dict = {}
    for pdf in sorted(app.paths.root.rglob("*.pdf")):
        pressed = re.search(rb"pressed ([\w,-]*)", pdf.read_bytes()).group(1).decode()
        out.setdefault(pdf.parent.name, []).append(pressed)
    return out


def test_a_run_files_the_statement_and_the_1099_of_one_day_each_as_itself(page, run):
    page.set_content(_page(TAX_ROW, STATEMENT_ROW))
    run.cmd_discover(quiet=True)
    run.process(run._select())
    assert _filed(run) == {"Statements": ["g-statement"], "Tax Documents": ["g-tax"]}


def test_a_run_never_files_a_1099_unread_at_discovery_as_the_statement(page, run):
    """The audit's case through the whole run. The statement is filed as
    the statement, and the 1099 waits for a run that can read it."""
    page.set_content(_page(TAX_ROW, STATEMENT_ROW))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {"g-tax"}, **STALLED)
        run.cmd_discover(quiet=True)
    run.process(run._select())
    assert _filed(run) == {"Statements": ["g-statement"]}


def test_a_twin_discovery_saw_is_refused_when_the_download_cannot_see_it(page, run):
    """A row discovery saw may not be drawn when the download looks. How
    many rows discovery found travels with the document, through the whole
    run, and the refusal is written in its fixed words."""
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW))
    run.cmd_discover(quiet=True)
    page.evaluate("() => document.querySelector('[data-guid=r-twin]').remove()")
    run.process(run._select())
    assert _filed(run) == {}
    attempt = json.loads((run.paths.diagnostics / "download-attempt.json").read_text(encoding="utf-8"))
    assert [t.get("why") for t in attempt["responses"]] == [
        "discovery found more than one row of this date holding this kind of document"], attempt


def test_a_twin_a_later_discovery_saw_is_refused_though_the_first_saw_none(page, run):
    """The first discovery saw one row of the day and a later one saw two.
    The record carries the later count, so the statement is refused even
    when the download sees one row again."""
    page.set_content(_page(STATEMENT_ROW))
    run.cmd_discover(quiet=True)
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW))
    run.cmd_discover(quiet=True)
    page.set_content(_page(STATEMENT_ROW))
    run.process(run._select())
    assert _filed(run) == {}


def test_diagnose_counts_what_the_download_would_refuse(page, run, monkeypatch):
    """A repair needs the rows of a date and kind, and the controls that
    would not answer or whose two readings disagree, so Diagnose says how
    many of each it saw. Its look at the page's links and bills is other
    tests'."""
    monkeypatch.setattr(site, "survey", lambda pg, **k: {})
    monkeypatch.setattr(site, "survey_bills", lambda pg: [])
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW, TAX_ROW,
                           "<div><span>Issued 01/31/2026</span> <span>Form 1099-DIV</span> "
                           "<button data-guid='g-div'>View statement</button></div>"))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {"g-tax"}, **STALLED)
        run.cmd_diagnose()
    info = json.loads((run.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert [(d["kind"], d["rows"]) for d in info["documents_recognized"]] == [("statement", 2)], info
    assert (info["document_controls_unread"], info["document_controls_unsure"]) == (1, 1), info


# --- a whole run through a bill's Bill details (#45) ----------------------------
#
# The tester's Billing & Payments lists each bill with a Bill details, whose
# press draws that bill's statements as rows of statementPDF links. Here one
# bill's list holds a 1099 and a statement of one date.

def _billing(*rows):
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Billing &amp; Payments</title></head>"
            "<body><div role='main'><div class='page'><h1>My bills</h1><div class='bills'>"
            "<div class='bill-card'><h2>Auto</h2>"
            "<p><span>Billing account</span> <span>9900123401</span></p>"
            "<p><span>Amount due</span> <span>$123.45</span></p>"
            "<button data-guid='details' onclick=\"document.getElementById('details').innerHTML = ROWS\">"
            "Bill details</button></div></div><div id='details'></div></div></div>"
            "<script>const ROWS = %s;</script>%s</body></html>" % (json.dumps("".join(rows)), LISTENER))


@pytest.fixture
def billing(browser, tmp_path, monkeypatch):
    """Billing & Payments at its own address, served here, and the app
    working in it. Nothing else the page asks for leaves this machine, and
    the app's waits are a tenth as long, as in test_bill_details.py."""
    contexts = []

    def start(html):
        ctx = browser.new_context(accept_downloads=False)
        contexts.append(ctx)
        ctx.route("**/*", lambda r: r.abort())
        ctx.route("%s/billing" % BASE, lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        pg = ctx.new_page()
        pg.goto("%s/billing" % BASE)
        wait = pg.wait_for_timeout
        pg.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        monkeypatch.setattr(site, "_catch_pdf", _fake_catch)
        return _app_in(pg, tmp_path)

    yield start
    for ctx in contexts:
        ctx.close()


def test_a_bills_statement_and_1099_of_one_day_are_each_filed_as_themselves(billing):
    app = billing(_billing(MARKED_TAX, MARKED_STATEMENT))
    app.cmd_discover(quiet=True)
    assert sorted((r["title"], r["account"]) for r in app.discovery.data.values()) == [
        (STATEMENT, "...3401"), (TAX, "...3401")]
    app.process(app._select())
    assert _filed(app) == {"Statements": ["g-statement"], "Tax Documents": ["g-tax"]}


def test_a_bills_1099_unread_at_discovery_is_never_filed_as_its_statement(billing):
    """The audit's case on the tester's own page. The 1099 does not answer
    while the bill's list is read, and the press for the statement was the
    1099's, the first link of the day, filed in Statements."""
    app = billing(_billing(MARKED_TAX, MARKED_STATEMENT))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {"g-tax"}, **STALLED)
        app.cmd_discover(quiet=True)
    app.process(app._select())
    assert _filed(app) == {"Statements": ["g-statement"]}


# --- the shapes the Wells Fargo reviews found, in this app's words --------------

# View and Download, each naming the date for a screen reader.
DATED_NAMES_ROW = ("<div data-guid='r-statement'><span>Statement date 01/31/2026</span> "
                   "<span>Billing statement</span> "
                   "<button data-guid='g-view' aria-label='View bill for January 31, 2026'>View</button> "
                   "<button data-guid='g-download' aria-label='Download statement January 31, 2026'>"
                   "Download</button></div>")
CARD = ("<div data-guid='c-statement'><span>01/31/2026</span> Billing statement "
        "<button data-guid='g-view'>View bill</button> <button data-guid='g-download'>Download PDF</button></div>")
UNDATED_TAX_ROW = ("<div data-guid='r-tax'><span>Tax year 2025</span> <span>Form 1099-INT</span> "
                   "<button data-guid='g-tax'>Download 1099-INT</button></div>")
SECOND_UNDATED_TAX_ROW = ("<div data-guid='r-tax2'><span>Tax year 2025</span> <span>Form 1099-DIV</span> "
                          "<button data-guid='g-tax2'>Download 1099-DIV</button></div>")
BOTH_IN_ONE_ROW = ("<div data-guid='r-both'><span>Statement date 01/31/2026</span> "
                   "<button data-guid='g-statement'>View bill</button> "
                   "<button data-guid='g-tax'>Download 1099-INT</button></div>")
# Two statements under one heading that prints their date.
UNDER_ONE_DATE = ("<div data-guid='d-day'><h3>January 31, 2026</h3>"
                  "<div>Auto policy bill <button data-guid='g-first'>View</button></div>"
                  "<div>Home policy bill <button data-guid='g-second'>View</button></div></div>")


@pytest.mark.parametrize("content, first", [
    (_page(DATED_NAMES_ROW), "g-view"),
    (_blocks(CARD), "g-view"),
], ids=["names that print the date", "a card"])
def test_two_controls_of_one_statement_are_one_document(page, presses, tmp_path, content, first):
    """Two controls of one row, or of one card, fetch one document, so the
    statement is not refused as two."""
    page.set_content(content)
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == [first], (presses, trace)


@pytest.mark.parametrize("rows", [(STATEMENT_ROW, UNDATED_TAX_ROW, SECOND_UNDATED_TAX_ROW),
                                  (UNDATED_TAX_ROW, SECOND_UNDATED_TAX_ROW, STATEMENT_ROW)],
                         ids=["statement first", "tax forms first"])
def test_a_tax_row_without_a_date_is_never_pressed_for_a_tax_form_of_that_date(page, presses, tmp_path, rows):
    """This app's row rule already gave a tax row with no date of its own
    no date from the list around it. The download still pressed the first
    control of the date, the statement, for a tax form of that day."""
    page.set_content(_page(*rows))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_a_statement_beside_a_1099_in_one_row_is_never_pressed_for_it(page, presses, tmp_path):
    """The row's words decided the kind of every control in it, so both read
    as the tax form and the statement's View bill, the first, was pressed
    for the 1099. Read the old way View bill is still the tax form, read
    with care it is the statement, so it is left for a person, and the 1099
    is its own."""
    page.set_content(_page(BOTH_IN_ONE_ROW))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)
    presses.clear()
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace


def test_two_bills_under_one_date_heading_are_refused_rather_than_taken_as_one(page, presses, tmp_path):
    """No list says where one statement ends. Each bill's part prints words
    of its own, so each is a row, and two rows of one date holding
    statements cannot be told apart."""
    page.set_content(_blocks(UNDER_ONE_DATE))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 2)]


def test_a_date_heading_over_entries_that_print_none_is_their_date(page, presses, tmp_path):
    """A list grouped by day prints the date once, over the day's entries,
    and the heading dates them. The old reading takes the kind from the
    whole day's words, which name a 1099, so the statement's entry reads
    as a tax form that way and is left for a person rather than filed."""
    page.set_content("<ul><li>January 31, 2026<ul>"
                     "<li>Billing statement <button data-guid='g-statement'>View</button></li>"
                     "<li>Form 1099-INT <button data-guid='g-tax'>Download</button></li>"
                     "</ul></li></ul>" + LISTENER)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


def test_two_rows_under_one_date_heading_row_are_two_documents(page, presses, tmp_path):
    """A heading row prints the day, and the statements under it are rows
    holding nothing but their controls. Each table row is an entry of its
    own, so the two are two documents, and neither is guessed at."""
    page.set_content(_blocks("<table><tbody><tr><td colspan='2'>January 31, 2026</td></tr>"
                             "<tr><td><button data-guid='g-first'>View bill</button></td></tr>"
                             "<tr><td><button data-guid='g-second'>View bill</button></td></tr>"
                             "</tbody></table>"))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_a_control_that_calls_itself_a_statement_in_a_1099_row_is_filed_as_neither(page):
    """Some lists word every document's control the same. The row says 1099
    and the control says statement, so the two readings disagree and it is
    left for a person rather than filed as either."""
    page.set_content(_page("<div><span>Issued 01/31/2026</span> <span>Form 1099-INT</span> "
                           "<button data-guid='g-tax'>View statement</button></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1


def test_a_premium_tax_line_does_not_make_a_bill_a_tax_form(page):
    """This app reads tax only as a tax form (review of 0.41.0), and both
    readings call this bill a statement."""
    page.set_content(_page("<div><span>Statement date 01/31/2026</span> <span>Premium tax $4.56</span> "
                           "<button data-guid='g-statement'>View bill</button></div>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]


def test_a_menu_of_actions_is_not_an_entry(page, presses, tmp_path):
    """View and Download sit in a menu, each in a list item of its own,
    inside the entry that names a 1099. The list items print nothing of
    their own, so the entry around them says what both fetch."""
    page.set_content(_blocks("<div data-guid='e-tax'>01/31/2026 Form 1099-INT <ul>"
                             "<li><button data-guid='g-view'>View</button></li>"
                             "<li><button data-guid='g-download'>Download</button></li></ul></div>"))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(TAX, 1)]
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-view"], (presses, trace)


def test_entries_gathered_in_one_list_item_keep_their_own_kinds(page, presses, tmp_path):
    """A year's documents gathered in one list item, each entry printing its
    own date. Only the first of the day was ever found."""
    page.set_content("<ul><li>"
                     "<div>01/31/2026 Billing statement <button data-guid='g-statement'>View</button></div>"
                     "<div>01/31/2026 Form 1099-INT <button data-guid='g-tax'>View</button></div>"
                     "</li></ul>" + LISTENER)
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT), (DAY, "tax", TAX)]
    for title, guid in ((TAX, "g-tax"), (STATEMENT, "g-statement")):
        presses.clear()
        saved, trace = _download(page, tmp_path, title)
        assert saved and presses == [guid], (title, presses, trace)


def test_a_control_printing_a_1099_under_a_plain_label_is_the_tax_form(page):
    """Its label says only Download, and the words it shows name the form."""
    page.set_content(_blocks("<button data-guid='g-tax' aria-label='Download'>Form 1099-INT 01/31/2026</button>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


def test_a_view_beside_a_1099_control_is_never_pressed_for_the_1099(page, presses, tmp_path):
    """A row's View beside the row's Download 1099-INT. The row's words were
    read with the other control's name in them, so View read as the tax
    form and, coming first, was pressed for it. Read with care View is the
    statement, so the two readings disagree and View is left alone."""
    page.set_content(_page("<div><span>Statement date 01/31/2026</span> <span>Billing statement</span> "
                           "<button data-guid='g-statement'>View</button> "
                           "<button data-guid='g-tax'>Download 1099-INT</button></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


@pytest.mark.parametrize("content", [
    _blocks("<table><tbody><tr><td>01/31/2026</td><td>Form 1099-INT</td>"
            "<td><span>On screen</span> <button data-guid='g-view'>View</button></td>"
            "<td><span>As a file</span> <button data-guid='g-download'>Download</button></td></tr>"
            "</tbody></table>"),
    _blocks("<div>01/31/2026 Form 1099-INT "
            "<span>On screen <button data-guid='g-view'>View</button></span> "
            "<span>As a file <button data-guid='g-download'>Download</button></span></div>"),
], ids=["in a table row", "on a card"])
def test_a_caption_beside_each_control_keeps_them_one_document(page, presses, tmp_path, content):
    """A caption beside each control is words of its own, and it neither
    splits the entry in two nor hides what the entry is."""
    page.set_content(content)
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(TAX, 1)]
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_heading_that_says_tax_does_not_make_a_statement_a_tax_form(page, presses, tmp_path):
    """The day's heading names tax documents and one entry under it is the
    statement. Read with care the entry's own words are nearer and say
    statement, read the old way the heading says tax, so the statement is
    left for a person, never pressed for the 1099 or filed as one."""
    page.set_content("<ul><li>Tax documents and statements, January 31, 2026<ul>"
                     "<li>Billing statement <button data-guid='g-statement'>View</button></li>"
                     "<li>Form 1099-INT <button data-guid='g-tax'>Download</button></li>"
                     "</ul></li></ul>" + LISTENER)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


def test_a_control_in_a_part_of_an_entry_is_of_that_entry(page, presses, tmp_path):
    """The entry's words sit beside View, in a part of their own, and
    Download sits apart from them. A part of an entry is inside it, so the
    two controls fetch one document."""
    page.set_content(_blocks("<div>01/31/2026 "
                             "<div>Billing statement <button data-guid='g-view'>View</button></div>"
                             "<div><button data-guid='g-download'>Download</button></div></div>"))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_date_printed_in_one_control_dates_no_other_control(page, presses, tmp_path):
    """The statement's control prints its date and the 1099's prints none.
    This app's row rule takes no date for the 1099 from a row holding the
    other control's dated words, read either way, and the download pressed
    the statement for it all the same, the first control of the day."""
    page.set_content(_page("<div><button data-guid='g-statement'>View bill for January 31, 2026</button> "
                           "<button data-guid='g-tax'>Download 1099-INT</button></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace


def test_a_row_whose_other_control_names_a_previous_statement_dates_neither(page, presses, tmp_path):
    """The bill's row offers its own View bill beside a View previous
    statement. Read the old way the row writes another statement's date,
    so View bill has none. Read with care, leaving the other control out,
    the row's date is the bill's. The two disagree, so it is left for a
    person, and the previous statement's control dates nothing either way."""
    page.set_content(_page("<div><span>Statement date 01/31/2026</span> "
                           "<button data-guid='g-statement'>View bill</button> "
                           "<button data-guid='g-previous'>View previous statement</button></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace


def test_a_control_dated_only_by_its_name_in_a_list_is_an_entry_of_its_own(page, presses, tmp_path):
    """One View names its date only for a screen reader, in a list whose
    other statement prints the same date in a row of its own. Read either
    way the list dates neither of them, and the View is an entry apart
    from that row, so the two statements of the day are never one, and
    neither is guessed at."""
    page.set_content(_blocks("<div data-guid='d-list'><span>01/31/2026</span> "
                             "<div><button data-guid='g-first' aria-label='View bill for January 31, 2026'>"
                             "View</button></div>"
                             "<div><span>01/31/2026</span> <button data-guid='g-second'>View bill</button></div>"
                             "</div>"))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 2)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_a_plain_download_beside_view_1099_is_not_filed_as_a_statement(page, presses, tmp_path):
    """The form's name is in View 1099's own words, so with care the plain
    Download beside it names no kind and would be a statement. Read the old
    way it is the 1099, so it is left alone, and the statement's title
    presses nothing, where the old download pressed View 1099 for it."""
    page.set_content(_page("<div><span>Issued 01/31/2026</span> "
                           "<button data-guid='g-view'>View 1099</button> "
                           "<button data-guid='g-download'>Download</button></div>"))
    docs = site.collect_download_docs(page)
    assert [(d.title, d.rows) for d in docs] == [(TAX, 1)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-view"], (presses, trace)


# --- the shapes the review of this port found -----------------------------------
#
# Finding a second document of a day, the port filed the first two of these
# under a kind they are not, where the code before it found only the first.
# The third is a control passed over as absent.

# A bill, its policy's masked number printed beside a View of its own.
MASKED_ROW = ("<div data-guid='r-masked'><span>Statement date 01/31/2026</span> <span>Billing statement</span> "
              "<span>%s</span> <button data-guid='g-masked'>View</button></div>")
# The same, its policy's last four digits in the control's own words.
MASKED_CONTROL_ROW = ("<div data-guid='r-masked'><span>Statement date 01/31/2026</span> "
                      "<span>Billing statement</span> "
                      "<button data-guid='g-masked'>View billing statement for policy ending 1099</button></div>")


@pytest.mark.parametrize("row", [MASKED_ROW % policy for policy in (
    "Policy ****1099", "Policy ... 5498", "Policy … 1098", "Policy •••• 1099",
    "Policy XXXX-5498", "Policy #1098", "Homeowners ending in 1099", "Auto policy ending 1098",
    "Last four digits 5498", "Policy ●●●● 1099", "Policy ···· 1099",
    "Policy XXXX–1099", "Policy **** - 1099", "Policy ending - 1098", "Auto policy *1099",
    "Policy ****1099-Auto")]
    + [MASKED_CONTROL_ROW],
    ids=["asterisks", "dots", "an ellipsis", "bullets", "x's", "a number sign", "ending in", "a policy ending",
         "last four", "black circles", "middle dots", "x's and an en dash", "asterisks and a dash",
         "ending and a dash", "one asterisk", "a policy's line after the digits", "in the control's own words"])
def test_a_bill_of_a_policy_ending_1099_is_never_filed_as_a_tax_form(page, presses, tmp_path, row):
    """The bill names its policy by the last digits of its number, 1099,
    1098 or 5498, and both readings took those digits for the form, so the
    bill was filed as a Tax Document, alone or beside another bill of the
    day. Read with care they are the policy's, the two readings disagree,
    and it is left for a person. Three dots, an ellipsis, black circles,
    middle dots, a dash other than a hyphen after a mask and "last four
    digits" masked nothing as first ported, the last since only sixteen
    characters before the digits were read (fresh reviews of the Wells
    Fargo port). And a policy's line named after a dash, ****1099-Auto, was
    taken for a form's letters (fresh review of this port)."""
    page.set_content(_page(row))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    page.set_content(_page(STATEMENT_ROW, row))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace


# A 1099-INT's statementPDF link, naming only its date, for a screen reader.
DATED_BY_NAME_LINK = ("<a data-cy='statementPDF' data-guid='g-tax' aria-label='PDF, January 31, 2026'>"
                      "<span>PDF</span></a>")


@pytest.mark.parametrize("form", [
    "<div><span>Form 1099-INT</span> %s</div>" % DATED_BY_NAME_LINK,
    "<div role='listitem'><span>Form 1099-INT</span> %s</div>" % DATED_BY_NAME_LINK,
    "<article><span>Form 1099-INT</span> %s</article>" % DATED_BY_NAME_LINK,
    "<div><span>Form 1099-INT</span> <span>%s</span></div>" % DATED_BY_NAME_LINK,
], ids=["a block", "a list item by role", "an article", "a link in a part of its own"])
def test_a_marked_link_dated_only_by_its_name_takes_its_kind_from_its_own_part_of_the_page(page, presses,
                                                                                          tmp_path, form):
    """A statementPDF link names only its date, for a screen reader, beside
    a form's name, in a list whose other row prints a bill's date. The list
    is no row of the link's, so nothing around it was read and it was filed
    as a statement of its day. The part of the page holding it and no other
    control is read now, it names a tax form, and it is left for a person."""
    page.set_content(_page(OTHER_DAY_ROW, form))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [("2025-12-31", "statement", "Account Statement - December 31, 2025")]
    assert docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace


def test_a_link_dated_only_by_its_name_reads_no_words_it_shares_with_other_documents(page):
    """statementPDF links naming only their dates, each in a part of its
    own, under tabs that name statements and tax forms. The words around a
    link are read only as far as the part that holds it alone, so the tabs,
    which every document of the list shares, leave neither unsure, and both
    are filed as the code before filed them."""
    page.set_content(_blocks(
        "<div><div role='tablist'><button>Statements</button> <button>Tax forms</button></div>"
        "<div><a data-cy='statementPDF' data-guid='g-january' aria-label='PDF, January 31, 2026'>"
        "<span>PDF</span></a></div>"
        "<div><a data-cy='statementPDF' data-guid='g-december' aria-label='PDF, December 31, 2025'>"
        "<span>PDF</span></a></div></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [("2025-12-31", "statement", "Account Statement - December 31, 2025"),
                            (DAY, "statement", STATEMENT)] and docs.unsure == 0


@pytest.mark.parametrize("link", [
    "<a href='#' data-guid='%s' aria-label='Statement January 31, 2026'>View</a>",
    "<a data-cy='statementPDF' data-guid='%s' aria-label='PDF, January 31, 2026'><span>PDF</span></a>",
    "<input type='button' data-guid='%s' value='PDF' aria-label='View bill for January 31, 2026'>",
], ids=["named for a statement", "marked statementPDF", "input buttons"])
def test_two_statements_dated_only_by_their_names_stay_two_entries(page, presses, tmp_path, link):
    """Two bills' statements of one day, each a control naming only its date
    for a screen reader, each in a part of the page of its own, under a
    heading. A button drawn as an input was no other document control to
    this reading, so what was read around each for its kind reached the
    heading, and taken for their entry it made the two one document, and
    the first was pressed for both. Each entry is still the control alone,
    as before the part around it was read, so the two are refused rather
    than guessed at (fresh review of the Wells Fargo port)."""
    page.set_content(_blocks("<div><h3>Statements</h3><div>%s</div><div>%s</div></div>"
                             % (link % "g-auto", link % "g-home")))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 2)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


REPLACE_JS = "e => { e.replaceWith(e.cloneNode(true)); return true; }"


def _drawn_again_before(monkeypatch, guid, method, script=None):
    """The page draws a copy of the control `guid` in its place just before
    the read `method` of it, once, the way a list drawn again replaces its
    nodes. With `script`, only before an evaluate of that script."""
    from playwright.sync_api import ElementHandle
    real = getattr(ElementHandle, method)
    done: list = []

    def read(self, *args, **kwargs):
        if not done and (script is None or (args and args[0] == script)) \
                and ElementHandle.get_attribute(self, "data-guid") == guid:
            done.append(guid)
            ElementHandle.evaluate(self, REPLACE_JS)
        return real(self, *args, **kwargs)
    monkeypatch.setattr(ElementHandle, method, read)
    return done


@pytest.mark.parametrize("words, method, script, new_only", [
    ("View", "evaluate", "_ROW_OF_JS", False),
    ("View bill", "evaluate", "_ROW_OF_JS", False),
    ("View bill", "is_visible", None, True),
], ids=["a bare View as its row is read", "View bill as its row is read", "in a bill's view as it is seen"])
def test_a_control_drawn_again_as_it_is_read_is_counted_as_unread(page, monkeypatch, words, method, script,
                                                                  new_only):
    """The page draws a copy of the second bill's control in its place while
    the control is being read. Read off the page it shows nothing and has no
    row, and it was taken as no control at all, so the first bill's was the
    only statement of the day. A control that left the page while it was
    read counts as one that would not answer."""
    page.set_content(_page(
        "<div><span>Statement date 01/31/2026</span> <span>Billing statement, Auto</span> "
        "<button data-guid='g-first'>%s</button></div>"
        "<div><span>Statement date 01/31/2026</span> <span>Billing statement, Home</span> "
        "<button data-guid='g-second'>%s</button></div>" % (words, words)))
    if new_only:
        # Every control is one the bill's press brought (_mark_shown).
        page.evaluate("() => { window.__paperpullShownBefore = new WeakSet(); }")
    done = _drawn_again_before(monkeypatch, "g-second", method, getattr(site, script) if script else None)
    survey = site._survey(page, new_only=new_only)
    assert done == ["g-second"], "the copy was never drawn, so this shows nothing"
    assert survey.unread == 1 and [s.name for s in survey] == [words], (survey.unread, [s.name for s in survey])


# --- the shapes the fresh reviews of the Wells Fargo port found -----------------
#
# The two rules the review of this port brought went into the Wells Fargo
# app as well, and two fresh reviews there found these shapes, each one this
# app read the same way. The last digits of a masked number were taken for
# the policy's after a lone bullet or "ending", a link with nothing around
# it read the tabs and menus of the page, and the rules could file a control
# the reading before them had left for a person, or leave its twin
# unrefused. Each shape here is held to the answer the code before these
# rules gave.

BULLET, ELLIPSIS, EN_DASH = chr(0x2022), chr(0x2026), chr(0x2013)


def _form_row(words, date="Issued 01/31/2026"):
    """A row printing its date and a form's name, with a View of its own."""
    return ("<div data-guid='r-tax'><span>%s</span> <span>%s</span> "
            "<button data-guid='g-tax'>View</button></div>" % (date, words))


@pytest.mark.parametrize("words", ["Policy ...4321 %s 1099-INT" % BULLET,
                                   "Whole Life Pol%s 1099-INT" % ELLIPSIS,
                                   "Auto policy %s 1099-INT" % BULLET],
                         ids=["after a bullet", "after a cut nickname", "after a policy's name and a bullet"])
def test_a_form_named_after_a_bullet_or_an_ellipsis_is_never_filed_as_a_statement(page, presses, tmp_path,
                                                                                   words):
    """A form's name printed after a bullet or a nickname cut short, in a
    list item beside a statementPDF link naming only its date. The bullet
    was taken for a mask, so the form was no form, the link read as a
    statement both ways and the 1099 was saved as the day's statement, and
    beside the day's real statement the two were refused as twins. A lone
    bullet masks nothing, and a number with letters after it is a form's
    name."""
    form = ("<ul><li data-guid='r-form'>%s <a data-cy='statementPDF' data-guid='g-form'"
            " aria-label='PDF, January 31, 2026'><span>PDF</span></a></li></ul>" % words)
    page.set_content(_page(form))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    page.set_content(_page(STATEMENT_ROW, form))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


@pytest.mark.parametrize("row", [
    _form_row("Auto policy %s 1099-INT" % BULLET),
    _form_row("1099-INT", date="Year ending 01/31/2026"),
    _form_row("1099", date="Year ending 01/31/2026"),
    _form_row("Interest %s 1099" % BULLET),
    _form_row("Whole Life Pol%s 1099-INT" % ELLIPSIS),
    _form_row("Whole Life Pol%s 1099" % ELLIPSIS),
    _form_row("Fixed Annuity Contra%s 5498" % ELLIPSIS),
    _form_row("Whole Life Pol%s 1099%sINT" % (ELLIPSIS, EN_DASH)),
    _form_row("Annuity Contribution Information... 5498"),
    _form_row("Policy ... 1099-INT"),
    _form_row("Policy ... 1099%sINT" % EN_DASH),
], ids=["a 1099-INT after a bullet", "a 1099-INT after a year ending", "a 1099 after a year ending",
        "a 1099 after a bullet", "a 1099-INT after a cut nickname", "a 1099 after a cut name",
        "a 5498 after a cut name", "a 1099-INT with an en dash after a cut name",
        "a 5498 after three dots ending a word", "a 1099-INT after dots", "a 1099-INT with an en dash after dots"])
def test_a_form_named_after_a_bullet_a_period_or_an_ellipsis_is_still_a_tax_form(page, row):
    """Each was filed as a tax form before, and taken for a masked number's
    digits it was left for a person every run. A period's "ending" is no
    policy's, and the dates the careful reading leaves out had put it just
    before the form. Dots right after a letter cut a name short, and a
    form's name stays a form's name after dots."""
    page.set_content(_page(row))
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


@pytest.mark.parametrize("content, title, kept", [
    (_blocks("<section><p>Tax forms are listed under Tax documents.</p>"
             "<div><a data-cy='statementPDF' data-guid='g-statement' aria-label='PDF, January 31, 2026'>"
             "<span>PDF</span></a></div></section>"
             "<section><div><input type='checkbox' aria-label='Select'> Form 1099-INT "
             "<a data-cy='statementPDF' data-guid='g-1099' aria-label='PDF, January 31, 2026'><span>PDF</span></a>"
             "</div></section>"),
     STATEMENT, (STATEMENT, 2)),
    (_page(MASKED_ROW % ("Policy %s 1099" % (BULLET * 4)), TAX_ROW), TAX, (TAX, 2)),
], ids=["a statement unsure for the words near it", "a statement unsure for its masked number"])
def test_a_document_the_two_rules_leave_unsure_still_stops_its_twin(page, presses, tmp_path, content, title,
                                                                   kept):
    """The rules leave a statement for a person, and a control of the same
    day that reads as its kind both ways, a 1099 whose own part holds a box
    to tick, or the day's 1099-INT beside a bill taken for a tax form
    before, was then alone of its date and kind and was pressed for it. The
    code before refused both as two rows, and so does this one, since a
    control only the rules leave unsure is still an entry of what it was."""
    page.set_content(content)
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [kept]
    saved, trace = _download(page, tmp_path, title)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_a_document_the_two_rules_leave_unsure_stops_no_other_kind_or_day(page, presses, tmp_path):
    """A bill the masked-digits rule leaves unsure is held as the tax form
    both readings took it for before, so it stops only a tax form of its
    own day. The day's statement and a 1099-INT of another day are each
    pressed, as the code before pressed them."""
    page.set_content(_page(MASKED_ROW % "Policy ****1099", STATEMENT_ROW,
                           "<div><span>Issued 12/31/2025</span> <span>Form 1099-INT</span> "
                           "<button data-guid='g-older-tax'>Download 1099-INT</button></div>"))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)
    presses.clear()
    saved, trace = _download(page, tmp_path, "Tax Document - December 31, 2025", iso="2025-12-31")
    assert saved and presses == ["g-older-tax"], (presses, trace)


def test_a_control_unsure_of_its_date_is_no_entry_of_any_date(page, presses, tmp_path):
    """The bill's View beside a View previous statement has no date read the
    old way, since its row names another statement, and its row's date read
    with care, so it is left for a person, as it was before the two rules.
    Only a control the two rules alone leave unsure is held as an entry, so
    the day's statement in a row of its own is pressed, as the code before
    pressed it."""
    page.set_content(_page("<div><span>Statement date 01/31/2026</span> "
                           "<button data-guid='g-bill'>View bill</button> "
                           "<button data-guid='g-previous'>View previous statement</button></div>",
                           STATEMENT_ROW))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_the_two_rules_never_file_what_the_reading_before_them_left_for_a_person(page):
    """The old reading reads no row around a link that names only its date.
    Read with care as before, the masked digits beside it named a form, so
    it was left for a person. With the masked-digits rule alone the careful
    reading came to agree with the old one, and it was filed as a
    statement. The careful reading without the rules must agree too."""
    page.set_content(_page("<ul><li>Policy ****1099 <a data-cy='statementPDF' data-guid='g-x'"
                           " aria-label='PDF, January 31, 2026'><span>PDF</span></a></li></ul>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1


@pytest.mark.parametrize("chrome", [
    "<div role='tablist'><button>Statements</button> <button>Tax forms</button></div>",
    "<div><div role='tab'>Statements</div> <div role='tab'>Tax forms</div></div>",
    "<nav><a href='#'>Tax documents</a></nav>",
], ids=["tab buttons", "tabs by role", "a menu link"])
def test_a_lone_link_dated_only_by_its_name_reads_no_tabs_menus_or_links_around_it(page, presses, tmp_path,
                                                                                   chrome):
    """A statement alone on its page, its statementPDF link naming only its
    date, under tabs or a menu that name tax forms. Read as far as six
    levels up, the tabs made it a tax form read with care, and it was left
    for a person every run. The part read around a link holds no other
    control."""
    page.set_content(_blocks("<div>%s<div><a data-cy='statementPDF' data-guid='g-x'"
                             " aria-label='PDF, January 31, 2026'><span>PDF</span></a></div></div>" % chrome))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-x"], (presses, trace)


# --- the shapes the fresh review of this port found ------------------------------
#
# Ported as the Wells Fargo app has them, the two rules saved this where the
# reading they replace left it for a person. A control nobody sees cut short
# the part read around a link. It is held to the answer of the reading
# before.

@pytest.mark.parametrize("part", [
    "<div><span>Form 1099-INT</span> <form action='#'><input type='hidden' name='id' value='7'>%s</form></div>",
    "<div><a id='y2026'></a><span>Form 1099-INT</span> <div>%s</div></div>",
    "<div><span>Form 1099-INT</span> <button style='visibility:hidden'>Remove</button> <div>%s</div></div>",
], ids=["a hidden field of a form around it", "an empty anchor", "a control shown only on hover"])
def test_a_control_nobody_sees_does_not_cut_short_what_a_link_reads(page, presses, tmp_path, part):
    """A 1099-INT's statementPDF link names only its date, beside the form's
    name, inside a form whose hidden field carries the row's number, beside
    an empty anchor, or beside a control the page shows only on hover.
    Taken for another control, each cut short the part read around the
    link, so it read as a statement both ways and the 1099-INT was saved as
    the day's statement. None is drawn on the page, so the form's name is
    read and the 1099-INT is left for a person, as the reading before left
    it."""
    page.set_content(_blocks(part % ("<a data-cy='statementPDF' data-guid='g-1099' aria-label='PDF, January 31, 2026'>"
                                     "<span>PDF</span></a>")))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)


# --- a size printed after a document's date ------------------------------------
#
# A Wells Fargo tester's recording shows each statement's link naming its
# date and the size of its PDF, "Statement 09/30/26 (123K, PDF)". Printed
# here with a space, "(1099 KB, PDF)", it read as a 1099 the old way and with
# care, so a statement of that size was filed as a Tax Document, and a row
# printing nothing else made a bare View a tax form's control.

def _sized_statement(size, guid="g-statement"):
    return _marked(guid, "Statement date", "01/31/2026 (%s, PDF)" % size)


def _sized_link(size, guid="g-statement"):
    """A row whose marked link names the date and the size itself."""
    return ("<div data-cy='statementRow' data-guid='r-%s'><span>Billing statement</span> "
            "<a data-cy='statementPDF' data-guid='%s'>Statement 01/31/2026 (%s, PDF)</a></div>" % (guid, guid, size))


@pytest.mark.parametrize("size", ["1099 KB", "1098 K", "5498 KB", "1099K", "10990 KB", "123 KB"])
@pytest.mark.parametrize("row", [_sized_statement, _sized_link], ids=["in the row's words", "in the link's name"])
def test_a_statement_s_size_never_makes_it_a_tax_form(page, presses, tmp_path, size, row):
    """A statement of 1099 KB, 1098 K or 5498 KB was filed as that tax form,
    or left for a person when only its link named the size. The size says
    how large the PDF is and nothing of what it is, so no reading reads it,
    and the statement is filed and pressed like any other. One of 1099K,
    10990 KB or 123 KB was a statement before and still is."""
    page.set_content(_page(row(size)))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_a_size_beside_a_view_bill_is_read_by_no_reading(page, presses, tmp_path):
    """The size printed in the row beside a View bill. Read the old way the
    row's 1099 made the bill a tax form, read with care it was a statement,
    and it was left for a person every run."""
    page.set_content(_page("<div data-guid='r-statement'><span>Statement date 01/31/2026</span> "
                           "<span>Billing statement (1099 KB, PDF)</span> "
                           "<button data-guid='g-statement'>View bill</button></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_a_statement_sized_like_a_form_leaves_the_day_s_1099_its_own(page, presses, tmp_path):
    """Read as a tax form, the statement was a second tax form of its day,
    so the day's real 1099 was refused as its twin and neither was saved."""
    page.set_content(_page(_sized_statement("1099 KB"),
                           _marked("g-tax", "Form 1099-INT", "01/31/2026 (45 KB, PDF)")))
    assert sorted((d.title, d.rows) for d in site.collect_download_docs(page)) == [(STATEMENT, 1), (TAX, 1)]
    for title, guid in ((TAX, "g-tax"), (STATEMENT, "g-statement")):
        presses.clear()
        saved, trace = _download(page, tmp_path, title)
        assert saved and presses == [guid], (title, presses, trace)


@pytest.mark.parametrize("size", ["1099 KB", "45 KB"])
@pytest.mark.parametrize("row", [
    "<div data-guid='r-x'><span>01/31/2026 (%s, PDF)</span> <button data-guid='g-x'>View</button></div>",
    "<div data-cy='statementRow' data-guid='r-x'><span>Payment received 01/31/2026 (%s, PDF)</span> "
    "<a data-cy='statementPDF' title='View statement' data-guid='g-x'><span>PDF</span></a></div>",
], ids=["a bare View in a row that names nothing", "a marked link in a payment's row"])
def test_a_size_never_makes_a_row_name_a_document(page, presses, tmp_path, row, size):
    """A bare View is taken only from a row that names a statement or a tax
    form, and a marked link never from a payment's row that names neither.
    A size of 1099 KB named a 1099 for both, so the View was filed as a Tax
    Document and the payment's link was saved as one. Such a row reads as
    it does with any other size, and nothing in it is a document."""
    page.set_content(_page(row % size))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)


@pytest.mark.parametrize("size", ["45 KB", "1099 KB"])
@pytest.mark.parametrize("row, found", [
    ("<div data-guid='r-x'><span>Tax (%s, PDF)</span> <span>Forms 01/31/2026</span> "
     "<button data-guid='g-x'>View</button></div>", []),
    ("<div data-guid='r-x'><span>Tax (%s, PDF)</span> <span>Statement date 01/31/2026</span> "
     "<button data-guid='g-x'>View</button></div>", [(DAY, "statement", STATEMENT)]),
    ("<div data-cy='statementRow' data-guid='r-x'><span>Payment received 01/31/2026</span> "
     "<span>Tax (%s, PDF) forms</span> "
     "<a data-cy='statementPDF' title='View statement' data-guid='g-x'><span>PDF</span></a></div>", []),
    ("<div data-guid='r-x'><span>Premium tax (%s, PDF)</span> <span>Statement date 01/31/2026</span> "
     "<button data-guid='g-x'>View bill</button></div>", [(DAY, "statement", STATEMENT)]),
], ids=["tax and forms beside a bare View", "tax and statement beside a bare View",
        "tax and forms in a payment's row", "premium tax and a statement date"])
def test_the_words_on_either_side_of_a_size_are_never_read_as_one(page, row, found, size):
    """The size was first left out as a space, which joined the words
    around it, so "Tax (45 KB, PDF) Forms" read as "tax forms" and
    "Premium tax (45 KB, PDF) Statement date" as a tax statement. A bare
    View was taken as a tax form's, a payment's link was saved as a Tax
    Document, and a bill was left for a person. The words stay apart, as
    the size kept them, and each row reads as it did with the size in it
    (fresh review of this change)."""
    page.set_content(_page(row % size))
    docs = site.collect_download_docs(page)
    assert _found(docs) == found and docs.unsure == 0


def test_a_bills_statement_of_1099_kb_is_filed_under_statements(billing):
    app = billing(_billing(_sized_statement("1099 KB")))
    app.cmd_discover(quiet=True)
    app.process(app._select())
    assert _filed(app) == {"Statements": ["g-statement"]}


@pytest.mark.parametrize("words, date", [("Form 1099-INT", "01/31/2026 (1099 KB, PDF)"),
                                         ("Form 1099 MISC", "01/31/2026 (45 KB, PDF)"),
                                         ("Tax form", "01/31/2026 (5498 KB, PDF)"),
                                         ("Issued", "01/31/2026 (1099, PDF)")],
                         ids=["a 1099-INT of 1099 KB", "a 1099-MISC written with a space", "a tax form of 5498 KB",
                              "a form's number where a size would be"])
def test_a_form_s_own_name_is_still_read_beside_its_size(page, words, date):
    """Only a number with K or M in parentheses before PDF is a size and
    goes unread. A form's own name is read as it always was, 1099 MISC
    among them, which is how a 1099-MISC may be written."""
    page.set_content(_page(_marked("g-tax", words, date)))
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


# --- a document's button drawn as an input -------------------------------------
#
# The core finds a document's control by its role and its name, and an
# <input> of type button, submit, image or reset has a button's role. Both
# readings counted only links and buttons as the page's document controls,
# so such an input was no other document control to them. The words of its
# part were read as another control's, the date of its row was lent to a row
# that prints none, two such parts under one date heading were one entry,
# and a list holding its row was taken for the row of a bill beside it. Each
# shape here is read the way the same page drawn with buttons is, and an
# input the core never finds as a button, a box to tick or a text field, is
# still no document control.

INPUT_KINDS = ("button", "submit", "image", "reset")


def _input(kind, guid, label):
    """A document's button drawn as an <input> of `kind`, named `label` for
    a screen reader. An image is given a size so that it is drawn."""
    size = " src='data:,' width='24' height='24'" if kind == "image" else ""
    return "<input type='%s' data-guid='%s' aria-label='%s'%s>" % (kind, guid, label, size)


@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_two_bills_under_one_date_heading_drawn_as_inputs_are_two_documents(page, presses, tmp_path, kind):
    """Each bill's part prints words of its own, and drawn with buttons the
    two are refused as two rows. Drawn as inputs, neither was another
    document control to the other, so the part holding both was the entry
    of each, the two were one document, and the first bill's statement was
    pressed for the day's."""
    page.set_content(_blocks("<div data-guid='d-day'><h3>January 31, 2026</h3>"
                             "<div>Auto policy bill %s</div><div>Home policy bill %s</div></div>"
                             % (_input(kind, "g-first", "View bill"), _input(kind, "g-second", "View bill"))))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 2)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def _input_statement_row(kind):
    """A bill's statement row whose button is drawn as an input."""
    return ("<div data-guid='r-statement'><span>Statement date 01/31/2026</span> "
            "<span>Billing statement</span> %s</div>" % _input(kind, "g-statement", "View bill"))


@pytest.mark.parametrize("first", ["statement", "tax form"])
@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_a_tax_row_without_a_date_borrows_none_from_a_statement_drawn_as_an_input(page, presses, tmp_path,
                                                                                 kind, first):
    """The 1099-INT's row prints no date, so the row rule climbs to the list
    around every row, and beside a statement row drawn with a button it
    finds the list holding another row and gives no date. Drawn as an
    input, the statement's button was no other document control in the
    list, so the 1099-INT took the statement row's date, and it was filed
    and pressed as the day's tax form."""
    rows = (_input_statement_row(kind), UNDATED_TAX_ROW)
    page.set_content(_page(*(rows if first == "statement" else rows[::-1])))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_a_bill_naming_its_date_beside_a_1099_row_drawn_as_an_input_is_its_statement(page, presses, tmp_path,
                                                                                    kind):
    """The bill's control names its own date, in a list that prints a date
    and holds the day's 1099 row. Drawn with a button, the 1099's row is
    another row to the row rule, so the list is no row of the bill's, and
    the bill is filed by its own words. Drawn as an input, the row rule took
    the list for the bill's row and read the 1099's words in it, so the bill
    was left for a person every run."""
    page.set_content(_page("<div><span>Statement date 01/31/2026</span> "
                           "<div><button data-guid='g-bill' aria-label='View bill for January 31, 2026'>View</button>"
                           "</div><div><span>Issued 01/31/2026</span> <span>Form 1099-INT</span> %s</div></div>"
                           % _input(kind, "g-1099", "Download 1099-INT")))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT), (DAY, "tax", TAX)] and docs.unsure == 0
    for title, guid in ((STATEMENT, "g-bill"), (TAX, "g-1099")):
        presses.clear()
        saved, trace = _download(page, tmp_path, title)
        assert saved and presses == [guid], (title, presses, trace)


# A View that names no kind, and beside it a part naming the 1099-INT that
# holds the 1099-INT's own button.
VIEW_BESIDE_A_1099 = ("<div>01/31/2026 <button data-guid='g-view'>View</button> "
                      "<div><span>Form 1099-INT</span> %s</div></div>")


@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_a_plain_view_beside_a_1099_drawn_as_an_input_is_never_pressed_for_it(page, presses, tmp_path, kind):
    """Drawn with a button, the 1099-INT's part is the 1099-INT's alone, so
    View is the statement read with care and the tax form read the old way,
    and it is left for a person. Drawn as an input, that part was read as
    View's too, both readings made View the tax form, and View, coming
    first, was pressed for the 1099-INT."""
    page.set_content(_blocks(VIEW_BESIDE_A_1099 % _input(kind, "g-tax", "Download")))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)
    presses.clear()
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)


def test_a_run_files_a_1099_drawn_as_an_input_from_its_own_button(page, run):
    """The shape above through a whole run. The plain View was saved under
    Tax Documents, and the 1099-INT itself never was."""
    page.set_content(_blocks(VIEW_BESIDE_A_1099 % _input("button", "g-tax", "Download")))
    run.cmd_discover(quiet=True)
    run.process(run._select())
    assert _filed(run) == {"Tax Documents": ["g-tax"]}


@pytest.mark.parametrize("content", [
    "<table><tbody><tr><td>Statement date 01/31/2026</td><td>Billing statement</td><td>%s %s</td></tr>"
    "</tbody></table>",
    "<div><span>01/31/2026</span> Billing statement %s %s</div>",
    "<div>01/31/2026 Billing statement <span>On screen %s</span> <span>As a file %s</span></div>",
], ids=["in a table row", "on a card", "with a caption beside each"])
@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_view_and_download_drawn_as_inputs_stay_one_document(page, presses, tmp_path, kind, content):
    """Counted as document controls, two inputs of one entry still fetch one
    document, as View bill and Download PDF drawn with buttons do."""
    page.set_content(_blocks(content % (_input(kind, "g-view", "View bill"),
                                        _input(kind, "g-download", "Download PDF"))))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-view"], (presses, trace)


@pytest.mark.parametrize("kind", ["checkbox", "text"])
def test_a_box_to_tick_named_like_a_document_is_still_no_document_control(page, presses, tmp_path, kind):
    """The core finds a document's control by a button's or a link's role
    alone, so it never hands either reading a box to tick or a text field,
    whatever its label says, and neither is another document control to
    them. Counted as one, the box's own dated row inside the statement's row
    would make that row a list, and the statement would have no date of its
    own and be left for a person."""
    page.set_content(_blocks("<div><span>Statement date 01/31/2026</span> <span>Billing statement</span> "
                             "<button data-guid='g-statement'>View bill</button> "
                             "<div>12/31/2025 <input type='%s' aria-label='View bill'></div></div>" % kind))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


# --- the shapes the fresh review of the Wells Fargo port of these fixes found ---
#
# The fixes this port took from its review went into the Wells Fargo app,
# and a fresh review there found two shapes all three apps filed as a Tax
# Document by all three readings. A bill's statementPDF link naming the
# policy's masked number, ending 1099, and its date, under words that name
# tax documents, and a masked number with a dash and E-Bill after it. Each is
# now left for a person.

MASKED_STATEMENT_LINK = "<a data-cy='statementPDF' data-guid='g-masked'>Policy ****1099 01/31/2026 PDF</a>"


@pytest.mark.parametrize("content", [
    _blocks("<div><h2>Statements and tax documents</h2><form action='#'><div>%s</div></form></div>"
            % MASKED_STATEMENT_LINK),
    _blocks("<div><h2>Statements and tax documents</h2><form action='#'>"
            "<input type='hidden' name='id' value='7'><div>%s</div></form></div>" % MASKED_STATEMENT_LINK),
    _blocks("<div><h2>Tax documents</h2><div>%s</div></div>" % MASKED_STATEMENT_LINK),
    _blocks("<table><tbody><tr><td>Statements and tax documents</td><td>%s</td></tr></tbody></table>"
            % MASKED_STATEMENT_LINK),
], ids=["under a heading", "beside a hidden field", "under a heading of tax documents alone",
        "in a row naming tax documents"])
def test_a_bill_naming_only_a_masked_number_is_never_filed_as_a_tax_form_by_words_around_it(page, presses,
                                                                                           tmp_path, content):
    """The bill's statementPDF link names the policy's masked number and its
    date and no kind. The careful reading without the rules and the old
    reading took the digits for the form, and the careful reading took them
    for the policy's and read tax documents in the words above the link or
    beside it, so all three agreed and the bill was saved as the day's Tax
    Document. Two readings that agree only through the digits say nothing of
    its kind, so it is left for a person."""
    page.set_content(content)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [NONE_OF_THIS_KIND], trace


def test_a_bill_left_for_a_person_for_its_masked_number_still_stops_the_day_s_1099(page, presses, tmp_path):
    """It is held as the tax form all three readings filed it as, so the
    day's 1099-INT beside it is still refused as its twin, as it was
    before."""
    page.set_content(_blocks("<div><h2>Statements and tax documents</h2><div>%s</div></div>" % MASKED_STATEMENT_LINK,
                             TAX_ROW))
    docs = site.collect_download_docs(page)
    assert [(d.title, d.rows) for d in docs] == [(TAX, 2)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


@pytest.mark.parametrize("row", [MASKED_ROW % policy for policy in (
    "Policy ****1099-E-Bill", "Policy ****1099-E-Statement", "Policy ****1099%sE%sBill" % (EN_DASH, EN_DASH))]
    + ["<div data-cy='statementRow' data-guid='r-masked'><span>Statement date 01/31/2026</span> "
       "<a data-cy='statementPDF' data-guid='g-masked'>Policy ****1099-E-Statement PDF</a></div>"],
    ids=["E-Bill after a hyphen", "E-Statement after a hyphen", "en dashes", "in a statementPDF link's own words"])
def test_a_masked_number_with_a_dash_and_e_bill_after_it_is_still_the_policy_s(page, presses, tmp_path, row):
    """The bill prints the policy's masked number with a dash and E-Bill or
    E-Statement after it. E is a form's letter, as in 1098-E, and the dash
    after it was taken for the end of the form's name, so the digits named
    a form and the bill was saved as the day's Tax Document. A form's letter
    with a dash and a letter after it starts another word, so the bill is
    left for a person, and the day's other bill is still its own."""
    page.set_content(_page(row))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    page.set_content(_page(STATEMENT_ROW, row))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


@pytest.mark.parametrize("words", ["Annuity ****1099-R Distributions", "Annuity ****1099-R-2025"],
                         ids=["a space after the letter", "a dash and a year after the letter"])
def test_a_form_s_letters_before_a_space_or_a_dash_and_a_year_still_name_the_form(page, words):
    """A form's letters after a masked number still name the form when a
    space, or a dash and a number, follow them."""
    page.set_content(_page(_form_row(words)))
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


@pytest.mark.parametrize("words", ["%s1099-R-Annuity distribution" % BULLET, "%s1099 Annuity distribution" % BULLET,
                                   "Annuity ****1099-R-IRA"],
                         ids=["a 1099-R after a bullet with a word after it", "a 1099 after a bullet",
                              "a form's letter and a word after a mask"])
def test_a_link_naming_only_its_date_beside_a_masked_number_is_filed_as_neither(page, presses, tmp_path, words):
    """A form's statementPDF link names only its date, for a screen reader,
    beside the form's number printed after a bullet or a mask. The careful
    reading took the digits for a policy's and read no other kind around the
    link, the other two readings read nothing around it, and all three filed
    it as a bill. A 1099 after a bullet was saved as the day's bill that
    way, and once a form's letter with a dash and a letter after it was no
    form's name, so was a 1099-R-Annuity. A masked number's digits never
    decide a kind, so it is left for a person."""
    page.set_content(_page(OTHER_DAY_ROW, "<div><span>%s</span> %s</div>" % (words, DATED_BY_NAME_LINK)))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [("2025-12-31", "statement", "Account Statement - December 31, 2025")]
    assert docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)


def test_a_bill_link_naming_its_kind_under_a_masked_policy_is_still_filed(page, presses, tmp_path):
    """A bill's statementPDF link names itself a statement and its date, for
    a screen reader, under a heading printing the policy's masked number.
    Its own words decide its kind before that number is read, so it is
    filed and pressed as before."""
    page.set_content(_blocks("<div><h2>Auto policy ****1099</h2><div><a data-cy='statementPDF' data-guid='g-statement'"
                             " aria-label='Statement, January 31, 2026'><span>PDF</span></a></div></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_a_statement_already_in_manual_review_named_in_full_stays_where_it_is(tmp_path, monkeypatch):
    """A record a run started in another folder saved from 0.62.0 to 0.65.0
    names its file by its full path, and a run now names its folders from
    the install (#166). A statement set aside again for the same PDF as
    another bill's, already in Manual Review, keeps its name there, as one
    named from the install does."""
    install = tmp_path / "Example Install"
    install.mkdir()
    monkeypatch.chdir(install)
    app = receipt_app(app_mod, install, output_dir=".")
    app.paths.ensure()
    held = install / "Manual Review" / ("%s Account Statement.pdf" % DAY)
    held.write_bytes(text_pdf(["a statement set aside before"]))
    app.progress.update("k", {"pdf_path": str(held), "pdf_filename": held.name, "date": DAY,
                              "state": "Needs Manual Review", "downloaded_ok": False})
    app._distrust("k")
    assert sorted(p.name for p in held.parent.iterdir()) == [held.name]
    assert app.progress.get("k")["pdf_path"] == str(held)
