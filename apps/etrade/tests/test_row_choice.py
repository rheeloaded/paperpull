"""A download takes the row that names its document, never a neighbor's.

His 0.37.0 discovery found thirteen documents on eleven dates (#36). The
2025 list held six documents on five dates and the 2024 list five on
four, so two dates carry two documents each, with different titles. The
row lookup took the first row that printed the date, and review showed
it saving the other document's PDF under this one's name and reporting
success. A saved document is never tried again, so that would have
stayed wrong.

Every way of finding the row now looks at every row that prints the
date and takes the one that names the document, its whole text the
title, or the title then PDF, the way his recording named the link. A
row is taken by its date alone only when it is the only one and the
lists the page loaded held one document on that date. Anything else is
refused and written down in counts.

Everything here is invented. The rows have the shape his traces showed,
a table row whose link sits in a web component's shadow root and is
named "<title> PDF for <account>", and, since review asked, rows that
are not table rows at all. The tests drive a real browser, because the
shadow root and the accessible name are what a fake page gets wrong.
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

# The document's link in a web component, the way his table draws it.
DOC_LINK_JS = """
<script>
class DocLink extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const sr = this.attachShadow({mode: 'open'});
    const a = document.createElement('a');
    a.href = '#';
    a.textContent = this.dataset.label || this.dataset.title;
    a.setAttribute('aria-label', (this.dataset.label || this.dataset.title) + ' PDF for ' + this.dataset.account);
    a.dataset.guid = this.dataset.guid;
    a.addEventListener('click', (e) => { e.preventDefault(); fetch('/docs/' + this.dataset.guid + '.pdf'); });
    sr.appendChild(a);
  }
}
if (!customElements.get('doc-link')) customElements.define('doc-link', DocLink);
</script>
"""


def _short(iso):
    y, m, d = iso.split("-")
    return "%s/%s/%s" % (m, d, y[2:])


def _guid(iso, title):
    return "g-%s-%s" % (iso, title.split()[0])


def _tr_page(docs, label=""):
    """Table rows shaped like his, the link in a shadow root, an insert
    link beside it."""
    rows = "".join(
        "<tr class='row_level-1'><td><div>%s</div></td><td><div>%s</div></td>"
        "<td><div><doc-link data-title='%s' data-label='%s' data-guid='%s' data-account='%s'></doc-link></div></td>"
        "<td><a href='#' data-guid='insert-%s'>Client Relationship Summary</a></td></tr>"
        % (_short(iso), ACCOUNT, title, label, _guid(iso, title), ACCOUNT, _guid(iso, title))
        for iso, title in docs)
    return "<table><tbody>%s</tbody></table>%s" % (rows, DOC_LINK_JS)


def _li_or_div_page(docs, shape, label=""):
    """Rows that are list items, or plain divs that are neither table rows,
    list items nor role=row."""
    tag, outer = ("li", "ul") if shape == "li" else ("div", "div")
    rows = "".join(
        "<%s class='doc'><span>%s</span> <span><a href='#' data-guid='%s'>%s</a></span> <span>%s</span></%s>"
        % (tag, _short(iso), _guid(iso, title), label or title, ACCOUNT, tag)
        for iso, title in docs)
    return "<%s id='rows'>%s</%s>" % (outer, rows, outer)


PAIR = [("2025-11-30", RETIREMENT), ("2025-11-30", BROKERAGE), ("2025-05-31", BROKERAGE)]


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
def no_titles_remembered(request, monkeypatch):
    """Each test says which titles the lists gave, or none. A test on a page
    discovery walked keeps what discovery read."""
    if "after_discovery" not in request.fixturenames:
        monkeypatch.setattr(site, "_LISTED_TITLES", {})


def _guid_of(el):
    return el.evaluate("e => (e.closest('[data-guid]') || e.querySelector('[data-guid]') || e).dataset.guid || ''")


# --- the table row's own link ------------------------------------------------

@pytest.mark.parametrize("iso, title", PAIR)
def test_the_row_link_is_the_one_that_names_the_document(page, monkeypatch, iso, title):
    """It took the first row with the date, and on a shared date that was
    the other document's link (#36, review)."""
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 2, "2025-05-31": 1})
    page.set_content(_tr_page(PAIR))
    el, label = site._row_link_for(page, iso, title)
    assert el is not None and label == title
    assert _guid_of(el) == _guid(iso, title)


