"""A date or a total is found only as a number of its own.

The wrong-document check (identity.verify and identity.distinguish, which
delivery runs for every app that hands it what it asked for) found a
fact's ways of printing anywhere in a document's text. So "1/19/27" was
found inside "11/19/27" and "1.23" inside "31.23", and a January 19
purchase of $1.23 took a November 19 receipt for $31.23 as its own, by
its date and by its total both. A 2020 date was found inside a 2027 one
the same way, "08/23/20" at the front of "08/23/2027".

Now a digit may not touch the front of a date or an amount that starts
with one, nor a point or a comma joining it to one, and a digit may not
touch its end. A document number is matched as it was, since MIN_NUMBER
already keeps a short one out.

Measured before it changed, read only, on every saved document of every
install. No document lost its own date or total once a day written
before its month's name was asked for with its zero as well (05 Jan
2027). A plain search had found those by finding 5 Jan 2027 inside them,
and without the zero every statement printed that way lost its date. A
zero-padded month before a day without one (01/5/2027) was found the
same way and is asked for too, though nothing saved prints it.

validate_pdf takes the same kind of token, receipt_pdf.OnItsOwn, which
Uber hands its total and its printed dates as, and its date and total
pair finds each by the same rule, written once in identity.on_its_own.

Every date, amount and store here is invented.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import identity as I  # noqa: E402
from paperpull_core import receipt_pdf  # noqa: E402
from paperpull_core.testkit import text_pdf  # noqa: E402

PAD = ("\nPage 1 of 1. This document is provided for your records. "
       "Questions about it may be directed to member services.\n")


def verdict(expect, text):
    """Padded, since verify concludes nothing from less text than a real
    document carries."""
    return I.verify(None, expect, text=text + PAD)


JANUARY = I.Identity(date="2027-01-19", total="1.23")
NOVEMBER = I.Identity(date="2027-11-19", total="31.23")
NOVEMBER_RECEIPT = "Invented Grocer\nSale 11/19/27 4:12 PM\nTotal $31.23\n"


# -- a longer number holds a shorter one --------------------------------------

def test_a_date_is_not_found_inside_a_longer_one():
    v = verdict(I.Identity(date="2027-01-19"), NOVEMBER_RECEIPT)
    assert v.outcome == I.REFUSED


def test_an_amount_is_not_found_inside_a_larger_one():
    v = verdict(I.Identity(total="1.23"), NOVEMBER_RECEIPT)
    assert v.outcome == I.REFUSED


def test_a_grouped_amount_is_not_found_inside_a_larger_one():
    v = verdict(I.Identity(total="1284.55"), "Amount due $11,284.55")
    assert v.outcome == I.REFUSED


def test_a_two_digit_year_is_not_found_at_the_front_of_a_four_digit_one():
    v = verdict(I.Identity(date="2020-08-23"), "Statement closing 08/23/2027")
    assert v.outcome == I.REFUSED


def test_a_day_written_first_is_not_found_inside_another_day():
    v = verdict(I.Identity(date="2027-01-05"), "Statement date 15 Jan 2027")
    assert v.outcome == I.REFUSED


def test_the_receipt_beside_it_is_refused_rather_than_taken_as_its_own():
    """The case that started it. Every fact of the January purchase was
    found on the November receipt, so the check took it, and beside its
    real row it scored the same as that row and still passed."""
    assert I.verify(None, JANUARY, text=NOVEMBER_RECEIPT + PAD).outcome == I.REFUSED
    assert I.distinguish(None, JANUARY, [NOVEMBER],
                         text=NOVEMBER_RECEIPT + PAD).outcome == I.REFUSED
    assert I.distinguish(None, NOVEMBER, [JANUARY],
                         text=NOVEMBER_RECEIPT + PAD).outcome == I.VERIFIED


# -- and nothing a document prints of its own is lost -------------------------

@pytest.mark.parametrize("printed", [
    "Sale 1/19/27 4:12 PM",
    "Date:01/19/2027",
    "(Jan 19, 2027)",
    "Ordered on 2027-01-19.",
    "Placed January 19, 2027",
    "19 January 2027",
])
def test_a_date_printed_on_its_own_is_still_found(printed):
    assert verdict(I.Identity(date="2027-01-19"), printed).outcome == I.VERIFIED


@pytest.mark.parametrize("printed", [
    "Total $1.23",
    "Total 1.23.",
    "TOTAL 1.23USD",
    "Refund -$1.23",
    "Balance:1.23",
])
def test_an_amount_printed_on_its_own_is_still_found(printed):
    assert verdict(I.Identity(total="1.23"), printed).outcome == I.VERIFIED


def test_a_day_written_first_with_its_zero_is_still_found():
    """Statements print 05 Jan 2027. A plain search found them by finding
    5 Jan 2027 inside it, which a date found as a number of its own does
    not do, and measured without the zero every statement printed that
    way lost its own date."""
    for printed in ("Statement date 05 Jan 2027",
                    "Period 08 Dec 2026 to 05 January 2027"):
        assert verdict(I.Identity(date="2027-01-05"), printed).outcome == I.VERIFIED, printed


def test_a_month_with_its_zero_before_a_day_without_one_is_still_found():
    """01/5/2027 was found the same way, 1/5/2027 at its end. Nothing
    saved prints it, and it is asked for so no document that does is
    refused where the plain search took it."""
    for printed in ("Paid 01/5/2027", "Paid 01/5/27 9:14 AM"):
        assert verdict(I.Identity(date="2027-01-05"), printed).outcome == I.VERIFIED, printed


def test_a_till_that_prints_a_letter_at_a_time_is_still_read():
    spaced = "T o t a l  1 2 8 4 . 5 5   0 1 / 1 5 / 2 7"
    v = verdict(I.Identity(date="2027-01-15", total="1284.55"), spaced)
    assert v.outcome == I.VERIFIED
    assert set(v.matched) == {"date", "total"}


def test_only_a_date_and_a_total_are_held_to_a_number_of_their_own():
    """A document number is matched as it was, and so is anything the
    caller names nothing for."""
    text = "Reference 90012345678"
    assert I.contains(text, ["12345678"])
    assert I.contains(text, ["12345678"], fact="number")
    assert not I.contains("Sale 11/19/27", ["1/19/27"], fact="date")
    assert I.contains("Sale 11/19/27", ["1/19/27"])


def test_nothing_is_found_in_no_text():
    assert not I.on_its_own("1.23", "")
    assert not I.on_its_own("", "total 1.23")
    assert not I.contains("", ["1.23"], fact="total")


# -- validate_pdf takes the same kind of token --------------------------------

@pytest.fixture
def testco():
    """This process's provider, and whatever was bound before put back."""
    before = receipt_pdf._SPEC
    receipt_pdf.bind(SimpleNamespace(provider="Testco", token="testco", base_url=""))
    yield
    receipt_pdf.bind(before)


