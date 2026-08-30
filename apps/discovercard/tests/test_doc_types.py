"""Discover document classification + the READ-ONLY (credit card) safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import discovercard_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_card_statements():
    for title, summary in [
            ("Credit Card Statement", "Credit Card Statement"),
            ("Billing Statement - March 2026", "Billing Statement"),
            ("Monthly Statement", "Monthly Statement"),
            ("Statement", "Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms_classify_but_are_out_of_scope():
    """The rules still recognise a stray 1099 so it is never filed as a
    statement - but document_types lists Statement only, so it is skipped
    rather than half-collected. Discover tax documents are out of scope."""
    for title, summary in [
            ("2025 1099-MISC", "1099-MISC Tax Form"),
            ("Form 1099-C Cancellation of Debt", "1099-C Tax Form"),
            ("Tax Form Package 2025", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_card_paperwork_is_skipped():
    """Discover posts agreements and change-in-terms notices alongside
    statements; they are not documents worth archiving."""
    for title in ["Cardmember Agreement", "Change in Terms",
                  "Important Changes to Your Account", "Privacy Notice",
                  "Benefits Guide", "Rewards Program Agreement"]:
        assert doc_types.should_skip(title, RULES), title
    assert not doc_types.should_skip("Credit Card Statement", RULES)


def test_only_statements_are_in_scope():
    cfg = {"document_types": ["Statement"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert not doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, _, conf = doc_types.classify_document("Welcome Kit", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_mmddyyyy_exact():
    assert site.parse_period_date("Statement 01/15/2025")[0] == "2025-01-15"


def test_filename():
    assert build_pdf_filename("2026-03-15", "Credit Card Statement", "") == \
        "2026-03-15 Discover Credit Card Statement.pdf"


# -- SAFETY: the read-only guard, tuned for a credit card -----------------

def test_money_actions_are_never_safe():
    for label in ["Pay card", "Make a payment", "Schedule payment", "Autopay",
                  "Pay bills", "Transfer", "Send money with Zelle", "Zelle",
                  "Wire transfer", "Deposit", "Withdraw"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_card_specific_actions_are_never_safe():
    """The controls a card portal puts next to the statements: offers,
    rewards, borrowing against the card, and account changes."""
    for label in [
            # Discover's own names, which a generic card vocabulary misses
            "Redeem Cashback Bonus", "Cashback Bonus", "Redeem Miles",
            "Freeze it", "Freeze It", "Discover Deals", "Refer a Friend",
            "Credit Scorecard", "Spend Analyzer", "Shop with Discover",
            # generic card actions
            "Redeem rewards", "Redeem points", "Book travel",
            "Balance transfer", "Cash advance",
            "Request credit line increase", "Increase my credit limit",
            "Add authorized user", "Activate card", "Lock card",
            "Replace card", "Close account", "Dispute a charge",
            "Report fraud", "Report lost or stolen", "Apply now",
            # money movement and settings
            "Pay bill", "Make a payment", "Set up AutoPay",
            "Go paperless", "Update address", "Change username",
            "Submit", "Confirm", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_actions_are_safe():
    for label in ["Download", "Download PDF", "View statement",
                  "Download statement", "View document", "Open PDF", "View 1099", "Statement PDF", "View tax form"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


# -- SAFETY: dropdowns are controls too -----------------------------------
#
# Carried over from the Ally app, where the first live probe landed on the
# dashboard and the account-picker lookup matched a money-TRANSFER widget's
# <select>, then tried to set it. A card dashboard has the same hazard: a
# "pay from" account picker looks exactly like a statement-period picker.

def test_payment_widget_selects_are_refused():
    for identity in [
            "fromAccount | fromAccount | Select an account",
            "payFromAccount | Pay from | Make a payment",
            "amount | Amount | Payment",
            "paymentAmount | How much | Pay card",
            "payee | Select a payee | Bill Pay",
            "transferTo | To | Balance transfer"]:
        assert site.is_money_control(identity), identity


def test_statement_pickers_are_allowed():
    """A genuine document picker must still work, or the app cannot walk the
    card/period history at all."""
    for identity in [
            "statementPeriod | Statement period | Statements",
            "documentYear | Year | Statements & documents",
            "cardSelector | Choose a card | Documents",
            "taxYear | Tax year | Tax forms"]:
        assert not site.is_money_control(identity), identity


def test_unreadable_identity_fails_closed():
    assert site.is_money_control("")


def test_statement_pdf_re_reads_the_closing_date():
    """The confirmed download URL: the page's own statement link."""
    href = "/cardmembersvcs/statements/app/stmtPDF?view=true&date=20250115"
    m = site.STMT_PDF_RE.search(href)
    assert m and m.group(1) == "20250115"
    assert site._iso_from_yyyymmdd(m.group(1)) == "2025-01-15"


def test_statement_pdf_re_refuses_other_urls():
    """discovercard_download re-checks the stored URL before fetching it, so a
    stored value can never send the fetch somewhere else."""
    for href in ["/cardmembersvcs/statements/app/search",
                 "/cardmembersvcs/payments/app/pay?date=20250115",
                 "https://evil.example/stmtPDF?date=20250115",
                 "/cardmembersvcs/statements/app/stmtPDF?view=true"]:
        assert not site.STMT_PDF_RE.search(href), href


