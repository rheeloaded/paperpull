"""M&T mortgage document classification + the READ-ONLY (bank) safety guard.

Classification cases are provisional starting guesses for a mortgage servicing
account, to be re-pointed at the real titles once diagnose has run. The SAFETY
cases are not provisional: they are why this app is allowed near a mortgage
that can move money.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import mtb_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_mortgage_statements():
    for title, summary in [
            ("Mortgage Statement - June 2026", "Mortgage Statement"),
            ("Monthly Billing Statement", "Monthly Statement"),
            ("eStatement", "Mortgage Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_escrow_and_insurance_documents():
    for title, summary in [
            ("Annual Escrow Analysis", "Escrow Analysis"),
            ("Annual Escrow Account Disclosure Statement", "Escrow Statement"),
            ("Hazard Insurance Disbursement", "Hazard Insurance Notice"),
            ("Property Tax Disbursement", "Property Tax Notice")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.INSURANCE, (title, cat)
        assert s == summary, (title, s)


def test_escrow_beats_statement():
    """An escrow disclosure STATEMENT contains 'statement' but must file under
    escrow, not the generic mortgage-statement bucket."""
    cat, _, _ = doc_types.classify_document("Escrow Account Disclosure Statement", RULES)
    assert cat == doc_types.INSURANCE


def test_tax_forms():
    for title, summary in [
            ("1098 Mortgage Interest", "1098 Mortgage Interest Statement"),
            ("1099-INT 2025", "1099-INT Tax Form"),
            ("Tax Document Package", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_year_end():
    cat, s, _ = doc_types.classify_document("Year-End Statement 2025", RULES)
    assert cat == doc_types.YEAR_END and s == "Year-End Statement"


def test_no_credit_union_vocabulary_from_the_app_this_was_cloned_from():
    """Cloned from Navy Federal. A mortgage has no checking/savings/auto-policy
    documents, and the Dominion clone shipped Robinhood's vocabulary for
    months, so this guards against the same drift."""
    for title in ["Checking Account Statement", "Savings Statement",
                  "Auto Insurance Policy", "Credit Card Statement"]:
        _, summary, _ = doc_types.classify_document(title, RULES)
        for word in ("Checking", "Savings", "Auto Insurance", "Credit Card"):
            assert word not in summary, (title, summary)


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Mortgage Statement June 2026")[0] == "2026-06-30"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_statement_filename():
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-06-30", "Mortgage Statement", "") == \
        "2026-06-30 M&T Bank Mortgage Statement.pdf"


# -- SAFETY: a mortgage servicer can move real money ----------------------

def test_money_and_mortgage_actions_are_never_safe():
    for label in ["Make a Payment", "Pay My Mortgage", "Set Up Autopay",
                  "Principal Only Payment", "Payoff Quote", "Payoff Request",
                  "Escrow Analysis Change", "Transfer", "Wire", "Zelle",
                  "Refinance Your Loan", "Recast", "Request Forbearance",
                  "Edit", "Update", "Delete", "Submit", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_actions_are_safe():
    for label in ["Download", "View Statement", "Open PDF", "Save", "Print",
                  "1098 Tax Form", "eStatement", "View Document",
                  "Escrow Statement", "Year-End Statement"]:
        assert site.is_safe_control(label), label


def test_deny_by_default():
    for label in ["", "More", "Continue", "Next", "Help", "Menu"]:
        assert not site.is_safe_control(label), label


# -- SAFETY: every requested URL stays on an M&T host ---------------------

def test_urls_must_stay_on_an_mt_host():
    assert site.is_safe_url("https://onlinebanking.mtb.com/x")
    assert site.is_safe_url("https://www.mtb.com/log-in")
    for bad in ["https://onlinebanking.mtb.com.evil.test/x",
                "https://onlinebanking.mtb.com@evil.test/x",
                "http://onlinebanking.mtb.com/x",
                "https://mtb.com.evil.test/x",
                "https://evil.test/x",
                "//evil.test/x",
                "javascript:alert(1)"]:
        assert not site.is_safe_url(bad), bad
