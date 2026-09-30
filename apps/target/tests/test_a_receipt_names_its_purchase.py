"""A saved receipt names its purchase, and Target's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
Target. Measured on real saved receipts before this was enabled, all of
them name their purchase by its number or an item except an invoice that
holds only a delivery tip. When an order has more than one invoice the
app saves the first, and when that one is the tip it names nothing of the
order. It is put aside now rather than filed as the order's invoice.

Here the app's own _finish_pdf is handed each. Every number, item and
amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts as app_mod
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def online_order():
    return Purchase(purchase_type=ONLINE, order_number="900000000000001",
                    purchase_date="2026-02-14", total="$64.20",
                    items=[Item(name="Invented Puzzle Game - Deluxe Edition")])


# An invoice page prints no order number, so it names its order by an item
# or not at all, like the tip invoice below.
INVOICE = ["Invoice 2 of 2", "Invoice date: Sat, Feb 14, 2026",
           "Invoice number: 10000000000000001",
           "Item 10000001 - Invented Puzzle Game - Deluxe Edition",
           "Qty. 1  Unit price $59.99  Amount $59.99", "Invoice total $64.20"]

# The order's other invoice, a delivery tip and nothing of the order.
TIP_INVOICE = ["Invoice 1 of 2", "Invoice date: Sat, Feb 14, 2026",
               "Invoice number: 10000000000000002", "Item 10000002 - shipt_tip",
               "Qty. 1  Unit price $5.00  Amount $5.00", "Invoice total $5.00",
               "Target Circle Card", "About Target  Target Help  Returns",
               "TM & 2026 Target Brands, Inc."]


def store_trip():
    return Purchase(purchase_type=IN_STORE, order_number="1234-5678-0001-2345",
                    purchase_date="2026-06-12", total="$18.27",
                    items=[Item(name="Invented Dish Soap, 24 oz")])


STORE_RECEIPT = ["Target", "Anytown", "1234 Example Pkwy", "06/12/2026 02:14 PM",
                 "Invented Dish Soap, 24 oz  $4.49", "SUBTOTAL $17.00",
                 "TOTAL $18.27", "REC# 1234-5678-0001-2345"]

TARGET_PAGE = ["Target", "Sign in", "Orders  Online  In store",
               "Target Circle  Registry  Weekly Ad", "About Target  Target Help",
               "TM & 2026 Target Brands, Inc."]


def test_an_online_invoice_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), online_order(), INVOICE)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_store_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), store_trip(), STORE_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_target_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), online_order(), TARGET_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()


def test_a_tip_invoice_is_not_the_orders_invoice(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), online_order(), TIP_INVOICE)
    assert not filed.kept and filed.path.parent.name == "Manual Review"
