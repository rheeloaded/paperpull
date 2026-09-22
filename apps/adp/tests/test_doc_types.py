"""ADP Workforce Now classification, the guard, and the survey's promises.

The site layer is unverified, so what these pin is everything that must be
true before a tester ever runs it: the guard refuses every control that
touches pay, tax, time, benefits or a setting, the survey cannot leak a
number, and a row's date is read in the forms the site is likely to print
it in.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds the AppSpec
from paperpull_core import doc_types
import adp_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [('Pay Statement 09/12/2026', 'Pay Statement', 'STATEMENT'), ('Pay stub', 'Pay Statement', 'STATEMENT'), ('Earnings Statement', 'Pay Statement', 'STATEMENT'), ('W-2 2025', 'W-2 Tax Form', 'TAX'), ('W2 Wage and Tax Statement', 'W-2 Tax Form', 'TAX'), ('W-2c', 'W-2c Corrected Tax Form', 'TAX'), ('1095-C', '1095 Health Coverage Form', 'TAX')]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ['Privacy Notice', 'Employee Handbook', 'Benefits Guide 2026', 'Open Enrollment']:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip('Pay Statement 09/12/2026', RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    d, summ, kind, want = ('2026-09-12', 'Pay Statement', 'Statement', '2026-09-12 ADP Workforce Now Pay Statement Statement.pdf')
    assert build_pdf_filename(d, summ, kind) == want


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in ['Direct deposit', 'Update direct deposit', 'Tax withholding', 'W-4', 'Request time off', 'Timecard', 'Clock in', 'Enroll in benefits', 'Open enrollment', 'Add beneficiary', 'Update address', 'Change password', 'Submit', 'Approve', 'Acknowledge', 'Sign', 'Wisely card', 'Earned wage access', 'Chat with us', 'Contact HR']:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ['View', 'Download', 'View statement', 'Download statement', 'Pay statement', 'Pay stub', 'W-2', 'Tax statements', 'Annual statements', 'View PDF', 'Show older statements', 'Previous years', 'Print']:
        assert site.is_safe_control(label), label


def test_a_document_control_that_also_pays_is_refused():
    for label in ['View statement and update direct deposit', 'Pay statement and W-4']:
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
    docs_src = (Path(site.__file__).parent / "adp_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["list of 1", {"amount": "float"}], "n": "int"}


def test_the_survey_follows_only_documents_links():
    for text in ['Pay & Annual Statements', 'Pay and Annual Statements', 'Pay Statements', 'Tax Statements', 'W-2', 'Annual Statements', 'Myself']:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ['Direct Deposit', 'Time Off', 'Benefits', 'Timecard', 'Tax Withholding']:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ['https://workforcenow.adp.com/theme/index.html', 'https://my.adp.com/static/redbox/', 'https://online.adp.com/signin/v1/']:
        assert site.is_safe_url(u), u
    for u in ['https://adp.com.evil.test/s.pdf', 'http://workforcenow.adp.com/s.pdf', 'https://user@adp.com/s.pdf']:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_verified_status_is_stated_where_a_reader_will_see_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" not in src.split('"""')[1]
    assert "verified working against the live site" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested" not in readme


# -- the statement services, as the live site answered on 2026-09-21 ---------

PAY_RECORD = {
    "payDate": "2025-06-13",
    "netPayAmount": {"amountValue": 1234.56, "currencyCode": "USD"},
    "grossPayAmount": {"amountValue": 2345.67, "currencyCode": "USD"},
    "totalHours": 40.0,
    "payDetailUri": {"href": "/payroll/v1/workers/G000000000000000/pay-statements/ABC123"},
    "statementImageUri": {"href": "/payroll/v1/workers/G000000000000000/pay-statements/ABC123/images/ABC123.pdf"},
    "payAdjustmentIndicator": False,
}
TAX_RECORD = {
    "statementID": "TAX123",
    "statementName": "2025 W-2",
    "employerName": "EXAMPLE EMPLOYER INC",
    "form": {"code": "W2"},
    "statementYear": {"year": "2025"},
    "statementUri": {"href": "/payroll/v1/workers/G000000000000000/tax-statements/TAX123"},
    "statementImageUri": {"href": "/payroll/v1/workers/G000000000000000/tax-statements/TAX123/images/TAX123.pdf"},
}


def test_a_pay_statement_record_becomes_a_dated_statement_with_its_pdf_address():
    d = site.pay_statement_doc(PAY_RECORD)
    assert d.title == "Pay Statement" and d.date_text == "2025-06-13" and d.kind == "statement"
    assert d.href == "https://my.adp.com/myadp_prefix/payroll/v1/workers/G000000000000000/pay-statements/ABC123/images/ABC123.pdf"
    adj = site.pay_statement_doc({**PAY_RECORD, "payAdjustmentIndicator": True})
    assert adj.title == "Pay Statement Adjustment"
    assert site.pay_statement_doc({"payDate": "nonsense"}) is None


def test_a_tax_statement_record_is_filed_at_the_years_end_with_the_employer_in_its_title():
    d = site.tax_statement_doc(TAX_RECORD)
    assert d.title == "2025 W-2 EXAMPLE EMPLOYER INC" and d.date_text == "2025-12-31" and d.kind == "tax"
    assert d.href.endswith("/tax-statements/TAX123/images/TAX123.pdf")
    cat, summary, _ = doc_types.classify_document(d.title, RULES)
    assert cat == doc_types.TAX and summary == "W-2 Tax Form"
    assert site.tax_statement_doc({"statementName": "W-2"}) is None


def test_an_image_address_off_the_prefix_is_refused():
    assert site._image_url({"statementImageUri": {"href": "https://evil.test/x.pdf"}}) == ""
    assert site._image_url({"statementImageUri": {"href": "//evil.test/x.pdf"}}) == ""
    assert site._image_url({}) == ""


def test_the_worker_id_is_read_from_the_pages_own_calls():
    assert site.AOID_RE.search("https://my.adp.com/myadp_prefix/hr/v2/workers/GABCDEFGHJKLMNP1").group(1) == "GABCDEFGHJKLMNP1"
    assert site.AOID_RE.search("/payroll/v1/workers/GABCDEFGHJKLMNP1/pay-statements?x=1").group(1) == "GABCDEFGHJKLMNP1"
    assert site.AOID_RE.search("/workers/notanid/") is None
    assert "performance.getEntriesByType" in site._AOID_JS and "myadp-dashboard_pay-dashboard-wfn" in site._AOID_JS
