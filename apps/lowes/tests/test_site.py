"""The Lowe's site layer, against the shapes the live site showed on
2026-09-25. Every purchase, number and name here is invented."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import lowes_site as site
from paperpull_core.models import IN_STORE, ONLINE


def t_of(number: str) -> str:
    return base64.b64encode(number.encode()).decode()


def link(t: str, session="U2FsdGVkX1abc%2Fdef") -> str:
    return "https://www.lowes.com/mylowes/orders/details?t=%s&s=%s&ih=Qg==" % (t, session)


ONLINE_SEG = ("Order Date: Mar 4, 2026$18.40\n\t+21 Points\t\nOrder #300900000000000001\nView Details\n"
              "Write a Review\n1 Star\n2 Stars\n3 Stars\n4 Stars\n5 Stars\nGarden Hose 50-ft\n"
              "Delivered\nDelivered Friday, Mar 6, 2026\nTrack Package\nBuy it Again")
STORE_SEG = ("Order Date: Feb 1, 2026$42.10\n\t+49 Points\t\nTransaction #123456789\nView Details\n2\n"
             "5% off with Shop, Subscribe & Save\nWood Filler 6-oz\nCompleted\nBuy it Again")
RETURN_SEG = ("Return Initiated: Jan 9, 2026$12.00\n\t-14 Points\t\nOrder #203200000000000002\n"
              "View Details\nWrite a Review\nPaint Roller Cover\nReturn Received at Store\n"
              "We’re working on your refund now.\nBuy it Again")
CANCELED_SEG = ("Order Date: Dec 2, 2025$0.00\n\t+0 Points\t\nOrder #300900000000000003\nView Details\n"
                "Battery Gas Detector\nCanceled")


# -- the history --------------------------------------------------------------

def test_the_whole_history_is_read_by_address():
    assert site.orders_url(1) == "https://www.lowes.com/mylowes/orders?show=all"
    assert site.orders_url(3) == "https://www.lowes.com/mylowes/orders?page=3&show=all"


def test_the_session_token_is_left_off_the_saved_address():
    """A stale token sends you back to the list. The id alone opens the
    purchase, and is what is kept."""
    t = t_of("123456789")
    assert site.details_id(link(t)) == t
    assert site.details_url(t) == "https://www.lowes.com/mylowes/orders/details?t=" + t
    assert site.details_id("https://www.lowes.com/mylowes/orders/details?s=abc") == ""
    assert site.details_id("https://www.lowes.com/mylowes/orders/details?t=<script>") == ""


def test_headers_and_links_pair_in_order():
    segs = [ONLINE_SEG, STORE_SEG, RETURN_SEG, CANCELED_SEG]
    links = [link(t_of("300900000000000001")), link("MjAyNjAyMDEzMjc0MTIzNDU2Nzg5"),
             link(t_of("203200000000000002")), link(t_of("300900000000000003"))]
    cards = site.pair_cards(segs, links)
    assert [c.number for c in cards] == ["300900000000000001", "123456789",
                                         "203200000000000002", "300900000000000003"]
    assert [c.kind for c in cards] == [ONLINE, IN_STORE, ONLINE, ONLINE]
    assert cards[2].label == "Return Initiated"
    assert all("s=" not in c.href for c in cards)


def test_a_page_whose_headers_and_links_disagree_is_not_guessed_at():
    """Pairing the wrong link would save one purchase's receipt under
    another's name, so a mismatch pairs nothing."""
    assert site.pair_cards([ONLINE_SEG, STORE_SEG], [link(t_of("300900000000000001"))]) == []


def test_an_online_link_that_carries_another_number_is_refused():
    assert site.pair_cards([ONLINE_SEG], [link(t_of("300900000000000999"))]) == []


def test_a_card_becomes_a_purchase():
    [c] = site.pair_cards([STORE_SEG], [link("MjAyNjAyMDEzMjc0MTIzNDU2Nzg5")])
    p = site.card_to_purchase(c)
    assert (p.purchase_type, p.purchase_date, p.total, p.status) == (IN_STORE, "2026-02-01", "$42.10", "Completed")
    assert p.order_number == "123456789"
    assert p.items[0].name == "Wood Filler 6-oz", "not the discount line or the image count"
    assert p.document_type == "Receipt"
    assert p.details_url.endswith("?t=MjAyNjAyMDEzMjc0MTIzNDU2Nzg5")


def test_a_return_is_its_own_kind_of_document():
    [c] = site.pair_cards([RETURN_SEG], [link(t_of("203200000000000002"))])
    p = site.card_to_purchase(c)
    assert p.document_type == "Return" and p.status == "Returned"
    assert (p.purchase_date, p.total) == ("2026-01-09", "$12.00")
    assert p.items[0].name == "Paint Roller Cover"


