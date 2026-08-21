"""Ally document classification + the READ-ONLY (bank) safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import ally_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_bank_statements():
    for title, summary in [
            ("Interest Checking Statement", "Interest Checking Statement"),
            ("Online Savings Statement - December 2025", "Online Savings Statement"),
            ("Money Market Statement", "Money Market Statement"),
            ("Spending Account Statement", "Spending Account Statement"),
            ("Monthly Statement", "Monthly Statement")]:
        cat, s, conf = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_cd_and_ira_statements():
    for title, summary in [
            ("CD Statement", "CD Statement"),
            ("Certificate of Deposit - 12 Month", "CD Statement"),
            ("IRA Statement 2025", "IRA Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms():
    for title, summary in [
            ("2025 1099-INT", "1099-INT Tax Form"),
            ("Form 1099-MISC", "1099-MISC Tax Form"),
            ("1099-R Distribution", "1099-R Tax Form"),
            ("5498 IRA Contribution Information", "5498 Tax Form"),
            ("Tax Form Package 2025", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_tax_beats_statement():
    """A 1099-INT names an account and a year; it must file under Tax, not
    Statements."""
    cat, _, _ = doc_types.classify_document(
        "1099-INT for Online Savings 2025", RULES)
    assert cat == doc_types.TAX


def test_skip_patterns():
    assert doc_types.should_skip("Privacy Notice", RULES)
    assert doc_types.should_skip("Electronic Communication Consent", RULES)
    assert doc_types.should_skip("Deposit Agreement", RULES)
    assert doc_types.should_skip("Fee Schedule", RULES)
    assert not doc_types.should_skip("Interest Checking Statement", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
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
    assert build_pdf_filename("2025-12-31", "Online Savings Statement", "") == \
        "2025-12-31 Ally Online Savings Statement.pdf"


def test_tax_filename():
    assert build_pdf_filename("2025-12-31", "1099-INT Tax Form", "") == \
        "2025-12-31 Ally 1099-INT Tax Form.pdf"


# -- SAFETY: the read-only bank guard -------------------------------------

def test_money_and_account_actions_are_never_safe():
    for label in ["Transfer", "Transfer money", "Send with Zelle", "Zelle",
                  "Pay bills", "Bill Pay", "Make a payment", "Schedule payment",
                  "Deposit", "Mobile deposit", "Withdraw", "Wire transfer",
                  "Buy", "Sell", "Trade", "Apply now", "Open an account",
                  "Get a quote", "Dispute a charge", "Report fraud",
                  "Lock card", "Activate card", "Add payee", "Order checks",
                  "Change beneficiary", "Update address", "Continue", "Submit",
                  "Confirm", "Agree", "Accept", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_ally_specific_actions_are_never_safe():
    """Controls unique to Ally Bank's portal that move money, change a
    product, or alter a setting."""
    for label in ["Create a bucket", "Edit buckets", "Enable round ups",
                  "Turn on Surprise Savings", "Boost your savings",
                  "Set up recurring transfer", "Renew CD", "Roll over CD",
                  "Close account", "Early withdrawal", "Go paperless",
                  "Manage delivery preferences", "Allocate to a goal",
                  "Link an external account", "Open a new savings account"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_actions_are_safe():
    for label in ["Download", "Download PDF", "View statement", "View document",
                  "Open PDF", "Save", "View 1099", "Download 1099-INT",
                  "Download statement", "View tax form", "Statement PDF"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


# -- SAFETY: dropdowns are controls too -----------------------------------
#
# Regression test for a real find. On 2026-08-18 the first live probe landed on
# Ally's dashboard instead of the statements page, and the account-picker
# lookup matched the money-TRANSFER widget's <select id="fromAccount">, then
# tried to set it. Nothing was submitted, but selecting an option in a transfer
# form is not read-only behaviour. Dropdowns are now identity-checked.

def test_transfer_widget_selects_are_refused():
    """The exact identities Ally's transfer widget presents."""
    for identity in [
            "fromAccount | fromAccount | Select an Account",
            "toAccount | toAccount | Select an Account",
            "id | name | aria-label | Transfer money | met-dashboard__card",
            "amount | Amount | Transfer",
            "frequency | How often | Schedule a transfer",
            "payee | Select a payee | Bill Pay",
            "zelleRecipient | Recipient | Send money with Zelle",
            "depositAccount | Deposit to | Remote deposit"]:
        assert site.is_money_control(identity), identity