def test_rows_of_a_shared_date_that_name_nothing_are_refused(page, monkeypatch):
    """When the page does not print the document's title, two rows of one
    date cannot be told apart, so nothing is taken."""
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 2})
    page.set_content(_tr_page(PAIR[:2], label="View"))
    trace: list = []
    assert site._row_link_for(page, "2025-11-30", BROKERAGE, trace) == (None, "")
    assert trace == [{"note": "not sure which is this document, so nothing was pressed",
                      "way": "row link", "why": "no row of this date names this document",
                      "carrying_the_date": 2, "naming_the_document": 0, "listed_that_day": 2}]


def test_one_row_is_taken_by_its_date_only_when_the_lists_say_it_is_alone(page, monkeypatch):
    """The only row of a date may still be another document of that date,
    one the list did not show. The lists the page loaded settle it."""
    page.set_content(_tr_page([("2025-05-31", BROKERAGE)], label="View"))
    monkeypatch.setattr(site, "_LISTED", {})
    assert site._row_link_for(page, "2025-05-31", BROKERAGE, []) == (None, "")
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 2})
    assert site._row_link_for(page, "2025-05-31", BROKERAGE, []) == (None, "")
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    el, _label = site._row_link_for(page, "2025-05-31", BROKERAGE, [])
    assert el is not None and _guid_of(el) == _guid("2025-05-31", BROKERAGE)


# --- a document control anywhere on the page ------------------------------

def _control_page(docs):
    return "<div id='rows'>%s</div>" % "".join(
        "<div class='doc'><span>%s</span> <span><a href='#' data-guid='%s' aria-label='%s PDF for %s'>%s</a></span></div>"
        % (_short(iso), _guid(iso, title), title, ACCOUNT, title) for iso, title in docs)


@pytest.mark.parametrize("iso, title", PAIR)
def test_the_control_is_the_one_that_names_the_document(page, monkeypatch, iso, title):
    """The same first-match mistake, one step later in the download."""
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 2, "2025-05-31": 1})
    page.set_content(_control_page(PAIR))
    el, name = site._control_for(page, iso, title, [])
    assert el is not None and site.names_title(name, title)
    assert _guid_of(el) == _guid(iso, title)


def test_a_control_for_a_document_no_control_names_is_refused(page, monkeypatch):
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 3})
    page.set_content(_control_page(PAIR))
    trace: list = []
    assert site._control_for(page, "2025-11-30", "Annual Fee Notice", trace) == (None, "")
    assert trace[0]["way"] == "control" and trace[0]["carrying_the_date"] == 2


# --- the row found by walking the page -------------------------------------

@pytest.fixture
def clicks(monkeypatch):
    """Stands in for the catch, and remembers which document each click
    landed on. `fail` lists the kinds of candidate that bring nothing."""
    got: list = []
    fail: set = set()

    def fake(page, el, label, out_path, trace=None, dl_dir=None):
        got.append((_guid_of(el), label))
        return not any(word in label for word in fail)
    monkeypatch.setattr(site, "_catch_pdf", fake)
    return got, fail


@pytest.mark.parametrize("shape", ["li", "div"])
@pytest.mark.parametrize("iso, title", PAIR)
def test_the_row_by_date_is_the_one_that_names_the_document(page, clicks, monkeypatch, tmp_path,
                                                             shape, iso, title):
    """With list items the first element with the date won. With plain
    divs the walk up from a date that prints as 11/30/25 never stopped
    at the row and reached the whole list, whose first title was another
    date's document (#36, review)."""
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 2, "2025-05-31": 1})
    page.set_content(_li_or_div_page(PAIR, shape))
    trace: list = []
    assert site._try_every_way(page, tmp_path, iso, tmp_path / "out.pdf", title, trace)
    assert clicks[0] == [(_guid(iso, title), title)]


