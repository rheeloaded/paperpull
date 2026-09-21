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
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', 'Statement', '2026-08-31 ETRADE Monthly Statement Statement.pdf')
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
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


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
