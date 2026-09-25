"""Is this the document we asked for.

The failure this exists to catch is silent. A row index off by one, or a
modal that did not close so the next capture re-read the last document,
writes a perfectly valid PDF to a correct-looking path and reports
success. Nobody finds out until a tax year is being reconciled.

So these tests are mostly about the two ways the check itself could be
worse than useless. Passing a document it should have refused, which
returns us to no check at all, and refusing one it should have passed,
which would break forty eight working apps at once.
"""
import json

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import identity as I


PAD = ("\nPage 1 of 1. This statement is provided for your records. "
       "Questions about this document may be directed to member services.\n")


def verdict(expect, text):
    """Padded, because verify concludes nothing from less text than a
    real document carries, and every fixture here is one line."""
    return I.verify(None, expect, text=(text or "") + PAD)


PAGE = """
    Costco Wholesale
    Warehouse #1234
    Order Number 8421997301
    January 15, 2026
    Subtotal            1,204.18
    Total              $1,284.55
"""


# -- the question it is actually for ------------------------------------------

def test_the_right_document_is_verified():
    v = verdict(I.Identity(date="2026-01-15", total="1284.55",
                           number="8421997301"), PAGE)
    assert v.outcome == I.VERIFIED
    assert set(v.matched) == {"date", "total", "number"}


def test_the_neighboring_document_is_refused():
    """The realistic failure. An index off by one captures the receipt
    below the one being written, and every other check passes."""
    v = verdict(I.Identity(date="2026-02-09", total="76.41",
                           number="8421997999"), PAGE)
    assert v.outcome == I.REFUSED
    assert v.matched == ()
    assert not v.ok


def test_one_strong_fact_is_enough():
    """A provider that renders an amount as an image still prints the
    order number, and a document that agrees about its number is not the
    wrong document."""
    v = verdict(I.Identity(date="2026-09-09", total="9.99",
                           number="8421997301"), PAGE)
    assert v.outcome == I.VERIFIED
    assert v.matched == ("number",)


# -- the check must not be satisfied by something every document carries ------

def test_the_provider_name_alone_does_not_verify_anything():
    """This is the hole in validate_pdf's expect_tokens. Every page of
    every statement says Costco, so satisfying the check with it means
    the check passes always."""
    v = verdict(I.Identity(kind="Costco Wholesale"), PAGE)
    assert v.outcome == I.UNCHECKED
    assert v.checked == ()


def test_a_zero_total_is_not_a_fact():
    """A statement with nothing on it shows 0.00, so it tells two
    documents apart exactly never."""
    assert I.amount_variants("0.00") == []
    assert verdict(I.Identity(total="0.00"), PAGE).outcome == I.UNCHECKED


def test_a_short_number_is_not_a_fact():
    """Looking for 12 in a statement finds 2012, 120.00 and page 12."""
    assert I.number_variants("12") == []
    assert I.number_variants("8421997301") != []


def test_a_placeholder_number_is_not_a_fact():
    assert I.number_variants("0000000") == []
    assert I.number_variants("XXXXXXXX") == []


def test_a_kind_is_recorded_and_never_decides():
    v = verdict(I.Identity(kind="Statement", number="8421997301"), PAGE)
    assert "kind" not in v.checked
    assert v.outcome == I.VERIFIED


# -- the ways a provider prints a date, which is where this breaks -----------

def test_an_iso_date_is_found_however_the_provider_prints_it():
    for printed in ("2026-01-15", "01/15/2026", "1/15/2026", "01/15/26",
                    "January 15, 2026", "Jan 15, 2026", "Jan. 15, 2026",
                    "15 January 2026", "2026/01/15", "01.15.2026"):
        v = verdict(I.Identity(date="2026-01-15"), "Statement for " + printed)
        assert v.outcome == I.VERIFIED, printed


def test_day_first_is_deliberately_not_matched():
    """15/01/2026 would make 01/02/2026 match both January 2nd and
    February 1st. A check that matches the wrong document is worse than
    no check."""
    v = verdict(I.Identity(date="2026-01-15"), "Statement for 15/01/2026 only")
    assert v.outcome == I.REFUSED


