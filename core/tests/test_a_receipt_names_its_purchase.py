"""A saved receipt has to name its purchase, and the provider's name is not that.

validate_pdf passed a PDF when any expected token appeared in its text,
and the first token expected_tokens_for handed it was the provider's own
name, which every page of the provider's site carries. On 2026-09-29 a
Walmart order list, printed after a sign-in in the middle of a run, was
filed as an online order's invoice that way and marked downloaded, so the
invoice itself would never have been asked for.

So the provider's name counts for nothing now, whoever hands it over, and
a PDF with text has to show the purchase's order number, its ISO date or
the start of an item's name. An app whose receipts can show none of those,
a till receipt with no number and no item the check could know, hands over
the date and total its list showed, and those count together.

Measured before it was enabled, on real saved receipts of every provider
that had any, it kept all of them but an invoice that named nothing of
its order.

Every order number, item, store and amount here is invented.
"""
from types import SimpleNamespace

import pytest

from paperpull_core import receipt_pdf
from paperpull_core.models import Item, Purchase
from paperpull_core.testkit import text_pdf


@pytest.fixture(autouse=True)
def walmart():
    """This process's provider, and whatever was bound before put back."""
    before = receipt_pdf._SPEC
    receipt_pdf.bind(SimpleNamespace(provider="Walmart", token="walmart", base_url=""))
    yield
    receipt_pdf.bind(before)


def check(tmp_path, lines, tokens):
    path = tmp_path / "saved.pdf"
    path.write_bytes(text_pdf(lines))
    return receipt_pdf.validate_pdf(path, 1000, tokens)


# The order list as Walmart's own page shows it, a store purchase with its
# date and an online order without one. Printed in place of the online
# order's invoice, it names Walmart and no fact of that order.
ORDER_LIST = ["Walmart  Save money. Live better.", "Purchase history",
              "Store purchase", "Purchased at Example Supercenter",
              "Jun 12, 2026", "$23.41", "View details",
              "Delivered", "$58.20", "View details"]

# The online order as the run held it after reading that list, the list's
# first date written into it and no item found.
MISREAD = Purchase(order_number="10000000000000000003", purchase_date="2026-06-12",
                   total="$58.20")

INVOICE = ["Walmart", "Jun 3, 2026 order", "Order# 10000000000000000003",
           "Invented Garden Hose, 50 ft  $41.97", "Invented Brass Hose Nozzle  $9.98",
           "Subtotal $51.95", "Tax $6.25", "Total $58.20"]


# -- a page that names only the provider ---------------------------------------

def test_the_order_list_is_not_an_orders_invoice(tmp_path):
    result = check(tmp_path, ORDER_LIST, receipt_pdf.expected_tokens_for(MISREAD))
    assert not result.ok
    assert "does not mention" in result.reason
    assert "order number, date or items" in result.reason


def test_the_provider_is_not_among_what_a_receipt_must_mention():
    tokens = receipt_pdf.expected_tokens_for(MISREAD)
    assert "walmart" not in [str(t).lower() for t in tokens]


def test_the_providers_name_handed_over_by_a_caller_counts_for_nothing(tmp_path):
    for name in ("walmart", "Walmart", " walmart "):
        result = check(tmp_path, ORDER_LIST, [name, "10000000000000000003"])
        assert not result.ok, name


def test_a_store_that_is_the_provider_counts_for_nothing(tmp_path):
    """Uber hands over the store a purchase was bought from as well, and a
    ride's store is Uber."""
    receipt_pdf.bind(SimpleNamespace(provider="Uber", token="uber", base_url=""))
    page = ["Uber", "Sign in to Uber", "Ride  Drive  Business  Uber Eats", "Help"]
    ride = Purchase(order_number="00000000-0000-4000-8000-000000000001",
                    purchase_date="2026-06-01", total="$14.20", store_info="Uber")
    tokens = receipt_pdf.expected_tokens_for(ride) + [ride.store_info]
    assert not check(tmp_path, page, tokens).ok


