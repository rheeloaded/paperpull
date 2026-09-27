"""The Apple Store side, against the shapes the order list and details pages
embedded on the owner's own account, 2026-09-27. Every order, product,
address and amount here is invented."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import apple_site as site

SECURE = "https://secure9.store.apple.com"


def detail_url(number):
    return "%s/shop/order/detail/100001/%s?_si=TEST" % (SECURE, number)


def invoice_url(number):
    return "%s/shop/order/print/invoice/100001/INV%s" % (SECURE, number[-7:])


def listed_order(number, product, delivery, item_key="0000101"):
    return {"d": {"webOrderNumber": number}, "c": [item_key],
            item_key: {"d": {"quantity": 1, "deliveryDate": delivery,
                             "productShortName": product,
                             "imageData": {"src": "https://example.test/x.jpg"},
                             "orderDetailUrl": detail_url(number)}}}


LIST = {"meta": {"l": ["/orderList"], "h": {"x-aos-model-page": "OrdersPage"}},
        "orderList": {
            "d": {"prevOrders": "W0000000001,W0000000002,W0000000003",
                  "moreOrdersAvailable": False, "pageOffset": 0},
            "a": {"more": {"url": SECURE + "/shop/order/listX?_a=more&_m=orderList",
                           "submit": True}},
            "c": ["order-W0000000001", "order-W0000000002", "order-W0000000003"],
            "order-W0000000001": listed_order("W0000000001", "iPad Air 11‑inch",
                                              "Delivered May 2, 2026"),
            "order-W0000000002": listed_order("W0000000002", "AirPods 4", "Picked Up Apr 18"),
            "order-W0000000003": listed_order("W0000000003", "Mac mini", "Canceled"),
        }}


def detail(number, placed, product, tracker, invoice=True, total="$655.21"):
    header = {"orderNumber": number, "isReturnKitOrder": False,
              "orderPlacedDate": placed, "id": "orderDetail-orderHeader", "isSMB": False}
    if invoice:
        header["invoiceUrl"] = invoice_url(number)
    item = {"orderItemDetails": {"d": {
                "quantity": 1, "deliveryDate": "", "itemShortName": product.split(" - ")[0],
                "totalPrice": "$612.34", "productName": product, "listPrice": "$612.34"}},
            "orderItemStatusTracker": {"d": tracker}}
    return {"meta": {}, "orderDetail": {
        "c": ["orderHeader", "orderItems", "pricingSummary"],
        "orderHeader": {"d": header},
        "orderItems": {"c": ["orderItem-0000101"], "orderItem-0000101": item,
                       # A trade-in's placeholder, which is not an item.
                       "giveBackOrderItem-000010": {"d": {"productName": "Trade In"}}},
        "pricingSummary": {"d": {"subTotal": "$612.34", "taxAmount": "$42.87",
                                 "orderTotal": total}}}}


DELIVERED = detail("W0000000001", "April 28, 2026",
                   "iPad Air 11‑inch Wi‑Fi 128GB - Starlight",
                   {"statusDescription": "DELIVERED", "currentStatus": "DELIVERED"})
PICKED_UP = detail("W0000000002", "April 18, 2026", "AirPods 4",
                   {"statusDescription": "PICKED_UP", "currentStatus": "PICKED_UP"})
# RECORDED shape. A canceled item's tracker has no currentStatus at all, and
# the order has no invoiceUrl.
CANCELED = detail("W0000000003", "March 9, 2026", "Mac mini M4 16GB",
                  {"statusDescription": "CANCELED", "canceledDate": "March 10, 2026"},
                  invoice=False, total="$0.00")


# -- the list -------------------------------------------------------------------------

def test_the_list_is_one_record_per_order_with_its_details_address():
    got = site.parse_order_list(LIST)
    assert got["more"] is False
    assert [o["order_number"] for o in got["orders"]] == ["W0000000001", "W0000000002", "W0000000003"]
    assert got["orders"][0]["detail_url"] == detail_url("W0000000001")
    assert [o["items"][0]["status"] for o in got["orders"]] == ["Delivered", "Picked Up", "Canceled"]
    assert got["orders"][1]["items"][0]["name"] == "AirPods 4", "a non-breaking space is a space"


def test_the_list_says_when_older_orders_exist():
    more = copy.deepcopy(LIST)
    more["orderList"]["d"]["moreOrdersAvailable"] = True
    assert site.parse_order_list(more)["more"] is True


def test_a_details_address_off_apples_hosts_is_not_kept():
    odd = copy.deepcopy(LIST)
    odd["orderList"]["order-W0000000001"]["0000101"]["d"]["orderDetailUrl"] = \
        "https://secure9.store.apple.com.evil.test/shop/order/detail/1/W0000000001"
    assert site.parse_order_list(odd)["orders"][0]["detail_url"] == ""


def test_an_order_is_listed_once_and_a_broken_one_not_at_all():
    odd = copy.deepcopy(LIST)
    odd["orderList"]["c"] += ["order-W0000000001", "order-nonsense", "missing"]
    odd["orderList"]["order-nonsense"] = {"d": {"webOrderNumber": "not an order"}}
    assert [o["order_number"] for o in site.parse_order_list(odd)["orders"]] == [
        "W0000000001", "W0000000002", "W0000000003"]


def test_a_page_with_no_list_is_an_empty_one():
    assert site.parse_order_list(None) == {"orders": [], "more": False}
    assert site.parse_order_list({"orderList": "x"}) == {"orders": [], "more": False}


# -- the details --------------------------------------------------------------------

def test_a_delivered_orders_details():
    got = site.parse_order_detail(DELIVERED)
    assert got["order_number"] == "W0000000001"
    assert got["placed"] == "2026-04-28"
    assert got["invoice_url"] == invoice_url("W0000000001")
    assert got["total"] == "$655.21" and got["tax"] == "$42.87"
    assert [(i["name"], i["status"]) for i in got["items"]] == [
        ("iPad Air 11-inch Wi-Fi 128GB - Starlight", "Delivered")]


def test_a_picked_up_order_becomes_a_purchase_with_its_invoice():
    listed = site.parse_order_list(LIST)["orders"][1]
    purchase = site.store_purchase(listed, site.parse_order_detail(PICKED_UP))
    assert purchase.key == "Apple Store:W0000000002"
    assert purchase.purchase_date == "2026-04-18"
    assert purchase.status == "Picked Up"
    assert purchase.receipt_url == invoice_url("W0000000002")
    assert purchase.details_url == detail_url("W0000000002")
    assert purchase.store_info == "Apple Store"
    assert not site.is_canceled(purchase)


def test_a_canceled_order_has_no_invoice_and_reads_canceled():
    listed = site.parse_order_list(LIST)["orders"][2]
    purchase = site.store_purchase(listed, site.parse_order_detail(CANCELED))
    assert purchase.status == "Canceled" and purchase.receipt_url == ""
    assert site.is_canceled(purchase)


def test_an_order_not_invoiced_yet_is_not_called_canceled():
    """Apple invoices an item once it ships or is ready for pickup."""
    placed = detail("W0000000004", "May 20, 2026", "Apple Pencil (USB-C)",
                    {"statusDescription": "PROCESSING", "currentStatus": "PROCESSING"},
                    invoice=False)
    purchase = site.store_purchase({"order_number": "W0000000004"}, site.parse_order_detail(placed))
    assert purchase.status == "Processing" and purchase.receipt_url == ""
    assert not site.is_canceled(purchase)


def test_part_of_an_order_canceled_is_not_the_order_canceled():
    assert site.order_status(["Delivered", "Canceled"]) == "Delivered"
    assert site.order_status(["Canceled", "Canceled"]) == "Canceled"
    assert site.order_status(["Shipped", "Delivered", "Shipped"]) == "Shipped, Delivered"


def test_an_invoice_address_off_apples_hosts_is_dropped():
    odd = copy.deepcopy(DELIVERED)
    odd["orderDetail"]["orderHeader"]["d"]["invoiceUrl"] = "https://evil.test/shop/order/print/invoice/1/X"
    assert site.parse_order_detail(odd)["invoice_url"] == ""
    odd["orderDetail"]["orderHeader"]["d"]["invoiceUrl"] = SECURE + "/shop/order/cancel/W0000000001"
    assert site.parse_order_detail(odd)["invoice_url"] == "", "only an invoice page"


def test_a_details_page_for_another_order_is_refused():
    listed = site.parse_order_list(LIST)["orders"][0]
    assert site.store_purchase(listed, site.parse_order_detail(PICKED_UP)) is None


@pytest.mark.parametrize("url,detail_ok,invoice_ok", [
    (detail_url("W0000000001"), True, False),
    (invoice_url("W0000000001"), False, True),
    ("https://www.apple.com/shop/order/detail/1/W0000000001", True, False),
    ("https://store.apple.com/shop/order/print/invoice/1/INV1", False, True),
    ("https://secure12.store.apple.com/shop/order/print/invoice/1/INV1", False, True),
    ("https://securex.store.apple.com/shop/order/print/invoice/1/INV1", False, False),
    ("https://evil.store.apple.com/shop/order/detail/1/W0000000001", False, False),
    ("http://secure9.store.apple.com/shop/order/detail/1/W0000000001", False, False),
    ("https://secure9.store.apple.com/shop/order/cancel/W0000000001", False, False),
])
def test_only_apples_own_details_and_invoice_pages_are_opened(url, detail_ok, invoice_ok):
    assert site.is_order_detail_url(url) is detail_ok
    assert site.is_invoice_url(url) is invoice_ok


def test_an_invoice_off_apples_hosts_is_never_opened():
    class _Context:
        def new_page(self):
            raise AssertionError("a tab was opened for an address that is not Apple's")
    for url in ("https://evil.test/shop/order/print/invoice/1/X", "", None,
                "javascript:alert(1)", detail_url("W0000000001")):
        with pytest.raises(ValueError):
            site.open_invoice(_Context(), url)


def test_a_details_page_off_apples_hosts_is_never_opened():
    class _Page:
        def goto(self, *a, **kw):
            raise AssertionError("navigated to an address that is not Apple's")
    assert site.read_order_detail(_Page(), "https://evil.test/shop/order/detail/1/W1") == (site.NO_DATA, None)


# -- the embedded data itself ----------------------------------------------------------

def test_the_embedded_json_is_read_or_refused():
    assert site.init_data_from('{"orderList": {}}') == {"orderList": {}}
    for bad in ("", None, "not json", "[1, 2]"):
        assert site.init_data_from(bad) is None
