"""A Best Buy details page, isolated and printed, in a real browser.

The page's own "Print Receipt" calls window.print and "View Receipt" only
spins, so neither is pressed. The smallest visible block holding this
purchase's number, a total and a SKU is kept. Every purchase is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_site as site
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


PAGE = """<html><body>
<header>Shop Deals Support &amp; Services Top Deals</header>
<main><div class="order-details-page__column-wrapper">
  <h1>Order Details</h1><a href="javascript:void(0)" onclick="window.print()">Print Receipt</a>
  <p>Purchase Date: May 26, 2026</p><p>Order Number: BBY01-800000000007</p><p>Total: $501.37</p>
  <h2>Order Summary</h2><p>Sales Tax, Fees &amp; Surcharges: $28.38</p>
  <div><p>Invented Console 1TB</p><p>Model: INV-00001</p><p>SKU: 1234567</p><p>Quantity: 1</p>
       <p>Item Total: $516.37</p><a href="#">Write a Review</a></div>
</div>
<aside>Recommended for you: Invented Headset</aside></main>
<div class="confirmIt modal-backdrop in" id="confirmIt-backdrop">How was your visit?</div>
<footer>Corporate Information | Careers | Get the latest deals and more.</footer></body></html>"""


def test_the_receipt_block_is_printed_and_nothing_else(page, tmp_path):
    page.set_content(PAGE)
    site.hide_survey(page)
    assert site.receipt_is_present(page)
    assert site.details_number(page) == "BBY01-800000000007"
    assert site.isolate_receipt(page, "BBY01-800000000007")
    out = tmp_path / "r.pdf"
    receipt_pdf.print_page_to_pdf(page, out)
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    assert "Order Number: BBY01-800000000007" in text and "SKU: 1234567" in text
    for gone in ("Top Deals", "Recommended", "Corporate Information", "How was your visit",
                 "Write a Review", "Print Receipt"):
        assert gone not in text, gone
    assert not receipt_pdf.was_print_called(page)


def test_a_page_for_another_purchase_is_not_isolated(page):
    page.set_content(PAGE)
    assert not site.isolate_receipt(page, "BBY01-899999999999")
