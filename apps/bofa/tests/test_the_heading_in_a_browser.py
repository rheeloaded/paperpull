"""The Statements heading opened in a real browser, on a made-up statements
page that draws its list the way the two recordings on #121 showed it and
the way appchamp's first real run met it (2026-10-26).

The page asks its list as it loads and draws nothing under its headings,
each shut, its panel hidden. Pressing the Statements heading asks the list
again, with lang, and draws a row for each statement, a "Download PDF" link
whose words go on in a span drawn off the screen. The app reloads the page,
hears the call, finds no link, presses the heading once through
paperpull_core.pressing, and learns the links' form from what the press's
answer lists. A chat bubble over the heading stops the run with nothing
pressed.

Every address is served by the test itself through Playwright's routing,
nothing goes to the network, and every value is made up.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

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

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements &amp; Documents</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
      white-space: nowrap; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style></head>
<body><main><h1>Statements &amp; Documents</h1>
<section>
  <div id="cat-stmt"><button type="button" name="stmts" aria-label="Statements"
      aria-expanded="false" aria-controls="panel-stmt"><span class="i"></span><span>Statements</span><span
      class="i"></span></button><div id="panel-stmt" hidden
      style="display: block; height: 0px; overflow: hidden;"></div></div>
  <div id="cat-tax"><button type="button" name="tax" aria-label="Tax Documents"
      aria-expanded="false" aria-controls="panel-tax"><span>Tax Documents</span></button><div
      id="panel-tax" hidden style="display: block; height: 0px; overflow: hidden;"></div></div>
</section></main>
%(extra)s
<script>
window.asked = [];
async function ask(body) {
  window.asked.push(body);
  const r = await fetch('%(list)s', {method: 'POST', body: JSON.stringify(body),
    headers: {'content-type': 'application/json', 'x-standin-csrf': 'TOKEN-T'}});
  return r.json();
}
ask({acctToken: 'K-ALPHA-0001', docCategoryId: 'CAT-TAX', year: '2026'}).then(got => {
  const tax = document.getElementById('panel-tax');
  tax.innerHTML = got.documentList.map(r =>
    '<div class="row" tabindex="0"><div aria-hidden="true"><a href="#"><span>Download PDF</span><span class="sr"> for ' +
    r.docDisplayName + ' for ' + r.accountDisplayName + '</span></a></div></div>').join('');
});
document.querySelector('[aria-controls=panel-stmt]').addEventListener('click', async (e) => {
  const b = e.currentTarget;
  b.setAttribute('aria-expanded', 'true');
  const got = await ask({acctToken: 'K-ALPHA-0001', docCategoryId: 'CAT-STMT', lang: 'en', year: '2026'});
  const panel = document.getElementById('panel-stmt');
  panel.hidden = false;
  panel.style.height = 'auto';
  panel.innerHTML = got.documentList.map(r =>
    '<div class="row" tabindex="0"><div aria-hidden="true"><a href="%(link)s' + r.docId + '" id="d' + r.docId +
    '" data-a="x" data-b="' + r.docId + '"><span>Download PDF</span><span class="sr"> for ' +
    r.docDisplayName + ' for ' + r.accountDisplayName + '</span></a></div></div>').join('');
});
</script></body></html>"""

COVER = '<div class="cover">Chat with us</div>'
LOAD_ROW = sb.row("DOC000000000777", sb.ACCOUNTS[0], "2026-03-01", "Tax Form", category="CAT-TAX")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


