"""A press for a document lands on that document and nothing else.

Review of the third repair of #36 found the download could still press
the other document of a date, or an insert, by way of the element around
them. Any element whose words began with the title then PDF counted as
the document's name, so a cell holding this document's link beside the
other document's, or beside an insert, was pressed as this document's
name once its own link brought nothing, and a press on the middle of a
cell lands on whatever sits there. The same review found four smaller
ways. A notice link worded without "insert" was pressed after the
document's own link. The guard read the document's title in place of a
named link's own words. A PDF answering the last document's click could
be caught during this one's. One row carrying a date the lists held two
documents on was taken as holding only this one.

Everything here is invented. Each page records where every click truly
landed, in the capture phase before any handler runs, so the tests see
the element a press reached and not the one the app meant to press. They
drive a real browser, since where a press on a cell's middle lands is
what a fake page gets wrong.
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
ALONE = "2025-10-31"

# Where each click landed, by the data-guid around its target.
LISTENER = ("<script>window.hits = [];"
            "document.addEventListener('click', e => { const g = e.target.closest('[data-guid]');"
            " window.hits.push(g ? g.dataset.guid : e.target.tagName.toLowerCase());"
            " if (!g || g.tagName.toLowerCase() !== 'input') e.preventDefault(); }, true);</script>")

DOWNLOAD = ("<button type='button' data-guid='download' onclick=\"window.handed = Array.from("
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
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)


@pytest.fixture
def presses(monkeypatch):
    """Stands in for the catch. It presses the element the way the real
    catch does and remembers where the press landed. A press that lands
    on a guid in `brings` hands over a PDF."""
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
        return any(h in brings for h in landed)
    monkeypatch.setattr(site, "_catch_pdf", fake)
    return hits, brings


def _listed(monkeypatch, iso, titles):
    monkeypatch.setattr(site, "_LISTED", {iso: len(titles)})
    monkeypatch.setattr(site, "_LISTED_TITLES", {iso: set(titles)})


def _walk(page, iso, title=BROKERAGE):
    trace: list = []
    got = site._try_every_way(page, Path("."), iso, Path("unused.pdf"), title, trace)
    return got, trace


def _row_entry(trace):
    return next(t for t in trace if t.get("note") == "the document's row")


# --- an element around the document's name ---------------------------------

def test_a_wrapper_holding_both_documents_links_is_never_pressed(page, presses, monkeypatch):
    """One wrapper holds "<title> PDF" links for both documents of the date.
    Its words began with this title then PDF, so it counted as the name,
    and the press on its middle landed on the other document's link."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content("<ul><li><span>11/30/25</span> <div style='display:inline-block'>"
                     "<a href='#' data-guid='g-mine' style='display:block'>%s PDF</a>"
                     "<a href='#' data-guid='g-theirs' style='display:block;padding:30px 0'>%s PDF</a>"
                     "</div></li></ul>%s" % (BROKERAGE, RETIREMENT, LISTENER))
    got, trace = _walk(page, SHARED)
    hits, _brings = presses
    assert not got and hits == ["g-mine"], hits
    assert _row_entry(trace)["why_not"] == "the row names another document of this date"


def test_a_cell_that_prints_both_titles_is_never_pressed(page, presses, monkeypatch):
    """A cell prints both titles as text, each with its own PDF link. Every
    lookup refuses, and the whole download presses nothing."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content("<table><tbody><tr><td>11/30/25</td><td style='text-align:center'>"
                     "%s <a href='#' data-guid='g-mine'>PDF</a><br>"
                     "%s <a href='#' data-guid='g-theirs' style='display:inline-block;padding:20px 60px'>PDF</a>"
                     "</td></tr></tbody></table>%s" % (BROKERAGE, RETIREMENT, LISTENER))
    trace: list = []
    assert not site.download_bill(page, Path("."), SHARED, Path("unused.pdf"), BROKERAGE, trace)
    hits, _brings = presses
    assert hits == [], hits
    assert [t["way"] for t in trace if t.get("note", "").startswith("not sure which")] == \
        ["row link", "control", "row by date"], trace


def test_a_cell_that_starts_with_this_documents_link_is_not_its_name(page, presses, monkeypatch):
    """The cell's words are this document's link, "<title> PDF for
    <account>", then the other document's. They start the way the
    document's name does, but the cell holds another link, so only the
    link itself is pressed."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content("<table><tbody><tr><td>11/30/25</td><td style='text-align:center'>"
                     "<a href='#' data-guid='g-mine'>%s PDF for %s</a><br>"
                     "<a href='#' data-guid='g-theirs' style='display:inline-block;padding:20px 60px'>%s PDF</a>"
                     "</td></tr></tbody></table>%s" % (BROKERAGE, ACCOUNT, RETIREMENT, LISTENER))
    got, trace = _walk(page, SHARED)
    hits, _brings = presses
    assert not got and hits == ["g-mine"], hits
    kinds = [(c["kind"], c["left_out"]) for c in _row_entry(trace)["candidates"]]
    assert kinds.count(("title", False)) == 1, kinds