def test_rows_found_by_walking_that_name_nothing_are_refused(page, clicks, monkeypatch, tmp_path):
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 2})
    page.set_content(_li_or_div_page(PAIR[:2], "li", label="View"))
    trace: list = []
    assert not site._try_every_way(page, tmp_path, "2025-11-30", tmp_path / "out.pdf", BROKERAGE, trace)
    assert clicks[0] == []
    assert trace[-1]["way"] == "row by date"
    assert trace[-1]["why"] == "no row of this date names this document"
    assert (trace[-1]["carrying_the_date"], trace[-1]["naming_the_document"]) == (2, 0)


SHARED = "2025-11-30"
BOTH = {SHARED: {BROKERAGE, RETIREMENT}}


def test_a_control_for_another_document_of_the_date_is_never_tried(page, clicks, monkeypatch, tmp_path):
    """One row can hold both documents of a date. When this document's own
    link brings nothing, the other document's link used to be tried next
    as one of the row's controls, and its PDF saved under this name."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", BOTH)
    clicks[1].add(BROKERAGE)
    page.set_content("<ul><li><span>11/30/25</span> "
                     "<a href='#' data-guid='g-mine'>%s</a> "
                     "<a href='#' data-guid='g-theirs' aria-label='%s PDF for %s'>%s</a></li></ul>"
                     % (BROKERAGE, RETIREMENT, ACCOUNT, RETIREMENT))
    trace: list = []
    assert not site._try_every_way(page, tmp_path, SHARED, tmp_path / "out.pdf", BROKERAGE, trace)
    assert [g for g, _label in clicks[0]] == ["g-mine"], clicks[0]
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert [c["left_out"] for c in row["candidates"]] == [False, True]


def test_a_row_link_for_another_document_of_the_date_is_never_taken(page, clicks, monkeypatch, tmp_path):
    """The only row of the date prints this document's title as plain text,
    links the other document of that date, and has a View. The View could
    be either one's, so neither link is pressed, only the title (second
    review). The first repair took the View as this document's."""
    monkeypatch.setattr(site, "_LISTED", {SHARED: 2})
    monkeypatch.setattr(site, "_LISTED_TITLES", BOTH)
    page.set_content("<table><tbody><tr><td>11/30/25</td><td>%s</td>"
                     "<td><a href='#' data-guid='g-theirs'>%s</a></td>"
                     "<td><a href='#' data-guid='g-mine'>View</a></td></tr></tbody></table>"
                     % (BROKERAGE, RETIREMENT))
    trace: list = []
    assert site._row_link_for(page, SHARED, BROKERAGE, trace) == (None, "")
    assert trace[-1]["why"] == "no row of this date names this document"
    clicks[1].add(BROKERAGE)
    assert not site._try_every_way(page, tmp_path, SHARED, tmp_path / "out.pdf", BROKERAGE, trace)
    assert [label for _g, label in clicks[0]] == [BROKERAGE], clicks[0]


# Rows with a box each and the page's own Download button, which hands over
# the first ticked document, the way a list with a Download button would.
BOXES = """<ul>
<li><span>11/30/25</span> <input type='checkbox' data-guid='g-theirs' %s> <span>%s</span></li>
<li><span>10/31/25</span> <input type='checkbox' data-guid='g-mine'> <span>%s</span></li>
</ul>
<button type='button' onclick="window.handed = (document.querySelector('input:checked') || {}).dataset.guid">Download</button>
"""


