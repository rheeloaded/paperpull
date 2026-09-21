"""State Farm classification, the guard, and the survey's promises.

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
from paperpull_core.doc_types import INSURANCE  # noqa: F401
from paperpull_core import doc_types
import statefarm_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Monthly Statement - August 31, 2026', 'Monthly Statement', 'STATEMENT'), ('Bill - July 2026', 'Bill', 'STATEMENT'), ('Renewal notice', 'Renewal Notice', 'STATEMENT'), ('Payment receipt', 'Receipt', 'STATEMENT'), ('Auto ID card', 'ID Card', 'INSURANCE'), ('Declarations page', 'Declarations', 'INSURANCE'), ('Policy documents', 'Policy Document', 'INSURANCE')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Terms of service', 'Drive Safe & Save']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 31, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', 'Statement', '2026-08-31 State Farm Monthly Statement Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Pay bill', 'Make a payment', 'Set up autopay', 'File a claim', 'Report a claim', 'Change coverage', 'Add a vehicle', 'Add a driver', 'Get a quote', 'Start a quote', 'Cancel policy', 'Renew now', 'Contact my agent', 'Roadside assistance', 'Update address', 'Manage alerts', 'Go paperless', 'Submit', 'Confirm', 'Save Changes', 'Chat with us']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View bill', 'Download bill', 'Bill PDF', 'Renewal notice', 'ID cards', 'View ID card', 'Payment receipt', 'Policy documents', 'Declarations page', 'Billing history', 'See more documents', 'Print']:
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
    docs_src = (Path(site.__file__).parent / "statefarm_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


def test_the_survey_follows_only_documents_links():
    for text in ['Bills', 'Billing', 'Documents', 'Policy documents', 'ID cards', 'Receipts', 'Payment history']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Pay bill', 'Claims', 'Get a quote', 'Coverage', 'Agent']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://www.statefarm.com/customer-care/documents', 'https://apps.statefarm.com/x', 'https://auth.proofing.statefarm.com/login-ui/login']:
        assert site.is_safe_url(u), u
    for u in ['https://statefarm.com.evil.test/s.pdf', 'http://www.statefarm.com/s.pdf', 'https://user@statefarm.com/s.pdf']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme


# -- round two, from the first survey --------------------------------------

def test_the_document_center_is_first_and_sign_in_goes_through_my_accounts():
    assert site.BILLING_CANDIDATES[0] == "https://edocuments.statefarm.com/DocumentCenterUI/"
    assert site.URLS["login"] == "https://my.statefarm.com/"
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)
    assert site.is_safe_url("https://get-id-card.statefarm.com/")


def test_the_documents_link_that_mentions_claims_is_followed_and_a_claim_is_not():
    for text in ("Documents (excludes claims)", "View documents & PDFs", "Get insurance ID card",
                 "View Insurance Billing and Payment History"):
        assert site.is_safe_control(text), text
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ("File a claim", "Claims", "Report a claim", "Make a policy change", "Enroll in AutoPay"):
        assert not site.is_safe_control(text), text
