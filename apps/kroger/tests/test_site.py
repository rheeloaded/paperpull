"""The Kroger site layer, against the API shapes the page's own bundle
names. Every record here is made up. Nothing in them is a real purchase."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import kroger_site as site
from paperpull_core.models import IN_STORE, ONLINE, Purchase

RECORD_IN_STORE = {
    "receiptKey": "011~00123~20260913~5~1234",
    "purchaseType": "IN_STORE",
    "createdDateTime": {"value": "2026-09-13T15:04:05Z", "timezone": "UTC"},
    "total": "USD 42.17",
    "status": "COMPLETED",
    "lineItems": [
        {"upc": "0001111041700", "quantity": 2, "displayInfo": {"description": "Kroger 2% Milk"}},
        {"upc": "0001111060903", "quantity": 1},
    ],
}
RECORD_PICKUP = {
    "receiptKey": "011~00123~20260910~9~4321",
    "orderNumber": "123456789012",
    "purchaseType": "SELF_SERVE_PICKUP",
    "createdDateTime": {"value": "2026-09-10T09:00:00Z"},
    "total": 61.5,
    "status": "COMPLETED",
    "lineItems": [],
}
RECORD_PENDING = {
    "orderNumber": "123456789099",
    "purchaseType": "INSTACART_DELIVERY",
    "createdDateTime": {"value": "2026-09-21T09:00:00Z"},
    "total": "USD 30.00",
    "status": "INPROCESS",
}
RECORD_CANCELLED = {
    "orderNumber": "123456789055",
    "purchaseType": "SELF_SERVE_PICKUP",
    "createdDateTime": {"value": "2026-09-01T09:00:00Z"},
    "total": "USD 12.00",
    "status": "CANCELLED",
}


def test_an_in_store_record_becomes_an_in_store_purchase_keyed_by_its_receipt():
    p = site.record_to_purchase(RECORD_IN_STORE)
    assert p.purchase_type == IN_STORE
    assert p.order_number == "011~00123~20260913~5~1234"
    assert p.purchase_date == "2026-09-13"
    assert p.total == "$42.17"
    assert p.status == "Completed"
    assert p.store_info == "In-Store"
    assert p.receipt_url == "https://www.kroger.com/mypurchases/image/011~00123~20260913~5~1234"
    assert [i.name for i in p.items] == ["Kroger 2% Milk", "UPC 0001111060903"]
    assert p.items[0].quantity == "2"
    assert not site.record_is_pending(RECORD_IN_STORE)


def test_a_pickup_order_with_a_receipt_is_online_and_keyed_by_the_receipt_not_the_order():
    p = site.record_to_purchase(RECORD_PICKUP)
    assert p.purchase_type == ONLINE
    assert p.order_number == "011~00123~20260910~9~4321"
    assert p.total == "$61.50"
    assert p.store_info == "Pickup"


def test_a_pending_order_is_kept_by_its_order_number_and_marked_pending():
    p = site.record_to_purchase(RECORD_PENDING)
    assert site.record_is_pending(RECORD_PENDING)
    assert p.order_number == "123456789099"
    assert p.purchase_type == ONLINE
    assert "Pending" in p.notes
    assert p.status == "Inprocess"


def test_a_cancelled_order_without_a_receipt_is_not_pending():
    p = site.record_to_purchase(RECORD_CANCELLED)
    assert not site.record_is_pending(RECORD_CANCELLED)
    assert p.status == "Canceled"


def test_a_record_without_any_key_is_dropped_and_a_bad_key_too():
    assert site.record_to_purchase({"purchaseType": "IN_STORE"}) is None
    assert site.record_to_purchase({"receiptKey": "../../etc"}) is None
    assert site.record_to_purchase({"receiptKey": "a" * 100}) is None


def test_money_from_the_api_in_both_spellings():
    assert site.money_from_api("USD 12.34") == "$12.34"
    assert site.money_from_api(1234.5) == "$1,234.50"
    assert site.money_from_api("USD 1234") == "$1,234.00"
    assert site.money_from_api(None) == ""
    assert site.money_from_api("free") == ""


def test_purchase_types_route_to_the_right_folder():
    assert site.purchase_kind("IN_STORE") == IN_STORE
    assert site.purchase_kind("FUEL") == IN_STORE
    assert site.purchase_kind("SELF_SERVE_PICKUP") == ONLINE
    assert site.purchase_kind("INSTACART_DELIVERY") == ONLINE
    assert site.purchase_kind("SOMETHING_NEW") == ONLINE
    assert site.purchase_label("FUEL") == "Fuel Center"
    assert site.purchase_label("SOMETHING_NEW") == "Something New"


RECEIPT_TEXT = """Print
In Store
Kroger
1980 Example Center
Springfield, VA 22150
09/13/2026 3:04 PM
Kroger 2% Milk $3.29
Bananas 2 @ $0.59 $1.18
Kroger Large Eggs
$4.99
Subtotal $9.46
Sales Tax $0.00
Total $9.46
VISA $9.46
Total Savings $1.20
"""


class _Page:
    url = "https://www.kroger.com/mypurchases/image/011~00123~20260913~5~1234"

    def __init__(self, body, has_area=True):
        self._body = body
        self._has = has_area

    def title(self):
        return "Kroger"

    def locator(self, sel):
        page = self

        class _L:
            def count(self_):
                return 1 if (page._has or sel == "body") else 0

            @property
            def first(self_):
                return self_

            def inner_text(self_, timeout=0):
                return page._body

            def all(self_):
                return []
        return _L()


def test_the_rendered_receipt_gives_items_and_never_the_summary_lines():
    p = site.extract_details(_Page(RECEIPT_TEXT), Purchase(purchase_type=IN_STORE, order_number="x"))
    names = [i.name for i in p.items]
    assert "Kroger 2% Milk" in names
    assert "Bananas" in names
    assert "Kroger Large Eggs" in names
    for bad in ("Subtotal", "Sales Tax", "Total", "VISA", "Total Savings", "Print"):
        assert not any(n.startswith(bad) for n in names), bad
    assert p.total == "$9.46"
    assert p.purchase_date == "2026-09-13"
    assert site.receipt_is_present(_Page(RECEIPT_TEXT))
    assert not site.receipt_is_present(_Page(RECEIPT_TEXT, has_area=False))


def test_the_pages_own_words_for_empty_missing_and_failed_are_recognized():
    assert site.history_state(_Page("No Orders Yet\nLooks like there aren't any orders to show.")) == "empty"
    assert site.history_state(_Page("Missing Loyalty ID")) == "no-loyalty"
    assert site.history_state(_Page("Orders\nRecent Items\nIn-Store 09/13/2026 $42.17")) == ""
    assert site.receipt_failed(_Page("There was a problem loading the receipt. Please try again."))
    assert not site.receipt_failed(_Page(RECEIPT_TEXT))


def test_nothing_that_shops_refunds_tips_or_prints_is_safe():
    for t in ("Add all to cart", "Add to Cart", "Buy again", "Start Your Order", "Request a Refund",
              "Update Tip", "Clip Coupon", "Cancel Order", "Print", "Share Feedback", "Sign Out"):
        assert not site.is_safe_control(t), t
    for t in ("View Receipt", "Purchase Details", "Purchase History", "Order Receipt"):
        assert site.is_safe_control(t), t


def test_only_kroger_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.kroger.com/mypurchases/image/011~00123~20260913~5~1234")
    assert site.is_safe_url("https://www.kroger.com/mypurchases")
    assert not site.is_safe_url("https://kroger.com.evil.test/x")
    assert not site.is_safe_url("http://www.kroger.com/")
    assert not site.is_safe_url("https://user@kroger.com/")


def test_the_diagnose_file_keeps_shapes_and_masks_values():
    masked = site.mask_json([RECORD_IN_STORE, RECORD_PICKUP, RECORD_PENDING, RECORD_CANCELLED])
    assert len(masked) == 4 and masked[3] == "... 1 more"
    first = masked[0]
    assert first["purchaseType"] == "IN_STORE" and first["status"] == "COMPLETED"
    assert "20260913" not in first["receiptKey"] and "~" in first["receiptKey"]
    assert "42" not in first["total"]
    assert first["lineItems"][0]["quantity"] == 2
    assert "0001111041700" not in site.to_json(masked)
    assert site.mask_text("card 4111111111111111 for pat@example.com") == "card ################ for <email>"