@pytest.mark.parametrize("left_ticked", [True, False])
def test_download_is_not_pressed_while_another_box_is_ticked(page, monkeypatch, tmp_path, left_ticked):
    """When nothing else in the row brings the PDF, the row's box is ticked
    and the page's Download pressed. A box left ticked from another
    document made Download hand over that one. The box the app ticked is
    cleared again either way, so it cannot do the same to the next one."""
    monkeypatch.setattr(site, "_LISTED", {"2025-10-31": 1})
    pressed: list = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        if label != "Download":
            return False                            # the title brings nothing
        el.click()
        pressed.append(pg.evaluate("window.handed"))
        return True
    monkeypatch.setattr(site, "_catch_pdf", fake)
    page.set_content(BOXES % ("checked" if left_ticked else "", RETIREMENT, BROKERAGE))
    trace: list = []
    got = site._try_every_way(page, tmp_path, "2025-10-31", tmp_path / "out.pdf", BROKERAGE, trace)
    if left_ticked:
        assert not got and pressed == []
        assert {"note": "another box is ticked too, so Download was not pressed", "ticked": 2} in trace
    else:
        assert got and pressed == ["g-mine"]
    assert trace[-1] == {"note": "this document's box was cleared again"}
    assert page.evaluate("document.querySelector('[data-guid=g-mine]').checked") is False
    assert page.evaluate("document.querySelector('[data-guid=g-theirs]').checked") is left_ticked


def test_a_date_range_on_the_page_is_not_a_row(page, clicks, monkeypatch, tmp_path):
    """A year applied may print its range, and the range carries the year's
    last day, the date a year-end statement has (review)."""
    monkeypatch.setattr(site, "_LISTED", {"2023-12-31": 1, "2023-11-30": 1})
    rows = _li_or_div_page([("2023-12-31", BROKERAGE), ("2023-11-30", BROKERAGE)], "div")
    for chip in ("<div class='range'>Showing 01/01/2023 - 12/31/2023</div>",
                 "<ul class='chips'><li>01/01/2023 - 12/31/2023</li></ul>"):
        clicks[0].clear()
        page.set_content(chip + rows)
        assert site._try_every_way(page, tmp_path, "2023-12-31", tmp_path / "out.pdf", BROKERAGE, [])
        assert clicks[0] == [(_guid("2023-12-31", BROKERAGE), BROKERAGE)], (chip, clicks[0])


def test_an_insert_is_never_tried_for_the_document(page, clicks, monkeypatch, tmp_path):
    """The row's insert link hands over a different PDF. When the title
    brings nothing, the insert must not be saved in its place."""
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    clicks[1].add(BROKERAGE)
    page.set_content("<ul><li><span>05/31/25</span> <span data-guid='g-title'>%s</span> "
                     "<a href='#' data-guid='g-insert'>Client Relationship Summary</a></li></ul>" % BROKERAGE)
    assert not site._try_every_way(page, tmp_path, "2025-05-31", tmp_path / "out.pdf", BROKERAGE, [])
    assert clicks[0] and all(g != "g-insert" for g, _label in clicks[0]), clicks[0]


# --- the whole download, on a page served at E*TRADE's address --------------

def _serve(browser, html):
    ctx = browser.new_context()

    def answer(route):
        url = route.request.url
        if "/docs/" in url and url.endswith(".pdf"):
            name = url.rsplit("/", 1)[-1][:-4]
            return route.fulfill(status=200, content_type="application/pdf",
                                 body=b"%PDF-1.4\n% invented " + name.encode() + b"\n%%EOF\n")
        route.fulfill(status=200, content_type="text/html",
                      body="<!doctype html><html><body><h1>Statements &amp; Documents</h1>%s</body></html>" % html)
    ctx.route("https://us.etrade.com/**", answer)
    return ctx


def test_the_download_saves_nothing_when_it_cannot_tell_the_rows_apart(browser, monkeypatch, tmp_path):
    """End to end. Two documents of one date whose rows only say View.
    The old download clicked the first View and saved it."""
    monkeypatch.setattr(site, "_LISTED", {"2025-11-30": 2})
    ctx = _serve(browser, _li_or_div_page(PAIR[:2], "li", label="View").replace(
        "<a href='#' data-guid='", "<a href='#' onclick=\"event.preventDefault();fetch('/docs/'+this.dataset.guid+'.pdf')\" data-guid='"))
    try:
        pg = ctx.new_page()
        out = tmp_path / "out.pdf"
        trace: list = []
        assert not site.download_bill(pg, tmp_path / "dl", "2025-11-30", out, title=BROKERAGE, trace=trace)
        assert not out.exists()
        refusals = [t for t in trace if t.get("note", "").startswith("not sure which")]
        assert refusals and {t["way"] for t in refusals} >= {"control", "row by date"}
    finally:
        ctx.close()


