"""A saved receipt names its purchase, and Lowe's name alone is not that.

Lowe's details page must show this purchase's number in its heading
before anything is printed, and the printed PDF then passes the check
every receipt app runs, which used to pass any page that said Lowes. That
last check is the one here, the app's own _finish_pdf. Measured on real
saved receipts before this was enabled, every one printed its number.
Every number, item and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import lowes_receipts as app_mod
from paperpull_core.models import IN_STORE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app


def purchase():
    return Purchase(purchase_type=IN_STORE, order_number="308000001",
                    purchase_date="2026-06-03", total="$52.14",
                    items=[Item(name="Invented 5-Gallon Bucket")])


RECEIPT = ["Transaction # 308000001", "Purchase Date Jun 3, 2026",
           "Store #0000 Anytown", "Invented 5-Gallon Bucket",
           "Item # 1000001  Model # INV5", "Subtotal $48.95", "Tax $3.19",
           "Total $52.14"]

# Lowes.com, as a footer says it, since the apostrophe of the PDF's own
# font does not read back as one.
LOWES_PAGE = ["Lowes.com", "Sign In  Purchase History  Lists",
              "Find a Store  Weekly Ad", "Lowes.com Terms  Privacy Statement"]


def test_a_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), purchase(), RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_lowes_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), purchase(), LOWES_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