def test_an_insert_beside_the_link_in_one_cell_is_never_pressed(page, presses, monkeypatch):
    """One document on its date. Its cell holds its link and an insert
    link. The cell passed for the name, and the insert passed as not an
    insert, since everything after "PDF for" was taken off its words."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<table><tbody><tr><td>10/31/25</td><td style='text-align:center'>"
                     "<a href='#' data-guid='g-mine'>%s PDF for %s</a><br>"
                     "<a href='#' data-guid='g-insert' style='display:inline-block;padding:20px 80px'>Insert</a>"
                     "</td></tr></tbody></table>%s" % (BROKERAGE, ACCOUNT, LISTENER))
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert not got and hits == ["g-mine"], hits


def test_his_shape_presses_the_documents_own_link(page, presses, monkeypatch):
    """The positive twin, in the shape his page has, one table row per
    document, the link named "<title> PDF for <account>" and the insert in
    a cell of its own. Each document's own link is pressed and saved."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", BOTH)
    rows = "".join(
        "<tr><td>11/30/25</td><td>%s</td>"
        "<td><a href='#' data-guid='g-%s' aria-label='%s PDF for %s'>%s</a></td>"
        "<td><a href='#' data-guid='g-%s-insert'>Insert</a></td></tr>" % (ACCOUNT, g, t, ACCOUNT, t, g)
        for g, t in (("theirs", RETIREMENT), ("mine", BROKERAGE)))
    page.set_content("<table><tbody>%s</tbody></table>%s" % (rows, LISTENER))
    hits, brings = presses
    brings.update({"g-mine", "g-theirs"})
    assert site.download_bill(page, Path("."), SHARED, Path("unused.pdf"), BROKERAGE, [])
    assert site.download_bill(page, Path("."), SHARED, Path("unused.pdf"), RETIREMENT, [])
    assert hits == ["g-mine", "g-theirs"], hits


# --- what names the document ------------------------------------------------

def test_the_name_is_the_title_then_pdf_then_an_account_and_nothing_else():
    assert site.names_title(BROKERAGE, BROKERAGE)
    assert site.names_title("%s PDF" % BROKERAGE, BROKERAGE)
    assert site.names_title("  %s  pdf  for  %s " % (BROKERAGE, ACCOUNT), BROKERAGE)
    for other in ("%s PDF Privacy Notice" % BROKERAGE, "%s PDF %s PDF" % (BROKERAGE, RETIREMENT),
                  "%s PDF insert" % BROKERAGE, "%s Summary" % BROKERAGE, "View %s" % BROKERAGE):
        assert not site.names_title(other, BROKERAGE), other


def test_a_link_whose_words_run_on_past_the_title_is_not_its_name(page, presses, monkeypatch):
    """"<title> PDF Privacy Notice" starts the way the document's name does
    and hands over a notice. It was pressed as the name once the
    document's own link brought nothing."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <a href='#' data-guid='g-mine'>%s</a> "
                     "<a href='#' data-guid='g-notice'>%s PDF Privacy Notice</a></li></ul>%s"
                     % (BROKERAGE, BROKERAGE, LISTENER))
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert not got and hits == ["g-mine"], hits


# --- inserts ----------------------------------------------------------------

def test_what_an_element_shows_keeps_every_word_when_judged_for_an_insert():
    """Only a label has the account after "PDF for" taken off. What an
    element shows can be a whole cell, and taking off everything after
    "PDF for" there took the insert's word with it."""
    shows = "%s PDF for %s Insert" % (BROKERAGE, ACCOUNT)
    assert site._is_insert_text((shows,), BROKERAGE)
    assert not site._is_insert_text((BROKERAGE,), BROKERAGE, ("%s PDF for Client Reserve - 4242" % BROKERAGE,))