def test_what_the_download_writes_carries_nothing_the_page_said(browser, monkeypatch, tmp_path):
    """download-attempt.json is attached to a public issue. Its row outline
    carried every element's own text, the account column among it, with
    no redaction at all, and the labels went through redaction, which
    keeps a four-digit account ending (#36, review)."""
    monkeypatch.setattr(site, "_LISTED", {"2025-05-31": 1})
    row = ("<div id='rows'><div class='doc'><span>05/31/25</span> <span><a href='/docs/acct-4242/s.pdf?token=abc123' "
           "aria-label='%s for %s' onclick=\"event.preventDefault();fetch('/docs/g-2025-05-31-Brokerage.pdf')\">%s</a>"
           "</span> <span>%s</span></div></div>" % (BROKERAGE, ACCOUNT, BROKERAGE, ACCOUNT))
    ctx = _serve(browser, row)
    try:
        pg = ctx.new_page()
        out = tmp_path / "out.pdf"
        trace: list = []
        assert site.download_bill(pg, tmp_path / "dl", "2025-05-31", out, title=BROKERAGE, trace=trace), trace
        assert b"g-2025-05-31-Brokerage" in out.read_bytes()
        text = json.dumps(trace)
        assert "the document's row" in text and "<the title>" in text
        for leaked in ("Invented", "4242", "Brokerage", "token", "abc123", "acct", "05/31"):
            assert leaked not in text, (leaked, text)
    finally:
        ctx.close()


# --- the shapes the trace is built from ------------------------------------

def test_an_address_leaves_as_its_kind_and_plain_words():
    assert site.mask_href("https://us.etrade.com/etx/pxy/accountdocs#/documents") == \
        "etrade:/etx/pxy/accountdocs#/documents"
    assert site.mask_href("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems"
                          "?RequestID=1234567&SeqID=88") == \
        "etrade:/etaz/api/adsal/accountdocs/v2/searchItems?RequestID&SeqID"
    # A parameter name leaves only from the list E*TRADE was seen to use.
    assert site.mask_href("https://us.etrade.com/docs/Stmt_4242_20250531.pdf?acct=4242") == \
        "etrade:/docs/#.pdf?#"
    assert site.mask_href("https://tracker.example/pixel?u=someone") == "elsewhere"
    assert site.mask_href("/docs/acct-4242/s.pdf") == "relative:/docs/#/#.pdf"


def test_a_plain_word_in_an_address_leaves_only_when_it_is_on_the_list():
    """A piece was judged by its shape, so a file named for its owner, or a
    route naming an account's type, left as written (review of #36)."""
    assert site.mask_href("https://us.etrade.com/docs/JaneExample_Statement.pdf") == \
        "etrade:/docs/#.pdf"
    assert site.mask_href("https://us.etrade.com/etx/pxy/accountdocs#/documents/SampleBrokerage") == \
        "etrade:/etx/pxy/accountdocs#/documents/#"
    assert site.mask_href("https://us.etrade.com/profile/household/members") == "etrade:/#/#/#"
    assert site.mask_href("javascript:void(0)") == "javascript"


def test_an_outline_line_is_built_only_from_what_may_leave():
    hostile = {"depth": 2, "tag": "a", "cls": ["acct-4242", "doc_link"], "role": "link",
               "type": "", "aria": "%s PDF for %s" % (BROKERAGE, ACCOUNT), "own": ACCOUNT,
               "href": "https://us.etrade.com/docs/4242.pdf?token=abc", "pointer": True}
    line = site._outline_line(hostile, BROKERAGE)
    assert line == "    a.doc_link [link] aria=<the title> = <text of 4 words> href=etrade pdf {pointer}"
    assert site._outline_line({"tag": "<img onerror=x>", "own": "05/31/25"}) == "? = <date>"


# --- the whole Pilot, in his order, with a shared date ---------------------

