"""Pressing a row's receipt control, in a real browser (#42).

His 0.39.1 Pilot reached the In-Store tab for every receipt, then raised
AttributeError on each one before anything was pressed. The download
listener was handed downloads.append, a built-in method, and Playwright
marks the function it is given, which a built-in cannot be. No test pressed
a receipt control in a browser, so nothing had ever run that line.

The orders page and a receipt viewer are served here on www.meijer.com,
and every other request is refused, so nothing leaves this machine. Every
date, store and amount is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site
from paperpull_core.models import IN_STORE

ORDERS = "https://www.meijer.com/shopping/orders.html"
VIEWER = "https://www.meijer.com/receipt-viewer.html"

PAGE = """<!doctype html><html><body><main><h1>Orders and Receipts</h1>
<div role="tablist">
  <a role="tab" href="#" onclick="show('online');return false">Online Orders</a>
  <a role="tab" href="#" onclick="show('store');return false">In-Store Receipts</a>
</div>
<div id="online"><p>You haven't placed any orders yet</p></div>
<div id="store" style="display:none"><ul>
 <li class="order-card"><div class="date">In-Store: 09/19/2026</div><div>1600 Invented Road</div>
  <div class="totals"><span>$31.23</span>&nbsp;&nbsp;6 items</div>
  <a href="javascript:void(0)" onclick="PRESS;return false">view receipt pdf</a></li>
