"""PG&E document classification + the READ-ONLY (utility billing) guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import pge_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_statements():
    for title, summary in [
            ("Energy Statement - July 22, 2026", "Energy Statement"),
            ("Account Statement", "Account Statement"),
            ("Monthly Account Statement - December 2025", "Monthly Statement"),
            ("Detailed Bill", "Detailed Bill"),
            ("Monthly Bill", "Monthly Statement"),
            ("Bill", "Bill")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_a_utility_has_no_brokerage_vocabulary():
    for title in ["Brokerage Statement", "Crypto Statement",
                  "Consolidated 1099", "1099-B", "1042-S"]:
        _, summary, _ = doc_types.classify_document(title, RULES)
        assert "Crypto" not in summary and "Brokerage" not in summary, title
        assert "1099" not in summary and "1042" not in summary, title


def test_generic_tax_catch_still_routes():
    cat, _, _ = doc_types.classify_document("Tax Document", RULES)
    assert cat == doc_types.TAX


def test_boilerplate_is_skipped():
    for t in ["Privacy Policy", "Terms of Service", "Regulatory Communication"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Energy Statement - July 22, 2026", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to PG&E", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_year_only():
    assert site.parse_period_date("2025 Annual Summary")[0] == "2025-12-31"


def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Monthly Statement", "") == \
        "2025-12-31 PG&E Monthly Statement.pdf"


def test_account_statement_filename():
    assert build_pdf_filename("2026-07-22", "Account Statement", "") == \
        "2026-07-22 PG&E Account Statement.pdf"


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
    for label in ["Download", "Download Your Energy Statement PDF", "View bill",
                  "View statement", "Open PDF", "Download bill",
                  "Download report", "View document"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


def test_a_bare_save_is_refused_on_purpose():
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    # "edit" with only a trailing boundary matched the end of "Credit", so a
    # bill row that carried a credit was refused. The verbs themselves must
    # still be refused.
    for label in ["View Bill PDF (Credit)", "Credit Statement PDF"]:
        assert site.is_safe_control(label), label
    for label in ["Edit profile", "Change address", "Update payment method",
                  "Editing preferences", "Changed"]:
        assert not site.is_safe_control(label), label


def test_a_bill_row_hands_over_the_pdf_control_and_never_pay():
    class El:
        def __init__(self, text="", aria=None):
            self.text, self.aria = text, aria
        def inner_text(self, timeout=None):
            return self.text
        def get_attribute(self, name):
            return self.aria if name == "aria-label" else None

    pay, view = El("Pay"), El("View Bill PDF")
    assert site.pick_document_control([pay, view]) is view
    assert site.pick_document_control([El("Pay bill"), El("Make a payment")]) is None
    assert site.pick_document_control([El(""), El("", aria="View Bill PDF")]).aria == "View Bill PDF"
    assert site.pick_document_control([]) is None
    assert site.pick_document_control(None) is None


def test_the_page_picker_is_the_only_control_outside_a_row():
    assert site.is_page_picker("1 | Jump to")
    assert site.is_page_picker("Page 2")
    assert not site.is_page_picker("Pay | Jump to")
    assert not site.is_page_picker("")
    assert site.is_page_option("3", 3)
    assert not site.is_page_option("3 Pay", 3)
    assert not site.is_page_option("", 3)


def test_the_history_page_is_the_only_place_that_counts_as_found():
    class Page:
        def __init__(self, url, title="Bill and payment history"):
            self.url, self._title = url, title
        def title(self):
            return self._title
    assert site.on_documents_page(Page("https://myaccount.pge.com/myaccount/s/bill-and-payment-history"))
    assert not site.on_documents_page(Page("https://myaccount.pge.com/myaccount/s/"))
    assert not site.on_documents_page(Page("https://evil.test/bill-and-payment-history"))
    assert not site.on_documents_page(Page(
        "https://myaccount.pge.com/myaccount/s/bill-and-payment-history", "Page Not Found"))
