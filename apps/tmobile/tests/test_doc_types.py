"""T-Mobile document classification + the READ-ONLY carrier safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds T-Mobile's AppSpec
from paperpull_core import doc_types
import tmobile_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_bills_are_monthly_statements():
    for title, summary in [
            ("Monthly Statement - December 12, 2025", "Monthly Statement"),
            ("Monthly Account Statement - December 2025", "Monthly Statement"),
            ("Download detailed bill", "Monthly Statement"),
            ("Account Statement", "Account Statement"),
            ("Bill", "Monthly Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms():
    for title, summary in [("2025 Form 1099", "1099 Tax Form"),
                           ("Tax document", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_payment_receipts_and_marketing_are_skipped():
    for t in ["Payment receipt", "Payment confirmation", "AutoPay enrollment",
              "Paperless billing", "Customer Agreement", "Privacy Policy", "Usage details"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - December 12, 2025", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to T-Mobile", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_year_only():
    assert site.parse_period_date("2025 Form 1099")[0] == "2025-12-31"


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Monthly Statement", "") == \
        "2025-12-31 T-Mobile Monthly Statement.pdf"


def test_account_statement_filename():
    assert build_pdf_filename("2026-07-22", "Account Statement", "") == \
        "2026-07-22 T-Mobile Account Statement.pdf"


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
                  "View statement", "Open PDF", "Download bill",
                  "Download report", "View document"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


def test_a_bare_save_is_refused_on_purpose():
    """"Save" used to count as a document action here. On a site that can move
    money it is far more likely to commit a settings change, and allowing it
    was why "Save Changes" passed the guard. "Save PDF" still passes, because
    that one names the document."""
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label
