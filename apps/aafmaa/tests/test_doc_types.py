"""AAFMAA document classification + the READ-ONLY safety guard.

The classification cases are provisional: they encode what the rules file
currently expects, and should be re-pointed at real Member Center titles once
diagnose has run. The SAFETY cases are not provisional - they are the reason
this app is allowed to touch an account that can pay premiums and take loans.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import aafmaa_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_premium_and_billing_statements():
    for title, summary in [
            ("Premium Statement", "Premium Statement"),
            ("Premium Notice - March 2026", "Premium Statement"),
            ("Billing Statement", "Billing Statement"),
            ("Loan Statement", "Loan Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_insurance_documents():
    for title, summary in [
            ("Certificate of Insurance", "Certificate of Insurance"),
            ("Policy Document", "Policy Document"),
            ("Coverage Summary", "Coverage Summary"),
            ("Survivor Assistance Checklist", "Survivor Assistance Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.INSURANCE, title
        assert s == summary, (title, s)


def test_annual_statement_is_a_year_end_summary():
    """Checked before the statement rules on purpose - an annual statement
    says "statement" but belongs with the year-end paperwork."""
    cat, s, _ = doc_types.classify_document("2025 Annual Statement", RULES)
    assert cat == doc_types.YEAR_END
    assert s == "Annual Statement"


def test_tax_forms():
    for title, summary in [
            ("1099-INT", "1099-INT Tax Form"),
            ("Form 1099-R", "1099-R Tax Form"),
            ("2025 Tax Document", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_boilerplate_is_skipped():
    for t in ["Privacy Notice", "Terms of Use", "Membership Brochure"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Premium Statement", RULES)


def test_no_foreign_vocabulary_leaked_from_the_app_this_was_cloned_from():
    """This app began as a copy of the USAA one. A clone that keeps the old
    provider's rules quietly classifies documents the new provider never
    issues - which is exactly what happened to the Dominion app for months."""
    for title in ["Checking Account Statement", "Savings Statement",
                  "Auto Insurance Declarations", "Credit Card Statement"]:
        _, summary, _ = doc_types.classify_document(title, RULES)
        for word in ("Checking", "Savings", "Auto", "Credit Card"):
            assert word not in summary, (title, summary)


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Premium Statement March 2026")[0] == "2026-03-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-03-31", "Premium Statement", "") == \
        "2026-03-31 AAFMAA Premium Statement.pdf"


# -- SAFETY: this portal can pay premiums and take policy loans -----------

def test_money_moving_controls_are_never_safe():
    """Every one of these is advertised on the Member Center's own front page
    or is one click from it. None may ever be activated."""
    for label in ["Pay Premiums", "Pay Now", "Make a Payment", "Payment History",
                  "Check Loan Balances", "Request a Loan", "Loan Repayment",
                  "Surrender Policy", "Withdraw Cash Value", "Enroll in AutoPay",
                  "Update Contact Information", "Update Family Information",
                  "Change Beneficiary", "Add Bank Account", "Apply Now",
                  "Cancel Coverage", "Edit", "Submit", "Confirm", "Transfer",
                  "Authorize", "Accept"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download PDF", "View Statement", "Open PDF",
                  "Print", "View Policy Document",
                  "Certificate of Insurance", "Premium Statement",
                  "Annual Statement", "1099-INT", "Digital Vault",
                  "View Correspondence", "Download e-Statement"]:
        assert site.is_safe_control(label), label


def test_deny_by_default():
    """Anything unrecognised is refused - clearing the blocklist is not
    enough, a control must also look like a document action."""
    for label in ["", "More", "Continue", "Next", "Options", "Help",
                  "Go", "Select", "Details"]:
        assert not site.is_safe_control(label), label


# -- SAFETY: the one dialog this project answers --------------------------

REAL_DISCLOSURE = (
    "Please Confirm Downloading X.pdf The document that you are accessing "
    "contains personal and confidential information. If you are using a "
    "private computer and would like to view your document on the Member "
    "Center, please click on the Download button. I confirm that I have read "
    "the message above and understand the potential risk. View Cancel")


def test_the_real_disclosure_is_recognised():
    assert site.is_view_disclosure(REAL_DISCLOSURE)


def test_any_money_word_disqualifies_the_dialog():
    for word in ("payment", "premium", "transfer", "beneficiary",
                 "surrender", "withdraw", "loan", "autopay"):
        assert not site.is_view_disclosure(REAL_DISCLOSURE + " " + word), word


def test_other_dialogs_are_never_the_disclosure():
    for text in ("Are you sure you want to log out?",
                 "Confirm your changes", "Session expiring, stay signed in?",
                 ""):
        assert not site.is_view_disclosure(text), text


def test_a_bare_save_is_refused_on_purpose():
    """"Save" used to count as a document action here. On a site that can move
    money it is far more likely to commit a settings change, and allowing it
    was why "Save Changes" passed the guard. "Save PDF" still passes, because
    that one names the document."""
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label
