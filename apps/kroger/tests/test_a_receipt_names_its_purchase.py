"""A saved receipt names its purchase, and Kroger's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
Kroger. The receipt page a tester recorded (#41) prints the purchase's key
as its Order Number, and its items, so a receipt is kept on those. A
receipt that shows neither, one whose Item Details never filled in, is
kept on the date and total the purchase list gave, which the app hands
over as well. Here the app's own _finish_pdf is handed each. The receipt
has the recorded receipt's shape, and every item, number and address in it
is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import kroger_receipts as app_mod
from paperpull_core.models import IN_STORE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app

KEY = "540~00123~2026-09-20~101~1234567"
ROW = {"purchase_date": "2026-09-20", "total": "$21.48", "order_number": KEY}


def purchase():
    return Purchase(purchase_type=IN_STORE, order_number=KEY, purchase_date="2026-09-20",
                    total="$21.48", store_info="Metro Market",
                    items=[Item(name="Invented Cold Brew Coffee, 32 oz"),
                           Item(name="Invented Sparkling Water, 12 pk")])


HEADER = ["Order Type: In Store", "Order Date: Sep. 20, 2026",
          "Order Number: " + KEY, "Loyalty Card (last 4): 12345"]
STORE = ["Metro Market", "100 Example Rd", "Anytown, WI 53000 USA"]
SUMMARY = ["Order Summary", "Original Item Total", "$23.46", "Sales Tax", "+$0.52",
           "Order Total", "$21.48"]
ITEMS = ["Item Details", "2 Items", "Invented Cold Brew Coffee, 32 oz", "$6.49",
         "1 x $6.49 each", "UPC: 0001111000222", "Invented Sparkling Water, 12 pk",
         "$6.99", "3 x $2.33 each", "UPC: 0001111000444"]

RECEIPT = HEADER + STORE + SUMMARY + ITEMS + ["Payment Details", "$21.48"]

# The same receipt with no number and no items on it, only its date and
# its total.
BARE = ["Order Type: In Store", "Order Date: Sep. 20, 2026"] + STORE + SUMMARY

KROGER_PAGE = ["Kroger", "Sign In  My Purchases  Weekly Ad  Digital Coupons",
               "Purchase History", "Privacy Policy  Terms and Conditions",
               "2026 The Kroger Co. All Rights Reserved."]


def test_a_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), purchase(), RECEIPT, listed=ROW)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_receipt_with_only_its_date_and_total_is_kept(tmp_path):
    bare = purchase()
    bare.items = []
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), bare, BARE, listed=ROW)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_the_same_receipt_is_kept_when_the_list_kept_no_record_of_it(tmp_path):
    """The purchase's own date and total stand in, since the only record
    by then is the state the app wrote before its check."""
    bare = purchase()
    bare.items = []
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), bare, BARE)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_kroger_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), purchase(), KROGER_PAGE,
                           listed=ROW)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
