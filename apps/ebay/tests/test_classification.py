"""Deterministic local classification tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import classification
from paperpull_core.classification import classify_items, load_rules
from paperpull_core.models import Item

RULES = load_rules()


def test_groceries_high_confidence():
    items = [
        Item(name="Good & Gather Whole Milk 1 Gallon", line_total="$3.99"),
        Item(name="Wonder Bread Classic White", line_total="$2.49"),
        Item(name="Large Eggs Grade A 12ct", line_total="$4.29"),
        Item(name="Tillamook Cheddar Cheese", line_total="$5.99"),
    ]
    c = classify_items(items, RULES)
    assert c.summary == "Groceries"
    assert c.confidence == classification.HIGH


def test_single_significant_item():
    c = classify_items([Item(name="Shark Navigator Lift-Away Upright Vacuum")], RULES)
    assert c.summary == "Vacuum Cleaner"
    assert c.confidence == classification.HIGH


def test_primary_product_with_accessories():
    items = [
        Item(name='TCL 55" 4K Smart TV Roku TV', line_total="$299.99"),
        Item(name="HDMI Cable 6ft", line_total="$9.99"),
    ]
    c = classify_items(items, RULES)
    assert c.summary == "Television"
    assert c.confidence == classification.HIGH


def test_childrens_clothing():
    items = [
        Item(name="Kids Boys' Shorts", line_total="$8.00"),
        Item(name="Toddler Girls' Sundress", line_total="$7.00"),
        Item(name="Youth Boys' Socks 6-Pack", line_total="$6.00"),
    ]
    c = classify_items(items, RULES)
    assert c.summary == "Children's Clothing"


def test_majority_category_wins():
    # cleaning items carry most of the dollar value -> Cleaning Supplies
    items = [
        Item(name="Milk 2% Half Gallon", line_total="$3.00"),
        Item(name="Bananas 2lb", line_total="$1.50"),
        Item(name="Clorox Disinfecting Wipes", line_total="$4.00"),
        Item(name="Dawn Dish Soap", line_total="$3.50"),
    ]
    c = classify_items(items, RULES)
    assert c.summary == "Cleaning Supplies"


def test_combined_categories():
    # groceries 45% / cleaning 40% / paper 15% -> combined summary
    items = [
        Item(name="Milk 2% Half Gallon", line_total="$3.00"),
        Item(name="Bananas 2lb", line_total="$1.50"),
        Item(name="Clorox Disinfecting Wipes", line_total="$4.00"),
        Item(name="Bounty Paper Towels 2pk", line_total="$1.50"),
    ]
    c = classify_items(items, RULES)
    assert c.summary == "Groceries and Household"


def test_mixed_low_confidence():
    items = [
        Item(name="zzqx unknowable widget"),
        Item(name="mystery gadget deluxe"),
    ]
    c = classify_items(items, RULES)
    assert c.summary == classification.MIXED
    assert c.confidence == classification.LOW


def test_empty_items():
    c = classify_items([], RULES)
    assert c.summary == classification.MIXED
    assert c.confidence == classification.LOW


def test_weighting_by_price():
    # cheap grocery + expensive electronics -> electronics dominates by $
    items = [
        Item(name="Candy Bar", line_total="$1.50"),
        Item(name="Sony Wireless Headphones", line_total="$199.99"),
    ]
    c = classify_items(items, RULES)
    assert c.summary in ("Headphones", "Electronics")


def test_short_keyword_word_boundary():
    # "pen" must not match inside "opened"; name contains no category keyword
    c = classify_items([Item(name="Opened-box mystery unit")], RULES)
    assert c.summary == classification.MIXED


# ---------------------------------------------------------------------------
# The eBay site layer, against the shapes the live site showed 2026-09-21.
# Every fixture here is made up.
# ---------------------------------------------------------------------------
import ebay_site as site
from paperpull_core.models import ONLINE, Purchase


def test_the_year_filter_speaks_the_sites_own_words():
    from datetime import date
    today = date(2026, 9, 21)
    assert site.year_filter_word(2026, today) == "THIS_YEAR"
    assert site.year_filter_word(2025, today) == "LAST_YEAR"
    assert site.year_filter_word(2022, today) == "FOUR_YEARS_AGO"
    assert site.year_filter_word(2016, today) == "TEN_YEARS_AGO"
    assert site.year_filter_word(2015, today) is None
    assert site.year_filter_word(2027, today) is None


def test_an_order_link_yields_both_ids_and_nothing_else_does():
    kind, oid, poid = site.parse_order_link("https://order.ebay.com/ord/show?orderId=25-12345-67890&purchaseOrderId=25-1513-123456")
    assert (kind, oid, poid) == (ONLINE, "25-12345-67890", "25-1513-123456")
    assert site.parse_order_link("https://www.ebay.com/itm/123456789012") == (None, None, None)
    assert site.order_details_url("25-12345-67890", "25-1513-1") == "https://order.ebay.com/ord/show?orderId=25-12345-67890&purchaseOrderId=25-1513-1"


CARD_TEXT = """Crucial RAM 32GB (2x16GB) DDR5 5600MT/s Memory CT16G56C46S5.M8G1
Delivered
Order date:Sep 13, 2026Order total:US $314.00(Auto-paid)Order number:25-12345-67890

