"""E*TRADE classification, the guard, and the survey's promises.

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
import etrade_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Monthly Statement - August 31, 2026', 'Monthly Statement', 'STATEMENT'), ('Brokerage statement', 'Account Statement', 'STATEMENT'), ('Trade Confirmation 08/12/2026', 'Trade Confirmation', 'STATEMENT'), ('2025 Form 1099 Consolidated', '1099 Tax Form', 'TAX')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Prospectus', 'Margin agreement']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 31, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', '', '2026-08-31 ETRADE Monthly Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Trade', 'Buy', 'Sell', 'Place order', 'Cancel order', 'Trade options', 'Exercise', 'Transfer money', 'Wire funds', 'Deposit', 'Withdraw', 'Take a distribution', 'Link bank account', 'Roll over', 'Contribute', 'Margin', 'Update address', 'Manage alerts', 'Go paperless', 'Submit', 'Confirm', 'Save Changes', 'Chat with us']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View statement', 'Download statement', 'Statement PDF', 'Trade confirmations', 'Confirmations', '1099', 'Tax documents', 'Tax center', 'See more statements', 'Print']:
        assert site.is_safe_control(label), label


def test_a_document_control_that_also_pays_is_refused():
    for label in ['View statement and trade', 'Sell and view statement']:
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
    docs_src = (Path(site.__file__).parent / "etrade_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["1 item(s)", {"amount": "number"}], "n": "number"}


def test_the_survey_follows_only_documents_links():
    for text in ['Statements', 'Documents', 'Tax Documents', 'Tax center', 'Trade confirmations', 'Confirmations']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Trade', 'Transfer', 'Accounts', 'Portfolio', 'Markets']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://us.etrade.com/etx/pxy/documents', 'https://www.etrade.com/x']:
        assert site.is_safe_url(u), u
    for u in ['https://etrade.com.evil.test/s.pdf', 'http://us.etrade.com/s.pdf', 'https://user@etrade.com/s.pdf', 'https://www.morganstanley.com/x']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme


# -- round two, from the first survey --------------------------------------

def test_the_documents_page_is_first_and_its_api_is_recognized():
    assert site.BILLING_CANDIDATES[0] == "https://us.etrade.com/etx/pxy/accountdocs"
    assert site.DOCS_API_RE.search("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems?x=1")
    assert site.is_safe_url("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems")


def test_the_search_answer_gives_each_document_a_date_a_title_and_a_hint():
    body = {"defaultDocumentList": [
        {"documentGuid": "g1", "documentId": "i1", "documentTypeName": "STATEMENTS", "documentDisplayName": "Statement",
         "documentTitle": "Monthly Statement", "documentDate": "08/31/2026", "keyAccountNo": "x", "displayMultipleAccounts": "Brokerage -1234"},
        {"documentGuid": "g2", "documentId": "i2", "documentTypeName": "TAX", "documentTitle": "1099 Consolidated",
         "documentDate": "2026-02-15"},
        {"documentGuid": "g3", "documentTitle": "no date"},
    ], "numFound": "3"}
    got = site._docs_from_api(body)
    assert [(d["date"], d["title"], d["hint"]) for d in got] == [
        ("2026-08-31", "Monthly Statement", "g1|i1"), ("2026-02-15", "1099 Consolidated", "g2|i2")]
    assert site._docs_from_api({}) == []


# -- round three, the period picker and the row's own link -----------------

def test_the_period_picker_and_its_periods_are_the_only_controls_outside_a_row():
    for t in ("Last 90 Days", "Last 12 Months", "Year to Date", "All", "Last 7 Years", "2024", "Custom Range"):
        assert site.is_date_filter(t), t
    for t in ("Apply", "Download", "Trade", "Last 90 Days Pay", "", "Transfer money"):
        assert not site.is_date_filter(t), t


def test_the_widest_period_wins():
    options = ["Last 30 Days", "Last 90 Days", "Year to Date", "Last 12 Months", "Last 24 Months", "Last 7 Years", "Custom Range"]
    import re
    choice = None
    for pat in site._WIDEST:
        for t in options:
            if re.search(pat, t, re.I):
                choice = t
                break
        if choice:
            break
    assert choice == "Last 7 Years"


def test_the_documents_page_is_reloaded_when_it_is_already_open():
    import inspect
    src = inspect.getsource(site.goto_docs_capturing)
    assert "page.reload(" in src and "already" in src
    assert site.DOCS_URL.endswith("#/documents")


# -- round four, dates in every form and a picker of years (#36) -------------

def test_an_api_date_is_read_in_every_form_etrade_could_send():
    assert site.parse_api_date("2026-09-15") == "2026-09-15"
    assert site.parse_api_date("2026-09-15T00:00:00.000Z") == "2026-09-15"
    assert site.parse_api_date("1789516800000") == "2026-09-16"
    assert site.parse_api_date(1789516800) == "2026-09-16"
    assert site.parse_api_date("09/15/2026") == "2026-09-15"
    assert site.parse_api_date(None) is None and site.parse_api_date("soon") is None
    assert site.date_shape("1789516800000") == "#############"
    docs = site._docs_from_api({"defaultDocumentList": [
        {"documentDate": "1789516800000", "documentTitle": "Brokerage Statement", "documentTypeName": "Statements",
         "documentGuid": "g1", "documentId": "d1", "displayMultipleAccounts": "Individual ...1234"}]})
    assert docs and docs[0]["date"] == "2026-09-16" and docs[0]["hint"] == "g1|d1"


def test_years_count_as_periods_and_the_year_walk_exists():
    for t in ("2026", "2019", "Last 90 Days", "Year to Date"):
        assert site.is_date_filter(t), t
    assert not site.is_date_filter("Apply") and not site.is_date_filter("Download")
    src = inspect.getsource(site.widen_date_filter)
    assert "_choose_period(page, year, capture, trace)" in src
