"""Every tab a Print receipts press opens is closed, or handed back to be.

The press hands back a tab it opened, and the caller closes that one when
it is done with the receipt. It kept only the newest tab it heard of, so a
press that opened two handed back the second and left the first open in
the person's browser, and a press whose download came first handed back
the download and left its tab open.

In a real browser. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import target_site as site  # noqa: E402

RECEIPTS = "https://www.target.com/orders/902000101/receipts"
ELSEWHERE = "https://elsewhere.example/offer"

PAGE = """<!doctype html><html><body><main><h1>Receipts and invoices</h1>
<button id="print" type="button">Print receipts</button></main><script>
const ELSEWHERE = '%s';
document.getElementById('print').addEventListener('click', () => {
  %%s
});
</script></body></html>""" % ELSEWHERE

# Two tabs, both at once, so each is there a second and a half later when
# the press first looks.
TWO_TABS = ("window.open(ELSEWHERE + '?first', '_blank');"
            " window.open(ELSEWHERE + '?second', '_blank');")

# A download and a tab, both at once, so each is there a second and a half
# later when the press first looks, and the download is taken.
TAB_AND_DOWNLOAD = (
    "const a = document.createElement('a');"
    " a.href = URL.createObjectURL(new Blob(['%PDF-1.4 invented receipt ' + 'x'.repeat(400)],"
    "                                       {type: 'application/pdf'}));"
    " a.download = 'receipt.pdf'; document.body.appendChild(a); a.click();"
    " window.open(ELSEWHERE, '_blank');")


@pytest.fixture()
def target():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    served = {"press": ""}
    asked: list = []

    def elsewhere(route):
        asked.append(route.request.resource_type)
        route.fulfill(status=200, content_type="text/html",
                      body="<html><body><h1>An offer</h1></body></html>")

    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(RECEIPTS, lambda r: r.fulfill(
        status=200, content_type="text/html", body=PAGE % served["press"]))
    ctx.route(ELSEWHERE + "*", elsewhere)
    page = ctx.new_page()
    heard: list = []
    ctx.on("page", lambda p: heard.append(p))

    def show(press):
        served["press"] = press
        page.goto(RECEIPTS)
        return page

    yield SimpleNamespace(show=show, ctx=ctx, heard=heard, asked=asked)
    browser.close()
    driver.stop()


def test_one_of_two_tabs_is_handed_back_and_the_other_closed(target):
    page = target.show(TWO_TABS)
    kind, shown = site.trigger_print_receipt(page, page.locator("#print"), timeout_ms=3000)
    assert kind == "popup"
    assert len(target.heard) == 2, "the press opened two tabs"
    older, newest = target.heard
    assert shown is newest and not newest.is_closed(), "the newest is handed back, as before"
    assert older.is_closed(), "the other tab the press opened is closed"
    assert target.asked == ["document", "document"], "neither tab was read"
    shown.close()
    assert target.ctx.pages == [page]


def test_a_tab_beside_a_download_is_closed(target):
    page = target.show(TAB_AND_DOWNLOAD)
    kind, download = site.trigger_print_receipt(page, page.locator("#print"), timeout_ms=3000)
    assert kind == "download"
    assert download.suggested_filename == "receipt.pdf"
    assert len(target.heard) == 1, "the press opened a tab as well"
    assert all(p.is_closed() for p in target.heard), "the tab is closed, the download is what came back"
    assert target.asked == ["document"]
    assert target.ctx.pages == [page]