def test_a_statement_dated_by_month_is_matched_by_period():
    for printed in ("January 2026", "Jan 2026", "01/2026", "2026-01"):
        v = verdict(I.Identity(period="2026-01"), "Billing period " + printed)
        assert v.outcome == I.VERIFIED, printed


def test_a_nonsense_date_supplies_no_fact():
    for bad in ("", "not a date", "2026-13-01", "2026-01-99", "01/15/2026"):
        assert I.date_variants(bad) == [], bad


# -- amounts ------------------------------------------------------------------

def test_an_amount_is_found_grouped_or_plain_or_with_a_sign():
    for printed in ("1284.55", "1,284.55", "$1,284.55", "$1284.55"):
        v = verdict(I.Identity(total="1284.55"), "Amount due " + printed)
        assert v.outcome == I.VERIFIED, printed


def test_an_amount_given_the_way_a_page_showed_it_still_works():
    assert verdict(I.Identity(total="$1,284.55"), PAGE).outcome == I.VERIFIED


def test_a_credit_matches_its_own_magnitude():
    assert verdict(I.Identity(total="-1284.55"), PAGE).outcome == I.VERIFIED


# -- a till prints one letter at a time ---------------------------------------

def test_text_spaced_out_per_letter_is_still_matched():
    """A warehouse receipt renders as T o t a l 1 2 8 4 . 5 5 and no
    ordinary search finds anything in it."""
    spaced = "O r d e r  8 4 2 1 9 9 7 3 0 1  T o t a l  1 2 8 4 . 5 5"
    v = verdict(I.Identity(number="8421997301"), spaced + " " * 40)
    assert v.outcome == I.VERIFIED


# -- the three answers that are not yes or no ---------------------------------

def test_a_scan_is_unreadable_rather_than_wrong():
    """An image-only PDF disagrees with nothing, which is not the same as
    agreeing, and refusing it would throw away every provider that scans.

    Unpadded on purpose. These are the cases about there being too little
    text to conclude from, so the helper that supplies text would remove
    the thing being tested."""
    v = I.verify(None, I.Identity(number="8421997301"), text="")
    assert v.outcome == I.UNREADABLE
    assert v.ok


def test_a_nearly_empty_render_is_unreadable_too():
    v = I.verify(None, I.Identity(number="8421997301"), text="1")
    assert v.outcome == I.UNREADABLE


def test_no_expectation_at_all_is_unchecked_and_says_so():
    assert I.verify(None, None, text=PAGE).outcome == I.UNCHECKED
    assert not I.Identity().is_checkable()


def test_unchecked_and_unreadable_both_allow_the_file_and_only_refused_does_not():
    assert verdict(I.Identity(), PAGE).ok
    assert I.verify(None, I.Identity(number="8421997301"), text="").ok
    assert not verdict(I.Identity(number="8421997999"), PAGE).ok


# -- it may never take a run down ---------------------------------------------

def test_a_file_that_cannot_be_read_does_not_raise():
    v = I.verify("C:/nowhere/not-a-file.pdf", I.Identity(number="8421997301"))
    assert v.outcome == I.UNREADABLE


def test_rubbish_in_the_fields_does_not_raise():
    v = verdict(I.Identity(date=None, total=object(), number=b"\xff"), PAGE)
    assert v.outcome in (I.UNCHECKED, I.REFUSED, I.VERIFIED)


# -- what a reader is told ----------------------------------------------------

def test_a_refusal_says_something_captured_the_wrong_document():
    said = " ".join(I.summarize(
        verdict(I.Identity(number="8421997999"), PAGE).report()))
    assert "wrong document" in said


def test_an_unreadable_document_is_named_as_two_possibilities():
    said = " ".join(I.summarize(
        I.verify(None, I.Identity(number="8421997301"), text="").report()))
    assert "scan" in said and "blank" in said


def test_nothing_to_check_against_is_worth_saying_out_loud():
    said = " ".join(I.summarize(verdict(I.Identity(), PAGE).report()))
    assert "would not have been noticed" in said


