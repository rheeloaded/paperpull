"""American Family classification, the guard, and the survey's promises.

The site layer is unverified, so what these pin is everything that must be
true before a tester ever runs it: the guard refuses every control that
pays, claims, changes coverage or changes a setting, the survey cannot leak
a number, and a row's date is read in the forms the site is likely to
print it in.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds the AppSpec
from paperpull_core import doc_types
import amfam_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Billing Statement - September 2026', 'Billing Statement', 'STATEMENT'), ('Your bill is ready', 'Billing Statement', 'STATEMENT'), ('Payment receipt', 'Payment Receipt', 'STATEMENT'), ('Auto Declarations Page', 'Declarations Page', 'INSURANCE'), ('Insurance ID Card', 'Insurance ID Card', 'INSURANCE'), ('Renewal Notice', 'Renewal Notice', 'INSURANCE'), ('Homeowners Policy', 'Policy Document', 'INSURANCE'), ('Form 1099', '1099 Tax Form', 'TAX')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Newsletter', 'Special offers', 'Brochure']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip('Billing Statement - September 2026', RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-09-01', 'Billing Statement', '', '2026-09-01 American Family Billing Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Pay now', 'Make a payment', 'Set up autopay', 'File a claim', 'Report a claim', 'Change coverage', 'Add a vehicle', 'Add a driver', 'Start a quote', 'Get a quote', 'Cancel policy', 'Renew now', 'Roadside assistance', 'Contact my agent', 'Update address', 'Go paperless', 'Manage alerts', 'Submit', 'Confirm', 'Save Changes', 'Chat with us', 'KnowYourDrive', 'Apply discount']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View documents', 'Download statement', 'Policy documents', 'Declarations page', 'ID cards', 'View ID card', 'Billing history', 'Payment history', 'Renewal notice', 'View bill', 'Print', 'See more documents']:
        assert site.is_safe_control(label), label


def test_a_document_control_that_also_pays_is_refused():
    for label in ['View bill and pay', 'Pay and view statement', 'Download ID card and add driver']:
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
    docs_src = (Path(site.__file__).parent / "amfam_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


def test_the_survey_follows_only_documents_links():
    for text in ['Documents', 'Policy Documents', 'My Documents', 'Billing', 'Billing & Payments', 'Billing History', 'ID Cards', 'Policies', 'Declarations']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Pay Now', 'Claims', 'File a Claim', 'Get a Quote', 'Coverage', 'Agent']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://myaccount.amfam.com/documents', 'https://www.amfam.com/x', 'https://docs.amfam.com/x.pdf']:
        assert site.is_safe_url(u), u
    for u in ['https://amfam.com.evil.test/s.pdf', 'http://myaccount.amfam.com/s.pdf', 'https://user@amfam.com/s.pdf']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme
