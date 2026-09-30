"""A saved receipt names its order, and The Home Depot's name alone is not that.

Home Depot's details page must show this purchase's number in its heading
before anything is printed, and the printed PDF then passes the check
every receipt app runs, which used to pass any page that said Home Depot.
That last check is the one here, the app's own _finish_pdf. Measured on
real saved receipts before this was enabled, every one printed its order
number. Every number, item and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import homedepot_receipts as app_mod
from paperpull_core.models import ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def order():
    return Purchase(purchase_type=ONLINE, order_number="WH10000001",
                    purchase_date="2026-06-03", total="$37.88",
                    items=[Item(name="Invented 25 ft. Tape Measure")])


RECEIPT = ["Order Details", "Order # WH10000001", "Order Date: 06/03/2026",
           "Invented 25 ft. Tape Measure", "Model # INV25  Store SKU # 1000000001",
           "Subtotal $35.62", "Sales Tax $2.26", "Total $37.88"]

HOME_DEPOT_PAGE = ["The Home Depot", "How doers get more done.",
                   "Sign In  Purchase History  Store Finder",
                   "Truck & Tool Rental  Gift Cards",
                   "2000-2026 Home Depot. All Rights Reserved."]


def test_a_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_home_depot_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), HOME_DEPOT_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
