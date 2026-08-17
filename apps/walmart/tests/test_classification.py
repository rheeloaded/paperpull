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
        Item(name="Wonder Nation Boys' T-Shirt", line_total="$8.00"),
        Item(name="Wonder Nation Girls' Leggings", line_total="$7.00"),
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


def test_parse_items_from_text_multi_item_row():
    import walmart_site
    text = ("Dishwasher Detergent Packs - 45ct\n$14.89\nQty 1\n"
            "18pk Plastic Hangers White\n$3.00\nQty 1\n"
            "Liquid Laundry Detergent - 90 fl oz\n$12.99\nQty 1")
    items = walmart_site._parse_items_from_text(text)
    assert [i.unit_price for i in items] == ["$14.89", "$3.00", "$12.99"]
    assert all(i.quantity == "1" for i in items)


def test_parse_items_html_entities_and_noise():
    import walmart_site
    text = ("Purchased\nJul 22, 4:48 PM\nat Springfield\n"
            "Seventh Generation Free &#38; Clear Packs\n$14.89\nQty 2")
    items = walmart_site._parse_items_from_text(text)
    assert len(items) == 1
    assert items[0].name == "Seventh Generation Free & Clear Packs"
    assert items[0].quantity == "2"