def test_a_link_that_shows_an_insert_after_the_account_is_passed_over(page):
    """The insert's link shows "<title> PDF for <account> Insert". It
    comes first in the row and names the document by the rule, so it was
    taken for the document's own link."""
    page.set_content("<table><tbody><tr><td>05/31/25</td>"
                     "<td><a href='#' data-guid='g-insert'>%s PDF for %s Insert</a></td>"
                     "<td><a href='#' data-guid='g-doc' aria-label='%s PDF for %s'>%s</a></td>"
                     "</tr></tbody></table>" % (BROKERAGE, ACCOUNT, BROKERAGE, ACCOUNT, BROKERAGE))
    el, label = site._row_link_for(page, "2025-05-31", BROKERAGE, [])
    assert el is not None and el.get_attribute("data-guid") == "g-doc" and label == BROKERAGE


# --- a control that says something else ----------------------------------

@pytest.mark.parametrize("beside, pressed", [
    ("Privacy Notice", ["g-mine"]),               # names some other thing
    ("View", ["g-mine", "g-beside"]),             # a bare action may be this document's
    ("Download PDF", ["g-mine", "g-beside"]),
])
def test_a_notice_in_the_documents_row_is_never_pressed_for_it(page, presses, monkeypatch, beside, pressed):
    """The lists held this one document on the date and its row names it.
    When its own link brings nothing, a link beside it that says something
    other than View or Download is a notice or another document, and only
    an insert's own word used to keep one from being pressed."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <a href='#' data-guid='g-mine'>%s</a> "
                     "<a href='#' data-guid='g-beside'>%s</a></li></ul>%s" % (BROKERAGE, beside, LISTENER))
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert not got and hits == pressed, hits


UNNAMED = ("<table><tbody><tr><td>10/31/25</td><td>%s</td>%s"
           "<td><a href='#' data-guid='g-doc'>Invented Single Statement</a></td>"
           "<td><a href='#' data-guid='g-insert'>Client Relationship Summary</a></td></tr></tbody></table>")


@pytest.mark.parametrize("notice, taken", [("", "g-doc"),
                                           ("<td><a href='#' data-guid='g-notice'>Privacy Notice</a></td>", "")])
def test_a_row_that_names_nothing_uses_its_other_link_only_when_there_is_one(page, presses, monkeypatch,
                                                                            notice, taken):
    """The lists held this one document on the date, and the row prints it
    under another name. Its one link that is not an insert is its own. With
    a notice beside it there are two, and either could be, so neither is
    pressed. The first link was taken, the notice here."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content((UNNAMED % (ACCOUNT, notice)) + LISTENER)
    el, _label = site._row_link_for(page, ALONE, BROKERAGE, [])
    assert (el.get_attribute("data-guid") if el is not None else "") == taken
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert hits == ([taken] if taken else []), hits


def test_a_notice_beside_a_view_in_a_row_that_names_nothing_is_never_pressed(page, presses, monkeypatch):
    """The lists held this one document on the date, and its row prints
    neither its title nor another name for it. The View is its own. A
    notice beside it, worded without "insert", was pressed next (review)."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>%s</td>"
                     "<td><a href='#' data-guid='g-view'>View</a></td>"
                     "<td><a href='#' data-guid='g-notice'>Important Notice</a></td></tr></tbody></table>%s"
                     % (ACCOUNT, LISTENER))
    el, _label = site._row_link_for(page, ALONE, BROKERAGE, [])
    assert el is not None and el.get_attribute("data-guid") == "g-view"
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert not got and hits == ["g-view"], hits


def test_the_other_title_anywhere_in_the_row_keeps_its_view_unpressed(page, presses, monkeypatch):
    """The row names this document and holds a View and a link reading
    "View <the other title>". Only a word that started with the other
    title said the row held it, so the View was pressed and could be the
    other document's."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content("<ul>"
                     "<li><span>11/30/25</span> <span data-guid='g-mine-title'>%s</span> "
                     "<a href='#' data-guid='g-view'>View</a> <a href='#' data-guid='g-theirs'>View %s</a></li>"
                     "<li><span>11/30/25</span> <span>Invented account notice</span></li>"
                     "</ul>%s" % (BROKERAGE, RETIREMENT, LISTENER))
    got, trace = _walk(page, SHARED)
    hits, _brings = presses
    assert not got and hits == ["g-mine-title"], hits
    assert _row_entry(trace)["why_not"] == "the row names another document of this date"


