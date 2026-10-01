"""A saved receipt names its purchase, and Uber's name alone is not that.

Uber's receipts are its own PDFs, asked for by the purchase's id, and
checked for their Receipt ID or their date and total before they are
filed (site.identity_for). After that comes the check every receipt app
runs, which used to pass any page that said Uber, and Uber hands it the
store a purchase came from as well, which for a ride is Uber. Neither
counts now. Measured on real saved receipts before this was enabled,
every one still names its purchase, by its total, its date or its store.
Here the app's own _finish_pdf is handed each. Every id, place, distance
and amount is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import uber_receipts as app_mod
from paperpull_core.models import Item, Purchase
from paperpull_core.testkit import file_a_receipt, receipt_app
from uber_site import EATS, RIDES


def ride():
    return Purchase(purchase_type=RIDES, order_number="00000000-0000-4000-8000-000000000001",
                    purchase_date="2026-06-01", total="$14.20", store_info="Uber",
                    fulfillment="Ride", items=[Item(name="UberX, 3.02 miles, 14 minutes")])


RIDE_RECEIPT = ["Uber", "Thanks for riding, Dana", "June 1, 2026", "Total $14.20",
                "Trip fare $11.95", "Booking Fee $2.25", "UberX 3.02 miles | 14 min",
                "Visa 1234  6/1/26 9:14 AM  $14.20"]


def eats_order():
    """An older Uber Eats receipt paid by card, which prints no id and no
    item this check would find, only the store, the date and the total."""
    return Purchase(purchase_type=EATS, order_number="00000000-0000-4000-8000-000000000002",
                    purchase_date="2025-03-14", total="$23.10",
                    store_info="Invented Noodle House",
                    items=[Item(name="Plate"), Item(name="Bowl")])


EATS_RECEIPT = ["Invented Noodle House", "March 14, 2025", "1  Plate  $9.50",
                "1  Bowl  $8.75", "Service Fee $1.50", "Delivery Fee $0.99",
                "Total $23.10"]

UBER_PAGE = ["Uber", "Sign in to Uber", "Ride  Drive  Business  Uber Eats",
             "Help  Privacy  Accessibility  Terms",
             "2026 Uber Technologies Inc."]


def test_a_ride_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), ride(), RIDE_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_an_older_eats_receipt_is_kept(tmp_path):
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), eats_order(), EATS_RECEIPT)
    assert filed.kept and filed.record["downloaded_ok"] is True


def test_a_page_naming_only_uber_is_put_aside(tmp_path):
    """A ride's store is Uber, and that counts for nothing either."""
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), ride(), UBER_PAGE)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()


def january_order():
    return Purchase(purchase_type=EATS, order_number="00000000-0000-4000-8000-000000000003",
                    purchase_date="2027-01-19", total="$4.56",
                    store_info="Invented Noodle House",
                    items=[Item(name="Plate"), Item(name="Bowl")])


# Another store's receipt from November 19, which holds the January order's
# 1/19/27 inside its own 11/19/27.
NOVEMBER_RECEIPT = ["Invented Taco Stand", "November 19, 2027", "2  Taco  $31.00",
                    "Service Fee $3.56", "Total $34.56", "Paid 11/19/27 7:42 PM  $34.56"]


def test_another_days_receipt_holding_this_ones_date_is_put_aside(tmp_path):
    """The total and the dates count only as numbers of their own. Found
    anywhere, the January order's date was found inside the November
    receipt's and that receipt was kept as the January order's."""
    filed = file_a_receipt(receipt_app(app_mod, tmp_path), january_order(), NOVEMBER_RECEIPT)
    assert not filed.kept and not filed.record.get("downloaded_ok")
    assert filed.path.parent.name == "Manual Review" and filed.path.exists()


def test_the_tokens_for_the_total_and_the_dates_are_numbers_of_their_own():
    from paperpull_core.receipt_pdf import OnItsOwn
    from uber_site import receipt_tokens
    tokens = receipt_tokens(january_order())
    assert OnItsOwn(("$4.56",)) in tokens and "Invented Noodle House" in tokens
    dates = [t for t in tokens if isinstance(t, OnItsOwn) and "1/19/27" in t]
    assert len(dates) == 1 and "January 19, 2027" in dates[0]
    assert all(isinstance(t, (OnItsOwn, str)) and t for t in tokens)
