"""Deterministic local classification tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import classification
from classification import classify_items, load_rules
from models import Item

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
        Item(name="Amazon Essentials Kids Boys' T-Shirt", line_total="$8.00"),
        Item(name="Amazon Essentials Kids Girls' Leggings", line_total="$7.00"),
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


def test_parse_amazon_summary_items():
    """Amazon's printable summary lists items as '<qty> of: <title>'."""
    import amazon_site
    text = (
        "Order Placed: January 5, 2025\n"
        "Amazon.com order number: 111-2223333-4445555\n"
        "Items Ordered\n"
        "2 of: Amazon Basics AA Alkaline Batteries, 48 Count\n"
        "$18.99\n"
        "1 of: Bounty Paper Towels, 12 Rolls\n"
        "$24.49\n"
        "Grand Total: $43.48\n"
    )
    items = amazon_site._parse_items_from_summary_text(text)
    assert len(items) == 2
    assert items[0].quantity == "2"
    assert items[0].unit_price == "$18.99"
    assert items[0].name.startswith("Amazon Basics AA Alkaline")
    assert items[1].quantity == "1"
    assert items[1].unit_price == "$24.49"


def test_parse_amazon_summary_html_entities():
    import amazon_site
    text = "1 of: Seventh Generation Free &#38; Clear Packs\n$14.89\n"
    items = amazon_site._parse_items_from_summary_text(text)
    assert len(items) == 1
    assert items[0].name == "Seventh Generation Free & Clear Packs"


def test_parse_amazon_current_invoice_layout():
    """Current Amazon layout: title / 'Sold by:' / price. Real page text."""
    import amazon_site
    text = (
        "Order Summary\n"
        "Order placed December 30, 2025  Order # 111-2223334-5556667\n"
        "Print\nShip to\nJane Doe\n123 Main St\nSPRINGFIELD, IL 62704\n"
        "United States\nPayment method\nAmazon Visa ending in 0000\n"
        "Amazon gift card balance\nView related transactions\nOrder Summary\n"
        "Item(s) Subtotal:\n$30.99\nShipping & Handling:\n$0.00\n"
        "Total before tax:\n$30.99\nEstimated tax to be collected:\n$1.86\n"
        "Gift Card Amount:\n-$32.85\nGrand Total:\n$0.00\n"
        "AXL 10mm Stem, IKEA Office Chair Wheels, 2.5 Inch Rollerblade Casters\n"
        "Sold by: AXL Global\n"
        "Return window closed on February 2, 2026\n"
        "$30.99\n$30.99\nBack to top\n"
    )
    items = amazon_site._parse_items_from_summary_text(text)
    assert len(items) == 1, [i.name for i in items]
    assert items[0].name.startswith("AXL 10mm Stem")
    assert items[0].unit_price == "$30.99"
    # address / payment / totals lines must never become items
    joined = " ".join(i.name for i in items)
    for junk in ("Main", "SPRINGFIELD", "Visa", "Grand Total", "Subtotal"):
        assert junk not in joined


def test_amazon_order_id_and_date_parsing():
    import amazon_site
    body = "Order Placed: January 5, 2025\nAmazon.com order number: 111-2223333-4445555"
    assert amazon_site.ORDER_ID_RE.search(body).group(1) == "111-2223333-4445555"
    assert amazon_site.parse_date("Order Placed: January 5, 2025") == "2025-01-05"


def test_amazon_print_invoice_url():
    import amazon_site
    url = amazon_site.print_invoice_url("111-2223333-4445555")
    assert url.endswith("summary/print.html?orderID=111-2223333-4445555")