def statements_page(browser, extra="", in_a_form=False):
    """A tab on the made-up statements page, with every address served
    here, and the list and the PDFs each one asked for. in_a_form puts
    the Statements heading, with no type, inside a form that posts."""
    context = browser.new_context(viewport={"width": 1000, "height": 700})
    seen = {"lists": [], "pdfs": []}
    html = PAGE % {"list": LIST_PATH, "link": sb.LINK_BASE, "extra": extra}
    if in_a_form:
        html = html.replace('<div id="cat-stmt"><button type="button"',
                            '<div id="cat-stmt"><form method="post" action="/paperless"><button', 1)
        html = html.replace('</button><div id="panel-stmt" hidden',
                            '</button></form><div id="panel-stmt" hidden', 1)
        assert '<form method="post"' in html and '</button></form>' in html

    def serve(route):
        req = route.request
        url = req.url
        if url.startswith(sb.PAGE_URL.split("?")[0]):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif url == sb.LIST_URL and req.method == "POST":
            body = json.loads(req.post_data or "{}")
            seen["lists"].append(body)
            # The page's own ask as it loads is for another category and
            # lists something else, as the recordings' did (one row, and
            # seven in appchamp's run). The heading's ask, and the app's,
            # are for the Statements category.
            rows = (sb.STATEMENTS.get((body.get(sb.KEY), body.get("year")), [])
                    if body.get("docCategoryId") == "CAT-STMT" else [LOAD_ROW])
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(sb.answer(rows)))
        elif url.startswith(sb.LINK_BASE):
            seen["pdfs"].append(url)
            route.fulfill(status=200, content_type="application/pdf", body=_PDF,
                          headers={"content-disposition":
                                   'attachment; filename="eStmt_2026-01-15.pdf"'})
        else:
            route.abort()
    context.route("**/*", serve)
    page = context.new_page()
    page.goto(sb.PAGE_URL)
    page.wait_for_function("window.asked && window.asked.length >= 1")
    return context, page, seen


@pytest.fixture(autouse=True)
def fresh():
    site.forget()
    yield
    site.forget()


def test_the_shut_heading_is_opened_once_and_the_links_form_learned(browser):
    context, page, seen = statements_page(browser)
    try:
        assert site.drawn_links(page) == [], "the made-up page drew a link under a shut heading"
        call = site.learn(page)
        assert call.facts["statements_heading"] == "opened"
        assert call.template is not None and call.links == 2
        assert call.facts["links_to_other_pages"] == 2 and call.facts["links_with_an_id"] == 2
        # The links are of rows only the press's answer lists, so that answer
        # was heard, and the heading says it is open now.
        assert call.facts["list_read_after_the_heading"] is True
        assert call.facts["heading_expanded_after"] is True
        assert call.facts["times_the_list_was_read"] == 2 and call.facts["rows_read"] == 3
        # The press's own ask, with lang, is the one heard after the reload's.
        asked = page.evaluate("window.asked")
        assert [b.get("lang") for b in asked] == [None, "en"]
        assert page.get_attribute("[aria-controls=panel-stmt]", "aria-expanded") == "true"
        assert page.get_attribute("[aria-controls=panel-tax]", "aria-expanded") == "false"
        data, day = site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                                        document_id="DOC000000000101", year="2026")
        assert data.startswith(b"%PDF") and day == "2026-01-15"
        assert seen["pdfs"] == [sb.LINK_BASE + "DOC000000000101"]
    finally:
        context.close()


def test_a_heading_that_would_submit_a_form_is_never_pressed(browser):
    context, page, seen = statements_page(browser, in_a_form=True)
    try:
        call = site.learn(page)
        assert call.facts["statements_heading"] == "refused"
        assert call.template is None
        # Not pressed, so the page asked nothing more and posted nothing.
        assert [b.get("lang") for b in page.evaluate("window.asked")] == [None]
        assert page.get_attribute("[aria-controls=panel-stmt]", "aria-expanded") == "false"
        assert page.url.startswith(sb.PAGE_URL.split("?")[0])
    finally:
        context.close()


def test_an_open_heading_is_not_pressed_again(browser):
    context, page, seen = statements_page(browser)
    try:
        site.learn(page)
        # The next look at the page, a minute later in a long run, without a
        # reload in between, finds the heading open and its links drawn.
        assert site.open_statements(page) == "already expanded"
        assert [b.get("lang") for b in page.evaluate("window.asked")] == [None, "en"]
    finally:
        context.close()


def test_a_chat_bubble_over_the_heading_stops_the_run_with_nothing_pressed(browser, monkeypatch):
    monkeypatch.setattr(pressing, "PRESS_MS", 500)
    context, page, seen = statements_page(browser, extra=COVER)
    try:
        with pytest.raises(pressing.Stop) as stopped:
            site.learn(page)
        assert isinstance(stopped.value, pressing.Covered)
        assert stopped.value.step == "expand the statements heading"
        assert page.get_attribute("[aria-controls=panel-stmt]", "aria-expanded") == "false"
        assert [b.get("lang") for b in page.evaluate("window.asked")] == [None]
        assert not seen["pdfs"]
    finally:
        context.close()
