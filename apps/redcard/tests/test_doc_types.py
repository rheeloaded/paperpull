"""Target Circle Card document classification + the READ-ONLY (credit-card)
safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doc_types
import redcard_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_statements():
    for title, summary in [
            ("Account Statement", "Account Statement"),
            ("Monthly Account Statement - December 2025", "Monthly Statement"),
            ("Billing Statement", "Billing Statement"),
            ("Statement - November 2025", "Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_year_end_summaries():
    for title in ["2025 Year-End Summary", "Year End Summary",
                  "Annual Summary 2024", "Year in Review"]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.YEAR_END, title
        assert s == "Year-End Summary", (title, s)


def test_tax_forms():
    for title, summary in [
            ("1099-INT", "1099-INT Tax Form"),
            ("Form 1099-MISC", "1099-MISC Tax Form"),
            ("1099-C Cancellation of Debt", "1099-C Tax Form"),
            ("Tax Document", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_disclosures_and_agreements_are_skipped():
    for t in ["Cardmember Agreement", "Privacy Statement", "Disclosure",
              "Terms and Conditions", "Benefits Guide", "Change in Terms"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Account Statement", RULES)
    assert not doc_types.should_skip("2025 Year-End Summary", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Year-End Summary", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.YEAR_END, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to Target Circle Card", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_slash_date():
    assert site.parse_period_date("Statement 11/30/2025")[0] == "2025-11-30"


def test_year_only():
    assert site.parse_period_date("2025 Year-End Summary")[0] == "2025-12-31"


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Monthly Statement", "") == \
        "2025-12-31 Target Circle Card Monthly Statement.pdf"


def test_year_end_filename():
    assert build_pdf_filename("2025-12-31", "Year-End Summary", "") == \
        "2025-12-31 Target Circle Card Year-End Summary.pdf"


# -- SAFETY: the read-only credit-card guard ------------------------------

def test_money_and_account_controls_are_never_safe():
    for label in ["Pay", "Pay bill", "Make a payment", "Autopay",
                  "Balance transfer", "Transfer", "Withdraw", "Deposit",
                  "Move money", "Send", "Redeem", "Redeem points",
                  "Membership Rewards", "Cash back", "Apply", "Apply now",
                  "Add card", "Link bank", "Dispute charge", "Report lost card",
                  "Book travel", "Cancel card", "Activate card", "Lock card",
                  "Freeze account", "Manage card", "Confirm", "Continue",
                  "Agree", "Enroll", "Upgrade"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download PDF", "View statement", "View document",
                  "Open PDF", "Save PDF", "View 1099", "Year-End Summary",
                  "Download statement (PDF)"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")
