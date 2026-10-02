"""A tab a statement's press opens is read only at Ally's own address.

When a row's press brings no download, the app takes the first tab the
press opened and fetches that tab's own address, and the fetch carries the
signed-in session. Nothing looked at the address first, so a PDF served in
a tab off Ally's hosts was written as the statement. The check after the
press did not catch it. It hears only the answers Ally's own page gets, so
it kept the file when it heard none, and called it verified when the page's
own answer named the statement asked for. Chase's twin of this function
turns such a tab away, and Ally's now does too. A blob the page made, and a
tab at Ally's own address, are read as before.

In a real browser. Every page here is made up and served from memory, every
other request is refused, and no name resolves, so nothing leaves this
machine.
"""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import ally_site as site  # noqa: E402

DOCUMENTS = site.URLS["documents"]
DOCUMENT_ID = "INVENTED0916"
# What Ally's page asks its own service for, one statement by its id.
ANSWER = "https://secure.ally.com/acs/v1/bank-statements/" + DOCUMENT_ID
VIEWER = "https://secure.ally.com/bank/statements-and-forms/invented-viewer"
ELSEWHERE = "https://elsewhere.example/statement.pdf"
DATE = "2026-09-16"
STATEMENT = b"%PDF-1.4 invented statement September 16, 2026 " + b"x" * 400
FOREIGN = b"%PDF-1.4 invented document from elsewhere " + b"y" * 400

PAGE = """<!doctype html><html><head><style>
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style></head><body><main>
 <h1>Statements and Tax Forms</h1>
 <label for="statementYear">Year</label>
 <select id="statementYear"><option>2026</option><option>2025</option></select>
 <table>
  <thead><tr><th>Date Posted</th><th>Statement Title</th></tr></thead>
  <tbody><tr><td>September 16, 2026</td>
   <td><span class="sr-only">Download statement for: </span>
   <button type="button" id="statement">Statement</button></td></tr></tbody>
 </table>
</main><script>
const ANSWER = '%s', VIEWER = '%s', ELSEWHERE = '%s';
document.getElementById('statement').addEventListener('click', () => { %%s });
</script></body></html>""" % (ANSWER, VIEWER, ELSEWHERE)

# A tab somewhere else, and nothing from Ally's own page.
OFF_HOST = "window.open(ELSEWHERE, '_blank');"

# Ally's own page is answered with the very statement asked for, and then
# the press opens a tab somewhere else. That answer is all the check after
# the press hears, so it called the PDF from elsewhere verified.
ANSWERED_THEN_OFF_HOST = "fetch(ANSWER).then(() => window.open(ELSEWHERE, '_blank'));"

# Ally's page asks for the statement by its id and opens the answer as a
# blob in a tab. Typed as text, since this browser has no PDF viewer and
# would save a PDF tab as a download rather than show it.
BLOB = ("fetch(ANSWER).then(r => r.blob()).then(b => window.open("
        "URL.createObjectURL(new Blob([b], {type: 'text/plain'})), '_blank'));")

# A tab at an address on Ally.
ON_HOST = "window.open(VIEWER, '_blank');"


@pytest.fixture()
def ally(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    served = {"press": ""}
    asked = {ANSWER: [], VIEWER: [], ELSEWHERE: []}

    def answer(route):
        asked[ANSWER].append(route.request.resource_type)
        route.fulfill(status=200, content_type="application/pdf", body=STATEMENT)

    def tab(url, pdf):
        def serve(route):
            # The tab is a page to look at, the way a PDF viewer shows one.
            # Asked for by a fetch, it answers with the PDF, the way the app
            # reads it.
            kind = route.request.resource_type
            asked[url].append(kind)
            if kind == "document":
                route.fulfill(status=200, content_type="text/html",
                              body="<html><body><h1>A statement</h1></body></html>")
            else:
                route.fulfill(status=200, content_type="application/pdf", body=pdf)
        return serve

    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(DOCUMENTS, lambda r: r.fulfill(
        status=200, content_type="text/html", body=PAGE % served["press"]))
    ctx.route(ANSWER, answer)
    ctx.route(VIEWER, tab(VIEWER, STATEMENT))
    ctx.route(ELSEWHERE, tab(ELSEWHERE, FOREIGN))
    page = ctx.new_page()
    heard: list = []
    ctx.on("page", lambda p: heard.append(p))
    fetched: list = []
    real_fetch = site._fetch_as_b64

    def fetch(where, url, *a, **kw):
        fetched.append((where, url))
        return real_fetch(where, url, *a, **kw)

    monkeypatch.setattr(site, "_fetch_as_b64", fetch)
    # Reaching the page is tested elsewhere. The page above is the
    # statements page.
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def show(press):
        served["press"] = press
        page.goto(DOCUMENTS)
        # The app waits 20 seconds for a download and half a second between
        # looks for a tab. Here two seconds, and a twentieth of a second.
        wait, expect = page.wait_for_timeout, page.expect_download
        page.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        page.expect_download = lambda *a, timeout=None, **kw: expect(*a, timeout=2000, **kw)
        return page

    yield SimpleNamespace(show=show, ctx=ctx, heard=heard, asked=asked, fetched=fetched)
    browser.close()
    driver.stop()


def _download(page, out):
    return site.ally_download(page, page.context, "", DATE, out, document_id=DOCUMENT_ID)


def _files(folder):
    return [p for p in folder.rglob("*") if p.is_file()]


@pytest.mark.parametrize("press, answered", [
    (OFF_HOST, []),
    (ANSWERED_THEN_OFF_HOST, ["fetch"]),
], ids=["Ally's page heard nothing", "Ally's page heard the statement asked for"])
def test_a_tab_off_allys_hosts_is_never_fetched_or_saved(ally, tmp_path, caplog, press, answered):
    page = ally.show(press)
    out = tmp_path / "Statements" / "2026-09-16 Ally Statement.pdf"
    with caplog.at_level(logging.INFO, logger=site.log.name):
        assert _download(page, out) is False
    assert _files(tmp_path) == []
    assert ally.asked[ANSWER] == answered
    assert len(ally.heard) == 1, "the press opened its one tab"
    assert ally.asked[ELSEWHERE] == ["document"], "the tab loaded and the app never fetched it"
    assert ally.fetched == []
    assert any("refusing to fetch a document from outside Ally" in r.getMessage()
               for r in caplog.records), caplog.text
    assert all(p.is_closed() for p in ally.heard), "the tab turned away is closed, as every tab read is"
    assert ally.ctx.pages == [page]


def test_a_blob_the_page_made_is_read_as_before(ally, tmp_path):
    page = ally.show(BLOB)
    out = tmp_path / "Statements" / "2026-09-16 Ally Statement.pdf"
    assert _download(page, out) is True
    assert out.read_bytes() == STATEMENT
    assert ally.asked[ANSWER] == ["fetch"]
    assert len(ally.heard) == 1
    [(where, url)] = ally.fetched
    assert where is page and url.startswith("blob:https://secure.ally.com/"), url
    assert all(p.is_closed() for p in ally.heard)
    assert ally.ctx.pages == [page]


def test_a_tab_at_allys_own_address_is_read_as_before(ally, tmp_path):
    page = ally.show(ON_HOST)
    out = tmp_path / "Statements" / "2026-09-16 Ally Statement.pdf"
    assert _download(page, out) is True
    assert out.read_bytes() == STATEMENT
    assert len(ally.heard) == 1
    assert ally.fetched == [(ally.heard[0], VIEWER)]
    assert ally.asked[VIEWER] == ["document", "fetch"]
    assert all(p.is_closed() for p in ally.heard)
    assert ally.ctx.pages == [page]
