"""Navy Federal document classification + the READ-ONLY (bank) safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doc_types
import navyfederal_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_bank_statements():
    for title, summary in [
            ("Checking Account Statement", "Checking Statement"),
            ("Savings Statement - December 2025", "Savings Statement"),
            ("Credit Card Statement", "Credit Card Statement"),
            ("Monthly Statement", "Monthly Statement")]:
        cat, s, conf = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms():
    for title, summary in [
            ("2025 1099-INT", "1099-INT Tax Form"),
            ("Form 1099-R", "1099-R Tax Form"),
            ("1098 Mortgage Interest", "1098 Tax Form"),
            ("Tax Form Package 2025", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_insurance_documents():
    for title, summary in [
            ("Auto Insurance Policy", "Auto Insurance Policy"),
            ("Homeowners Policy Declarations", "Insurance Declarations"),
            ("Renters Policy Package", "Renters Insurance Policy"),
            ("Insurance ID Card", "Insurance ID Card")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.INSURANCE, (title, cat)


def test_insurance_billing_beats_statement():
    """An insurance BILLING STATEMENT contains 'statement' but must be filed
    under Insurance, not Bank Statements."""
    cat, s, _ = doc_types.classify_document("Auto Insurance Billing Statement", RULES)
    assert cat == doc_types.INSURANCE, (cat, s)


def test_declarations_page():
    cat, s, _ = doc_types.classify_document("Policy Declarations Page", RULES)
    assert cat == doc_types.INSURANCE and s == "Insurance Declarations"


def test_skip_patterns():
    assert doc_types.should_skip("Privacy Notice", RULES)
    assert doc_types.should_skip("Electronic Communication Consent", RULES)
    assert not doc_types.should_skip("Checking Statement", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document", "Insurance Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.INSURANCE, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome Kit", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_mmddyyyy_exact():
    assert site.parse_period_date("Statement 01/15/2025")[0] == "2025-01-15"


def test_year_only():
    assert site.parse_period_date("2025 1099-INT")[0] == "2025-12-31"


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Checking Statement", "") == \
        "2025-12-31 Navy Federal Checking Statement.pdf"


def test_insurance_filename():
    assert build_pdf_filename("2025-06-30", "Auto Insurance Policy", "") == \
        "2025-06-30 Navy Federal Auto Insurance Policy.pdf"


# -- SAFETY: the read-only bank guard -------------------------------------

def test_money_and_account_actions_are_never_safe():
    for label in ["Transfer", "Transfer money", "Send with Zelle", "Zelle",
                  "Pay bills", "Bill Pay", "Make a payment", "Schedule payment",
                  "Deposit", "Mobile deposit", "Withdraw", "Wire transfer",
                  "Buy", "Sell", "Trade", "Apply now", "Open an account",
                  "Get a quote", "Dispute a charge", "Report fraud",
                  "Lock card", "Activate card", "File a claim", "Start a claim",
                  "Cancel policy", "Renew policy", "Add payee", "Order checks",
                  "Change beneficiary", "Update address", "Continue", "Submit",
                  "Confirm", "Agree", "Accept", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_actions_are_safe():
    for label in ["Download", "Download PDF", "View statement", "View document",
                  "Open PDF", "Save", "View 1099", "Download declarations",
                  "View policy documents"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")
