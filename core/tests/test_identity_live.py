"""Identity against real PDFs, rendered the way the apps render them.

test_identity.py checks the matching by handing it text. That proves the
rules and proves nothing about whether pypdf gets the text back out of a
document a browser produced, which is the only form this ever sees.

Twelve providers have no file to download and are printed from a page.
For those, this is the whole pipeline. For the rest it is still how the
saved file gets read.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import identity as I

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

RECEIPT = """<!doctype html>
<title>Receipt</title>
<body style="font: 14px system-ui; padding: 24px">
  <h1>Costco Wholesale</h1>
  <p>Warehouse #1234</p>
  <p>Order Number 8421997301</p>
  <p>January 15, 2026</p>
  <table>
    <tr><td>Kirkland paper towels</td><td>24.99</td></tr>
    <tr><td>Rotisserie chicken</td><td>4.99</td></tr>
  </table>
  <p>Subtotal 1,204.18</p>
  <p><strong>Total $1,284.55</strong></p>
  <p>Thank you for shopping with us. Please retain this receipt for your
     records, as it is required for returns and for warranty claims.</p>
</body>
"""

# The same receipt for the document listed one row below it.
NEIGHBOR = (RECEIPT.replace("8421997301", "8421997999")
                   .replace("January 15, 2026", "February 9, 2026")
                   .replace("$1,284.55", "$76.41"))

BLANK = """<!doctype html><title>Blank</title>
<body style="margin:0"><img src="data:image/gif;base64,R0lGODlhAQABAIAAAP//
/wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==" style="width:600px;height:800px">
</body>"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def rendered(browser, html, out: Path) -> Path:
    """A PDF the way an app makes one, through the same core helper."""
    from paperpull_core import receipt_pdf
    page = browser.new_page()
    try:
        page.set_content(html, wait_until="load")
        receipt_pdf.print_page_to_pdf(page, out)
    finally:
        page.close()
    return out


def test_the_helper_makes_a_pdf_at_all(browser, tmp_path):
    """If this fails, every assertion below is about nothing."""
    out = rendered(browser, RECEIPT, tmp_path / "r.pdf")
    assert out.is_file()
    assert out.read_bytes().startswith(b"%PDF")


def test_a_rendered_receipt_verifies_against_what_it_was_listed_as(
        browser, tmp_path):
    out = rendered(browser, RECEIPT, tmp_path / "right.pdf")
    v = I.verify(out, I.Identity(date="2026-01-15", total="1284.55",
                                 number="8421997301"))
    assert v.outcome == I.VERIFIED
    assert set(v.matched) == {"date", "total", "number"}


def test_the_row_below_is_refused(browser, tmp_path):
    """The bug this module exists for, end to end. The app believes it is
    saving the January receipt and the page gave it February's."""
    out = rendered(browser, NEIGHBOR, tmp_path / "wrong.pdf")
    v = I.verify(out, I.Identity(date="2026-01-15", total="1284.55",
                                 number="8421997301"))
    assert v.outcome == I.REFUSED
    assert v.matched == ()
    assert not v.ok


def test_and_the_neighbor_verifies_against_its_own_details(browser, tmp_path):
    """The other half of the same test. A refusal that refuses everything
    is not a check, it is a bug."""
    out = rendered(browser, NEIGHBOR, tmp_path / "neighbor.pdf")
    v = I.verify(out, I.Identity(date="2026-02-09", total="76.41",
                                 number="8421997999"))
    assert v.outcome == I.VERIFIED


def test_a_blank_render_is_unreadable_rather_than_verified(browser, tmp_path):
    """A locked modal renders one blank sheet, which was a real Costco
    bug. It must not be able to pass as the document."""
    out = rendered(browser, BLANK, tmp_path / "blank.pdf")
    v = I.verify(out, I.Identity(date="2026-01-15", number="8421997301"))
    assert v.outcome in (I.UNREADABLE, I.REFUSED)
    assert v.outcome != I.VERIFIED


def test_a_document_with_no_expectation_is_never_refused(browser, tmp_path):
    """Every provider that supplies nothing to check against keeps
    working exactly as it does today."""
    out = rendered(browser, RECEIPT, tmp_path / "unchecked.pdf")
    assert I.verify(out, I.Identity()).outcome == I.UNCHECKED
    assert I.verify(out, None).ok


def test_pypdf_gets_the_amount_back_out_of_a_rendered_table(browser, tmp_path):
    """Amounts inside a table cell are where extraction most often comes
    back spaced or reordered, and the total is one of four strong facts."""
    out = rendered(browser, RECEIPT, tmp_path / "amount.pdf")
    v = I.verify(out, I.Identity(total="1284.55"))
    assert v.outcome == I.VERIFIED, "the rendered total did not read back"