def test_a_title_inside_this_documents_own_title_is_not_another_document(page, presses, monkeypatch):
    """The positive twin. The other document's title is a piece of this
    one's, "Annual <title>" beside "<title>". This document's own words
    carrying it do not make its row hold the other, so its View is used."""
    annual = "Annual " + BROKERAGE
    _listed(monkeypatch, SHARED, [annual, BROKERAGE])
    page.set_content("<ul>"
                     "<li><span>11/30/25</span> <span>%s</span> <a href='#' data-guid='g-theirs'>View</a></li>"
                     "<li><span>11/30/25</span> <span data-guid='g-mine-title'>%s</span> "
                     "<a href='#' data-guid='g-mine'>View</a></li>"
                     "</ul>%s" % (BROKERAGE, annual, LISTENER))
    got, trace = _walk(page, SHARED, annual)
    hits, _brings = presses
    assert not got and hits == ["g-mine-title", "g-mine"], hits
    assert _row_entry(trace)["holds_only_this_document"] is True


@pytest.mark.parametrize("row", [
    # the other document printed under words that are not its listed title
    "<ul><li><span>11/30/25</span> <a href='#' data-guid='g-mine'>%s</a> "
    "<a href='#' data-guid='g-theirs'>Retirement Summary PDF</a></li></ul>" % BROKERAGE,
    # and a bare action beside this document's name
    "<table><tbody><tr><td>11/30/25</td><td><a href='#' data-guid='g-mine'>%s</a></td>"
    "<td><button data-guid='g-theirs'>Download statement</button></td></tr></tbody></table>" % BROKERAGE,
])
def test_one_row_carrying_a_date_the_lists_held_two_on_holds_both(page, presses, monkeypatch, row):
    """One row prints the date and the lists held two documents on it, so
    the row carries both, whatever words the other one is given. Only this
    document's own name is pressed."""
    _listed(monkeypatch, SHARED, [BROKERAGE, RETIREMENT])
    page.set_content(row + LISTENER)
    got, trace = _walk(page, SHARED)
    hits, _brings = presses
    assert not got and hits and set(hits) == {"g-mine"}, hits
    assert _row_entry(trace)["why_not"] == "fewer rows carry this date than the lists held documents"


# --- the guard reads the element's own words ------------------------------

def test_a_named_link_whose_own_words_are_forbidden_is_not_taken(page):
    """The link's label names the document and what it shows says to
    cancel an order. The guard read the document's title in its place."""
    page.set_content("<table><tbody><tr><td>05/31/25</td>"
                     "<td><a href='#' data-guid='g-x' aria-label='%s PDF for %s'>Cancel order</a></td>"
                     "</tr></tbody></table>" % (BROKERAGE, ACCOUNT))
    assert site._row_link_for(page, "2025-05-31", BROKERAGE, []) == (None, "")


@pytest.mark.parametrize("label, listed", [
    ("%s PDF for %s" % (BROKERAGE, ACCOUNT), {}),        # named by its label
    ("View statement", {"2025-05-31": 1}),             # the one control of a date of one document
])
def test_a_control_whose_own_words_are_forbidden_is_not_taken(page, monkeypatch, label, listed):
    """The control's label passed and what it shows was never read."""
    monkeypatch.setattr(site, "_LISTED", listed)
    monkeypatch.setattr(site, "_LISTED_TITLES", {d: {BROKERAGE} for d in listed})
    page.set_content("<div id='rows'><div class='doc'><span>05/31/25</span> "
                     "<a href='#' data-guid='g-x' aria-label='%s'>Cancel order</a></div></div>" % label)
    assert site._control_for(page, "2025-05-31", BROKERAGE, []) == (None, "")