def test_statement_pickers_are_allowed():
    """A genuine statements picker must still be usable, or the app cannot
    walk the account/year history at all."""
    for identity in [
            "accountSelect | Select account | Statements",
            "statement-year | Year | Statements & documents",
            "documentYear | Choose a year | Documents",
            "taxYear | Tax year | Tax forms"]:
        assert not site.is_money_control(identity), identity


def test_unreadable_identity_fails_closed():
    """If we cannot tell what a control is, we do not touch it."""
    assert site.is_money_control("")
    assert site.is_money_control(None or "")


# -- the statements API ---------------------------------------------------
#
# Shape confirmed live 2026-08-18 from
#   GET https://secure.ally.com/acs/v1/bank-statements
#   {"statements": [{iraType, documentId, trustName, documentName, uploadDate}]}
# The ids and names below are INVENTED - only the field names and the shape are
# real. Never paste a live documentId or account name into a fixture.

def test_api_record_is_normalized():
    rec = site._normalize_api_statement({
        "iraType": False,
        "documentId": "10000000000000000000000000000001",
        "trustName": "Pat Q Sample and Alex R Example",
        "documentName": "Statement",
        "uploadDate": "2025-12-16T01:00:00-05:00"})
    assert rec["date"] == "2025-12-16"
    assert rec["documentId"] == "10000000000000000000000000000001"
    assert rec["title"] == "Statement"
    # the registration name is kept verbatim for re-finding the row...
    assert rec["account"] == "Pat Q Sample and Alex R Example"
    # ...and with nothing mapped, the label is that same name - not a guess
    assert rec["label"] == "Pat Q Sample and Alex R Example"


def test_registration_label_is_never_inferred_from_the_name():
    """Regression test. An earlier version read "and"/"&" as Joint and
    everything else as Individual - which silently mislabels a TRUST
    registration, since "Sample Family Trust" contains neither. A wrong label
    is worse than a long one: it is not obviously wrong on the shelf.
    """
    for name in ["Sample Family Trust",
                 "Pat Q Sample Revocable Living Trust",
                 "Pat Q Sample and Alex R Example",
                 "Pat Q Sample"]:
        assert site.account_label(name) == name, name


def test_registration_label_uses_your_mapping():
    labels = {"Sample Family Trust": "Trust",
              "Pat Q Sample and Alex R Example": "Joint"}
    assert site.account_label("Sample Family Trust", labels=labels) == "Trust"
    assert site.account_label("Pat Q Sample and Alex R Example",
                              labels=labels) == "Joint"
    # unmapped stays verbatim rather than falling back to a guess
    assert site.account_label("Pat Q Sample", labels=labels) == "Pat Q Sample"


def test_ira_flag_is_allys_own_and_yields_to_your_mapping():
    """iraType comes from the API, so it is trustworthy - but an explicit
    mapping still wins."""
    assert site.account_label("Pat Q Sample", ira_type=True) == "IRA"
    assert site.account_label("Pat Q Sample", ira_type=True,
                              labels={"Pat Q Sample": "My IRA"}) == "My IRA"
    assert site.account_label("") == ""


def test_api_record_without_a_usable_date_is_dropped():
    assert site._normalize_api_statement(
        {"documentId": "x", "documentName": "Statement", "uploadDate": ""}) is None


def test_api_record_defaults_a_missing_name():
    rec = site._normalize_api_statement(
        {"documentId": "x", "uploadDate": "2025-03-16T01:00:00-04:00"})
    assert rec["title"] == "Statement"


def test_statements_api_url_is_recognized():
    assert site.STATEMENTS_API_RE.search("https://secure.ally.com/acs/v1/bank-statements")
    assert site.STATEMENTS_API_RE.search(
        "https://secure.ally.com/acs/v1/bank-statements?year=2025")
    assert not site.STATEMENTS_API_RE.search("https://secure.ally.com/acs/v1/transfers")