def test_statement_url_must_stay_on_discovers_host():
    """The fetch carries the signed-in session's cookies, so the URL guard
    parses and compares scheme+host rather than trusting a string prefix.
    Review of this app fetched from evil.test through the old
    startswith("http") check; both of those probes are pinned here."""
    rel = "/cardmembersvcs/statements/app/stmtPDF?view=true&date=20250115"
    assert site.resolve_statement_url(rel) == site.BASE + rel
    absolute = site.BASE + rel
    assert site.resolve_statement_url(absolute) == absolute
    for href in [
            "https://evil.test/cardmembersvcs/statements/app/stmtPDF?date=20250115",
            "https://card.discover.com.evil.test/statements/app/stmtPDF?date=20250115",
            "https://card.discover.com@evil.test/statements/app/stmtPDF?date=20250115",
            "http://card.discover.com/cardmembersvcs/statements/app/stmtPDF?date=20250115",
            "//evil.test/statements/app/stmtPDF?date=20250115",
            "javascript:fetch('/statements/app/stmtPDF?date=20250115')"]:
        assert site.resolve_statement_url(href) is None, href


def test_period_label_re_reads_both_forms():
    for row, want in [
            ("Mar 16 - Apr 15, 2025 PDF", "Mar 16 - Apr 15, 2025"),
            ("Dec 16, 2024 - Jan 15, 2025 PDF", "Dec 16, 2024 - Jan 15, 2025"),
            ("Current (Apr 16 - May 15, 2025) PDF", "Current (Apr 16 - May 15, 2025)")]:
        m = site.PERIOD_LABEL_RE.search(row)
        assert m, row
        assert m.group(1).strip() == want, (row, m.group(1))


def test_served_last4_reads_the_card_from_the_filename():
    """Discover's Content-Disposition is the only place a single-card login
    states the card's last four digits."""
    cd = "inline; filename=Discover-Statement-20250115-1234.pdf"
    assert site.served_last4(cd) == "1234"
    assert site.served_last4("inline; filename=statement.pdf") == ""
    assert site.served_last4("") == ""


def test_the_pdf_control_clears_the_guard():
    """The statement links are labelled just "PDF"."""
    assert site.is_safe_control("PDF")
    assert site.is_safe_control("View Billing Statement PDF")
    # ...while the neighbouring transactions-export control, which opens a
    # modal dialog, must never be treated as a document action to click.
    assert not site.is_safe_control("Set up AutoPay")


# -- SAFETY: the first live probe tried to set a control on a SIGN-IN form ---
#
# Every guessed URL missed and the app landed on Discover's public 404, where
# the account-picker lookup matched the marketing site's "what do you want to
# log into" dropdown and tried to select in it. Not a money widget, so the
# money test correctly did not fire - and nothing else was asking.

def test_signin_form_controls_are_refused():
    for identity in [
            "choose-card | choose-card | login-form | loginForm | choose-card",
            "userid | User ID | logon-form",
            "cardSelect | Select | signInForm | Log In"]:
        assert site.is_forbidden_control_context(identity), identity


def test_product_pickers_are_refused_by_their_options():
    """Context-free: a product chooser gives itself away wherever it appears."""
    opts = ["Select an Account", "Credit Card", "Bank Account",
            "Student Loans", "Personal Loans", "Home Loans"]
    assert site.is_forbidden_control_context("innocent-looking-id", opts)


def test_forbidden_context_fails_closed_on_an_unreadable_identity():
    assert site.is_forbidden_control_context("")
    assert site.is_forbidden_control_context(None)


def test_a_real_statement_picker_still_passes():
    """Over-blocking would leave the app unable to read anything."""
    for identity in ["statementPeriod | Statement period | Statements",
                     "documentYear | Year | Statements & documents"]:
        assert not site.is_forbidden_control_context(identity, ["2026", "2025"]), identity


def test_signed_out_urls_are_recognised():
    """A live run ended on Discover's logoff page, which matched none of the
    original markers - "universalLogin" does not contain "/login" - so the app
    kept trying instead of saying the session had ended."""
    class FakePage:
        def __init__(self, url): self.url = url
        class _L:
            def count(self): return 0
        def locator(self, _sel): return self._L()
    for url in [
            "https://portal.discover.com/customersvcs/universalLogin/logoff_confirmed#/recent",
            "https://card.discover.com/cardmembersvcs/logout",
            "https://card.discover.com/session-expired"]:
        assert site.looks_signed_out(FakePage(url)), url
    assert not site.looks_signed_out(
        FakePage("https://card.discover.com/cardmembersvcs/statements/app/activity#/recent"))


def test_public_and_error_pages_are_recognised():
    class FakePage:
        def __init__(self, url): self.url = url
    for url in ["https://www.discover.com/discover/data/misc/error404.shtml",
                "https://www.discover.com/credit-cards/index.html",
                "https://card.discover.com/cardmembersvcs/404"]:
        assert site.looks_public_or_error(FakePage(url)), url
    assert not site.looks_public_or_error(
        FakePage("https://card.discover.com/cardmembersvcs/statements/app/activity#/recent"))


def test_a_bare_save_is_refused_on_purpose():
    """"Save" used to count as a document action here. On a site that can move
    money it is far more likely to commit a settings change, and allowing it
    was why "Save Changes" passed the guard. "Save PDF" still passes, because
    that one names the document."""
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label