def test_a_name_whose_label_is_forbidden_is_not_pressed(page, presses, monkeypatch):
    """What it shows is the title, its label says to sell. Only what it
    showed was read."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> "
                     "<a href='#' data-guid='g-x' aria-label='Sell shares'>%s</a></li></ul>%s"
                     % (BROKERAGE, LISTENER))
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert not got and hits == [], hits


def test_the_account_a_link_names_is_not_read_as_an_action(page, presses, monkeypatch):
    """The account after "PDF for" is the account's name, which a person
    chooses, not what the link does. A nickname with a guarded word in it
    refused the document's own link."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<div id='rows'><div class='doc'><span>10/31/25</span> "
                     "<a href='#' data-guid='g-mine' aria-label='%s PDF for Invented Rollover - 4242'>%s</a>"
                     "</div></div>%s" % (BROKERAGE, BROKERAGE, LISTENER))
    hits, brings = presses
    brings.add("g-mine")
    assert site.download_bill(page, Path("."), ALONE, Path("unused.pdf"), BROKERAGE, [])
    assert hits == ["g-mine"], hits
    assert site._guard_word("%s PDF for Invented Trading - 4242" % BROKERAGE, BROKERAGE) == "%s PDF" % BROKERAGE
    assert site._guard_word("Transfer %s PDF for x" % BROKERAGE, BROKERAGE) == "Transfer %s PDF for x" % BROKERAGE


@pytest.mark.parametrize("box", [
    "<input type='checkbox' data-guid='g-box' aria-label='Enroll in paperless delivery'>",
    "<label><input type='checkbox' data-guid='g-box'> Enroll in paperless delivery</label>",
])
def test_a_box_whose_words_are_forbidden_is_not_ticked(page, presses, monkeypatch, box):
    """The row's box was ticked without its words passing the guard."""
    _listed(monkeypatch, ALONE, [BROKERAGE])
    page.set_content("<ul><li><span>10/31/25</span> <span>%s</span> %s</li></ul>%s%s"
                     % (BROKERAGE, box, DOWNLOAD, LISTENER))
    got, _trace = _walk(page, ALONE)
    hits, _brings = presses
    assert not got and "download" not in hits and "g-box" not in hits, hits
    assert page.evaluate("document.querySelector('[data-guid=g-box]').checked") is False


# --- one box, drawn by a web component --------------------------------------

SHADOW_BOX = """
<ul><li><span>10/31/25</span> <span>%s</span> <doc-box data-guid='g-box'></doc-box></li></ul>
%s
<script>
class DocBox extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    this.setAttribute('role', 'checkbox');
    this.setAttribute('aria-checked', 'false');
    const sr = this.attachShadow({mode: 'open'});
    sr.innerHTML = "<input type='checkbox' tabindex='-1' style='pointer-events:none'>";
    this.addEventListener('click', () => {
      const i = sr.querySelector('input');
      i.checked = !i.checked;
      this.setAttribute('aria-checked', i.checked ? 'true' : 'false');
    });
  }
}
customElements.define('doc-box', DocBox);
</script>
"""


def test_a_box_drawn_in_a_shadow_root_counts_once(page, monkeypatch):
    """A role=checkbox element whose native box sits in its shadow root was
    counted as two ticked boxes, so its own document was never handed
    over."""
    pressed: list = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        if label != "Download":
            return False
        el.click()
        pressed.append(label)
        return True
    monkeypatch.setattr(site, "_catch_pdf", fake)
    page.set_content(SHADOW_BOX % (BROKERAGE, DOWNLOAD))
    box = page.locator("doc-box")
    assert site._ticked(page) == 0
    box.click()
    assert site._ticked(page) == 1
    box.click()
    trace: list = []
    assert site._tick_and_download(page, box, Path("."), Path("unused.pdf"), trace), trace
    assert pressed == ["Download"]
    assert page.evaluate("document.querySelector('doc-box').getAttribute('aria-checked')") == "false"


