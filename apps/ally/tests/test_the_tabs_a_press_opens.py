"""Every tab a statement row's press opens is closed, whatever came of it.

When a row's control fires no download, the app takes the first new tab
the press opened, reads the statement there when it is at Ally's own
address, and closed that tab and no other. So a second tab from the same
press stayed open in the person's browser, and so did a tab opened by a
press whose download came through. Chase does the same press the same way
and had the same leak.

In a real browser. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import ally_site as site  # noqa: E402

DOCUMENTS = "https://secure.ally.com/dashboard/statements"
VIEWER = "https://secure.ally.com/acs/v1/documents/invented/view"
ELSEWHERE = "https://elsewhere.example/offer"
DATE = "2026-09-16"
PDF = b"%PDF-1.4 invented statement " + b"x" * 400

PAGE = """<!doctype html><html><body><main><h1>Statements</h1>
<table><tr><td>September 16, 2026</td><td>Statement</td>
<td><button id="row" aria-label="Download statement for: Statement">Download</button></td></tr></table>
</main><script>
const VIEWER = '%s', ELSEWHERE = '%s';
document.getElementById('row').addEventListener('click', () => {
  %%s
});
</script></body></html>""" % (VIEWER, ELSEWHERE)

# The statement in a tab on Ally, and a second and a half later a second
# tab somewhere else. The gap keeps the tabs in the order they opened,
# since the app reads the first.
TWO_TABS = ("window.open(VIEWER, '_blank');"
            " setTimeout(() => window.open(ELSEWHERE, '_blank'), 1500);")

# A tab somewhere else, and two seconds later the statement as a download.
# The gap lets the browser announce the tab well before the press is over,
# since a tab announced only after that is a race of its own.
TAB_THEN_DOWNLOAD = (
    "window.open(ELSEWHERE, '_blank');"
    " setTimeout(() => {"
    "  const a = document.createElement('a');"
    "  a.href = URL.createObjectURL(new Blob(['%PDF-1.4 invented statement ' + 'x'.repeat(400)],"
    "                                        {type: 'application/pdf'}));"
    "  a.download = 'statement.pdf'; document.body.appendChild(a); a.click(); }, 2000);")


@pytest.fixture()
def ally():
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
        # The tab is a page to look at. Asked for by a fetch, it answers
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

    def show(press):
        served["press"] = press
        page.goto(DOCUMENTS)
        # The app waits 20 seconds for a download and half a second between
        # looks for a tab. Here five seconds, and a twentieth of a second.
        wait, expect = page.wait_for_timeout, page.expect_download
        page.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        page.expect_download = lambda *a, timeout=None, **kw: expect(*a, timeout=5000, **kw)
        return page

    yield SimpleNamespace(show=show, ctx=ctx, heard=heard, asked=asked)
    browser.close()
    driver.stop()


def _capture(page, out):
    return site._download_via_row(page, page.context, "", DATE, out)


def test_a_second_tab_from_the_same_press_is_closed(ally, tmp_path):
    page = ally.show(TWO_TABS)
    out = tmp_path / "Statements" / "2026-09-16 Ally Statement.pdf"
    out.parent.mkdir(parents=True)
    assert _capture(page, out) is True
    assert out.read_bytes() == PDF
    assert len(ally.heard) == 2, "the press opened two tabs"
    assert ally.asked[ELSEWHERE] == ["document"], "the second tab was never read"
    assert all(p.is_closed() for p in ally.heard), "both tabs are closed"
    assert ally.ctx.pages == [page]


def test_a_tab_opened_by_a_press_whose_download_came_is_closed(ally, tmp_path):
    page = ally.show(TAB_THEN_DOWNLOAD)
    out = tmp_path / "Statements" / "2026-09-16 Ally Statement.pdf"
    out.parent.mkdir(parents=True)
    assert _capture(page, out) is True
    assert out.read_bytes().startswith(b"%PDF-1.4 invented statement ")
    assert len(ally.heard) == 1, "the press opened a tab before its download"
    assert ally.asked[ELSEWHERE] == ["document"]
    assert all(p.is_closed() for p in ally.heard), "the tab is closed though the download came"
    assert ally.ctx.pages == [page]