def test_a_canceled_order_says_so():
    [c] = site.pair_cards([CANCELED_SEG], [link(t_of("300900000000000003"))])
    assert site.card_to_purchase(c).status == "Canceled"


def test_an_item_name_is_never_a_label():
    [c] = site.pair_cards([ONLINE_SEG], [link(t_of("300900000000000001"))])
    assert site.card_to_purchase(c).items[0].name == "Garden Hose 50-ft"


# -- the details page ------------------------------------------------------------

class _Page:
    def __init__(self, body, url="https://www.lowes.com/mylowes/orders/details?t=x"):
        self.body, self.url = body, url

    def locator(self, sel):
        return self

    def inner_text(self, timeout=0):
        return self.body


def test_the_heading_is_read_for_each_kind():
    assert site.details_number(_Page("Order Details\nTransaction # 123456789\nPlaced")) == "123456789"
    assert site.details_number(_Page("Order Details\nOrder #300900000000000001\nPlaced")) == "300900000000000001"
    assert site.details_number(_Page("Order Details\nOrder Details 203200000000000002\nPlaced")) \
        == "203200000000000002", "a return's heading has no #"


DETAILS = """Order Details
Transaction # 123456789
Placed February 1, 2026$42.10
Completed
Completed Date: Sunday, Feb 1, 2026
Springfield Lowe's
100 MAIN ST,
Springfield, VA, 22150
Wood Filler 6-oz
Item #111222 Model #WF6
$9.98 /ea.
QTY 2
Write a Review
1 Star
2 Stars
3 Stars
4 Stars
5 Stars
$19.96
$17.96
Saved $2.00 with Military Discount
Paint Roller Cover
Item #333444 Model #PRC9
$4.00 /ea.
QTY 1
$4.00
Order Summary
Subtotal
$21.96
Tax
$1.32
Total Billed
$42.10
"""


def test_items_are_read_past_the_review_stars():
    items = site.extract_items(DETAILS)
    assert [(i.name, i.quantity, i.unit_price, i.line_total) for i in items] == [
        ("Wood Filler 6-oz", "2", "$9.98", "$17.96"),
        ("Paint Roller Cover", "1", "$4.00", "$4.00"),
    ]


def test_the_details_page_gives_date_total_and_store():
    p = site.card_to_purchase(site.pair_cards([STORE_SEG], [link("MjAyNjAyMDEzMjc0MTIzNDU2Nzg5")])[0])
    p = site.extract_details(_Page(DETAILS), p)
    assert (p.purchase_date, p.total, p.store_info) == ("2026-02-01", "$42.10", "Springfield Lowe's")
    assert site.receipt_is_present(_Page(DETAILS))
    assert not site.receipt_is_present(_Page("Order Details\nLoading..."))


# -- guards --------------------------------------------------------------------

def test_nothing_that_changes_an_order_can_be_pressed():
    for name in ("Start a Return", "Buy it Again", "Track Package", "Write a Review", "Cancel Order",
                 "Edit Quantity", "Add New Item", "Subscribe & Save", "Add Existing Receipt",
                 "Search Store Purchase", "Lowe's Credit Center", "Print Details"):
        assert not site.is_safe_control(name), name


def test_reading_controls_are_allowed():
    for name in ("View Details", "Orders & Purchases", "Go to next page", "3"):
        assert site.is_safe_control(name), name


def test_only_lowes_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.lowes.com/mylowes/orders")
    assert not site.is_safe_url("http://www.lowes.com/mylowes/orders")
    assert not site.is_safe_url("https://lowes.com.example.test/x")
    assert not site.is_safe_url("https://www.lowesfoods.com/")


def _opened(purchase):
    from unittest.mock import MagicMock
    page = MagicMock()
    site.goto_details(page, purchase)
    return page.goto.call_args[0][0]


def test_a_stored_details_address_is_followed():
    from paperpull_core.models import Purchase
    t = t_of("123456789")
    p = Purchase(purchase_type=IN_STORE, order_number="123456789", details_url=site.details_url(t))
    assert _opened(p) == site.details_url(t)


def test_an_online_order_without_a_usable_address_is_rebuilt_from_its_number():
    from paperpull_core.models import Purchase
    for bad in ("", "https://evil.test/mylowes/orders/details?t=x", "https://www.lowes.com/pd/thing/1"):
        p = Purchase(purchase_type=ONLINE, order_number="300900000000000001", details_url=bad)
        assert _opened(p) == site.details_url(t_of("300900000000000001")), bad


def test_a_store_purchase_without_a_usable_address_opens_only_the_history():
    """Its id cannot be rebuilt, and the heading check refuses the page
    before anything could be saved under its name."""
    from paperpull_core.models import Purchase
    p = Purchase(purchase_type=IN_STORE, order_number="123456789", details_url="https://evil.test/x")
    assert _opened(p) == site.ORDERS_URL
