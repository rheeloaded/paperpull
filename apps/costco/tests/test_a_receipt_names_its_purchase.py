"""A saved receipt names its purchase, and Costco's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
Costco. It no longer does, and a warehouse receipt, whose key this app
invents and no receipt prints, is kept on the items it prints. A gas
receipt has no item and no number, so the app hands over the date and
total the list showed for it, and a receipt printing both is kept. One
with no Costco in its text was put aside before, since the name was all
the check could find on it (#47 is where the shape comes from). Here the
app's own _finish_pdf is handed each. Every number, item and amount is
invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_receipts as app_mod
import costco_site as site
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def warehouse_trip():
    return Purchase(purchase_type=IN_STORE, purchase_date="2026-06-12", total="$146.81",
                    order_number=site.warehouse_key("2026-06-12", "$146.81", "Springfield"),
                    items=[Item(name="KS PAPER TOWEL"), Item(name="ORGANIC EGGS")])


WAREHOUSE_RECEIPT = ["SPRINGFIELD #1234", "1234 Example Blvd", "Anytown, VA 22000",
                     "E 1000001 KS PAPER TOWEL 21.99", "E 1000002 ORGANIC EGGS 7.49",
                     "SUBTOTAL 140.00", "TAX 6.81", "**** TOTAL 146.81",
                     "06/12/2026 14:02 1234 5 67 890"]


def gas_stop():
    return Purchase(purchase_type=IN_STORE, purchase_date="2026-06-14", total="$36.37",
                    order_number=site.warehouse_key("2026-06-14", "$36.37", "Springfield"))


# The row the Warehouse tab showed for it, as discovery keeps it.
GAS_ROW = {"purchase_date": "2026-06-14", "total": "$36.37"}

GAS_RECEIPT = ["Gas Station Receipt", "SPRINGFIELD #1234", "Pump 4", "Gallons 11.024",
               "Price 3.299", "Regular", "Total Sale $36.37", "06/14/2026 09:14"]


def online_order():
    return Purchase(purchase_type=ONLINE, order_number="1000000001",
                    purchase_date="2026-04-30", total="$89.99",
                    items=[Item(name="Invented Patio Umbrella, 9 ft")])


ONLINE_INVOICE = ["Order Details", "Order Number: 1000000001", "Order Date: 04/30/2026",
                  "Invented Patio Umbrella, 9 ft  $89.99", "Order Total $89.99"]

COSTCO_PAGE = ["Costco", "Orders & Purchases", "Warehouse  Online",
               "Sign In / Register", "Membership  Costco Next  Services",
               "Terms and Conditions  Your Privacy Rights"]


def test_a_warehouse_receipt_is_kept_on_its_items(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), warehouse_trip(), WAREHOUSE_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_gas_receipt_is_kept_on_its_rows_date_and_total(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), gas_stop(), GAS_RECEIPT,
                           listed=GAS_ROW)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_gas_receipt_is_kept_when_the_list_kept_no_record_of_it(tmp_path):
    """The app writes the purchase's state before the check, so by then
    there is a record, and it says nothing the list showed."""
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), gas_stop(), GAS_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_another_days_gas_receipt_is_put_aside(tmp_path):
    other = [ln.replace("06/14/2026", "06/07/2026").replace("36.37", "41.02")
             for ln in GAS_RECEIPT]
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), gas_stop(), other, listed=GAS_ROW)
    assert not filed.kept and not filed.record.get("downloaded_ok")


def test_an_online_invoice_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), online_order(), ONLINE_INVOICE)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_costco_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), warehouse_trip(), COSTCO_PAGE,
                           listed={"purchase_date": "2026-06-12", "total": "$146.81"})
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