def test_summarizing_something_that_is_not_a_report_is_empty():
    assert I.summarize(None) == []
    assert I.summarize("refused") == []


# -- the canary. This report goes in a file a tester posts publicly -----------

CANARY = """
    CANARYNAME
    123 CANARYSTREET
    Order Number CANARY8421997301
    Card ending CANARY4821
    January 15, 2026
    Total $1,284.55
"""


def test_no_value_reaches_the_report():
    """The point of reporting rather than returning what was seen. That a
    date disagreed is ours to publish. The date is not."""
    v = I.verify(None, I.Identity(date="2026-01-15", total="1284.55",
                                  number="CANARY8421997301",
                                  kind="CANARYKIND"), text=CANARY)
    body = json.dumps(v.report())
    for secret in ("CANARY", "8421997301", "1284.55", "1,284.55",
                   "2026-01-15", "January", "4821", "CANARYSTREET"):
        assert secret not in body, secret


def test_the_report_carries_the_field_names_because_that_is_the_point():
    v = I.verify(None, I.Identity(date="2026-01-15", number="8421997301"),
                 text=PAGE)
    body = json.dumps(v.report())
    assert "date" in body and "number" in body and "verified" in body


def test_the_sentence_a_reader_sees_carries_no_value_either():
    for expect in (I.Identity(number="CANARY8421997301"),
                   I.Identity(date="2026-01-15", total="1284.55")):
        for text in (CANARY, "", "nothing like it at all, but long enough  "):
            assert "CANARY" not in I.verify(None, expect, text=text).say()
            assert "1284" not in I.verify(None, expect, text=text).say()


# -- and through the failure file, which is the file that gets posted --------

def test_a_verdict_reaches_the_failure_file_without_its_values(tmp_path):
    """write_failure is what a tester attaches. The verdict travels in
    it, so the canary has to hold on that path too and not only on
    Verdict.report."""
    from paperpull_core import failure

    v = I.verify(None, I.Identity(date="2026-01-15", total="1284.55",
                                  number="CANARY8421997301"), text=CANARY)
    path = failure.write_failure(tmp_path, "pilot", "save the document",
                                 provider="Testco", identity=v,
                                 say=lambda *a, **k: None)
    assert path, "no failure file was written"
    body = Path(path).read_text(encoding="utf-8")
    for secret in ("CANARY", "8421997301", "1284.55", "2026-01-15"):
        assert secret not in body, secret
    # The canary text carries the matching values on purpose, so this is
    # the harder direction. A verdict that found all three has held all
    # three in its hand and must still write none of them down.
    assert "identity" in body
    assert "verified" in body


def test_the_failure_file_says_something_captured_the_wrong_document(tmp_path):
    from paperpull_core import failure

    v = I.verify(None, I.Identity(number="8421997999"), text=PAGE + PAD)
    path = failure.write_failure(tmp_path, "pilot", "save the document",
                                 provider="Testco", identity=v,
                                 say=lambda *a, **k: None)
    said = " ".join(failure.summarize(json.loads(Path(path).read_text("utf-8"))))
    assert "wrong document" in said


def test_a_failure_file_with_no_verdict_is_unchanged(tmp_path):
    """Forty eight apps write one of these today without an identity, and
    every one of them has to keep working."""
    from paperpull_core import failure

    path = failure.write_failure(tmp_path, "pilot", "read the rows",
                                 provider="Testco", say=lambda *a, **k: None)
    assert "identity" not in json.loads(Path(path).read_text("utf-8"))


# -- the comparative check, for rows that share a fact ------------------------

NFCU_CHECKING = ("Navy Federal Credit Union\n"
                 "Combined Checking and Savings Statement\n"
                 "Statement date 08/24/2026\n" + "Member copy. " * 12)
NFCU_LOAN = ("Navy Federal Credit Union\n"
             "Account Statement\n"
             "Statement date 08/24/2026\n" + "Member copy. " * 12)

