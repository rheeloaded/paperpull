"""A saved invoice names its order, and Walmart's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
Walmart. On 2026-09-29 the order list, printed after a sign-in in the
middle of a run, was kept that way as an online order's invoice and marked
downloaded, so the invoice itself would never have been asked for. The
list names Walmart and none of that order's own facts.

Here the app's own _finish_pdf is handed each. The receipts are shaped as
Walmart prints them. Each prints the number the app keys its purchase on,
but broken up with dashes, an online order's Order# in two groups and a
store purchase's TC# in groups of four, and the check looks for the number
written the way the app keeps it, so it never finds it. A receipt passes
on its items. Measured on real saved receipts before this was enabled,
every one did, and every one printed its number that way. Every number,
item and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import walmart_receipts as app_mod
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app

ONLINE_ORDER = Purchase(purchase_type=ONLINE, order_number="100000000000003",
                        purchase_date="2026-06-03", total="$58.20",
                        items=[Item(name="Invented Garden Hose, 50 ft"),
                               Item(name="Invented Brass Hose Nozzle")])

INVOICE = ["Walmart", "Jun 3, 2026 order", "Order# 1000000-00000003", "Delivered",
           "Invented Garden Hose, 50 ft", "Qty 1  $41.97",
           "Invented Brass Hose Nozzle", "Qty 1  $9.98",
           "Subtotal $51.95", "Tax $6.25", "Total $58.20"]

STORE_TRIP = Purchase(purchase_type=IN_STORE, order_number="20000000000000000004",
                      purchase_date="2026-06-12", total="$23.41",
                      items=[Item(name="Invented Whole Milk, 1 gal"),
                             Item(name="Invented Sourdough Loaf")])

STORE_RECEIPT = ["Walmart", "Save money. Live better.", "Example Supercenter",
                 "INVENTED WHOLE MILK, 1 GAL  3.48", "INVENTED SOURDOUGH LOAF  4.97",
                 "SUBTOTAL 21.94", "TAX 1.47", "TOTAL 23.41", "06/12/26 14:02:11",
                 "TC# 2000-0000-0000-0000-0004"]

# What the run printed in place of the online order's invoice, with the
# order's date as the run held it after reading the list.
ORDER_LIST = ["Walmart  Save money. Live better.", "Purchase history",
              "Store purchase", "Purchased at Example Supercenter",
              "Jun 12, 2026", "$23.41", "View details",
              "Delivered", "$58.20", "View details"]


def misread_order():
    return Purchase(purchase_type=ONLINE, order_number="100000000000003",
                    purchase_date="2026-06-12", total="$58.20")


def test_an_online_invoice_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), ONLINE_ORDER, INVOICE)
    assert filed.kept and filed.record["downloaded_ok"] is True
    assert filed.path.exists() and filed.path.parent.name != "Manual Review"


def test_a_store_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), STORE_TRIP, STORE_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_the_order_list_is_put_aside_not_kept_as_the_invoice(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), misread_order(), ORDER_LIST)
    assert not filed.kept
    assert not filed.record.get("downloaded_ok"), "marked downloaded, never asked for again"
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
    assert "does not mention" in filed.record["notes"]
