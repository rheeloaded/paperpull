"""Lowe's pages as they are really built, in a real browser.

A purchase on the history is not one element. The list is a flat run of
rows in one shared container, a header row and then item and status rows,
and one purchase's header on the real page put its date in a row of its
own. Climbing up from each View Details link found four purchases on a
page of five. And a page with one purchase on it let the climb reach the
filter bar, whose "In Progress" became that purchase's status.

The details page keeps a hidden print copy beside the visible receipt,
smaller than it, and taking the smallest block printed a blank page.

In a real browser, because innerText and layout are what went wrong and a
fake page cannot get them wrong the same way. Every purchase is invented.
"""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import lowes_site as site
from paperpull_core.models import IN_STORE, ONLINE


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def t_of(number):
    return base64.b64encode(number.encode()).decode()


def head(label, date, total, kind, number, t, split=False):
    """A header row. split puts the date in a row of its own, the way one
    real purchase did."""
    href = "/mylowes/orders/details?t=%s&amp;s=U2FsdGVkX1abc&amp;ih=Qg==" % t
    date_row = '<div class="row"><h2>%s: %s</h2><span>%s</span></div>' % (label, date, total)
    num_row = ('<div class="row"><div class="col"><div class="row"><span>%s #%s</span></div>'
               '<div class="col"><a href="%s">View Details</a></div></div></div>' % (kind, number, href))
    if split:
        return date_row + num_row
    return '<div class="row">%s%s</div>' % (date_row, num_row)


def rows(name, status):
    return ('<div class="row"><a href="/pd/x/1">%s</a></div>'
            '<div class="row"><h3>%s</h3><button>Buy it Again</button></div>' % (name, status))


def history(*purchases, filters=True):
    bar = ('<div>Purchase History</div><button>All Orders</button><button>In Progress</button>'
           '<button>Delivered</button><select><option>Most Recent</option><option value="all">All</option></select>'
           if filters else "")
    body = "".join(purchases)
    return ('<html><body><nav>Shop All Deals</nav><main>%s<div class="list">%s</div>'
            '<p>Note: Your online order history can\'t be used as a receipt for returns.</p>'
            '<button>1</button><button>2</button><button>3</button>'
            '</main><footer><h3>ABOUT LOWE\'S</h3><a href="/pd/rec/9">Recommended Drill</a></footer></body></html>'
            % (bar, body))


P1 = head("Order Date", "Mar 4, 2026", "$18.40", "Order", "300900000000000001", t_of("300900000000000001")) \
    + rows("Garden Hose 50-ft", "Delivered")
P2 = head("Order Date", "Feb 1, 2026", "$42.10", "Transaction", "123456789", "MjAyNjAyMDExMjM0NTY3ODk=") \
    + rows("Wood Filler 6-oz", "Completed")
P3 = head("Order Date", "Jan 20, 2026", "$7.50", "Transaction", "987654321", "MjAyNjAxMjA5ODc2NTQzMjE=",
          split=True) + rows("Tape Measure 16-ft", "Completed")
P4 = head("Return Initiated", "Jan 9, 2026", "$12.00", "Order", "203200000000000002", t_of("203200000000000002")) \
    + rows("Paint Roller Cover", "Return Received at Store")
P5 = head("Order Date", "Dec 2, 2025", "$0.00", "Order", "300900000000000003", t_of("300900000000000003")) \
    + rows("Battery Gas Detector", "Canceled")


def test_every_purchase_on_a_flat_list_is_found(page):
    page.set_content(history(P1, P2, P3, P4, P5))
    cards = site.collect_cards(page)
    assert [c.number for c in cards] == ["300900000000000001", "123456789", "987654321",
                                         "203200000000000002", "300900000000000003"]
    ps = [site.card_to_purchase(c) for c in cards]
    assert [p.purchase_type for p in ps] == [ONLINE, IN_STORE, IN_STORE, ONLINE, ONLINE]
    assert [p.purchase_date for p in ps] == ["2026-03-04", "2026-02-01", "2026-01-20", "2026-01-09", "2025-12-02"]
    assert ps[3].document_type == "Return"
    assert ps[4].status == "Canceled"
    assert ps[2].items[0].name == "Tape Measure 16-ft", "the purchase whose date sits in its own row"


def test_a_lone_purchase_does_not_take_the_filter_bar_or_the_footer(page):
    page.set_content(history(P2))
    [c] = site.collect_cards(page)
    p = site.card_to_purchase(c)
    assert p.status == "Completed", "not the filter bar's In Progress"
    assert p.items[0].name == "Wood Filler 6-oz", "not the footer's recommended product"


def test_the_pager_says_how_many_pages(page):
    page.set_content(history(P1))
    assert site.page_count(page) == 3


DETAILS = """<html><body><nav>Shop All Deals Gift Zone</nav><main>
<div class="print" style="display:none"><div class="orderdetails-print-container">orderdetails
Transaction # 123456789 Placed February 1, 2026 $42.10 Total Billed $42.10</div></div>
<div class="crumbs">Home MyLowe's Orders &amp; Purchases Order Details</div>
<div class="receipt">
  <h1>Transaction # 123456789</h1><h3>Placed February 1, 2026</h3><span>$42.10</span>
  <button>Print Details</button>
  <div><h3>Completed</h3><p>Springfield Lowe's</p><p>100 MAIN ST,</p></div>
  <div><a href="/pd/x/1">Wood Filler 6-oz</a><p>Item #111222 Model #WF6</p><p>$9.98 /ea.</p><p>QTY 2</p>
       <a role="button" href="#">Write a Review</a><button>Buy it Again</button></div>
  <div><h3>Payment Method</h3><p>VISA</p><p>**** **** **** 0000</p></div>
  <div><h3>Order Summary</h3><p>Subtotal $17.96</p><p>Tax $1.08</p><p>Total Billed $42.10</p>
       <p>Note: Item pricing may update in cart when reordering.</p></div>
</div></main><footer><h3>ABOUT LOWE'S</h3></footer></body></html>"""


def test_the_visible_receipt_is_isolated_not_the_hidden_print_copy(page, tmp_path):
    page.set_content(DETAILS)
    assert site.receipt_is_present(page)
    assert site.details_number(page) == "123456789"
    assert site.isolate_receipt(page)
    shown = page.locator("body").inner_text()
    assert "Total Billed" in shown and "0000" in shown, "the card, which the print copy leaves out"
    for gone in ("Shop All", "ABOUT LOWE", "Buy it Again", "Write a Review", "Print Details",
                 "Note: Item pricing"):
        assert gone not in shown, gone
    from paperpull_core import receipt_pdf
    from pypdf import PdfReader
    out = tmp_path / "r.pdf"
    receipt_pdf.print_page_to_pdf(page, out)
    text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    assert "Total Billed" in text and "Transaction # 123456789" in text