def test_ambiguous_statements_are_numbered_not_named():
    """Ally posts several statements per date with NO registration, identical
    documentName and identical row labels - they differ only by documentId.
    Discovery must number them (so the downloader can aim at one) and flag
    them, never invent an account for them.
    """
    raw = [
        {"documentId": "aaa1", "trustName": "Sample Family Trust",
         "documentName": "Statement", "uploadDate": "2025-06-16T01:00:00-04:00"},
        {"documentId": "bbb2", "documentName": "Statement",
         "uploadDate": "2025-06-16T01:00:00-04:00"},
        {"documentId": "ccc3", "documentName": "Statement",
         "uploadDate": "2025-06-16T01:00:00-04:00"},
    ]
    recs = [site._normalize_api_statement(r) for r in raw]
    plain = [r for r in recs if not r["account"]]
    # numbering is applied by the collector; emulate its grouping step
    for i, r in enumerate(plain):
        r["occurrence"], r["ambiguous"] = i, len(plain) > 1
    assert [r["occurrence"] for r in plain] == [0, 1]
    assert all(r["ambiguous"] for r in plain)
    # the trust one is identified, and is not part of the ambiguous set
    trust = [r for r in recs if r["account"]]
    assert len(trust) == 1
    assert trust[0]["label"] == "Sample Family Trust"
    assert trust[0]["ambiguous"] is False


def test_date_needles_cover_the_row_formats():
    needles = site._date_needles("2026-08-16")
    assert "8/16/2026" in needles
    assert "08/16/2026" in needles
    assert "August 16, 2026" in needles
    assert "2026-08-16" in needles


# -- reading a statement PDF ----------------------------------------------
#
# Ally describes several statements per date identically, so what a PDF covers
# is only knowable from the PDF. These parse Ally's first-page layout. The
# fixture is synthetic - a real statement must never be committed - and it is
# deliberately generic: the parser must not know any account nickname.

STATEMENT_PAGE = """
          Ally Bank
          P.O. Box 951
          Philadelphia, PA 19105-0951

          0000/0000//0000/0000/0000/0000 000 01 00000
          PAT Q SAMPLE
          123 EXAMPLE ST
          SOMETOWN IL 60600-0000
                                            CUSTOMER STATEMENT
    Account Name                             Account Number        Beginning
    Everyday Checking                                     xxxxxx1234
    Rainy Day Savings                                     xxxxxx5678
    Total Account Balances:
"""


def test_reads_accounts_and_addressee():
    facts = site.parse_statement_text(STATEMENT_PAGE)
    assert facts.ok
    assert facts.accounts == [("Everyday Checking", "1234"),
                              ("Rainy Day Savings", "5678")]
    assert facts.addressee == "PAT Q SAMPLE"
    assert facts.account_summary() == "Everyday Checking + Rainy Day Savings"


def test_single_account_customer():
    page = STATEMENT_PAGE.replace(
        "    Rainy Day Savings                                     xxxxxx5678\n", "")
    facts = site.parse_statement_text(page)
    assert facts.accounts == [("Everyday Checking", "1234")]
    assert facts.account_summary() == "Everyday Checking"


def test_many_accounts_are_summarized_not_truncated_midname():
    page = STATEMENT_PAGE.replace(
        "    Total Account Balances:",
        "    Third Account Here                                    xxxxxx9012\n"
        "    Fourth Account Here                                   xxxxxx3456\n"
        "    Total Account Balances:")
    facts = site.parse_statement_text(page)
    assert len(facts.accounts) == 4
    assert facts.account_summary(40).endswith("+3 more")


def test_rows_outside_the_table_are_ignored():
    """A masked number elsewhere on the page is not an account row."""
    page = STATEMENT_PAGE.replace(
        "                                            CUSTOMER STATEMENT",
        "    Your card  xxxxxx9999 was mailed\n"
        "                                            CUSTOMER STATEMENT")
    facts = site.parse_statement_text(page)
    assert ("Your card", "9999") not in facts.accounts
    assert len(facts.accounts) == 2


