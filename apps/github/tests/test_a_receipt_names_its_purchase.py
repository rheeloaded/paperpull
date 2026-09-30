"""A saved receipt names its payment, and GitHub's name alone is not that.

The check a PDF passes before it is kept used to pass any page that said
GitHub. Nobody here has seen a real receipt, only that a tester's five
came back as PDFs from /account/receipt/<id> (#43), so the app hands over
the date and amount its row showed as well, and a receipt printing both
is kept whether or not it prints the id.

What this does not catch is the payment history itself printed as a
receipt, which happened on 2026-09-29 after a sign-in in the middle of a
run. The history names the payment's own id, date and amount, since that
is what a history is, so no check of the words on a page can tell it from
the payment's receipt. That wants a check of the page before it is
printed, the way Best Buy reads its details page's heading.

Here the app's own _finish_pdf is handed each. Every id and amount is
invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import github_receipts as app_mod
from paperpull_core.models import ONLINE, Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app

# The row as round two read it (#43), its date, its ID column and its amount.
ROW = {"purchase_date": "2026-06-01", "total": "$10.00", "order_number": "ABCD1234"}


def payment():
    return Purchase(purchase_type=ONLINE, order_number="ABCD1234",
                    purchase_date="2026-06-01", total="$10.00", status="Paid",
                    items=[Item(name="ABCD1234", quantity="1", line_total="$10.00")])


RECEIPT_WITH_ITS_ID = ["GitHub, Inc.", "Receipt", "Receipt number ABCD1234",
                       "Date Jun 1, 2026", "GitHub Copilot Pro (monthly)  $10.00",
                       "Total $10.00", "Charged to Visa ending in 4242"]

RECEIPT_WITHOUT_IT = ["GitHub, Inc.", "Receipt", "Billed on 06/01/2026",
                      "GitHub Copilot Pro (monthly)  $10.00",
                      "Total $10.00", "Charged to Visa ending in 4242"]

GITHUB_PAGE = ["GitHub", "Sign in to GitHub", "Username or email address",
               "Password", "Forgot password?", "Terms  Privacy  Docs"]


def test_a_receipt_that_prints_its_id_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), payment(), RECEIPT_WITH_ITS_ID,
                           listed=ROW)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_receipt_that_prints_only_its_date_and_amount_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), payment(), RECEIPT_WITHOUT_IT,
                           listed=ROW)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_the_same_receipt_is_kept_when_the_list_kept_no_record_of_it(tmp_path):
    """The payment's own date and amount stand in, since the only record
    by then is the state the app wrote before its check."""
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), payment(), RECEIPT_WITHOUT_IT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_github_is_put_aside(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), payment(), GITHUB_PAGE,
                           listed=ROW)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()