View order details

Delivered on Thu, Sep 17
No cancellations or returns.
Crucial RAM 32GB (2x16GB) DDR5 5600MT/s Memory CT16G56C46S5.M8G1
Used
US $314.00
Sold by:
someseller
user ID"""


def test_a_card_becomes_a_purchase_with_the_date_total_status_and_seller():
    card = site.RawCard(href=site.order_details_url("25-12345-67890", "25-1513-1"), text=CARD_TEXT,
                        order_id="25-12345-67890", purchase_order_id="25-1513-1",
                        title="Crucial RAM 32GB (2x16GB) DDR5 5600MT/s Memory CT16G56C46S5.M8G1", seller="someseller")
    p = site.card_to_purchase(card)
    assert p.purchase_date == "2026-09-13" and p.total == "$314.00" and p.status == "Delivered"
    assert p.order_number == "25-12345-67890" and p.store_info == "someseller"
    assert p.details_url.endswith("orderId=25-12345-67890&purchaseOrderId=25-1513-1")
    assert p.items[0].name.startswith("Crucial RAM") and p.purchase_type == ONLINE
    assert site.card_to_purchase(site.RawCard(href="", text="", order_id="")) is None


DETAILS = """Order details
Printer friendly page
Order info
Time placed\tSep 13, 2026 at 1:00 PM
Order number\t25-12345-67890
Total\t$314.00 (1 item)
Sold by\tsomeseller
Delivery info
Delivered on Thu, Sep 17
Item info

Crucial RAM 32GB (2x16GB) DDR5 5600MT/s Memory CT16G56C46S5.M8G1

$285.00
Unit price $285.00

Item number: 123456789012

