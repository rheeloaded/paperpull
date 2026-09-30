"""A saved receipt names its order, and Apple's name alone is not that.

Apple's receipts are checked for their own order number before they are
filed (site.identity_for), and after that by the same check every receipt
app runs, which used to pass any page that said Apple. That last check is
the one here, the app's own _finish_pdf. Measured on real saved receipts
before this was enabled, every one printed its order number. Every
number, item and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import apple_receipts as app_mod
from apple_site import APP_STORE, APPLE_STORE
from paperpull_core.models import Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def app_store_purchase():
    return Purchase(purchase_type=APP_STORE, order_number="MX1AB2CD3E",
                    purchase_date="2026-06-03", total="$3.17",
                    items=[Item(name="Invented Puzzle Game Pro")])


APP_STORE_RECEIPT = ["Apple", "Receipt", "DATE Jun 3, 2026", "ORDER ID MX1AB2CD3E",
                     "DOCUMENT NO. 100000000001", "Invented Puzzle Game Pro",
                     "In-App Purchase  $2.99", "Subtotal $2.99", "Tax $0.18",
                     "TOTAL $3.17"]


def store_order():
    return Purchase(purchase_type=APPLE_STORE, order_number="W1000000001",
                    purchase_date="2026-05-20", total="$106.99",
                    items=[Item(name="Invented Silicone Case")])


STORE_INVOICE = ["Apple Store", "Invoice", "Order Number W1000000001",
                 "Order Date May 20, 2026", "Invented Silicone Case  $99.00",
                 "Subtotal $99.00", "Tax $7.99", "Total $106.99"]

APPLE_PAGE = ["Apple", "Report a Problem", "Sign in with your Apple Account",
              "Privacy Policy  Terms of Use  Sales Policy",
              "Copyright 2026 Apple Inc. All rights reserved."]


def test_an_app_store_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), app_store_purchase(),
                           APP_STORE_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_an_apple_store_invoice_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), store_order(), STORE_INVOICE)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_apple_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), app_store_purchase(), APPLE_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
