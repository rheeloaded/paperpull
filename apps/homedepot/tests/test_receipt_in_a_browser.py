"""Home Depot's receipt is on the details page already, shown only in print.

"View Receipt" does nothing but call window.print(), which opens the
browser's own print dialog, and that dialog blocks the window until a
person closes it. So the receipt is taken without pressing anything, by
switching the page to print media and keeping the one block.

In a real browser, because print media and a print-only class are what
this rests on and a fake page cannot honor either. Every order is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import homedepot_site as site
from paperpull_core import receipt_pdf


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    pg.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
    yield pg
    browser.close()
    driver.stop()


PAGE = r"""<html><head><style>
.sui-hidden { display: none; }
@media print { .print\:sui-block { display: block; } }
</style></head><body>
<header>Shop All Services DIY Me</header>
<main>
  <h1>ORDER DETAILS</h1><h2>ORDER # WX00000001</h2>
  <a onclick="window.print()">View Receipt</a>
  <div class="sui-hidden print:sui-block sui-m-[10px]">
    <p>Date Ordered: October 06, 2025</p><p>Order Number: WX00000001</p><p>Order Total: $858.59</p>
    <h3>Delivery</h3><h3>Product Information</h3>
    <p>Invented Brand Vanity</p><p>1</p><p>$809.99</p><p>Model #INV-36-0</p><p>Store SKU #1000000001</p>
    <h3>Payment Information</h3><p>Payment Method</p><p>AX | Ending in 0000</p>
    <h3>Payment Details</h3><p>Subtotal</p><p>$899.99</p><p>Order Total</p><p>$858.59</p>
  </div>
  <section>Delivered October 5 <button>Buy Again</button> UP TO 40% OFF Select Online Bath</section>
</main><footer>Store Locator | Home Depot</footer></body></html>"""


def test_the_receipt_is_read_without_pressing_anything(page):
    page.set_content(PAGE)
    assert site.receipt_is_present(page)
    assert site.details_number(page) == "WX00000001"
    assert not receipt_pdf.was_print_called(page)


def test_the_printed_receipt_is_the_block_and_nothing_else(page, tmp_path):
    page.set_content(PAGE)
    assert site.isolate_receipt(page)
    out = tmp_path / "r.pdf"
    receipt_pdf.print_page_to_pdf(page, out)
    site.restore_screen(page)
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    assert "Order Number: WX00000001" in text and "Payment Details" in text
    for gone in ("Shop All", "Store Locator", "Buy Again", "OFF Select", "View Receipt"):
        assert gone not in text, gone
    assert not receipt_pdf.was_print_called(page), "the print dialog was never asked for"


def test_the_page_is_left_on_screen_media(page):
    page.set_content(PAGE)
    site.isolate_receipt(page)
    site.restore_screen(page)
    assert page.evaluate("() => matchMedia('print').matches") is False
