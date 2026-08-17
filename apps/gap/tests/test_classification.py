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
        Item(name="Gap Essentials Kids Boys' T-Shirt", line_total="$8.00"),
        Item(name="Gap Essentials Kids Girls' Leggings", line_total="$7.00"),
        Item(name="Toddler Boys' Shorts", line_total="$6.00"),
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


GAP_DETAILS_PAGE = (
    "PURCHASE SUMMARY\n"
    "Purchased:\n"
    "June 24, 2026 (10:06PM EDT)\n"
    "Purchase #:\n"
    "K4M9XQ2\n"
    "Total cost:\n"
    "$53.51 (4 items)\n"
    "Payment:\n"
    "Apple Pay\n"
    "DELIVERY\n"
    "Shipping (4 items)\n"
    "Jane Doe\n"
    "123 Main St\n"
    "SPRINGFIELD, IL 62704\n"
    "Delivered - 1 Item\n"
    "Tracking Number:\n"
    "99999999999999999999999999\n"
    "Package Carrier:\n"
    " UPS\n"
    "Short-Sleeve Rashguard Swim Top for Boys\n"
    "XL | Chrysolite\n"
    "Promo: PWP - Single Points - US\n"
    "$22.99\n"
    "$11.05\n"
    "Savings $11.50\n"
    "Delivered - 3 Items\n"
    "Kids Quarter Crew Socks (3-Pack) (2)\n"
    "L | White\n"
    "$14.95\n"
    "$10.58\n"
    "each\n"
    "Savings $3.95\n"
    "Modern Utility Jacket\n"
    "M | Navy\n"
    "$39.95\n"
    "SUMMARY OF CHARGES\n"
    "Subtotal (4 items)\n"
    "$50.49\n"
    "Savings\n"
    "-$40.35\n"
    "Shipping\n"
    "FREE\n"
    "Est. Tax\n"
    "$3.02\n"
    "Total\n"
    "$53.51\n"
)


def test_parse_gap_details_items():
    """Real Gap layout: title / 'size | color' / prices, discounted price second."""
    import gap_site
    items = gap_site._parse_items_from_summary_text(GAP_DETAILS_PAGE)
    assert len(items) == 3, [i.name for i in items]
    assert items[0].name == "Short-Sleeve Rashguard Swim Top for Boys"
    assert items[0].quantity == "1"
    assert items[0].unit_price == "$11.05"      # price paid, not the $22.99 list
    assert items[0].line_total == "$11.05"
    # a trailing "(2)" on the title is the quantity, and the price is "each"
    assert items[1].name == "Kids Quarter Crew Socks (3-Pack)"
    assert items[1].quantity == "2"
    assert items[1].unit_price == "$10.58"
    assert items[1].line_total == ""
    # an undiscounted item lists only one price
    assert items[2].name == "Modern Utility Jacket"
    assert items[2].unit_price == "$39.95"


def test_gap_items_skip_summary_charges_and_address_lines():
    """Header, payment, ship-to and charge-summary lines never become items."""
    import gap_site
    items = gap_site._parse_items_from_summary_text(GAP_DETAILS_PAGE)
    joined = " ".join(i.name for i in items)
    for junk in ("Main", "SPRINGFIELD", "Jane", "Apple Pay", "Total cost",
                 "PURCHASE", "Subtotal", "Tracking"):
        assert junk not in joined
    # the charge summary must not leak into a price either
    assert all(i.unit_price != "$50.49" for i in items)


def test_parse_gap_items_html_entities():
    import gap_site
    text = "Black &#38; White Striped Tee\nS | Bright White\n$14.89\n"
    items = gap_site._parse_items_from_summary_text(text)
    assert len(items) == 1
    assert items[0].name == "Black & White Striped Tee"


def test_gap_order_id_and_date_parsing():
    """Gap puts each label on its own line and the value on the next."""
    import gap_site
    assert gap_site.ORDER_ID_RE.search(GAP_DETAILS_PAGE).group(1) == "K4M9XQ2"
    lines = [l.strip() for l in GAP_DETAILS_PAGE.splitlines()]
    i = lines.index("Purchased:")
    assert gap_site.parse_date(gap_site._value_after_label(lines, i)) == "2026-06-24"
    assert gap_site.parse_order_link(
        "/my-account/order-details/K4M9XQ2") == ("Online", "K4M9XQ2")


def test_gap_order_details_url_is_the_receipt():
    import gap_site
    url = gap_site.order_details_url("K4M9XQ2")
    assert url == "https://secure-www.gap.com/my-account/order-details/K4M9XQ2"
    # Gap has no separate printable invoice: both point at the same page.
    assert gap_site.print_invoice_url("K4M9XQ2") == url


def test_gap_brand_from_narvar_tracking_link():
    import gap_site
    assert gap_site.brand_from_text(
        "https://oldnavy.narvar.com/oldnavy/tracking/x") == "Old Navy"
    assert gap_site.brand_from_text("https://gap.narvar.com/gap/tracking/x") == "Gap"
    assert gap_site.brand_from_text("no tracking link here") == ""


def test_gap_in_store_card_records_the_store():
    """Gap's history mixes in-store purchases in with online orders; the card
    names the store under a "Purchased In Store - N Items" line."""
    import gap_site
    card = gap_site.RawCard(
        href="", order_id="099999000011112026080812345",
        text=("Purchased on Aug 8, 2026\n"
              "#099999000011112026080812345\n"
              "Purchased In Store - 5 Items\n"
              "RIVERSIDE COMMONS\n"
              "Details\n"))
    card.in_store = bool(gap_site.IN_STORE_RE.search(card.text))
    card.store = gap_site.store_from_text(card.text)
    assert card.in_store is True
    assert card.store == "Riverside Commons"
    p = gap_site.card_to_purchase(card)
    assert p.purchase_date == "2026-08-08"
    assert p.store_info == "Riverside Commons"
    # the type comes from the card, never from the caller
    from paperpull_core.models import IN_STORE
    assert p.purchase_type == IN_STORE
    assert p.key == "In-Store:099999000011112026080812345"


def test_gap_in_store_and_online_route_to_different_folders(tmp_path):
    """In-store purchases must not land in the Online folder."""
    from paperpull_core.models import IN_STORE, ONLINE
    from storage import Paths
    paths = Paths(tmp_path)
    assert paths.folder_for(ONLINE).name == "Online"
    assert paths.folder_for(IN_STORE).name == "In-Store"
    assert paths.instore in paths.all_dirs()


def test_gap_online_card_records_the_brand_not_a_store():
    import gap_site
    card = gap_site.RawCard(
        href="", order_id="K7X4P2Q", brand="Old Navy",
        text="Order placed Nov 25, 2025\n#K7X4P2Q\nDelivered\n")
    assert gap_site.store_from_text(card.text) == ""
    p = gap_site.card_to_purchase(card)
    assert p.store_info == "Old Navy"
    from paperpull_core.models import ONLINE
    assert p.purchase_type == ONLINE


def test_gap_card_to_purchase_prefers_the_order_date():
    """A card shows both an order date and a delivery estimate; the delivery
    estimate must not become the purchase date."""
    import gap_site
    card = gap_site.RawCard(
        href="", order_id="K4M9XQ2", brand="Old Navy",
        text=("Order placed Jan 5, 2026\n"
              "Arriving Tue, Jan 9\n"
              "Total: $84.31\n"))
    p = gap_site.card_to_purchase(card)
    assert p.order_number == "K4M9XQ2"
    assert p.purchase_date == "2026-01-05"
    assert p.total == "$84.31"
    assert p.store_info == "Old Navy"
    assert p.key == "Online:K4M9XQ2"