</ul></div>
<script>
function show(which) {
  document.getElementById('online').style.display = which === 'online' ? '' : 'none';
  document.getElementById('store').style.display = which === 'store' ? '' : 'none';
}
function saveReceipt() {
  const pdf = '%PDF-1.4\\n% invented receipt 09/19/2026\\n' + 'x'.repeat(300) + '\\n%%EOF\\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
  a.download = 'receipt.pdf';
  document.body.appendChild(a);
  a.click();
}
</script></main></body></html>"""


def _drive(press):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(ORDERS, lambda r: r.fulfill(status=200, content_type="text/html",
                                          body=PAGE.replace("PRESS", press)))
    ctx.route(VIEWER, lambda r: r.fulfill(status=200, content_type="text/html",
                                          body="<html><body><p>Your receipt is loading</p></body></html>"))
    pg = ctx.new_page()
    pg.goto(ORDERS)
    return driver, browser, pg


def _purchase(pg):
    assert site.show_tab_for(pg, IN_STORE)
    cards = site.collect_cards(pg)
    return next(p for p in map(site.card_to_purchase, cards) if p.purchase_date == "2026-09-19")


@pytest.mark.parametrize("press", [
    "saveReceipt()",
    # The page opens a window first, which is not the receipt, and the
    # download lands a moment later. The window's answer used to be kept as
    # if it were the receipt, which ended the wait before the download came.
    "window.open('%s', '_blank'); setTimeout(saveReceipt, 1500)" % VIEWER,
], ids=["a download", "a window, then a download"])
def test_a_receipt_the_row_downloads_is_saved(press):
    driver, browser, pg = _drive(press)
    try:
        trace: list = []
        body = site.press_row_receipt(pg, _purchase(pg), trace)
        assert body and body.startswith(b"%PDF-") and b"invented receipt 09/19/2026" in body, trace
        assert {"note": "the receipt came from the row's control",
                "control": "view receipt pdf", "how": "a download"} in trace, trace
    finally:
        browser.close()
        driver.stop()


# -- from the review of this change --------------------------------------------
#
# Until 0.39.2 the press never ran, so what it presses had never been tried
# on a real row. It pressed up to six of the row's controls in turn, a control
# with no words and an Email Receipt among them. Only the row's own receipt
# control is pressed now.

def _row_page(controls):
    return ("<!doctype html><html><body><main><div id='store'><ul>"
            "<li class='order-card'><div class='date'>In-Store: 09/19/2026</div><div>1600 Invented Road</div>"
            "<div class='totals'><span>$31.23</span>&nbsp;&nbsp;6 items</div>%s</li>"
            "</ul></div><script>window.__pressed = [];"
            "function saveReceipt() { const pdf = '%%PDF-1.4 invented receipt 09/19/2026 ' + 'x'.repeat(300);"
            " const a = document.createElement('a');"
            " a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));"
            " a.download = 'receipt.pdf'; document.body.appendChild(a); a.click(); }"
            "</script></main></body></html>" % controls)


def _drive_page(html, extra_routes=()):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(ORDERS, lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    for pattern, handler in extra_routes:
        ctx.route(pattern, handler)
    pg = ctx.new_page()
    pg.goto(ORDERS)
    purchase = next(p for p in map(site.card_to_purchase, site.collect_cards(pg))
                    if p.purchase_date == "2026-09-19")
    purchase.purchase_type = IN_STORE
    return driver, browser, pg, purchase


@pytest.mark.parametrize("before", [
    "<button onclick=\"window.__pressed.push('email receipt')\">Email receipt</button>",
    "<button class='icon' onclick=\"window.__pressed.push('no words')\"></button>",
    "<a href='javascript:void(0)' onclick=\"window.__pressed.push('share receipt');return false\">Share receipt</a>",
], ids=["an email receipt", "an icon with no words", "a share receipt"])
def test_only_the_rows_own_receipt_control_is_pressed(before):
    html = _row_page(before + "<a href='javascript:void(0)' onclick=\"window.__pressed.push('view receipt pdf');"
                     "saveReceipt(); return false\">view receipt pdf</a>")
    driver, browser, pg, purchase = _drive_page(html)
    try:
        body = site.press_row_receipt(pg, purchase, [])
        assert pg.evaluate("window.__pressed") == ["view receipt pdf"]
        assert body and b"invented receipt 09/19/2026" in body
    finally:
        browser.close()
        driver.stop()


def test_a_row_with_no_receipt_control_presses_nothing():
    html = _row_page("<button onclick=\"window.__pressed.push('email receipt')\">Email receipt</button>")
    driver, browser, pg, purchase = _drive_page(html)
    try:
        trace: list = []
        assert site.press_row_receipt(pg, purchase, trace) is None
        assert pg.evaluate("window.__pressed") == []
        assert {"note": "no control on the row reads as its receipt", "controls": 1} in trace, trace
    finally:
        browser.close()
        driver.stop()


def test_a_window_opened_blank_is_kept_until_it_is_filled():
    """The page warns that a pop-up blocker would stop it, so its window is
    opened on the press and filled once its own fetch answers."""
    pdf_url = "https://www.meijer.com/receipt/12345.pdf"
    pdf = b"%PDF-1.4\n% invented receipt 09/19/2026\n" + b"x" * 300 + b"\n%%EOF\n"
    html = _row_page("<a href='javascript:void(0)' onclick=\"const w = window.open('', '_blank');"
                     "setTimeout(() => { w.location.href = '%s'; }, 1200); return false\">"
                     "view receipt pdf</a>" % pdf_url)
    driver, browser, pg, purchase = _drive_page(html, [(pdf_url, lambda r: r.fulfill(
        status=200, content_type="application/pdf", body=pdf))])
    try:
        trace: list = []
        body = site.press_row_receipt(pg, purchase, trace)
        assert body and b"invented receipt 09/19/2026" in body
        assert len(pg.context.pages) == 1, "the window it opened is closed after"
        # and the file to attach says how it came, in words of the app's own.
        # A browser without a PDF viewer, this one, downloads what the window
        # is sent to, and a real Chrome shows it there.
        came = [t for t in trace if t.get("note") == "the receipt came from the row's control"]
        assert len(came) == 1 and came[0]["how"] in (
            "a download", "an answer to the window it opened", "the window it opened"), trace
    finally:
        browser.close()
        driver.stop()


def test_what_a_receipt_control_says():
    ok = [{"text": "view receipt pdf", "label": ""}, {"text": "View Receipt", "label": ""},
          {"text": "", "label": "Download PDF"}, {"text": "", "label": "View receipt PDF"}]
    no = [{"text": "Email receipt", "label": ""}, {"text": "", "label": ""},
          {"text": "", "label": "Email receipt PDF"}, {"text": "Hide receipt", "label": ""},
          {"text": "view receipt pdf", "label": "Pay now"}, {"text": "Archive", "label": ""}]
    assert all(site.is_receipt_control(c) for c in ok), ok
    assert not any(site.is_receipt_control(c) for c in no), no
