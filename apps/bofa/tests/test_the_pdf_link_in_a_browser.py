"""A Download PDF link whose address is "#", pressed in a real browser, on
a made-up statements page that draws its links the way appchamp's second
real run on #121 met them (2026-10-27).

The page asks its list as it loads and draws a "Download PDF" link for each
row, its words going on in a span drawn off the screen, its address "#".
A script of the page's own opens the PDF when one is pressed, one of three
ways. It fetches the PDF with a POST of JSON and saves it from a blob, it
opens the PDF's address in a tab of its own, or it goes to an address that
downloads it. The app reloads the page, finds every link's address is a
script, presses one through paperpull_core.pressing, hears the call its
PDF came by, asks that once more from inside the page, and asks every
other statement with its own row's call. The tab and the download the
press opened are gone after. A chat bubble over the links stops the run
with nothing pressed.

Every address is served by the test itself through Playwright's routing,
nothing goes to the network, and every value is made up.
"""
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import bofa_site as site
import standin_bank as sb
from paperpull_core import pressing

sync_api = pytest.importorskip("playwright.sync_api")

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40
LIST_PATH = urlsplit(sb.LIST_URL).path
CALL_PATH = urlsplit(sb.PDF_CALL_URL).path
HOST = "https://secure.bankofamerica.com"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements &amp; Documents</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
      white-space: nowrap; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style></head>
<body><main><h1>Statements &amp; Documents</h1>
<div id="cat-tax"><button type="button" aria-label="Tax Documents" aria-expanded="false"
    aria-controls="panel-tax"><span>Tax Documents</span></button><div id="panel-tax" hidden
    style="display: block; height: 0px; overflow: hidden;">
  <div class="row" tabindex="0"><div aria-hidden="true"><a href="#"><span>Download PDF</span><span
      class="sr"> for January Statement for Everyday Checking</span></a></div></div>
</div></div>
<div id="cat-stmt"><button type="button" aria-label="Statements" aria-expanded="true"
    aria-controls="panel-stmt"><span>Statements</span></button><div id="panel-stmt"></div></div>
