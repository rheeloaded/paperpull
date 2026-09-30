"""A saved receipt names its purchase, and Meijer's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
Meijer. A till receipt shaped like the member's own (#42) carries nothing
else the check could find, no number and no item the row gave, so the app
hands over the date and total the row showed, and a till receipt printing
both is kept.

Here the app's own _finish_pdf is handed each. Every amount, store and
word is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_receipts as app_mod
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app

ROW = {"purchase_date": "2026-09-19", "total": "$22.37", "order_number": "pexample0919"}


def till_purchase():
    """As the In-Store Receipts row gave it, the store's address as its
    description, which the receipt does not print that way."""
    return Purchase(purchase_type=IN_STORE, order_number="pexample0919",
                    purchase_date="2026-09-19", total="$22.37",
                    items=[Item(name="1234 Example Rd, Anytown MI")])


TILL = ["MEIJER STORE 000", "09/19/26 14:02", "SUBTOTAL 21.10", "TAX 1.27",
        "TOTAL 22.37", "THANK YOU"]


def online_order():
    return Purchase(purchase_type=ONLINE, order_number="ORD10000001",
                    purchase_date="2026-09-12", total="$48.60",
                    items=[Item(name="Invented Pickup Order")])


ONLINE_RECEIPT = ["Meijer", "Order ORD10000001", "Pickup Sep 12, 2026",
                  "Invented Heirloom Carrots, 2 lb  $5.99", "Order Total $48.60"]

MEIJER_PAGE = ["Meijer", "Your Orders", "Orders and Receipts",
               "Online Orders  In-Store Receipts",
               "You have not placed any orders yet.", "Privacy Policy  Terms of Use"]


def test_a_till_receipt_is_kept_on_its_rows_date_and_total(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), till_purchase(), TILL, listed=ROW)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_till_receipt_is_kept_when_the_list_kept_no_record_of_it(tmp_path):
    """_finish_pdf writes the purchase's state before it checks, which
    leaves a record holding only that. round five's own test found a till
    receipt put aside when that record was taken for the row."""
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), till_purchase(), TILL)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_an_online_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), online_order(), ONLINE_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_meijer_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), till_purchase(), MEIJER_PAGE,
                           listed=ROW)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()


def test_another_days_till_receipt_is_put_aside(tmp_path):
    other = [ln.replace("09/19/26", "09/12/26").replace("22.37", "31.23") for ln in TILL]
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), till_purchase(), other, listed=ROW)
    assert not filed.kept and not filed.record.get("downloaded_ok")
