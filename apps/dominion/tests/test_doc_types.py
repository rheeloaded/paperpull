"""Dominion document classification + the READ-ONLY (utility billing) guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import dominion_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_statements():
    # What Dominion actually posts is a monthly bill. The first case is the
    # exact title collect_download_docs() builds.
    for title, summary in [
            ("Statement - July 22, 2026", "Account Statement"),
            ("Account Statement", "Account Statement"),
            ("Monthly Account Statement - December 2025", "Monthly Statement"),
            ("Detailed Bill", "Detailed Bill"),
            ("Monthly Bill", "Monthly Statement"),
            ("Bill", "Bill")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_a_utility_has_no_brokerage_vocabulary():
    """This app was cloned from Robinhood and for a while classified
    "Crypto Statement" and "Consolidated 1099" as if a power company issued
    them. Nothing here should route on brokerage words."""
    for title in ["Brokerage Statement", "Crypto Statement",
                  "Consolidated 1099", "1099-B", "1042-S"]:
        _, summary, _ = doc_types.classify_document(title, RULES)
        assert "Crypto" not in summary and "Brokerage" not in summary, title
        assert "1099" not in summary and "1042" not in summary, title


def test_generic_tax_catch_still_routes():
    """Dominion issues no tax forms, but if one ever appears it should be
    filed rather than dropped into Other."""
    cat, _, _ = doc_types.classify_document("Tax Document", RULES)
    assert cat == doc_types.TAX


def test_boilerplate_is_skipped():
    for t in ["Privacy Policy", "Terms of Service", "Regulatory Communication"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Statement - July 22, 2026", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to Dominion", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_year_only():
    assert site.parse_period_date("2025 Annual Summary")[0] == "2025-12-31"


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Monthly Statement", "") == \
        "2025-12-31 Dominion Energy Monthly Statement.pdf"


def test_account_statement_filename():
    assert build_pdf_filename("2026-07-22", "Account Statement", "") == \
        "2026-07-22 Dominion Energy Account Statement.pdf"


# -- SAFETY: the read-only utility-billing guard --------------------------

def test_payment_and_account_controls_are_never_safe():
    for label in ["Pay", "Pay bill", "Make a payment", "Payment", "AutoPay",
                  "Auto Pay", "Schedule payment", "One-time payment",
                  "Payment plan", "Budget billing", "Enroll", "Unenroll",
                  "Start service", "Stop service", "Transfer service",
                  "Add bank account", "Add card", "Update", "Change", "Edit",
                  "Delete", "Confirm", "Submit", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download Your Detailed Bill PDF", "View bill",
                  "View statement", "Open PDF", "Save", "Download bill",
                  "Download report", "View document"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")
