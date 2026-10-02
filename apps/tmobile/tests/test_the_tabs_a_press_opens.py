"""A tab a bill's press opens is closed, whatever came of it.

A bill's Download detailed bill is handed to the core's delivery, so that
a bill T-Mobile someday opens in a tab rather than downloads is still
caught (see bill_request). A tab at T-Mobile's own address is read and a
tab anywhere else is turned away unread. Delivery closes the tabs a press
opened only when the request asks it to, and this app's did not, so a tab
turned away stayed open in the person's browser, one per bill, and so did
a tab the bill was read from. Navy Federal and Fairfax Water ask.

In a real browser. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import tmobile_site as site  # noqa: E402
from paperpull_core import delivery  # noqa: E402
from paperpull_core.testkit import text_pdf  # noqa: E402

HISTORY = site.BASE + "/bill/historical"
VIEWER = site.BASE + "/bill/view/invented"
ELSEWHERE = "https://elsewhere.example/offer"
DATE = "2027-02-17"
PDF = text_pdf(["T-Mobile bill", "Bill date 02/17/2027", "February 17, 2027"])

PAGE = """<!doctype html><html><body><main><h1>Bill history</h1>
<ul><li><span>Feb 17, 2027</span>
<button id="row" aria-label="Feb 17, 2027 Download detailed bill PDF">Download detailed bill</button></li></ul>
</main><script>
const VIEWER = '%s', ELSEWHERE = '%s';
document.getElementById('row').addEventListener('click', () => {
  %%s
});
</script></body></html>""" % (VIEWER, ELSEWHERE)

# The bill opens in a tab somewhere other than T-Mobile.
OFF_HOST = "window.open(ELSEWHERE, '_blank');"

# The bill opens in a tab on T-Mobile.
ON_TMOBILE = "window.open(VIEWER, '_blank');"


@pytest.fixture()
def tmobile():
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
        # with the bill, the way delivery reads it.
        kind = route.request.resource_type
        asked[VIEWER].append(kind)
        if kind == "document":
            route.fulfill(status=200, content_type="text/html",
                          body="<html><body><h1>Your bill</h1></body></html>")
        else:
            route.fulfill(status=200, content_type="application/pdf", body=PDF)

    def elsewhere(route):
        asked[ELSEWHERE].append(route.request.resource_type)
        route.fulfill(status=200, content_type="text/html",
                      body="<html><body><h1>An offer</h1></body></html>")

    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(HISTORY, lambda r: r.fulfill(
        status=200, content_type="text/html", body=PAGE % served["press"]))
    ctx.route(VIEWER, viewer)
    ctx.route(ELSEWHERE, elsewhere)
    page = ctx.new_page()
    heard: list = []
    ctx.on("page", lambda p: heard.append(p))

    def show(press):
        served["press"] = press
        page.goto(HISTORY)
        return page

    yield SimpleNamespace(show=show, ctx=ctx, heard=heard, asked=asked)
    browser.close()
    driver.stop()


def _deliver(page, out):
    # As the app hands it over, less the journal and with five seconds to
    # wait.
    request = site.bill_request(page, DATE)
    assert request is not None, "the bill's button was found"
    return delivery.deliver(page, request, out, is_safe_url=site.is_safe_url,
                            settle_ms=5000, strict=False)


def test_a_tab_off_tmobile_is_turned_away_unread_and_closed(tmobile, tmp_path):
    page = tmobile.show(OFF_HOST)
    out = tmp_path / "Bills" / "2027-02-17 T-Mobile Bill.pdf"
    out.parent.mkdir(parents=True)
    got = _deliver(page, out)
    assert got.outcome == delivery.NOTHING
    assert not out.exists()
    assert len(tmobile.heard) == 1, "the press opened its one tab"
    assert tmobile.asked[ELSEWHERE] == ["document"], "the tab was loaded and never fetched"
    assert all(p.is_closed() for p in tmobile.heard), "the tab turned away is closed"
    assert tmobile.ctx.pages == [page]


def test_a_tab_the_bill_was_read_from_is_closed(tmobile, tmp_path):
    page = tmobile.show(ON_TMOBILE)
    out = tmp_path / "Bills" / "2027-02-17 T-Mobile Bill.pdf"
    out.parent.mkdir(parents=True)
    got = _deliver(page, out)
    assert (got.outcome, got.mechanism) == (delivery.SAVED, delivery.TAB)
    assert out.read_bytes() == PDF
    assert len(tmobile.heard) == 1, "the press opened its one tab"
    assert all(p.is_closed() for p in tmobile.heard), "the tab is closed once read"
    assert tmobile.ctx.pages == [page]
