"""Chase document classification + the READ-ONLY (credit card) safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import chase_site as site
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
    rather than half-collected. Chase tax documents are out of scope."""
    for title, summary in [
            ("2025 1099-MISC", "1099-MISC Tax Form"),
            ("Form 1099-C Cancellation of Debt", "1099-C Tax Form"),
            ("Tax Form Package 2025", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_card_paperwork_is_skipped():
    """Chase posts agreements and change-in-terms notices alongside
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
        "2026-03-15 Chase Credit Card Statement.pdf"


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
    for label in ["Redeem rewards", "Redeem points", "Book travel",
                  "Balance transfer", "Cash advance", "My Chase Plan",
                  "My Chase Loan", "Request credit line increase",
                  "Increase my credit limit", "Add authorized user",
                  "Activate card", "Lock card", "Freeze card",
                  "Replace card", "Close account", "Dispute a charge",
                  "Report fraud", "Apply now", "Shop through Chase",
                  "Pay yourself back", "Go paperless", "Update address",
                  "Change username", "Submit", "Confirm", "Authorize"]:
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


def test_row_label_re_matches_chase_row_names():
    """A row names itself completely: date, type, card, action."""
    rx = site.row_label_re("2026-08-09", "SAPPHIRE RESERVE (...1234)")
    assert rx.search("Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234) Saves document")
    assert rx.search("Aug 9, 2026 Statement SAPPHIRE RESERVE (...1234) Saves document")
    # a different card, or a different day, on the same date is not it
    assert not rx.search("Aug 09, 2026 Statement FREEDOM (...5678) Saves document")
    assert not rx.search("Aug 19, 2026 Statement SAPPHIRE RESERVE (...1234) Saves document")


def test_row_name_re_reads_a_row():
    m = site.ROW_NAME_RE.search(
        "Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234) Saves document")
    assert m and m.group("card").strip() == "SAPPHIRE RESERVE (...1234)"
    assert m.group("type").strip() == "Statement"


def test_card_headers_are_the_only_non_document_control_allowed():
    assert site.is_card_control("FREEDOM (...5678)")
    assert site.is_card_control("SAPPHIRE RESERVE (...1234)")
    assert not site.is_card_control("Pay card")
    assert not site.is_card_control("Pay FREEDOM (...5678)")
    assert not site.is_card_control("Activate card (...5678)")
    assert not site.is_card_control("")


# -- SAFETY: controls inside a sign-in form ------------------------------
#
# Found on the Discover app and backported here. A first probe missed every
# guessed URL, landed on the provider's PUBLIC site, and the account-picker
# lookup matched the marketing page's "what do you want to log into" dropdown
# and set a value on it. Nothing was submitted and no credential was touched,
# but selecting inside a login form is not reading, and this app only reads.
# The enclosing form's id was already in the identity string the guard reads.

SIGNIN_IDENTITIES = [
    "whatDoYouWantToLogInto | login-form | Log in",
    "signin-form | Register | Create an account",
    "loginType | universalLogin | Sign On",
    "username | login | Password",
    "enrollment-form | Enroll now",
    "remember me | sign-up",
]

DOCUMENT_IDENTITIES = [
    "year | statement-year | Statements | Select year",
    "documentYear | Documents | View",
    "stmt-period | Statement period",
]


def test_a_control_in_a_signin_form_is_never_touched():
    for identity in SIGNIN_IDENTITIES:
        assert site.is_forbidden_control_context(identity), identity


def test_a_real_document_picker_still_works():
    """The guard must not be so broad that it refuses the pickers this app
    needs, or discovery quietly returns nothing."""
    for identity in DOCUMENT_IDENTITIES:
        assert not site.is_forbidden_control_context(identity), identity


def test_an_unreadable_identity_fails_closed():
    assert site.is_forbidden_control_context("")
    assert site.is_forbidden_control_context(None or "")


def test_money_widgets_are_still_refused():
    for identity in ("fromAccount | transfer-form | Transfer money",
                     "payee | billpay", "amount | send money"):
        assert site.is_forbidden_control_context(identity), identity


def test_a_bare_save_is_refused_on_purpose():
    """"Save" used to count as a document action here. On a site that can move
    money it is far more likely to commit a settings change, and allowing it
    was why "Save Changes" passed the guard. "Save PDF" still passes, because
    that one names the document."""
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label
