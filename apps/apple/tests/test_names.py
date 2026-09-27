"""What a receipt is called, and what it must carry to be filed at all.
Every product, order and amount here is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import apple_site as site
from paperpull_core import classification, identity
from paperpull_core.models import Item, Purchase

RULES = classification.load_rules(Path(__file__).resolve().parents[1] / "category_rules.json")


def named(*items):
    got = classification.classify_items(
        [Item(name=n, line_total=t) for n, t in items], RULES)
    return got.summary, got.confidence


# -- file names ------------------------------------------------------------------

def test_an_app_store_receipt_is_filed_under_what_was_bought():
    storage.set_filename_owner("")
    p = Purchase(purchase_type="App Store", purchase_date="2026-05-14",
                 order_number="MLF0TEST01", summary="Apple One")
    assert storage.build_pdf_filename(p.purchase_date, p.summary, "Receipt", record=p) == \
        "2026-05-14 Apple Apple One Receipt.pdf"


def test_an_apple_store_invoice_is_filed_under_its_product():
    storage.set_filename_owner("")
    p = Purchase(purchase_type="Apple Store", purchase_date="2026-04-28",
                 order_number="W0000000001", summary="Magic Keyboard")
    assert storage.build_pdf_filename(p.purchase_date, p.summary, "Receipt", record=p) == \
        "2026-04-28 Apple Magic Keyboard Receipt.pdf"


def test_two_receipts_on_one_day_are_told_apart_by_their_order_numbers(tmp_path):
    first = storage.unique_path(tmp_path, "2026-05-14 Apple Apple One Receipt.pdf", 240,
                                distinguisher="MLF0TEST01")
    first.write_bytes(b"%PDF-1.7")
    second = storage.unique_path(tmp_path, "2026-05-14 Apple Apple One Receipt.pdf", 240,
                                 distinguisher="MLF0TEST02")
    assert second.name == "2026-05-14 Apple Apple One Receipt MLF0TEST02.pdf"


# -- a store order is named for its product ----------------------------------------------

@pytest.mark.parametrize("product,summary", [
    ("iPhone 16 128GB Ultramarine", "iPhone"),
    ("13-inch MacBook Air M4 16GB - Sky Blue", "MacBook Air"),
    ("MacBook Pro 14-inch M4 Pro", "MacBook Pro"),
    ("Magic Keyboard for iPad Air 11-inch (M3) - US English", "Magic Keyboard"),
    ("iPad Air 11-inch Wi-Fi 128GB - Starlight", "iPad Air"),
    ("Apple Watch Series 10 GPS 42mm Case with Sport Band", "Apple Watch"),
    ("AppleCare+ for iPad Air", "AppleCare"),
    ("iPhone 16 Silicone Case with MagSafe - Denim", "Case"),
    ("46mm Plum Sport Loop", "Watch Band"),
    ("20W USB-C Power Adapter", "Power Adapter"),
])
def test_one_product_names_its_order(product, summary):
    assert named((product, "$99.00")) == (summary, "High")


def test_a_product_with_its_accessories_is_named_for_the_product():
    assert named(("iPhone 16 128GB Ultramarine", "$829.00"),
                 ("iPhone 16 Clear Case with MagSafe", "$49.00")) == ("iPhone", "High")


def test_an_order_nothing_recognizes_is_left_for_review_names():
    summary, confidence = named(("Engraving Service", "$0.00"))
    assert confidence == "Low"


def test_the_rules_file_is_valid_and_names_no_document_it_would_refuse():
    """Parsed as the core parses it, so a syntax slip is found here."""
    assert RULES["significant_items"]["Magic Keyboard"] == ["magic keyboard"]
    assert "summary" not in str(RULES), "a summary key would make the census treat these as documents"


# -- the identity check ------------------------------------------------------------------

APP_STORE_TEXT = ("Receipt\nMay 14, 2026\nOrder ID: MLF0TEST01\nDocument: 000000000001\n"
                  "Apple Account: dana@example.com\nApple One\nPremier (Monthly)\n$21.43\n"
                  "Billing and Payment\nDana Example\nSubtotal $21.43")
STORE_TEXT = ("Apple Store\nInvoice Receipt\nOrder Number:\nW0000000001\nOrder Date:\n"
              "April 28, 2026\nIPAD AIR 11 WIFI 128GB STARLIGHT $612.34\nTotal $655.21")


def test_the_identity_carries_the_order_number_and_nothing_that_decides_else():
    p = Purchase(purchase_type="App Store", purchase_date="2026-05-14",
                 order_number="MLF0TEST01", total="$21.43")
    got = site.identity_for(p)
    assert got.number == "MLF0TEST01"
    assert sorted(got.strong()) == ["number"], "a date or total would let the wrong receipt through"


def test_a_receipt_carrying_its_own_order_id_is_verified():
    p = Purchase(order_number="MLF0TEST01")
    assert identity.verify(None, site.identity_for(p), text=APP_STORE_TEXT).outcome == identity.VERIFIED
    p = Purchase(order_number="W0000000001")
    assert identity.verify(None, site.identity_for(p), text=STORE_TEXT).outcome == identity.VERIFIED


def test_a_receipt_from_the_same_day_for_the_same_amount_is_still_refused():
    """The case a date and a total would have let through. Two renewals of
    the same subscription share both, and only the order number differs."""
    p = Purchase(purchase_date="2026-05-14", total="$21.43", order_number="MLF0TEST02")
    got = identity.verify(None, site.identity_for(p), text=APP_STORE_TEXT)
    assert got.outcome == identity.REFUSED