def test_unrecognised_layout_returns_nothing_rather_than_guessing():
    for junk in ("", "no table here at all", "Account Name Account Number"):
        assert not site.parse_statement_text(junk).ok


def test_addressee_is_title_cased_only_when_shouting():
    assert site.normalize_name("PAT Q SAMPLE") == "Pat Q Sample"
    assert site.normalize_name("PAT SAMPLE AND ALEX EXAMPLE") == \
        "Pat Sample and Alex Example"
    # already-cased names are left alone
    assert site.normalize_name("Pat McTavish") == "Pat McTavish"
    assert site.normalize_name("O'Neil-Smith") == "O'Neil-Smith"
    assert site.normalize_name("") == ""


# -- tax forms ------------------------------------------------------------
#
# The statements API takes docType=STATEMENTS, so a sibling value serves the
# forms. Rather than hardcode a guess, the app opens the page's own tax tab and
# reads whatever the SPA calls - so these check the TOLERANT parsing, which is
# what makes that possible.

def test_finds_the_document_array_under_any_key():
    for key in ("taxForms", "documents", "forms", "somethingNew"):
        payload = {key: [{"documentId": "a1", "documentName": "1099-INT",
                          "taxYear": 2025}]}
        found_key, items = site._find_doc_list(payload)
        assert found_key == key and len(items) == 1


def test_ignores_responses_with_no_document_array():
    for payload in ({}, {"count": 0}, {"statements": []}, {"x": ["a", "b"]}):
        assert site._find_doc_list(payload) == (None, [])


def test_tax_year_files_on_the_last_day_of_that_year():
    rec = site._normalize_tax_record(
        {"documentId": "t1", "documentName": "1099-INT", "taxYear": 2025})
    assert rec["date"] == "2025-12-31"
    assert rec["title"] == "1099-INT"
    assert rec["kind"] == "tax"


def test_tax_year_beats_the_posting_date():
    """Ally issues the 2025 form in January 2026. It must file under 2025 -
    an archive where the 2025 1099 sits in 2026 is wrong at tax time. This is
    the real shape from the live API."""
    rec = site._normalize_tax_record(
        {"corrected": False, "documentId": "t2", "documentName": "Form 1099-INT",
         "iraType": False, "taxYear": 2025,
         "uploadDate": "2026-01-10T01:00:00-05:00"})
    assert rec["date"] == "2025-12-31"


def test_posting_date_is_used_when_there_is_no_tax_year():
    rec = site._normalize_tax_record(
        {"documentId": "t2b", "formName": "1099-MISC",
         "uploadDate": "2026-01-31T01:00:00-05:00"})
    assert rec["date"] == "2026-01-31"


def test_corrected_forms_are_flagged():
    plain = site._normalize_tax_record(
        {"documentId": "t6", "documentName": "Form 1099-INT", "taxYear": 2025,
         "corrected": False})
    fixed = site._normalize_tax_record(
        {"documentId": "t7", "documentName": "Form 1099-INT", "taxYear": 2025,
         "corrected": True})
    assert plain["corrected"] is False and fixed["corrected"] is True
    # same year, same form: the flag is what keeps them apart on disk
    assert plain["date"] == fixed["date"]


def test_tax_record_tolerates_renamed_fields():
    rec = site._normalize_tax_record(
        {"id": "t3", "formType": "1099-INT", "year": "2024"})
    assert rec["documentId"] == "t3" and rec["date"] == "2024-12-31"


def test_undatable_tax_record_is_skipped_not_guessed():
    assert site._normalize_tax_record({"documentId": "t4"}) is None


def test_a_tax_form_classifies_as_tax_not_statement():
    rec = site._normalize_tax_record(
        {"documentId": "t5", "documentName": "1099-INT", "taxYear": 2025})
    cat, summary, _ = doc_types.classify_document(rec["title"], RULES)
    assert cat == doc_types.TAX and summary == "1099-INT Tax Form"


def test_tax_tab_label_clears_the_readonly_guard():
    for label in ("Tax Forms", "Tax Documents", "Tax Information"):
        assert site.TAX_TAB_RE.match(label), label
        assert site.is_safe_control(label), label


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
