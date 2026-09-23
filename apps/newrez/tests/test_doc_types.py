"""Newrez classification, the guard, and the survey's promises.

The site layer is unverified, so what these pin is everything that must be
true before a tester ever runs it: the guard refuses every control that
moves money or changes anything, the survey cannot leak a number, and a
row's date is read in the forms the site is likely to print it in.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds the AppSpec
from paperpull_core import doc_types
import newrez_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Monthly Statement - August 31, 2026', 'Monthly Statement', 'STATEMENT'), ('Mortgage statement', 'Account Statement', 'STATEMENT'), ('Escrow Analysis Statement', 'Escrow Analysis', 'STATEMENT'), ('Form 1098', '1098 Tax Form', 'TAX')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Servicing transfer notice', 'Welcome letter']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 31, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', '', '2026-08-31 Newrez Monthly Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Make a payment', 'Pay now', 'Set up autopay', 'Request payoff', 'Payoff quote', 'Escrow change', 'Hardship assistance', 'Apply for forbearance', 'Loan modification', 'Refinance', 'Upload documents', 'Update address', 'Manage alerts', 'Go paperless', 'Submit', 'Confirm', 'Save Changes', 'Chat with us']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View statement', 'Download statement', 'Statement PDF', '1098', 'Tax documents', 'Escrow analysis', 'See more statements', 'Print']:
        assert site.is_safe_control(label), label


def test_a_document_control_that_also_pays_is_refused():
    for label in ['View statement and pay', 'Pay and view statement']:
        assert not site.is_safe_control(label), label


def test_the_login_and_settings_vocabulary_is_refused_too():
    for label in ["Sign in", "Log in", "Remember me", "Preferences", "Settings", "Username"]:
        assert not site.is_safe_control(label), label


def test_dates_in_every_form_the_site_is_likely_to_print():
    assert site.parse_date("Aug 31, 2026 View statement") == "2026-08-31"
    assert site.parse_date("August 31, 2026") == "2026-08-31"
    assert site.parse_date("Statement 08/31/2026") == "2026-08-31"
    assert site.parse_date("08/31/26") == "2026-08-31"
    assert site.parse_date("2026-08-31") == "2026-08-31"
    assert site.parse_date("no date here") is None
    assert site.parse_period_date("August 2026") == ("2026-08-31", "August 2026")
    assert site.parse_period_date("2025 tax documents")[0] == "2025-12-31"


def test_the_survey_masks_numbers_and_takes_no_screenshot():
    assert site.redact("account 123456789 statement") == "account ######### statement"
    assert site.redact("Aug 31, 2026") == "Aug 31, 2026"
    for fn in (site.survey, site._page_summary, site.collect_documents):
        assert ".screenshot(" not in inspect.getsource(fn)
    docs_src = (Path(site.__file__).parent / "newrez_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


def test_the_survey_follows_only_documents_links():
    for text in ['Statements', 'Documents', 'Tax Documents', 'Statement history', 'Escrow analysis']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Make a payment', 'Payoff', 'Autopay', 'Escrow change', 'Help']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://myaccount.newrez.com/documents', 'https://www.newrez.com/x']:
        assert site.is_safe_url(u), u
    for u in ['https://newrez.com.evil.test/s.pdf', 'http://myaccount.newrez.com/s.pdf', 'https://user@newrez.com/s.pdf']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme


# -- round two, from the first survey --------------------------------------

def test_the_survey_follows_the_loan_controls_and_still_refuses_a_new_loan():
    for text in ("Access My Loan", "Account Details"):
        assert site.is_safe_control(text), text
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ("Make a Payment", "Apply for a loan", "Get a new loan", "Loan modification", "Request payoff"):
        assert not site.is_safe_control(text), text


def test_the_survey_follows_buttons_too():
    import inspect
    assert '("link", "button")' in inspect.getsource(site.survey)


def test_query_parameters_reach_the_survey_as_names_and_plain_words_only():
    got = site._safe_query("https://myaccount.newrez.com/x?docType=STATEMENT&range=LAST_90_DAYS&acct=12345678&key=d11-123456789&t=abcDEF123456789xyz&p=1")
    assert got == "docType=STATEMENT&range=LAST_90_DAYS&acct=...&key=...&t=...&p=..."
    assert site._safe_query("https://myaccount.newrez.com/x") == ""


# -- round three, the servicing app ----------------------------------------

def test_the_loan_number_comes_off_the_servicing_address_and_is_never_in_the_code():
    class _P:
        url = "https://servicing.newrez.com/servicing/1234567890/dashboard?x=1"
    assert site.loan_number(_P()) == "1234567890"
    _P.url = "https://myaccount.newrez.com/dashboard"
    assert site.loan_number(_P()) == ""
    src = Path(site.__file__).read_text(encoding="utf-8")
    import re
    assert not re.search(r"servicing/\d{6,}", src)
    assert site.STATEMENT_PAGES == ("/statements/monthly", "/statements/yearly")
    assert site.is_safe_url("https://servicing.newrez.com/servicing/1/statements/monthly")
    assert site.is_safe_control("Account Details") and site.ACCOUNT_DETAILS_RE.match("Account Details")


# -- round four, nine rows and no full date on any of them (#38) -------------

def test_a_month_and_a_year_dates_a_statement_and_a_year_dates_a_1098():
    """His page lists nine statements, each a View and a Download whose
    address is `javascript:void(0)`, and discovery reported none. Round
    three asked every row for a day of a month, which a mortgage
    statement list does not print."""
    assert site.parse_period_date("September 2026")[0] == "2026-09-30"
    assert site.parse_period_date("Sep 2026")[0] == "2026-09-30"
    assert site.parse_period_date("2025")[0] == "2025-12-31"
    # a day, when there is one, still wins
    assert site.parse_period_date("Statement Sep 5, 2026")[0] == "2026-09-05"


def test_a_month_written_with_a_slash_is_not_every_statement_of_that_year():
    """09/2026 used to fall through to the year rule, so twelve
    statements became one date and eleven were dropped as duplicates."""
    assert site.parse_period_date("09/2026")[0] == "2026-09-30"
    assert site.parse_period_date("12/2025")[0] == "2025-12-31"
    assert site.parse_period_date("01/2026")[0] == "2026-01-31"
    assert site.parse_period_date("02/2024")[0] == "2024-02-29", "a leap year"
    # not a month, so it is only a year
    assert site.parse_period_date("13/2026")[0] == "2026-12-31"


def test_the_row_walk_looks_for_a_period_and_not_only_for_a_full_date():
    js = site._ROW_OF_JS
    assert "depth < 8" in js
    assert r"\d{4}" in js
    for part in ("Jan|Feb", "19|20"):
        assert part in js, part


def test_discovery_and_capture_agree_on_how_a_row_is_dated():
    """They match rows the same way or capture looks for a document
    discovery never saw."""
    import inspect
    for fn in (site._read_rows, site._control_for):
        src = inspect.getsource(fn)
        assert "parse_period_date" in src, fn.__name__
        assert "parse_date(" not in src, fn.__name__