CHECKING = I.Identity(date="2026-08-24", label="Checking and Savings")
LOAN = I.Identity(date="2026-08-24", label="New Vehicle Loan")


def test_two_rows_on_one_date_are_told_apart_by_what_only_one_prints():
    """Eight Navy Federal dates carry a statement per account, because
    they are all billed on the same day. Asking whether the document
    mentions the date gets a yes from both."""
    v = I.distinguish(None, CHECKING, [LOAN], text=NFCU_CHECKING)
    assert v.outcome == I.VERIFIED
    assert v.matched == ("label",)


def test_the_neighbours_statement_is_refused_rather_than_accepted():
    """The capture came back with the checking statement while the loan
    statement was being written. Under the old check both mentioned the
    date and it passed."""
    v = I.distinguish(None, LOAN, [CHECKING], text=NFCU_CHECKING)
    assert v.outcome == I.REFUSED
    assert not v.ok


def test_a_document_printing_nothing_that_separates_them_says_so():
    """The loan statement names neither account. That is a document this
    cannot place, not a document belonging to the other row, and the
    difference is the whole reason for a third answer."""
    v = I.distinguish(None, LOAN, [CHECKING], text=NFCU_LOAN)
    assert v.outcome == I.UNCHECKED
    assert v.ok, "a document was refused for failing to print something it never prints"


def test_a_shared_date_stops_counting_as_evidence():
    """Both rows carry it, so it says nothing about which one this is."""
    v = I.distinguish(None, CHECKING, [LOAN], text=NFCU_CHECKING)
    assert "date" not in v.checked


# -- the Fairfax shape, where the document prints the neighbour's date --------

FAIRFAX_JULY = ("Fairfax Water  Account 0718\n"
                "Bill date 07/17/26   Due 08/17/26\n"
                "Previous bill 04/16/26\n"
                "Amount due 118.43\n" + "Please retain this notice. " * 12)

JULY = I.Identity(date="2026-07-17", total="118.43")
APRIL = I.Identity(date="2026-04-16", total="96.12")


def test_a_bill_that_prints_the_previous_date_is_still_placed_correctly():
    v = I.distinguish(None, JULY, [APRIL], text=FAIRFAX_JULY)
    assert v.outcome == I.VERIFIED


def test_and_the_previous_quarters_row_is_refused():
    """The case the old check got wrong. April's date is on the July
    bill, so verify said yes. April's amount is not, and the comparison
    is what notices."""
    v = I.distinguish(None, APRIL, [JULY], text=FAIRFAX_JULY)
    assert v.outcome == I.REFUSED


# -- it never refuses for want of a fact the provider does not print ----------

def test_a_document_that_prints_none_of_its_facts_is_unchecked_not_refused():
    """Eight of twenty five TSP documents do not mention their own date,
    because a mailbox row is dated when it was delivered. Under a plain
    all-must-match rule every one of those would be thrown away."""
    quarterly = ("Thrift Savings Plan\nQuarterly Participant Statement\n"
                 "For the period January 1 to March 31, 2022\n" + "TSP. " * 20)
    delivered = I.Identity(date="2022-04-04")
    other = I.Identity(date="2022-07-05")
    v = I.distinguish(None, delivered, [other], text=quarterly)
    assert v.outcome == I.UNCHECKED
    assert v.ok


def test_with_no_competing_rows_it_is_the_plain_check():
    assert I.distinguish(None, EXPECT_ONE, [], text=PAGE + PAD).outcome == \
        I.verify(None, EXPECT_ONE, text=PAGE + PAD).outcome


EXPECT_ONE = I.Identity(number="8421997301")


def test_a_scan_is_unreadable_here_too():
    v = I.distinguish(None, CHECKING, [LOAN], text="")
    assert v.outcome == I.UNREADABLE


def test_nothing_to_compare_with_is_unchecked():
    assert I.distinguish(None, None, [LOAN], text=NFCU_LOAN).outcome == I.UNCHECKED
    assert I.distinguish(None, I.Identity(), [LOAN],
                         text=NFCU_LOAN).outcome == I.UNCHECKED