Used
Returns not accepted.
Return window closed on Sep 10, 2026.
Buy again
More actions
Other actions
Contact seller
Shipping address
Pat Example
1 Main St
Springfield, Virginia 22150-1234
Payment info
p***e@example.com
$314.00
1 item
$285.00
Shipping
$11.90
Tax*
$17.10
Order total\t$314.00"""


class _Page:
    url = "https://order.ebay.com/ord/show?orderId=25-12345-67890&purchaseOrderId=25-1513-1"
    def __init__(self, body): self._body = body
    def locator(self, sel):
        page = self
        class _L:
            def inner_text(self_, timeout=0): return page._body
            def all(self_): return []
            def count(self_): return 0
        return _L()


def test_the_details_page_gives_the_date_the_total_the_seller_and_the_items():
    p = Purchase(purchase_type=ONLINE, order_number="25-12345-67890")
    p = site.extract_details(_Page(DETAILS), p)
    assert p.purchase_date == "2026-09-13" and p.total == "$314.00" and p.store_info == "someseller"
    assert p.status == "Delivered"
    assert [(i.name[:11], i.line_total, i.unit_price) for i in p.items] == [("Crucial RAM", "$285.00", "$285.00")]
    assert site.receipt_is_present(_Page(DETAILS)) and not site.receipt_is_present(_Page("Loading"))
    assert site.on_details_page(_Page(DETAILS)) and not site.on_details_page(type("P", (), {"url": "https://www.ebay.com/mye/myebay/purchase"})())


def test_an_address_a_price_and_a_label_are_never_an_item():
    p = site.extract_details(_Page(DETAILS), Purchase(purchase_type=ONLINE, order_number="x"))
    names = [i.name for i in p.items]
    for bad in ("Pat Example", "1 Main St", "Unit price", "Item number", "Contact seller", "$285.00",
                "Returns not accepted", "Return window", "Used", "Buy again"):
        assert not any(bad in n for n in names), bad
    assert len(names) == 1


def test_nothing_that_buys_sells_pays_or_talks_to_a_seller_is_safe():
    for t in ("Buy again", "Buy It Now", "Place bid", "Make an offer", "Pay now", "Resell", "Leave feedback",
              "Return this item", "Contact seller", "Cancel order", "Hide order", "Add to cart", "Sell one like this"):
        assert not site.is_safe_control(t), t
    for t in ("View order details", "Printer friendly page", "Purchase History"):
        assert site.is_safe_control(t), t


def test_only_ebay_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://order.ebay.com/ord/show?orderId=1")
    assert site.is_safe_url("https://www.ebay.com/mye/myebay/purchase")
    assert not site.is_safe_url("https://ebay.com.evil.test/x")
    assert not site.is_safe_url("http://www.ebay.com/")
    assert not site.is_safe_url("https://user@ebay.com/")


def test_an_older_orders_id_is_an_item_and_transaction_pair():
    kind, oid, poid = site.parse_order_link("https://order.ebay.com/ord/show?orderId=123456789012-1234567890123!1234&purchaseOrderId=12345")
    assert (kind, oid, poid) == (ONLINE, "123456789012-1234567890123!1234", "12345")
    assert site.parse_order_link("https://order.ebay.com/ord/show?orderId=../etc") == (None, None, None)
    assert site.parse_order_link("https://order.ebay.com/ord/show?orderId=") == (None, None, None)


OLDER_DETAILS = """Order details
Order info
Time placed\tJun 27, 2017 at 5:30 PM
Order number\t12345-67890
Total\t$69.88 (1 item)
Sold by\tsomeseller
Delivery info (1 of 2)
Delivered on Sat, Jul 1, 2017
Item info
New UJ-272 UJ272 9.5mm SATA Blu-ray BD DVD Burner Drive
$69.88
Unit price $69.88
Item number: 123456789012
New
Buy again
Delivery info (2 of 2)
Delivered on Sat, Jul 1, 2017
Shipped (Untracked)
Item info
New UJ-272 UJ272 9.5mm SATA Blu-ray BD DVD Burner Drive
$69.88
Unit price $69.88
Item number: 123456789012
Other actions
Payment info
$69.88
Order total $69.88
"""


def test_a_title_that_starts_with_a_condition_word_is_still_an_item():
    """"New" and "Used" on a line of their own are the condition. The same
    words starting a title are part of it. An older order lists the same
    item under each of its two delivery sections, which is one item."""
    p = site.extract_details(_Page(OLDER_DETAILS), Purchase(purchase_type=ONLINE, order_number="x"))
    assert [i.name for i in p.items] == ["New UJ-272 UJ272 9.5mm SATA Blu-ray BD DVD Burner Drive"]
    assert p.items[0].unit_price == "$69.88"


def test_ebays_own_order_not_found_page_is_recognized():
    assert site.order_not_found(_Page("Order not found\nUnfortunately there has been an error retrieving your order."))
    assert not site.order_not_found(_Page(DETAILS))
    assert not site.order_not_found(_Page(""))


def test_ebays_daily_limit_page_is_recognized_by_url_and_by_sentence():
    class _Limited(_Page):
        url = "https://pages.ebay.com/limitexceeded.html"
        def title(self): return "Daily limit exceeded"
    assert site.hit_daily_limit(_Limited(""))

    class _Worded(_Page):
        def title(self): return "eBay"
    assert site.hit_daily_limit(_Worded("You've exceeded the number of requests allowed in one day. Please try again tomorrow."))

    class _Fine(_Page):
        def title(self): return "Order details | eBay"
    assert not site.hit_daily_limit(_Fine(DETAILS))
