"""A saved receipt names its order, and Best Buy's name alone is not that.

Best Buy's details page must show this purchase's number in its heading
before anything is printed, and the printed PDF then passes the check
every receipt app runs, which used to pass any page that said Best Buy.
That last check is the one here, the app's own _finish_pdf. Measured on
real saved receipts before this was enabled, every one printed its order
number. Every number, item and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_receipts as app_mod
from paperpull_core.models import ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def order():
    return Purchase(purchase_type=ONLINE, order_number="BBY01-100000000001",
                    purchase_date="2026-06-03", total="$64.19",
                    items=[Item(name="Invented Wireless Mouse - Black")])


RECEIPT = ["Order Details", "Order BBY01-100000000001", "Order Date Jun 3, 2026",
           "Invented Wireless Mouse - Black", "Model: INV-100  SKU: 1000001",
           "Subtotal $59.99", "Tax $4.20", "Total Billed $64.19"]

BEST_BUY_PAGE = ["Best Buy", "Account  Order Status  Saved Items",
                 "Purchase History", "Sign in to see your purchases",
                 "Terms and Conditions  Privacy"]


def test_a_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_best_buy_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), BEST_BUY_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
