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
    for label in ["Download", "View Statement", "Open PDF", "Print",
                  "1098 Tax Form", "eStatement", "View Document",
                  "Escrow Statement", "Year-End Statement", "Download PDF"]:
        assert site.is_safe_control(label), label


def test_bare_save_is_refused_on_purpose():
    """"Save" used to be an allowed document action. On a portal that can move
    money a bare "Save" is far more likely to commit a settings change than to
    save a PDF, and "Save Changes" slipped through because of it. The real
    document controls all say download / view / open / print / pdf."""
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label


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


# -- SAFETY: what a review of the live code actually found --------------------
# Each test below pins a real defect that existed and was fixed. They are the
# regression net for the ways this app could quietly hurt someone.

def test_a_crafted_on_host_url_is_not_treated_as_a_document():
    """The endpoint used to be matched as a SUBSTRING of the whole URL, so a
    payment route carrying the endpoint name as a query parameter passed the
    host allowlist and would have been fetched with the live session cookie.
    The path is what decides now."""
    evil = ("https://onlinebanking.mtb.com/Payments/SchedulePayment"
            "?FetchStatementandNotices=1&dt=06/01/2026&amount=5000")
    assert site.is_safe_url(evil)          # it IS on an M&T host
    assert site._endpoint_of(evil) is None  # but it is NOT a document endpoint
    for other in ["https://onlinebanking.mtb.com/redirect?url=https://evil.test",
                  "https://onlinebanking.mtb.com/Session/Logoff?FetchTaxDocument=1",
                  "https://evil.test/Statements/FetchStatementandNotices",
                  ""]:
        assert site._endpoint_of(other) is None, other


def test_the_real_document_endpoints_still_resolve():
    assert site._endpoint_of(
        "https://onlinebanking.mtb.com/Statements/FetchStatementandNotices"
        "?t=MTGSTMT&a=1&dt=07/31/2026&stmtId=abc") == "statement"
    assert site._endpoint_of(
        "https://m.mtb.com/TaxDocuments/FetchTaxDocument?documentkey=abc") == "tax"


def test_only_mt_frames_are_read_or_clicked():
    """The collector walks every tab in the user's ordinary browser. Reading
    links out of - or clicking inside - an unrelated site is not acceptable."""
    class F:
        def __init__(self, url): self.url = url
    assert site.is_mt_frame(F("https://onlinebanking.mtb.com/Statements/x"))
    assert site.is_mt_frame(F("https://m.mtb.com/TaxDocuments/x"))
    for bad in ["https://mail.google.com/", "about:blank", "",
                "http://onlinebanking.mtb.com/x",
                "https://onlinebanking.mtb.com.evil.test/x"]:
        assert not site.is_mt_frame(F(bad)), bad


def test_settings_and_money_labels_that_once_slipped_through():
    """Every one of these passed is_safe_control before the verb families and
    settings words were added."""
    for label in ["Save Changes", "Request Payoff Statement", "Payoff Statement",
                  "Download Loss Mitigation Application", "Open Escrow Options",
                  "Save Paperless Settings", "Print check",
                  "Document Removal - save", "Statement Delivery Changes - Save",
                  "Enroll", "Consent", "Opt In", "Opt Out", "Turn off",
                  "Defer", "Close Account", "Add Bank Account",
                  "One-Time Payment", "Schedule a payment", "Manage AutoPay"]:
        assert not site.is_safe_control(label), label


def test_a_signin_page_returned_instead_of_a_pdf_is_recognised():
    """M&T answers an expired session with HTTP 200 and an HTML login page. If
    that is not spotted, every remaining document is filed as 'manual review'
    and the run ends looking successful with nothing saved."""
    assert site._looks_like_login_html(
        b"<!DOCTYPE html><html><body><form><input type=\"password\"></form>")
    assert site._looks_like_login_html(b"<html>Your session has expired</html>")
    assert not site._looks_like_login_html(b"%PDF-1.7 real document")
    assert not site._looks_like_login_html(b"")


def test_empty_href_does_not_fetch_the_home_page():
    """_abs('') used to return the bare host, which passed the host check and
    silently downloaded M&T's home page."""
    assert site._abs("") == ""
    assert site._endpoint_of(site._abs("")) is None


def test_tax_year_is_the_tax_year_not_the_availability_date():
    assert site._tax_year(
        "Available 01/15/2026 1098 Mortgage Interest Statement for 2025", "") == "2025"
    # account suffix here is a placeholder, never a real one
    assert site._tax_year("2025 1098 Mortgage Interest Statement (1234)", "") == "2025"
    assert site._tax_year("no year here", "2024") == "2024"


def test_the_cloned_navy_federal_machinery_is_gone():
    """Four of those functions clicked page controls with no safety check, one
    rebuilt a stale deep link, and one would have re-armed a wrong-document
    bug. Dead code near a mortgage is a loaded gun."""
    src = (Path(__file__).resolve().parents[1] / "mtb_site.py").read_text(encoding="utf-8")
    for gone in ("def collect_documents", "def collect_documents_via_api",
                 "def download_by_id", "def download_document_row",
                 "def _find_doc_row", "def document_deeplink",
                 "def next_page", "def expand_all", "def scroll_full_page",
                 "readDocument-", "blob:"):
        assert gone not in src, gone


def test_unknown_statement_types_are_not_called_mortgage_statements():
    """The page also lists notices and analysis statements. An unrecognised
    t= used to be labelled "Mortgage Statement", which would file a notice
    under a name that is not true."""
    import mtb_site
    assert mtb_site._STMT_TYPE.get("MTGSTMT") == "Mortgage Statement"
    assert mtb_site._STMT_TYPE.get("YESTMT") == "Year-End Statement"
    assert mtb_site._STMT_TYPE.get("NOTICE") is None
    src = (Path(__file__).resolve().parents[1] / "mtb_site.py").read_text(encoding="utf-8")
    assert '_STMT_TYPE.get(kind) or' in src, "unknown types must not default to a statement"
