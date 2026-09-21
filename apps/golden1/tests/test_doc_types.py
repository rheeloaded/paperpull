"""Golden 1 classification, the guard, and the survey's promises.

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
import golden1_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Monthly Statement - August 31, 2026', 'Monthly Statement', 'STATEMENT'), ('Checking statement', 'Account Statement', 'STATEMENT'), ('eStatement - July 2026', 'Account Statement', 'STATEMENT'), ('1099-INT', '1099-INT Tax Form', 'TAX')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Fee schedule', 'Account agreement']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 31, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', 'Statement', '2026-08-31 Golden 1 Monthly Statement Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Transfer', 'Send money with Zelle', 'Pay bills', 'Make a payment', 'Set up autopay', 'Deposit checks', 'Wire money', 'Apply now', 'Open an account', 'Close account', 'Lock card', 'Replace card', 'Change limit', 'Update address', 'Manage alerts', 'Go paperless', 'Order checks', 'Stop payment', 'Dispute a transaction', 'Add beneficiary', 'Submit', 'Confirm', 'Save Changes', 'Chat with us']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View statement', 'Download statement', 'eStatements', 'Statement PDF', '1099-INT', 'Tax documents', 'See more statements', 'Print']:
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
    docs_src = (Path(site.__file__).parent / "golden1_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


def test_the_survey_follows_only_documents_links():
    for text in ['Statements', 'eStatements', 'Documents', 'Tax Documents', 'View statements']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Transfer', 'Pay bills', 'Zelle', 'Accounts', 'Rewards']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://login.golden1.com/statements', 'https://www.golden1.com/x', 'https://online.golden1.com/x']:
        assert site.is_safe_url(u), u
    for u in ['https://golden1.com.evil.test/s.pdf', 'http://login.golden1.com/s.pdf', 'https://user@golden1.com/s.pdf']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme


# -- round two, the document vendor in a new tab --------------------------

def test_sign_in_and_the_documents_page_are_where_the_survey_found_them():
    assert site.URLS["login"] == "https://login.golden1.com/login/?realm=/alpha#/"
    assert site.BILLING_CANDIDATES[0] == "https://digitalbanking.golden1.com/accounts/documents"
    assert site.is_safe_url("https://ebank.hepsiian.com/cv/searchResults.jsf")
    assert not site.is_safe_url("https://hepsiian.com.evil.test/x")
    assert site.is_safe_control("View Documents") and site.VENDOR_BUTTON_RE.match("View Documents")


def test_the_vendor_tab_is_found_among_the_open_tabs():
    class _Tab:
        def __init__(self, url): self.url = url
        def is_closed(self): return False
    class _Ctx:
        pages = [_Tab("https://digitalbanking.golden1.com/accounts/documents"), _Tab("https://ebank.hepsiian.com/cv/searchResults.jsf")]
    class _P:
        context = _Ctx()
    assert site._vendor_tab(_P()).url.startswith("https://ebank.hepsiian.com")
    _Ctx.pages = _Ctx.pages[:1]
    assert site._vendor_tab(_P()) is None