def test_a_provider_whose_name_has_punctuation(tmp_path):
    """Lowe's, LOWES and lowes are one name. The page says Lowes.com, as a
    footer does, since the apostrophe of a PDF's own font does not read
    back as one."""
    receipt_pdf.bind(SimpleNamespace(provider="Lowe's", token="lowes", base_url=""))
    page = ["Lowes.com", "Sign in to your MyLowes account",
            "Email address", "Password", "Forgot password?"]
    assert not check(tmp_path, page, ["Lowe's", "LOWES", "lowes", "300000001"]).ok


def test_a_neighbors_receipt_is_no_longer_this_ones(tmp_path):
    """Every Walmart invoice says Walmart, so an invoice saved under the
    purchase next to it on the list used to pass as well."""
    other = Purchase(order_number="10000000000000000009", purchase_date="2026-05-30",
                     total="$12.00", items=[Item(name="Invented Dish Soap, 24 oz")])
    assert not check(tmp_path, INVOICE, receipt_pdf.expected_tokens_for(other)).ok


# -- what still passes ------------------------------------------------------------

def test_an_invoice_that_names_its_order_number_passes(tmp_path):
    own = Purchase(order_number="10000000000000000003", purchase_date="2026-06-03")
    result = check(tmp_path, INVOICE, receipt_pdf.expected_tokens_for(own))
    assert result.ok and result.text_token_found


def test_a_receipt_that_names_only_an_item_passes(tmp_path):
    """Walmart prints the number the app keys a purchase on with dashes in
    it, which this check does not see, and the real saved receipts measured
    passed on their items."""
    own = Purchase(order_number="20000000000000000004", purchase_date="2026-06-12",
                   items=[Item(name="Invented Garden Hose, 50 ft")])
    lines = ["WALMART", "Example Supercenter", "INVENTED GARDEN HOSE, 50 FT 41.97",
             "SUBTOTAL 41.97", "TOTAL 44.48", "06/12/26"]
    assert check(tmp_path, lines, receipt_pdf.expected_tokens_for(own)).ok


def test_a_receipt_that_prints_its_iso_date_passes(tmp_path):
    own = Purchase(order_number="wh-2026-06-12-44.48", purchase_date="2026-06-12")
    lines = ["Example Wholesale", "Purchased 2026-06-12", "Total 44.48"]
    assert check(tmp_path, lines, receipt_pdf.expected_tokens_for(own)).ok


def test_a_scan_with_no_text_passes(tmp_path):
    """An image of a receipt has nothing to disagree with, as before."""
    own = Purchase(order_number="10000000000000000003", purchase_date="2026-06-03")
    assert check(tmp_path, [], receipt_pdf.expected_tokens_for(own)).ok


def test_a_scan_whose_few_words_include_the_provider_passes(tmp_path):
    """A scan with a line of text on it, the store's name, was accepted on
    that name, and it still is. It is not a page."""
    own = Purchase(order_number="10000000000000000003", purchase_date="2026-06-03")
    assert check(tmp_path, ["WALMART  #1234"], receipt_pdf.expected_tokens_for(own)).ok


def test_a_few_words_that_name_nothing_are_refused_as_before(tmp_path):
    own = Purchase(order_number="10000000000000000003", purchase_date="2026-06-03")
    assert not check(tmp_path, ["Page 1 of 1"], receipt_pdf.expected_tokens_for(own)).ok


def test_asked_for_nothing_but_the_provider_it_is_checked_as_before(tmp_path):
    """No caller does this today. If one does, the name is all there is to
    look for, and it is looked for rather than waved through."""
    assert check(tmp_path, INVOICE, ["walmart"]).ok
    assert not check(tmp_path, ["Invented Quarterly", "Page 1 of 1", "Terms apply"],
                     ["walmart"]).ok