DOCS = {"Last 90 Days": [("2026-08-31", BROKERAGE)],
        "Year To Date": [("2026-08-31", BROKERAGE), ("2026-02-28", BROKERAGE)],
        "2025": PAIR,
        "2024": []}

PILOT_PAGE = """<!doctype html><html><body>
<h1>Statements &amp; Documents</h1>
<form id="filters">
  <button type="button" id="picker" aria-label="Timeframe ,  Last 90 Days">Last 90 Days</button>
  <div id="list" style="display:none">
    <div class="opt">Last 90 Days</div>
    <div class="opt">Year To Date</div>
    <div class="opt">2025</div>
    <div class="opt">2024</div>
  </div>
  <button type="reset">Reset</button>
  <button type="submit">Apply</button>
</form>
<div id="where"></div>
%s
<script>
const SHAPE = "__SHAPE__";
const ACCOUNT = "__ACCOUNT__";
let current = "Last 90 Days", pending = null;
const picker = document.getElementById("picker");
const list = document.getElementById("list");
if (SHAPE === "tr") {
  list.setAttribute("role", "listbox");
  for (const o of list.children) o.setAttribute("role", "option");
}
picker.addEventListener("click", () => {
  list.style.display = list.style.display === "none" ? "block" : "none";
});
for (const o of list.children) {
  o.style.cursor = "pointer";
  o.addEventListener("click", () => { pending = o.textContent.trim(); list.style.display = "none"; });
}
function shortDate(iso) {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return m + "/" + d + "/" + y.slice(2);
}
function fetchPdf(e, guid) { e.preventDefault(); fetch("/docs/" + guid + ".pdf"); }
function search(tf) {
  return fetch("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems", {
    method: "POST", headers: {"Content-Type": "text/plain"},
    body: JSON.stringify({TimeFrame: tf, pageNum: 1})
  }).then(r => r.json()).then(b => {
    const where = document.getElementById("where");
    let html = "";
    for (const d of b.defaultDocumentList) {
      const day = shortDate(d.documentDate), t = d.documentTitle, g = d.documentGuid;
      if (SHAPE === "tr") {
        html += "<tr class='row_level-1'><td><div>" + day + "</div></td><td><div>" + ACCOUNT + "</div></td>" +
                "<td><div><doc-link data-title='" + t + "' data-guid='" + g + "' data-account='" + ACCOUNT + "'></doc-link></div></td>" +
                "<td><a href='#' onclick=\\"fetchPdf(event, 'insert-" + g + "')\\">Client Relationship Summary</a></td></tr>";
      } else {
        html += "<div class='doc'><span>" + day + "</span> <span><a href='#' onclick=\\"fetchPdf(event, '" + g + "')\\">" +
                t + "</a></span> <span>" + ACCOUNT + "</span></div>";
      }
    }
    where.innerHTML = SHAPE === "tr" ? "<table><tbody>" + html + "</tbody></table>" : "<div id='rows'>" + html + "</div>";
  });
}
document.getElementById("filters").addEventListener("submit", (e) => {
  e.preventDefault();
  if (pending) { current = pending; pending = null; }
  picker.setAttribute("aria-label", "Timeframe ,  " + current);
  picker.textContent = current;
  search(current);
});
search(current);
</script></body></html>"""


def _pilot_answer(route):
    req = route.request
    if req.method != "POST":
        return route.fulfill(status=204, headers={"access-control-allow-origin": "*"})
    tf = json.loads(req.post_data or "{}").get("TimeFrame", "")
    body = {"defaultDocumentList": [
        {"documentGuid": _guid(d, t), "documentId": "i-%s" % d, "documentTypeName": "Statements",
         "documentTitle": t, "documentDate": d + "T00:00:00",
         "displayMultipleAccounts": ACCOUNT} for d, t in DOCS.get(tf, [])]}
    route.fulfill(status=200, content_type="application/json",
                  headers={"access-control-allow-origin": "*"}, body=json.dumps(body))