</main>
%(extra)s
<script>
window.asked = [];
const HOW = '%(how)s';
async function ask(body) {
  window.asked.push(body);
  const r = await fetch('%(list)s', {method: 'POST', body: JSON.stringify(body),
    headers: {'content-type': 'application/json', 'x-standin-csrf': 'TOKEN-T'}});
  return r.json();
}
async function openPdf(r) {
  if (HOW === 'fetch') {
    const got = await fetch('%(call)s', {method: 'POST',
      body: JSON.stringify({docId: r.docId, acctToken: r.acctToken, lang: 'en'}),
      headers: {'content-type': 'application/json', 'x-standin-csrf': 'TOKEN-T'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await got.blob());
    a.download = 'eStmt_' + r.date + '.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } else if (HOW === 'tab') {
    window.open('/sample/viewdoc?doc=' + encodeURIComponent(r.docId), '_blank');
  } else if (HOW === 'alone') {
    window.open('/sample/viewdoc?doc=' + encodeURIComponent(r.docId), '_blank', 'noopener');
  } else if (HOW === 'view') {
    location.href = '/sample/viewdoc?doc=' + encodeURIComponent(r.docId);
  } else {
    location.href = '/sample/getdoc?doc=' + encodeURIComponent(r.docId);
  }
}
ask({acctToken: 'K-ALPHA-0001', docCategoryId: 'CAT-STMT', lang: 'en', year: '2026'}).then(got => {
  const panel = document.getElementById('panel-stmt');
  got.documentList.forEach(r => {
    const row = document.createElement('div');
    row.setAttribute('tabindex', '0');
    row.innerHTML = '<div aria-hidden="true"><span>' + r.date + '</span></div>' +
      '<div aria-hidden="true"><a href="#">View PDF</a><a href="#"><span>Download PDF</span><span class="sr"> for ' +
      r.docDisplayName + ' for ' + r.accountDisplayName + '</span></a></div>';
    row.querySelectorAll('a')[1].addEventListener('click', e => { e.preventDefault(); openPdf(r); });
    panel.appendChild(row);
  });
});
</script></body></html>"""

COVER = '<div class="cover">Chat with us</div>'


@pytest.fixture(scope="module")
def playwright():
    # One for both browsers, since a second at once in one thread is refused.
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(playwright):
    try:
        b = playwright.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()


@pytest.fixture(scope="module")
def viewer(playwright):
    """Chromium with its PDF viewer, which shows a PDF in a tab where the
    headless shell above downloads it, as a person's Edge or Chrome does."""
    try:
        b = playwright.chromium.launch(headless=True, channel="chromium")
    except Exception as e:
        pytest.skip("no Chromium with a PDF viewer to drive: %s" % e)
    yield b
    b.close()


@pytest.fixture(autouse=True)
def fresh():
    site.forget()
    yield
    site.forget()


def statements_page(browser, how, extra=""):
    """A tab on the made-up statements page whose links open their PDF
    `how`, with every address served here, and every PDF asked for."""
    context = browser.new_context(viewport={"width": 1000, "height": 700}, accept_downloads=True)
    seen = {"pdfs": []}
    html = PAGE % {"list": LIST_PATH, "call": CALL_PATH, "how": how, "extra": extra}

    def pdf(route, doc, inline=False):
        seen["pdfs"].append(doc)
        route.fulfill(status=200, content_type="application/pdf", body=_PDF, headers={
            "content-disposition": '%s; filename="eStmt_2026-01-15.pdf"' % (
                "inline" if inline else "attachment")})

    def serve(route):
        req = route.request
        parts = urlsplit(req.url)
        if req.url.startswith(sb.PAGE_URL.split("?")[0]):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif req.url == sb.LIST_URL and req.method == "POST":
            body = json.loads(req.post_data or "{}")
            rows = sb.STATEMENTS.get((body.get(sb.KEY), body.get("year")), [])
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(sb.answer(rows)))
        elif parts.path == CALL_PATH and req.method == "POST":
            pdf(route, json.loads(req.post_data or "{}").get("docId"))
        elif parts.path in ("/sample/viewdoc", "/sample/getdoc"):
            pdf(route, parse_qs(parts.query).get("doc", [""])[0], inline=parts.path == "/sample/viewdoc")
        else:
            route.abort()
    context.route("**/*", serve)
    page = context.new_page()
    page.goto(sb.PAGE_URL)
    page.wait_for_function("document.querySelectorAll('#panel-stmt a').length >= 2")
    return context, page, seen


@pytest.mark.parametrize("how, method, kind", [("fetch", "POST", "json"), ("tab", "GET", "get"),
                                               ("go", "GET", "get")])
def test_a_link_that_opens_its_pdf_by_a_script_is_pressed_once_and_its_call_learned(
        browser, how, method, kind):
    context, page, seen = statements_page(browser, how)
    try:
        call = site.learn(page)
        assert call.template is None and call.facts["pdf_links"] == 2
        assert call.facts["links_to_this_page"] == 2 and call.facts["pdf_link"] == "pressed"
        assert call.pdf is not None and call.pdf.method == method
        assert call.facts["pdf_url_kind"] == kind and call.facts["pdf_url_read_again"] is True
        # The first link's statement, by the press and once more by the app.
        assert seen["pdfs"] == ["DOC000000000101"] * 2
        # Nothing the press opened is left, and the tab is where it was.
        assert context.pages == [page] and site.on_statements_page(page)
        data, day = site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-02-15",
                                        document_id="DOC000000000102", year="2026")
        assert data.startswith(b"%PDF") and day == "2026-01-15"
        assert seen["pdfs"][-1] == "DOC000000000102"
        if how == "fetch":
            assert call.facts["downloads_in_the_page"] == 1
            assert call.pdf.headers.get("x-standin-csrf") == "TOKEN-T"
        else:
            assert call.facts["downloads"] + call.facts["tabs_opened"] >= 1
    finally:
        context.close()


@pytest.mark.parametrize("how", ["tab", "alone", "view"])
def test_a_pdf_shown_in_the_viewer_is_learned_and_the_tab_put_back(viewer, how):
    """In a tab of its own, which is closed, opened with no way back to the
    page too, or in the statements tab, which is taken back to the
    statements page."""
    context, page, seen = statements_page(viewer, how)
    try:
        call = site.learn(page)
        assert call.pdf is not None and call.pdf.method == "GET"
        assert call.facts["pdf_url_read_again"] is True
        assert call.facts.get("back_to_the_page") is (True if how == "view" else None)
        assert context.pages == [page] and site.on_statements_page(page)
        data, _day = site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-02-15",
                                         document_id="DOC000000000102", year="2026")
        assert data.startswith(b"%PDF") and seen["pdfs"][-1] == "DOC000000000102"
    finally:
        context.close()


def test_a_chat_bubble_over_the_links_stops_the_run_with_nothing_pressed(browser, monkeypatch):
    monkeypatch.setattr(pressing, "PRESS_MS", 500)
    context, page, seen = statements_page(browser, "fetch", extra=COVER)
    try:
        with pytest.raises(pressing.Stop) as stopped:
            site.learn(page)
        assert isinstance(stopped.value, pressing.Covered)
        assert stopped.value.step == "download a statement"
        assert not seen["pdfs"] and context.pages == [page]
    finally:
        context.close()
