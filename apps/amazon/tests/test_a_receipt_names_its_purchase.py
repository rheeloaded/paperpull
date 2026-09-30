"""A saved order summary names its order, and Amazon's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
Amazon, which every page of the site does. Here the app's own _finish_pdf
is handed a printable order summary, which it keeps, and an Amazon page
that names no order, which it puts aside. Measured on real saved summaries
before this was enabled, every one printed its order number. Every
number, item and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts as app_mod
from paperpull_core.models import ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def order():
    return Purchase(purchase_type=ONLINE, order_number="111-2223333-4445555",
                    purchase_date="2026-06-03", total="$27.98",
                    items=[Item(name="Invented Stainless Water Bottle, 32 oz")])


SUMMARY = ["Final Details for Order #111-2223333-4445555",
           "Order Placed: June 3, 2026",
           "Amazon.com order number: 111-2223333-4445555",
           "Order Total: $27.98",
           "Items Ordered  Price",
           "1 of: Invented Stainless Water Bottle, 32 oz  $24.99",
           "Sold by: Example Seller",
           "Item(s) Subtotal: $24.99", "Total before tax: $24.99",
           "Estimated tax to be collected: $2.99", "Grand Total: $27.98"]

# The chrome of any Amazon page, and no order in it.
AMAZON_PAGE = ["amazon", "Hello, sign in  Account & Lists  Returns & Orders",
               "Your Orders", "Looks like you have not placed an order in this period.",
               "Conditions of Use  Privacy Notice  Your Ads Privacy Choices",
               "1996-2026, Amazon.com, Inc. or its affiliates"]


def test_an_order_summary_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), SUMMARY)
    assert filed.kept and filed.record["downloaded_ok"] is True
    assert filed.path.parent.name != "Manual Review"


def test_a_page_naming_only_amazon_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), AMAZON_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
