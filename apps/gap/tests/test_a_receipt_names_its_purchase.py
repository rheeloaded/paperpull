"""A saved receipt names its order, and Gap's name alone is not that.

Gap's word is short enough to be found in text that has nothing to do
with Gap, since the check also reads the text with its spaces taken out,
and "big apple" reads as "bigapple". It passed any page with those three
letters in a row. Here the app's own _finish_pdf is handed an order's
details page, which it keeps, and a Gap page naming no order, which it
puts aside. Measured on real saved receipts before this was enabled,
every one printed its order number. Every number, item and amount is
invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import gap_receipts as app_mod
from paperpull_core.models import ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def order():
    return Purchase(purchase_type=ONLINE, order_number="1ABC234",
                    purchase_date="2026-06-03", total="$42.50",
                    items=[Item(name="Invented Relaxed Crewneck T-Shirt")])


RECEIPT = ["Order Details", "Order #1ABC234", "Placed on June 3, 2026",
           "Invented Relaxed Crewneck T-Shirt", "Size M  Qty 1  $24.00",
           "Subtotal $40.00", "Tax $2.50", "Total $42.50"]

GAP_PAGE = ["Gap", "Sign In  Order History  Gap Good Rewards", "Orders & Returns",
            "Customer Service  Privacy Policy", "2026 Gap Inc."]


def test_a_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_gap_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), GAP_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()


def test_three_letters_in_a_row_are_not_gap(tmp_path):
    page = ["Visit the Big Apple flagship store on Fifth Avenue",
            "Store hours and directions", "Sign in to see your orders"]
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), order(), page)
    assert not filed.kept
