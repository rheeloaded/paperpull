"""A review of the Meijer receipt press before it first runs (#42).

The press raised before anything was pressed from 0.31.0 to 0.39.1, so it
had never run on a real account, and a review of the version meant to fix
that pressed a wrapper at its middle, where an Email Receipt icon sat,
pressed a link reading view receipt pdf whose screen reader name said
Email, tried a copy hidden at this width, pressed November's receipt for a
January purchase whose date "1/19/2026" sits inside "11/19/2026", and found
no control when the row's words sit in a block beside it. Each of those is
a case here.

Pages are served on https://www.meijer.com and every other request is
refused, so nothing leaves this machine. Every date, store and amount is
invented.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site
from paperpull_core.models import IN_STORE

ORDERS = "https://www.meijer.com/shopping/orders.html"

SAVE_JS = ("function saveReceipt(tag) { const pdf = '%PDF-1.4 invented receipt ' + tag + ' ' + 'x'.repeat(300);"
           " const a = document.createElement('a');"
           " a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));"
           " a.download = 'receipt.pdf'; document.body.appendChild(a); a.click(); }")


def link(tag="0919", extra=""):
    return ("<a href='javascript:void(0)' %s onclick=\"window.__pressed.push('view receipt pdf %s');"
            "saveReceipt('%s'); return false\">view receipt pdf</a>" % (extra, tag, tag))


def row(date, controls, store="1600 Invented Road", amount="$31.23"):
    return ("<li class='order-card'><div class='date'>In-Store: %s</div><div>%s</div>"
            "<div class='totals'><span>%s</span>&nbsp;&nbsp;6 items</div>%s</li>" % (date, store, amount, controls))


def page_of(rows, head=""):
    return ("<!doctype html><html><head>%s</head><body><main><div id='store'><ul>%s</ul></div>"
            "<script>window.__pressed = []; %s</script></main></body></html>" % (head, "".join(rows), SAVE_JS))


@pytest.fixture
def browser_ctx():
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    browser = driver.chromium.launch(headless=True)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    try:
        yield ctx
    finally:
        browser.close()
        driver.stop()


def open_orders(ctx, html):
    ctx.route(ORDERS, lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    pg = ctx.new_page()
    pg.goto(ORDERS)
    return pg


def purchase_for(pg, date):
    ps = [p for p in map(site.card_to_purchase, site.collect_cards(pg)) if p and p.purchase_date == date]
    assert ps, "no purchase for %s" % date
    p = ps[0]
    p.purchase_type = IN_STORE
    return p


# 1. A wrapper whose only words are the link's is itself a candidate, it comes
#    before the link, and it is pressed at its middle.
def test_a_wrapper_around_the_link_is_never_pressed_at_its_middle(browser_ctx):
    controls = ("<div class='receipt-actions' style='display:grid;grid-template-columns:1fr 1fr 1fr;width:330px'>"
                + link() +
                "<button class='icon-email' aria-label='Email receipt' style='width:100%;height:24px'"
                " onclick=\"window.__pressed.push('email receipt')\"></button>"
                "<button class='icon-print' aria-label='Print receipt' style='width:100%;height:24px'"
                " onclick=\"window.__pressed.push('print receipt')\"></button></div>")
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    trace = []
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    pressed = pg.evaluate("window.__pressed")
    assert pressed == ["view receipt pdf 0919"], (pressed, trace[:2])
    assert body and b"receipt 0919" in body


def test_a_block_wrapper_with_the_link_at_its_right_end_presses_the_link(browser_ctx):
    controls = "<div class='receipt-pdf' style='text-align:right'>" + link() + "</div>"
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    trace = []
    t0 = time.monotonic()
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    took = time.monotonic() - t0
    pressed = pg.evaluate("window.__pressed")
    assert pressed == ["view receipt pdf 0919"] and body, (pressed, round(took, 1), trace)


# 3. The visible words say view receipt, the name a screen reader hears says
#    email. The guard knows neither email nor share nor print nor send.
@pytest.mark.parametrize("attr", ["aria-label='Email receipt'", "title='Email this receipt'",
                                  "aria-label='Share receipt'", "aria-label='Text receipt to my phone'"])
def test_a_control_named_email_but_reading_view_receipt_is_not_pressed(browser_ctx, attr):
    controls = ("<a href='javascript:void(0)' %s onclick=\"window.__pressed.push('the mislabeled one');"
                "return false\">view receipt pdf</a>" % attr)
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), [])
    pressed = pg.evaluate("window.__pressed")
    assert pressed == [], pressed
    assert body is None


# 4. The same control twice, once in a layout that is hidden at this width.
def test_a_hidden_copy_of_the_control_ahead_of_the_shown_one_is_passed_over(browser_ctx):
    controls = ("<a class='mobile-only' style='display:none' href='javascript:void(0)' "
                "onclick=\"window.__pressed.push('mobile');return false\">view receipt pdf</a>" + link())
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    trace = []
    t0 = time.monotonic()
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    took = time.monotonic() - t0
    print("\nTRACE 4:", trace, "took", round(took, 1))
    assert body and b"receipt 0919" in body, (round(took, 1), trace)


# 5. A January receipt, and a November one from the same store for the same
#    amount above it. "1/19/2026" is inside "11/19/2026".
@pytest.mark.parametrize("other,mine,date", [("11/19/2026", "01/19/2026", "2026-01-19"),
                                             ("12/15/2026", "02/15/2026", "2026-02-15")])
def test_the_right_rows_receipt_when_another_date_contains_this_one(browser_ctx, other, mine, date):
    rows = [row(other, link("other")), row(mine, link("mine"))]
    pg = open_orders(browser_ctx, page_of(rows))
    p = purchase_for(pg, date)
    body = site.press_row_receipt(pg, p, [])
    pressed = pg.evaluate("window.__pressed")
    assert pressed == ["view receipt pdf mine"], pressed
    assert body and b"receipt mine" in body


# 6. Another tab of the same browser on meijer.com answers with a PDF during
#    the press, which presses a control that produces nothing.
def test_a_pdf_in_another_tab_is_not_taken(browser_ctx):
    other_url = "https://www.meijer.com/other.html"
    other_pdf = "https://www.meijer.com/other.pdf"
    browser_ctx.route(other_url, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><script>setTimeout(() => fetch('/other.pdf'), 1500)</script></body></html>"))
    browser_ctx.route(other_pdf, lambda r: r.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4 ANOTHER TAB " + b"x" * 300))
    controls = ("<a href='javascript:void(0)' onclick=\"window.__pressed.push('view receipt pdf');"
                "return false\">view receipt pdf</a>")
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    p = purchase_for(pg, "2026-09-19")
    other = browser_ctx.new_page()
    other.goto(other_url)
    body = site.press_row_receipt(pg, p, [])
    assert body is None, body[:40]
    assert not other.is_closed(), "another tab was closed"


# 7. The window the press opens goes off meijer.com and hands over a PDF
#    there. The response path refuses an off-host PDF, the download path
#    does not look at the host.
def test_a_download_in_a_window_off_meijer_is_not_taken(browser_ctx):
    vendor = "https://receipts.vendor.example/r/abc"
    browser_ctx.route(vendor, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><script>" + SAVE_JS + " saveReceipt('OFFHOST');</script></body></html>"))
    controls = ("<a href='javascript:void(0)' onclick=\"window.open('%s', '_blank');return false\">"
                "view receipt pdf</a>" % vendor)
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    trace = []
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    assert body is None, (body[:40], trace)


# 8. The window the press opens opens one more. That one is neither listened
#    to nor closed.
def test_a_window_opened_by_the_window_is_not_left_open(browser_ctx):
    viewer = "https://www.meijer.com/receipt-viewer.html"
    pdf_url = "https://www.meijer.com/receipt/2.pdf"
    browser_ctx.route(viewer, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><script>window.open('%s', '_blank')</script></body></html>" % pdf_url))
    browser_ctx.route(pdf_url, lambda r: r.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4 GRANDCHILD " + b"x" * 300))
    controls = ("<a href='javascript:void(0)' onclick=\"window.open('%s', '_blank');return false\">"
                "view receipt pdf</a>" % viewer)
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    trace = []
    site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    pg.wait_for_timeout(500)
    left = [p.url for p in browser_ctx.pages if p != pg]
    assert not left, left


# 9. A window opened blank and never filled is closed, and the wait ends.
def test_a_window_left_blank_is_closed(browser_ctx):
    controls = ("<a href='javascript:void(0)' onclick=\"window.open('', '_blank');return false\">"
                "view receipt pdf</a>")
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    t0 = time.monotonic()
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), [])
    took = time.monotonic() - t0
    assert body is None
    assert len(browser_ctx.pages) == 1
    assert took < 20, took


# 10. More than ten candidates ahead of the receipt, so the handles are paired
#     by an index past 9.
def test_the_handle_pressed_is_the_candidate_picked_past_ten(browser_ctx):
    icons = "".join("<span class='receipt-icon' style='cursor:pointer' "
                    "onclick=\"window.__pressed.push('icon %d')\"></span>" % i for i in range(14))
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", icons + link())]))
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), [])
    assert pg.evaluate("window.__pressed") == ["view receipt pdf 0919"]
    assert body


# 11. The address of the window the press opened is fetched again, twice.
def test_the_windows_address_is_not_fetched_twice_more(browser_ctx):
    viewer = "https://www.meijer.com/receipt-viewer.html?id=77"
    hits = []

    def serve(r):
        hits.append(r.request.resource_type)
        r.fulfill(status=200, content_type="text/html", body="<html><body>Loading</body></html>")
    browser_ctx.route(viewer, serve)
    controls = ("<a href='javascript:void(0)' onclick=\"window.open('%s', '_blank');return false\">"
                "view receipt pdf</a>" % viewer)
    pg = open_orders(browser_ctx, page_of([row("09/19/2026", controls)]))
    site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), [])
    assert len(hits) <= 2, hits


# 13. The date, the store and the amount sit in a block of their own, and the
#     control beside it. The innermost element holding all three is that
#     block, and it holds no control.
def test_a_row_whose_words_sit_in_a_block_beside_the_control(browser_ctx):
    row_html = ("<li class='order-card'><div class='info'><div class='date'>In-Store: 09/19/2026</div>"
                "<div>1600 Invented Road</div><div class='totals'><span>$31.23</span>&nbsp;&nbsp;6 items</div></div>"
                "<div class='actions'>" + link() + "</div></li>")
    pg = open_orders(browser_ctx, page_of([row_html]))
    trace = []
    body = site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    assert body and pg.evaluate("window.__pressed") == ["view receipt pdf 0919"], trace


# 12. What a failed click writes into the file testers attach.
def test_a_failed_click_writes_no_page_words(browser_ctx):
    head = ("<style>#veil{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9}</style>")
    controls = link()
    html = page_of([row("09/19/2026", controls)], head=head).replace(
        "<main>", "<main><div id='veil'>Dana Quill card ending 4242 saved</div>")
    pg = open_orders(browser_ctx, html)
    trace = []
    site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace)
    print("\nTRACE 12:", trace)
    fails = [t for t in trace if t.get("note") == "click failed"]
    assert fails, trace
    assert "4242" not in str(fails) and "Dana" not in str(fails), fails


def test_two_rows_that_fit_one_purchase_press_nothing_and_say_so(browser_ctx):
    """The same store, amount and day twice. Neither is guessed at."""
    rows = [row("09/19/2026", link("a")), row("09/19/2026", link("b"))]
    pg = open_orders(browser_ctx, page_of(rows))
    trace = []
    assert site.press_row_receipt(pg, purchase_for(pg, "2026-09-19"), trace) is None
    assert pg.evaluate("window.__pressed") == []
    assert {"note": "more than one row fits this purchase, so none was pressed", "rows": 2} in trace, trace


def test_the_front_page_is_never_a_receipt_address():
    """An empty link, a "#" or a "/" resolves to Meijer's front page, which
    would have been printed and filed as the receipt."""
    for href in ("https://www.meijer.com", "https://www.meijer.com/", "https://www.meijer.com#"):
        assert not site.is_receipt_address(href), href
    assert site.is_receipt_address("https://www.meijer.com/shopping/receipt/12345.pdf")
    card = site.RawCard(text="In-Store: 09/19/2026 $31.23", links=[
        {"text": "view receipt", "label": "", "href": ""}, {"text": "view receipt", "label": "", "href": "#"},
        {"text": "view receipt", "label": "", "href": "/"}])
    assert site.receipt_links(card) == []