@pytest.fixture(scope="module", params=["tr", "div"])
def after_discovery(request, browser):
    """A page left the way Pilot leaves it, discovery first. "tr" is his
    shape, options by role and the link in a shadow root. "div" has plain
    options, so the period showing is not among what the list offers, and
    rows that are not table rows."""
    shape = request.param
    html = PILOT_PAGE.replace("__SHAPE__", shape).replace("__ACCOUNT__", ACCOUNT) % (
        DOC_LINK_JS if shape == "tr" else "")
    ctx = browser.new_context()

    def serve(route):
        url = route.request.url
        if "/docs/" in url and url.endswith(".pdf"):
            name = url.rsplit("/", 1)[-1][:-4]
            return route.fulfill(status=200, content_type="application/pdf",
                                 body=b"%PDF-1.4\n% invented " + name.encode() + b"\n%%EOF\n")
        route.fulfill(status=200, content_type="text/html", body=html)
    ctx.route("https://us.etrade.com/**", serve)
    ctx.route("https://ext-web.etrade.com/**", _pilot_answer)
    pg = ctx.new_page()
    docs = site.collect_download_docs(pg)
    yield shape, pg, docs
    ctx.close()


def test_discovery_found_both_documents_of_the_shared_date(after_discovery):
    _shape, pg, docs = after_discovery
    assert sorted((d.date_text, d.title) for d in docs) == sorted(
        {(d, t) for period in DOCS.values() for d, t in period})
    assert site._LISTED == {"2026-08-31": 1, "2026-02-28": 1, "2025-11-30": 2, "2025-05-31": 1}
    assert site._LISTED_TITLES["2025-11-30"] == {BROKERAGE, RETIREMENT}


@pytest.mark.parametrize("iso, title", [("2026-02-28", BROKERAGE)] + PAIR)
def test_each_document_of_a_shared_date_saves_its_own_pdf(after_discovery, tmp_path, iso, title):
    """In Pilot's order, newest first. Each saved file is the one asked
    for, never its neighbor on the same date and never an insert."""
    _shape, pg, _docs = after_discovery
    out = tmp_path / "out.pdf"
    trace: list = []
    assert site.download_bill(pg, tmp_path / "dl", iso, out, title=title, trace=trace), trace
    body = out.read_bytes()
    assert body.startswith(b"%PDF-")
    assert b"invented " + _guid(iso, title).encode() + b"\n" in body, body


# --- discovery without a list, from the rows the page shows ----------------

# No searchItems answer, so discovery reads the rows. One row on the first
# date, and two rows that print the very same words on the second.
NO_LIST_ROWS = [("2023-08-31", "a"), ("2023-05-31", "b"), ("2023-05-31", "c")]


def test_without_a_list_the_rows_say_which_dates_hold_one_document(browser, monkeypatch, tmp_path):
    """A document found from the rows gets a title this file makes up, which
    no row prints, so its download can only go by date. That is taken only
    when the page showed one row on the date, and two rows that print the
    same words are still two."""
    monkeypatch.setattr(site, "_LISTED", {})
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td><a href='#' onclick=\"event.preventDefault();"
        "fetch('/docs/g-%s.pdf')\">View</a></td></tr>" % (_short(iso), ACCOUNT, g)
        for iso, g in NO_LIST_ROWS)
    ctx = _serve(browser, "<table><tbody>%s</tbody></table>" % rows)
    try:
        pg = ctx.new_page()
        docs = site.collect_download_docs(pg)
        assert sorted(d.date_text for d in docs) == ["2023-05-31", "2023-08-31"]
        assert site._LISTED == {"2023-08-31": 1, "2023-05-31": 2}
        title = {d.date_text: d.title for d in docs}
        out = tmp_path / "alone.pdf"
        assert site.download_bill(pg, tmp_path / "dl", "2023-08-31", out, title=title["2023-08-31"])
        assert b"invented g-a\n" in out.read_bytes()
        shared = tmp_path / "shared.pdf"
        trace: list = []
        assert not site.download_bill(pg, tmp_path / "dl", "2023-05-31", shared,
                                      title=title["2023-05-31"], trace=trace)
        assert not shared.exists()
        assert any(t.get("note", "").startswith("not sure which") for t in trace), trace
    finally:
        ctx.close()
