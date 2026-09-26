"""The Best Buy site layer, against the shapes the live site showed on
2026-09-25. Every purchase, number and name here is invented."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_site as site
from paperpull_core.models import IN_STORE, ONLINE

QUERY = {"url": "https://www.bestbuy.com/gateway/graphql", "headers": {"content-type": "application/json"},
         "body": {"operationName": "consolidatedQuery", "query": "query consolidatedQuery { x }",
                  "variables": {"year": 2025, "orderOffset": 0, "purchaseOffset": 0,
                                "orderLimit": 5, "purchaseLimit": 5}}}


def entry(i, kind="online", total=10.0, created="2025-06-01T10:00:00-05:00"):
    number = "BBY01-80000000%04d" % i if kind == "online" else "100 1 %d 060125" % i
    return {"id": number, "orderType": kind, "orderTotal": total, "created": created,
            "orderStatusTitle": "Complete"}


class _Page:
    """Answers the in-page query with invented years, ten at a time."""

    def __init__(self, by_year, errors_for=()):
        self.by_year, self.errors_for, self.bodies = by_year, set(errors_for), []

    def evaluate(self, js, args):
        url, headers, body = args
        self.bodies.append(body)
        v = body["variables"]
        if v["year"] in self.errors_for:
            return {"status": 200, "data": {"errors": [{"message": "Bad Request"}]}}
        rows = self.by_year.get(v["year"], [])
        online = [e for e in rows if e["orderType"] != "store"][v["orderOffset"]:v["orderOffset"] + v["orderLimit"]]
        store = [e for e in rows if e["orderType"] == "store"][v["purchaseOffset"]:v["purchaseOffset"] + v["purchaseLimit"]]
        more = (v["orderOffset"] + len(online) < sum(1 for e in rows if e["orderType"] != "store")
                or v["purchaseOffset"] + len(store) < sum(1 for e in rows if e["orderType"] == "store"))
        return {"status": 200, "data": {"data": {"customer": {"purchaseHistoryOrdersExperience": {
            "closedOrdersAndTransactions": {"entries": online + store, "pageInfo": {"hasNext": more}},
            "openOrders": {"entries": [], "pageInfo": {"hasNext": False}}}}}}}

    def wait_for_timeout(self, ms):
        pass


# -- the history ----------------------------------------------------------------

def test_a_year_is_asked_ten_at_a_time_with_the_pages_own_query():
    page = _Page({2025: [entry(i) for i in range(4)]})
    got = site.fetch_year(page, QUERY, 2025)
    assert len(got["entries"]) == 4 and got["complete"]
    assert page.bodies[0]["variables"]["orderLimit"] == 10, "Best Buy refuses twenty"
    assert page.bodies[0]["operationName"] == "consolidatedQuery"


def test_online_orders_and_store_purchases_page_with_their_own_offsets():
    rows = [entry(i) for i in range(23)] + [entry(i, "store") for i in range(12)]
    page = _Page({2022: rows})
    got = site.fetch_year(page, QUERY, 2022)
    assert len(got["entries"]) == 35 and got["complete"]
    assert [(b["variables"]["orderOffset"], b["variables"]["purchaseOffset"]) for b in page.bodies] == \
        [(0, 0), (10, 10), (20, 12)]


def test_an_error_answer_is_not_taken_for_an_empty_year():
    got = site.fetch_year(_Page({}, errors_for={2013}), QUERY, 2013)
    assert got["status"] == "errors" and not got["complete"]


def test_nothing_is_asked_without_the_pages_query():
    assert site.fetch_year(_Page({}), None, 2025)["status"] == "no query"
    assert site.fetch_year(_Page({}), dict(QUERY, url="https://evil.test/gateway/graphql"), 2025)["entries"] == []


# -- entries become purchases -------------------------------------------------------

def test_an_online_order():
    p = site.entry_to_purchase(entry(7, total=501.37, created="2026-05-26T14:56:09-05:00"))
    assert (p.purchase_type, p.purchase_date, p.total, p.document_type) == (ONLINE, "2026-05-26", "$501.37", "Receipt")
    assert p.details_url == "https://www.bestbuy.com/profile/ss/orders/order-details/BBY01-800000000007/view"


def test_a_store_purchase_is_dated_by_its_own_number():
    """Old ones carry the time Best Buy moved its records, years later."""
    e = {"id": "147 41 6953 100815", "orderType": "store", "orderTotal": 42.79,
         "created": "2021-01-28T03:00:00.000Z", "orderStatusTitle": "Purchased in Store"}
    p = site.entry_to_purchase(e)
    assert (p.purchase_type, p.purchase_date) == (IN_STORE, "2015-10-08")
    assert p.details_url == ("https://www.bestbuy.com/purchasehistory/purchase-details"
                             "?purchaseKey=147%2041%206953%20100815")


def test_a_store_purchase_written_in_utc_keeps_its_evening_date():
    e = {"id": "BBY01-800000000001", "orderType": "online", "orderTotal": 5, "created": "2025-11-20T01:06:11.182Z"}
    assert site.entry_to_purchase(e).purchase_date == "2025-11-19"


def test_an_order_placed_in_a_store_opens_the_order_page():
    e = {"id": "1122000000001", "orderType": "online", "orderTotal": 105.99, "created": "2023-08-25T13:18:52-05:00"}
    p = site.entry_to_purchase(e)
    assert p.details_url.endswith("/profile/ss/orders/order-details/1122000000001/view")
    assert p.purchase_type == IN_STORE, "a number without BBY is a store's"


def test_a_return_is_its_own_document():
    p = site.entry_to_purchase(entry(3, "store", total=-147.33))
    assert (p.total, p.document_type) == ("-$147.33", "Return")


def test_a_reference_is_not_a_purchase_to_fetch():
    """An old order kept only as a pointer, no date, total or status, whose
    details page sends you back to the list."""
    e = {"id": "BBY01-700000000001", "orderType": "reference", "orderTotal": 0, "created": ""}
    assert site.is_reference(e)
    assert site.entry_to_purchase(e) is None


def test_an_entry_with_no_usable_number_is_dropped():
    for bad in ("", "<script>", "BBY01-12", "1 2 3"):
        assert site.entry_to_purchase({"id": bad, "orderType": "online"}) is None


# -- the details page --------------------------------------------------------------------

ORDER_PAGE = """Order Details
Purchase Date: May 26, 2026
Order Number: BBY01-800000000007
Total: $501.37
Invented Console 1TB with Controller
Serial:
000000000001
Model:
INV-00001
SKU:
1234567
Quantity:
1
Item Total:
$516.37
Product Price:
$487.99
Home Delivery
Model:
HOME DELIVERY
SKU:
8500000
Quantity:
1
Item Total:
$0.00
"""

STORE_PAGE = """Purchase Details
Purchase Date: Dec 22, 2022
Order Number: 100 1 2546 122222
Total: $37.08
Net Total: $34.99
Sales Tax: $2.09
Store Purchase
Store Location
SPRINGFIELD VA
Invented Install Kit
Model:5300000000
SKU:5100000
Quantity:1
Item Total:$34.99
Purchased in Store
"""


class _Body:
    def __init__(self, text):
        self.text, self.url = text, "https://www.bestbuy.com/x"

    def locator(self, sel):
        return self

    def inner_text(self, timeout=0):
        return self.text


def test_items_on_an_order_page_pass_over_the_serial():
    items = site.extract_items(ORDER_PAGE)
    assert [(i.name, i.quantity, i.line_total, i.unit_price) for i in items] == [
        ("Invented Console 1TB with Controller", "1", "$516.37", "$487.99"),
        ("Home Delivery", "1", "$0.00", ""),
    ]


def test_items_on_a_store_purchase_page_read_their_inline_labels():
    [item] = site.extract_items(STORE_PAGE)
    assert (item.name, item.quantity, item.line_total) == ("Invented Install Kit", "1", "$34.99")


def test_the_details_page_gives_date_total_and_store():
    from paperpull_core.models import Purchase
    p = site.extract_details(_Body(STORE_PAGE), Purchase(purchase_type=IN_STORE, order_number="100 1 2546 122222"))
    assert (p.purchase_date, p.total, p.store_info) == ("2022-12-22", "$37.08", "Best Buy Springfield Va")
    assert site.details_number(_Body(STORE_PAGE)) == "100 1 2546 122222"
    assert site.details_number(_Body(ORDER_PAGE)) == "BBY01-800000000007"
    assert site.receipt_is_present(_Body(ORDER_PAGE))


# -- guards ------------------------------------------------------------------------------

def test_receipt_buttons_and_everything_that_changes_an_order_are_refused():
    for name in ("Print Receipt", "View Receipt", "Buy Again", "Start a Return", "Write a Review",
                 "Cancel Order", "Pay Your Bill at Citibank", "Trade-In Program", "Accessibility Survey"):
        assert not site.is_safe_control(name), name


def test_the_range_menu_and_details_are_allowed():
    for name in ("View order details", "Past 3 Years", "2021"):
        assert site.is_safe_control(name), name


def test_only_best_buy_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.bestbuy.com/purchasehistory/purchases")
    assert not site.is_safe_url("http://www.bestbuy.com/purchasehistory/purchases")
    assert not site.is_safe_url("https://bestbuy.com.example.test/x")
    assert not site.is_safe_url("https://www.bestbuy.ca/")


# -- a page read before its product names drew -----------------------------------

EARLY_PAGE = """Order Details
Purchase Date: Jan 3, 2025
Order Number: BBY01-800000000009
Total: $263.94
Shipping Address
SPRINGFIELD, VA  22150 US
Serial:
SERIAL00000
Model:
INV-WATCH
SKU:
6500000
Quantity:
1
Item Total:
$263.94
Digital Delivery
someone@example.test
Model:
DIGITAL ITEM
SKU:
6400000
Quantity:
1
Item Total:
$0.00
"""


def test_an_address_or_email_is_never_taken_for_an_item_name():
    """One order was read before its names had drawn, and its items came
    out as the shipping address and a delivery email."""
    items = site.extract_items(EARLY_PAGE)
    assert len(items) == 2 and all(i.name == "" for i in items)


def test_the_details_keep_only_named_items():
    from paperpull_core.models import Purchase
    p = site.extract_details(_Body(EARLY_PAGE), Purchase(order_number="BBY01-800000000009"))
    assert p.items == []