def check(tmp_path, lines, tokens):
    path = tmp_path / "saved.pdf"
    path.write_bytes(text_pdf(lines))
    return receipt_pdf.validate_pdf(path, 1000, tokens)


NOVEMBER_LINES = ["Invented Grocer", "Sale 11/19/27 4:12 PM", "Total $31.23",
                  "Thank you for shopping with us today."]


def test_a_token_on_its_own_is_found_only_as_a_number_of_its_own(tmp_path, testco):
    january = [receipt_pdf.OnItsOwn(I.date_variants("2027-01-19")),
               receipt_pdf.OnItsOwn(("$1.23", "1.23"))]
    assert not check(tmp_path, NOVEMBER_LINES, january).ok
    november = [receipt_pdf.OnItsOwn(I.date_variants("2027-11-19"))]
    assert check(tmp_path, NOVEMBER_LINES, november).ok


def test_one_found_is_enough_as_with_any_token(tmp_path, testco):
    tokens = [receipt_pdf.OnItsOwn(I.date_variants("2027-01-19")),
              receipt_pdf.OnItsOwn(("$31.23",))]
    assert check(tmp_path, NOVEMBER_LINES, tokens).ok


def test_the_same_date_handed_over_plain_is_found_anywhere(tmp_path, testco):
    """Why Uber hands its dates over as OnItsOwn. A plain token is found
    inside a longer number, as it always was."""
    assert check(tmp_path, NOVEMBER_LINES, I.date_variants("2027-01-19")).ok


@pytest.mark.parametrize("printed", ["05 JAN 2027  4:12 PM", "01/5/27 4:12 PM"])
def test_the_date_and_total_pair_finds_a_date_written_with_a_zero(tmp_path, testco, printed):
    """A till receipt with no number and no item the check knows is named
    by the date and total its list showed, each found only as a number of
    its own. The plain search found these prints by finding 5 Jan 2027 or
    1/5/27 inside them, and the zero forms date_variants asks for keep
    them found."""
    from paperpull_core.models import Purchase
    purchase = Purchase(purchase_date="2027-01-05", total="$7.42")
    listed = {"purchase_date": "2027-01-05", "total": "$7.42"}
    tokens = receipt_pdf.expected_tokens_for(purchase, listed=listed)
    lines = ["Invented Market", printed, "BALANCE DUE 7.42",
             "Thank you for shopping with us today."]
    assert check(tmp_path, lines, tokens).ok


def test_an_empty_token_on_its_own_is_left_out_like_any_empty_token(tmp_path, testco):
    """A purchase with no total hands an empty one. It is not found, and
    it does not stand in for the store the page does not name."""
    tokens = [receipt_pdf.OnItsOwn(()), "Invented Noodle House"]
    assert not check(tmp_path, NOVEMBER_LINES, tokens).ok
    assert check(tmp_path, NOVEMBER_LINES, [receipt_pdf.OnItsOwn(())]).ok
