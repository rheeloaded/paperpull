"""The Home Depot site layer, against the shapes the live site showed on
2026-09-25. Every order, number and name here is invented."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import homedepot_site as site
from paperpull_core.models import IN_STORE, ONLINE, Purchase

HISTORY = "https://www.homedepot.com/oms/customer/order/v1/user/0A1B2C3D4E5F6G7H8I/orderhistory"


# -- the history request -------------------------------------------------------

def test_only_the_pages_own_history_request_is_replayed():
    assert site.history_request_ok(HISTORY)
    for bad in ("https://evil.test/oms/customer/order/v1/user/0A1B2C3D/orderhistory",
                "https://www.homedepot.com/oms/customer/order/v1/user/0A1B2C3D/orderdetails",
                "https://www.homedepot.com/oms/customer/order/v1/user/../orderhistory",
                "http://www.homedepot.com/oms/customer/order/v1/user/0A1B2C3D/orderhistory"):
        assert not site.history_request_ok(bad), bad


class _FetchPage:
    """Answers the in-page fetch with pages of invented orders."""

    def __init__(self, total, status=200):
        self.total, self.status, self.bodies = total, status, []

    def evaluate(self, js, args):
        url, body = args
        self.bodies.append(body)
        req = body["orderHistoryRequest"]
        start = (req["pageNumber"] - 1) * req["pageSize"]
        n = max(0, min(req["pageSize"], self.total - start))
        orders = [{"orderNumbers": ["WX%08d" % (start + i)], "orderOrigin": "online",
                   "salesDate": "2026-01-%02dT10:00:00Z" % (1 + (start + i) % 28), "type": "COM",
                   "totalAmount": 10.5 + i} for i in range(n)]
        return {"status": self.status, "data": {"orderCount": self.total, "orders": orders}}


REQUEST = {"url": HISTORY, "body": {"orderHistoryRequest": {
    "pageSize": 20, "pageNumber": 1, "startDate": "2024-08-25", "endDate": "2026-09-25",
    "timezone": "America/New_York"}}}


def test_every_page_of_the_history_is_read_with_the_pages_own_range():
    page = _FetchPage(45)
    got = site.fetch_orders(page, REQUEST)
    assert len(got["orders"]) == 45 and got["count"] == 45
    assert [b["orderHistoryRequest"]["pageNumber"] for b in page.bodies] == [1, 2, 3]
    assert all(b["orderHistoryRequest"]["startDate"] == "2024-08-25" for b in page.bodies), \
        "Home Depot refuses a range further back than two years"


def test_a_refused_request_stops_and_says_so():
    got = site.fetch_orders(_FetchPage(10, status=400), REQUEST)
    assert got["status"] == 400 and got["orders"] == []


def test_no_request_seen_means_nothing_is_asked():
    assert site.fetch_orders(_FetchPage(5), None)["status"] == "no history request"
    assert site.fetch_orders(_FetchPage(5), {"url": "https://evil.test/x", "body": {}})["orders"] == []


def test_an_order_becomes_a_purchase():
    p = site.order_to_purchase({"orderNumbers": ["WX12345678"], "orderOrigin": "online",
                                "salesDate": "2025-10-05T09:36:36Z", "type": "COM", "totalAmount": 95.37})
    assert (p.purchase_type, p.purchase_date, p.order_number, p.total) == (ONLINE, "2025-10-05", "WX12345678", "$95.37")
    assert p.details_url == ("https://www.homedepot.com/myaccount/order-details?orderNumber=WX12345678"
                             "&salesDate=2025-10-05T09:36:36Z&orderOrigin=online")


def test_a_store_order_is_filed_as_one():
    p = site.order_to_purchase({"orderNumbers": ["S12345678"], "orderOrigin": "store",
                                "salesDate": "2025-03-01T12:00:00Z", "totalAmount": 5})
    assert p.purchase_type == IN_STORE


def test_an_order_with_no_usable_number_is_dropped():
    for numbers in ([], [""], ["<script>"], ["x" * 40]):
        assert site.order_to_purchase({"orderNumbers": numbers, "salesDate": "2025-01-01"}) is None


# -- the receipt ------------------------------------------------------------------

RECEIPT = """Date Ordered: October 06, 2025

Order Number: WX00000001

Order Total: $858.59

Delivery

Product Information

Item

Qty

Price

Invented Brand 36 in Single Sink Vanity
with Marble Top

1

$809.99

Model #INV-36-0

Store SKU #1000000001

Second Invented Faucet

2

$20.00

Model #INV-F2

Store SKU #1000000002

Payment Information

Billing Address

Payment Method

AX | Ending in 0000

Payment Details

Subtotal
$899.99

Sales Tax
$48.60

Order Total
$858.59
"""


class _Page:
    def __init__(self, text):
        self.text, self.url = text, "https://www.homedepot.com/myaccount/order-details?orderNumber=WX00000001"

    def emulate_media(self, media=None):
        pass

    def evaluate(self, js, *a):
        return self.text


def test_items_are_read_backward_from_their_model_line():
    items = site.extract_items(RECEIPT)
    assert [(i.name, i.quantity, i.line_total) for i in items] == [
        ("Invented Brand 36 in Single Sink Vanity with Marble Top", "1", "$809.99"),
        ("Second Invented Faucet", "2", "$20.00"),
    ]


def test_the_receipt_gives_date_total_fulfillment_and_number():
    page = _Page(RECEIPT)
    p = site.extract_details(page, Purchase(order_number="WX00000001"))
    assert (p.purchase_date, p.total, p.fulfillment, p.status) == ("2025-10-06", "$858.59", "Delivery", "")
    assert site.details_number(page) == "WX00000001"
    assert site.receipt_is_present(page)


def test_a_canceled_order_is_known_by_its_receipt_not_its_history_total():
    """The history still says $569.07 for an order whose receipt bills nothing."""
    text = RECEIPT.replace("Order Total: $858.59", "Order Total: $0.00").replace("\nDelivery\n", "\nCanceled Items\n", 1)
    p = site.extract_details(_Page(text), Purchase(order_number="WX00000001", total="$569.07"))
    assert p.status == "Canceled"


def test_a_returned_order_keeps_its_receipt():
    text = RECEIPT.replace("\nDelivery\n", "\nReturn Completed\n", 1) + "\nRefund Total\n$858.59\n"
    p = site.extract_details(_Page(text), Purchase(order_number="WX00000001"))
    assert p.status == "Returned"


def test_a_pickup_says_so():
    text = RECEIPT.replace("\nDelivery\n", "\nPick Up\n", 1)
    assert site.extract_details(_Page(text), Purchase(order_number="WX00000001")).fulfillment == "Pick Up"


# -- guards --------------------------------------------------------------------

def test_view_receipt_and_everything_that_changes_an_order_are_refused():
    """View Receipt only opens the browser's print dialog, which blocks the
    window, so it is on the list too."""
    for name in ("View Receipt", "Buy Again", "Add to Cart", "Start a Return", "Cancel Order",
                 "Track Delivery", "Home Depot Credit Cards", "Instant Checkout", "Ask Magic Apron"):
        assert not site.is_safe_control(name), name


def test_reading_controls_are_allowed():
    for name in ("Purchase History", "Skip to Next Page", "2"):
        assert site.is_safe_control(name), name


def test_only_home_depot_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.homedepot.com/myaccount/purchase-history")
    assert not site.is_safe_url("http://www.homedepot.com/myaccount/purchase-history")
    assert not site.is_safe_url("https://homedepot.com.example.test/x")
    assert not site.is_safe_url("https://www.homedepotrental.com/")
