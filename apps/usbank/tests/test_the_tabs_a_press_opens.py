"""Every tab a statement row's press opens is closed, whatever came of it.

When a row's Download fires no download, the app looks for a window the
press opened and reads the statement from there. It only ever takes a new
tab whose address is on U.S. Bank's own hosts, rightly, since the fetch
carries the signed-in session. A new tab anywhere else was never taken and
never closed either, so it stayed open in the person's browser and the press
came back with nothing. Only the one tab it took was ever closed, so a press
that opened two left one open, and a tab opened by a press whose download
came through was left open too.

In a real browser. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import usbank_site as site  # noqa: E402

DOCUMENTS = "https://onlinebanking.usbank.com/digital/servicing/documents"
VIEWER = "https://onlinebanking.usbank.com/digital/servicing/statement-view"
ELSEWHERE = "https://elsewhere.example/offer"
DATE = "2026-09-12"
PDF = b"%PDF-1.4 invented statement " + b"x" * 400

PAGE = """<!doctype html><html><body><main data-testid="document-view">
<h1>Statements and documents</h1>
<div data-testid="list-of-statements"><div class="document-list">
<h3>Checking statements</h3><ul>
<li class="download-items"><span>September 12, 2026</span>
<button id="row" aria-label="Download September 12, 2026 statement">Download</button></li>
</ul></div></div></main><script>
const VIEWER = '%s', ELSEWHERE = '%s';
document.getElementById('row').addEventListener('click', () => {
  %%s
});
</script></body></html>""" % (VIEWER, ELSEWHERE)

# A window somewhere other than U.S. Bank, and nothing else.
OFF_HOST = "window.open(ELSEWHERE, '_blank');"

# The statement in a window on U.S. Bank, and a second and a half later a
# second window somewhere else.
TWO_TABS = ("window.open(VIEWER, '_blank');"
            " setTimeout(() => window.open(ELSEWHERE, '_blank'), 1500);")

# A window somewhere else, and two seconds later the statement as a
# download. The gap lets the browser announce the window well before the
# press is over, since a window announced only after that is a race of its
# own.
TAB_THEN_DOWNLOAD = (
    "window.open(ELSEWHERE, '_blank');"
    " setTimeout(() => {"
    "  const a = document.createElement('a');"
    "  a.href = URL.createObjectURL(new Blob(['%PDF-1.4 invented statement ' + 'x'.repeat(400)],"
    "                                        {type: 'application/pdf'}));"
    "  a.download = 'statement.pdf'; document.body.appendChild(a); a.click(); }, 2000);")


@pytest.fixture()
def usbank(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    served = {"press": ""}
    asked = {VIEWER: [], ELSEWHERE: []}

    def viewer(route):
        # The window is a page to look at. Asked for by a fetch, it answers
        # with the statement, the way the app reads it.
        kind = route.request.resource_type
        asked[VIEWER].append(kind)
        if kind == "document":
            route.fulfill(status=200, content_type="text/html",
                          body="<html><body><h1>Your statement</h1></body></html>")
        else:
            route.fulfill(status=200, content_type="application/pdf", body=PDF)

    def elsewhere(route):
        asked[ELSEWHERE].append(route.request.resource_type)
        route.fulfill(status=200, content_type="text/html",
                      body="<html><body><h1>An offer</h1></body></html>")

    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(DOCUMENTS, lambda r: r.fulfill(
        status=200, content_type="text/html", body=PAGE % served["press"]))
    ctx.route(VIEWER, viewer)
    ctx.route(ELSEWHERE, elsewhere)
    page = ctx.new_page()
    heard: list = []
    ctx.on("page", lambda p: heard.append(p))
    # Where the app ran its fetch, to tell a tab it read from one it did not.
    fetched_in: list = []
    real_evaluate = pw.Page.evaluate

    def evaluate(self, expression, arg=None):
        if expression == site._FETCH_AS_B64:
            fetched_in.append(self)
        return real_evaluate(self, expression, arg)

    monkeypatch.setattr(pw.Page, "evaluate", evaluate)

    def show(press):
        served["press"] = press
        page.goto(DOCUMENTS)
        # The app waits 30 seconds for a download and half a second between
        # looks for a window. Here five seconds, and a twentieth of a second.
        wait, expect = page.wait_for_timeout, page.expect_download
        page.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        page.expect_download = lambda *a, timeout=None, **kw: expect(*a, timeout=5000, **kw)
        return page

    yield SimpleNamespace(show=show, ctx=ctx, heard=heard, asked=asked, fetched_in=fetched_in)
    browser.close()
    driver.stop()


def _capture(page, out):
    return site._click_row_and_capture(page, page.context, "", DATE, out)


def _at(tabs, url):
    return [p for p in tabs if p.url == url]


def test_a_window_off_us_bank_is_left_unread_and_closed(usbank, tmp_path):
    page = usbank.show(OFF_HOST)
    out = tmp_path / "Statements" / "2026-09-12 U.S. Bank Statement.pdf"
    out.parent.mkdir(parents=True)
    assert _capture(page, out) is False
    assert not out.exists()
    assert len(usbank.heard) == 1, "the press opened its one window"
    assert usbank.asked[ELSEWHERE] == ["document"], "the window was loaded and never fetched"
    assert usbank.fetched_in == []
    assert all(p.is_closed() for p in usbank.heard), "the window it would not take is closed"
    assert usbank.ctx.pages == [page]


def test_a_second_window_from_the_same_press_is_closed(usbank, tmp_path):
    page = usbank.show(TWO_TABS)
    out = tmp_path / "Statements" / "2026-09-12 U.S. Bank Statement.pdf"
    out.parent.mkdir(parents=True)
    assert _capture(page, out) is True
    assert out.read_bytes() == PDF
    assert len(usbank.heard) == 2, "the press opened two windows"
    assert usbank.fetched_in == _at(usbank.heard, VIEWER), "only the window on U.S. Bank was read"
    assert usbank.asked[ELSEWHERE] == ["document"]
    assert all(p.is_closed() for p in usbank.heard), "both windows are closed"
    assert usbank.ctx.pages == [page]


def test_a_window_opened_by_a_press_whose_download_came_is_closed(usbank, tmp_path):
    page = usbank.show(TAB_THEN_DOWNLOAD)
    out = tmp_path / "Statements" / "2026-09-12 U.S. Bank Statement.pdf"
    out.parent.mkdir(parents=True)
    assert _capture(page, out) is True
    assert out.read_bytes().startswith(b"%PDF-1.4 invented statement ")
    assert len(usbank.heard) == 1, "the press opened a window before its download"
    assert usbank.asked[ELSEWHERE] == ["document"]
    assert all(p.is_closed() for p in usbank.heard), "the window is closed though the download came"
    assert usbank.ctx.pages == [page]