def test_the_comparative_verdict_leaks_no_value_either():
    secret = I.Identity(date="2026-08-24", label="CANARYACCOUNT")
    rival = I.Identity(date="2026-08-24", label="CANARYOTHER")
    v = I.distinguish(None, secret, [rival],
                      text="CANARYACCOUNT statement 08/24/2026 " * 6)
    body = json.dumps(v.report())
    for leak in ("CANARYACCOUNT", "CANARYOTHER", "08/24/2026", "2026-08-24"):
        assert leak not in body, leak
    assert "label" in body


# -- which rows count as competing --------------------------------------------

def rows(*specs):
    return [I.Identity(date=d, label=lab) for d, lab in specs]


def test_the_rows_either_side_are_rivals():
    """An index off by one is the commonest way a capture comes back
    with the wrong document."""
    r = rows(("2026-01-01", ""), ("2026-02-01", ""), ("2026-03-01", ""),
             ("2026-04-01", ""), ("2026-05-01", ""))
    got = I.rivals_for(r, 2, span=1)
    assert [x.date for x in got] == ["2026-02-01", "2026-04-01"]


def test_every_row_sharing_the_date_is_a_rival_however_far_away():
    """Navy Federal bills every account on one day, and those rows can
    be anywhere in the list."""
    r = rows(("2026-08-24", "Checking"), ("2026-07-24", "Checking"),
             ("2026-06-24", "Checking"), ("2026-05-24", "Checking"),
             ("2026-08-24", "Vehicle Loan"))
    got = I.rivals_for(r, 0, span=1)
    assert any(x.label == "Vehicle Loan" for x in got), \
        "the statement on the same date was not treated as a rival"


def test_the_row_itself_is_never_its_own_rival():
    r = rows(("2026-08-24", "a"), ("2026-08-24", "b"))
    assert all(x.label != "a" for x in I.rivals_for(r, 0))


def test_a_short_list_is_handled_without_running_off_either_end():
    r = rows(("2026-01-01", ""), ("2026-02-01", ""))
    assert len(I.rivals_for(r, 0)) == 1
    assert len(I.rivals_for(r, 1)) == 1
    assert I.rivals_for(r, 5) == ()
    assert I.rivals_for([], 0) == ()
    assert I.rivals_for(None, 0) == ()


def test_a_neighbourhood_beats_the_whole_list():
    """Measured. Against sixty four Navy Federal statements at once,
    sixteen were placeable by nothing, because a fact a rival shares
    stops counting and enough rivals share everything."""
    r = rows(*[("2026-%02d-01" % ((n % 12) + 1), "acct") for n in range(40)])
    assert len(I.rivals_for(r, 20, span=3)) < 12


# -- a check that cannot be made never takes a download down -------------------

@pytest.mark.parametrize("total", ["nan", "inf", "-Infinity", float("nan")])
def test_a_total_that_is_not_a_number_supplies_no_fact_and_raises_nothing(total):
    """nan parses as a float and prints as a word, and splitting "nan" on
    its point raised out of every check that asked."""
    assert I.amount_variants(total) == []
    assert not I.Identity(total=total).is_checkable()


def test_no_rivals_given_as_none_is_the_same_as_none_given(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    got = I.distinguish(pdf, I.Identity(date="2026-01-15"), None, text="x")
    assert got.outcome in (I.UNCHECKED, I.UNREADABLE, I.VERIFIED, I.REFUSED)


def test_a_check_that_raises_keeps_the_document_and_leaves_nothing_staged(
        tmp_path, monkeypatch):
    from paperpull_core import delivery

    def boom(*a, **kw):
        raise RuntimeError("the checker is unwell")
    monkeypatch.setattr(delivery, "distinguish", boom)
    got = delivery.place(b"%PDF-1.4\n" + b"x" * 2000, tmp_path / "s.pdf",
                         expect=I.Identity(date="2026-01-15"))
    assert got.outcome == delivery.SAVED
    assert got.verdict.outcome == I.UNCHECKED
    assert not list(tmp_path.glob("*.delivering"))