# --- a late answer to an earlier request -----------------------------------

def test_a_late_pdf_answering_an_earlier_request_is_not_this_documents(browser, tmp_path, monkeypatch):
    """A PDF asked for before this attempt, the last document's, arrives
    after this document's press. The catch took any PDF answer that
    arrived while it waited, and saved it under this document's name."""
    ctx = browser.new_context()
    held: list = []

    def answer(route):
        url = route.request.url
        if url.endswith("/docs/earlier.pdf"):
            held.append(route)
            return None
        if url.endswith("/docs/this.pdf"):
            return route.fulfill(status=200, content_type="application/pdf",
                                 body=b"%PDF-1.4\n% invented this\n%%EOF\n")
        return route.fulfill(status=200, content_type="text/html", body=(
            "<!doctype html><html><body><a id='doc' href='#' onclick=\"event.preventDefault();"
            "setTimeout(() => fetch('/docs/this.pdf'), 1500)\">%s</a>"
            "<script>fetch('/docs/earlier.pdf')</script></body></html>" % BROKERAGE))
    ctx.route("https://us.etrade.com/**", answer)
    real_take = site._take_new_pdf

    def late(dl_dir, seen, out_path):
        """The first look for a PDF after the press is when the earlier
        answer arrives, well before this document's own, 1.5 s later."""
        while held:
            held.pop().fulfill(status=200, content_type="application/pdf",
                               body=b"%PDF-1.4\n% invented earlier\n%%EOF\n")
        return real_take(dl_dir, seen, out_path)
    try:
        pg = ctx.new_page()
        pg.goto("https://us.etrade.com/etx/pxy/accountdocs")
        pg.wait_for_timeout(300)
        assert held, "the earlier request is waiting for its answer"
        out = tmp_path / "out.pdf"
        trace: list = []
        monkeypatch.setattr(site, "_take_new_pdf", late)
        assert site._catch_pdf(pg, pg.locator("#doc"), BROKERAGE, out, trace, None)
        assert b"invented this" in out.read_bytes(), out.read_bytes()
        assert {"note": "a PDF answering an earlier request was left alone", "type": "pdf"} in trace, trace
    finally:
        ctx.close()


# --- a step that sees no link ---------------------------------------------

def _slotted_table():
    """His table's other possible shape. The rows sit in a web component's
    shadow root and each link is slotted in from outside it, where a row's
    own links cannot be seen."""
    docs = [(RETIREMENT, "g-theirs"), (BROKERAGE, "g-mine")]
    light = "".join("<a slot='d%d' href='#' data-guid='%s' aria-label='%s PDF for %s'>%s</a>"
                    % (i, g, t, ACCOUNT, t) for i, (t, g) in enumerate(docs))
    rows = "".join("<tr><td>11/30/25</td><td>%s</td><td><slot name='d%d'></slot></td></tr>" % (ACCOUNT, i)
                   for i in range(len(docs)))
    return ("<doc-table>%s</doc-table><script>"
            "class DocTable extends HTMLElement { connectedCallback() {"
            " const sr = this.attachShadow({mode:'open'});"
            " sr.innerHTML = \"<table><tbody>%s</tbody></table>\"; } }"
            "customElements.define('doc-table', DocTable);</script>%s" % (light, rows, LISTENER))


def test_the_row_link_step_says_it_saw_no_link_rather_than_refusing(page, presses, monkeypatch):
    """It wrote "no row of this date names this document" ahead of a row
    walk that went on to find the document, which would mislead whoever
    reads the file."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", BOTH)
    page.set_content(_slotted_table())
    trace: list = []
    assert site._row_link_for(page, SHARED, BROKERAGE, trace) == (None, "")
    assert trace == [{"note": "the rows of this date show this step no link, so the row walk decides", "rows": 2}]
    hits, brings = presses
    brings.add("g-mine")
    trace = []
    assert site.download_bill(page, Path("."), SHARED, Path("unused.pdf"), BROKERAGE, trace)
    assert hits == ["g-mine"], hits
    assert not [t for t in trace if t.get("note", "").startswith("not sure which")], trace
    assert "Brokerage" not in json.dumps(trace) and "4242" not in json.dumps(trace)