# -- the date and total a list showed, together -----------------------------------

MEIJER = SimpleNamespace(provider="Meijer", token="meijer", base_url="")

# A till receipt as the member's own showed it (#42), the store, the date as
# the till prints it, the totals, and no number or item name the row gave.
TILL = ["MEIJER STORE 000", "09/19/26 14:02", "SUBTOTAL 21.10", "TAX 1.27",
        "TOTAL 22.37", "THANK YOU"]
ROW = {"purchase_date": "2026-09-19", "total": "$22.37", "order_number": "pexample0919"}


def till_purchase():
    return Purchase(order_number="pexample0919", purchase_date="2026-09-19",
                    total="$22.37", items=[Item(name="1234 Example Rd, Anytown")])


def test_a_till_receipt_is_named_by_its_rows_date_and_total(tmp_path):
    receipt_pdf.bind(MEIJER)
    tokens = receipt_pdf.expected_tokens_for(till_purchase(), listed=ROW)
    assert check(tmp_path, TILL, tokens).ok


def test_without_the_row_the_till_receipt_names_nothing(tmp_path):
    """Which is why the apps whose receipts look like this hand the row
    over, and the rest do not need to."""
    receipt_pdf.bind(MEIJER)
    assert not check(tmp_path, TILL, receipt_pdf.expected_tokens_for(till_purchase())).ok


def test_the_date_alone_or_the_total_alone_is_not_enough(tmp_path):
    receipt_pdf.bind(MEIJER)
    tokens = receipt_pdf.expected_tokens_for(till_purchase(), listed=ROW)
    other_total = [ln.replace("22.37", "31.23") for ln in TILL]
    other_date = [ln.replace("09/19/26", "09/12/26") for ln in TILL]
    assert not check(tmp_path, other_total, tokens).ok
    assert not check(tmp_path, other_date, tokens).ok


def test_the_pair_is_the_lists_and_not_the_page_that_was_misread(tmp_path):
    """The online order's card showed no date, so the list gives no pair.
    The date the misread page wrote into the purchase is never used, since
    the page it came from would pass a check built from it."""
    listed = {"purchase_date": "", "total": "$58.20"}
    tokens = receipt_pdf.expected_tokens_for(MISREAD, listed=listed)
    assert not any(isinstance(t, receipt_pdf.Together) for t in tokens)
    assert not check(tmp_path, ORDER_LIST, tokens).ok


def test_a_purchase_can_stand_in_for_its_row(tmp_path):
    """When the list kept no record of a purchase the app hands over the
    purchase itself, so a till receipt is not refused for that."""
    receipt_pdf.bind(MEIJER)
    p = till_purchase()
    assert check(tmp_path, TILL, receipt_pdf.expected_tokens_for(p, listed=p)).ok


def test_a_bare_state_is_no_record_of_the_row(tmp_path):
    """An app writes a purchase's state into the store its list is kept in
    before this check, so a purchase the list never held has a record by
    then that says nothing the list showed. The suite's own Meijer test
    found a till receipt put aside because that record was taken for the
    row."""
    receipt_pdf.bind(MEIJER)
    stub = {"state": "PDF Saved", "updated_at": "2026-09-29T23:40:00"}
    assert check(tmp_path, TILL, receipt_pdf.expected_tokens_for(till_purchase(),
                                                                 listed=stub)).ok


def test_a_row_that_showed_no_date_gives_no_pair_even_so(tmp_path):
    """A record with the fields and nothing in them is the list's own word
    that it showed no date, and the purchase's date is not put in its
    place, which is what keeps a misread page from vouching for itself."""
    listed = {"purchase_date": "", "total": "$58.20", "order_number": "10000000000000000003"}
    tokens = receipt_pdf.expected_tokens_for(MISREAD, listed=listed)
    assert not any(isinstance(t, receipt_pdf.Together) for t in tokens)
