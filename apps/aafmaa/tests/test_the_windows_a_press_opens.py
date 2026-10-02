"""Every window a document's View press opens is closed, whatever came of it.

The press watches for a download, a PDF answer and a window the press
opens, and closes the window afterward. It kept only the newest window it
heard of, so a press that opened two closed the second and left the first
open in the person's browser.

In a real browser. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine. The row's
postback target is handed to the press as the pager walk would find it.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import aafmaa_site as site  # noqa: E402

DOCUMENTS = site.URLS["documents"]
ELSEWHERE = "https://elsewhere.example/notice"
TARGET = "ctl00$Main$rptDocuments$ctl02$lnkViewDocument"

PAGE = """<!doctype html><html><body><main><h1>Documents</h1>
<table><tr><td>Annual Statement</td><td>09/12/2026</td>
<td><a id="row" href="javascript:__doPostBack('%s','')">View</a></td></tr></table>
</main><script>
function __doPostBack() {}
const ELSEWHERE = '%s';
document.getElementById('row').addEventListener('click', (e) => {
  e.preventDefault();
  // Two windows, and two seconds later the document as a download, so the
  // browser has announced both well before the press is over.
  window.open(ELSEWHERE + '?first', '_blank');
  setTimeout(() => window.open(ELSEWHERE + '?second', '_blank'), 300);
  setTimeout(() => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['%%PDF-1.4 invented statement ' + 'x'.repeat(400)],
                                          {type: 'application/pdf'}));
    a.download = 'statement.pdf'; document.body.appendChild(a); a.click(); }, 2000);
});
</script></body></html>""" % (TARGET, ELSEWHERE)


@pytest.fixture()
def aafmaa(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    asked: list = []

    def elsewhere(route):
        asked.append(route.request.resource_type)
        route.fulfill(status=200, content_type="text/html",
                      body="<html><body><h1>A notice</h1></body></html>")

    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(DOCUMENTS, lambda r: r.fulfill(status=200, content_type="text/html", body=PAGE))
    ctx.route(ELSEWHERE + "*", elsewhere)
    page = ctx.new_page()
    page.goto(DOCUMENTS)
    heard: list = []
    ctx.on("page", lambda p: heard.append(p))
    monkeypatch.setattr(site, "_fresh_view_target", lambda *a, **kw: TARGET)
    # The app's half-second looks, a tenth of a second here, so its thirty
    # seconds of them take six.
    wait = page.wait_for_timeout
    page.wait_for_timeout = lambda ms: wait(max(1, ms // 5))
    yield SimpleNamespace(page=page, ctx=ctx, heard=heard, asked=asked)
    browser.close()
    driver.stop()


def test_every_window_the_press_opened_is_closed(aafmaa, tmp_path):
    out = tmp_path / "Statements" / "2026-09-12 AAFMAA Annual Statement.pdf"
    out.parent.mkdir(parents=True)
    assert site.download_document_row(aafmaa.page, "Annual Statement", "09/12/2026",
                                      "", out) is True
    assert out.read_bytes().startswith(b"%PDF-1.4 invented statement ")
    assert len(aafmaa.heard) == 2, "the press opened two windows"
    assert aafmaa.asked == ["document", "document"], "neither window was read"
    assert all(p.is_closed() for p in aafmaa.heard), "both windows are closed"
    assert aafmaa.ctx.pages == [aafmaa.page]
