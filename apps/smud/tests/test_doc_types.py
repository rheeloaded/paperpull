"""SMUD classification, the guard, and the survey's promises.

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
import smud_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Monthly Statement - August 31, 2026', 'Monthly Statement', 'STATEMENT'), ('Bill - July 2026', 'Bill', 'STATEMENT'), ('Electric bill', 'Bill', 'STATEMENT')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Rate schedule', 'Rebate application']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 31, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', '', '2026-08-31 SMUD Monthly Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Pay bill', 'Make a payment', 'Set up autopay', 'Enroll in budget billing', 'Start service', 'Stop service', 'Move service', 'Report an outage', 'Payment arrangement', 'Request extension', 'Rate plans', 'Enroll in a program', 'Rebates', 'Update address', 'Manage alerts', 'Go paperless', 'Submit', 'Confirm', 'Save Changes', 'Chat with us']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View bill', 'Download bill', 'Bill PDF', 'Bill history', 'Billing history', 'Statement', 'See more bills', 'Print']:
        assert site.is_safe_control(label), label


def test_a_document_control_that_also_pays_is_refused():
    for label in ['View bill and pay', 'Pay and view bill']:
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
    docs_src = (Path(site.__file__).parent / "smud_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


def test_the_survey_follows_only_documents_links():
    for text in ['Bills', 'Billing', 'Bill history', 'Billing history', 'Statements', 'View bills']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Pay bill', 'Autopay', 'Programs', 'Rebates', 'Outages']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://myaccount.smud.org/billing/history', 'https://www.smud.org/x']:
        assert site.is_safe_url(u), u
    for u in ['https://smud.org.evil.test/s.pdf', 'http://myaccount.smud.org/s.pdf', 'https://user@smud.org/s.pdf']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme


# -- round two, from the first survey --------------------------------------

def test_the_billing_history_is_first_and_the_vendor_host_is_allowed():
    assert site.BILLING_CANDIDATES[0] == "https://myaccount.smud.org/manage/billing"
    assert site.ARCHIVE_URL == "https://myaccount.smud.org/manage/billing/archive"
    assert site.is_safe_url("https://secure8.i-doxs.net/SMUD/BillPopLogin.aspx?x=1")
    assert not site.is_safe_url("https://i-doxs.net.evil.test/x")


def test_the_download_control_wins_over_the_view_control():
    class _El:
        def __init__(self, name): self._name = name
        def get_attribute(self, k): return None
        def inner_text(self, timeout=0): return self._name
        def evaluate(self, js): return "09/03/2026 $93.63 View Download"
    class _Loc:
        def __init__(self, items): self._items = items
        def count(self): return len(self._items)
        def nth(self, i): return self._items[i]
    class _Page:
        def get_by_role(self, role, name=None):
            return _Loc([_El("View"), _El("Download")] if role == "link" else [])
    class _Or(_Loc):
        pass
    page = _Page()
    # _bill_controls joins button and link locators with or_; the fake link
    # locator carries both controls, the button one none
    orig = site._bill_controls
    site._bill_controls = lambda p: _Loc([_El("View"), _El("Download")])
    try:
        el, name = site._control_for(page, "2026-09-03")
        assert name == "Download"
        assert site._control_for(page, "2026-08-03") == (None, "")
    finally:
        site._bill_controls = orig


def test_a_greeting_never_carries_the_persons_name():
    assert site.redact("Welcome, ALEX Account 123456789") == "Welcome, [name] #########"
    assert site.redact("Good evening!") == "Good evening!"
    assert site.redact("Welcome back") == "Welcome back"
