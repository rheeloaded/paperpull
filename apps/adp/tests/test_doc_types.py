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
    d, summ, kind, want = ('2026-09-12', 'Pay Statement', '', '2026-09-12 ADP Workforce Now Pay Statement.pdf')
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
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["1 item(s)", {"amount": "number"}], "n": "number"}


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


# -- the identity check ADP asks for before a tax statement (#46) ------------

BLOCKED_BODY = b'''{"confirmMessage": {"protocolStatusCode": {"codeValue": "403"},
 "resourceMessages": [{"processMessages": [{
   "userMessage": {"messageTxt": "This transaction is blocked, because you have made too many unsuccessful attempts to verify your identity. You may remain logged in and do other tasks, but you must log out and log back in to complete this transaction.", "codeValue": "4820"},
   "developerMessage": {"messageTxt": "{\\"stepUpDevMsg\\": {\\"errorCode\\": \\"TO_MANY_UNSUCCESSFUL_CALLS\\"}}", "codeValue": "4820"}}]}]}}'''
STEP_UP_BODY = b'''{"confirmMessage": {"protocolStatusCode": {"codeValue": "403"},
 "resourceMessages": [{"processMessages": [{
   "userMessage": {"messageTxt": "For your security, we need to verify your identity before showing this document. Choose how you would like to receive your verification code.", "codeValue": "4810"}}]}]}}'''


def test_adps_own_words_tell_a_check_from_a_block():
    kind, msg = site.refusal_message(BLOCKED_BODY)
    assert kind == "blocked" and "log out and log back in" in msg
    kind, msg = site.refusal_message(STEP_UP_BODY)
    assert kind == "step-up" and "verify your identity" in msg
    assert site.refusal_message(b"not json") == ("", "")
    assert site.refusal_message(b'{"data": {"payStatements": []}}')[0] == ""


def test_a_refused_tax_statement_stops_the_guessing_and_says_which_it_is():
    import pytest
    calls = []

    class _Page:
        def evaluate(self, js, arg=None):
            calls.append(arg[0] if isinstance(arg, list) else arg)
            import base64 as _b64
            return {"status": 403, "type": "application/json", "size": len(BLOCKED_BODY),
                    "head": "", "b64": _b64.b64encode(BLOCKED_BODY).decode()}
        context = None

    site._PDF_BY_KEY[("2023-12-31", "2023 W-2")] = "https://my.adp.com/myadp_prefix/a/images/b.pdf"
    site._STATEMENT_BY_KEY[("2023-12-31", "2023 W-2")] = "https://my.adp.com/myadp_prefix/a"
    with pytest.raises(site.TaxAccessBlocked):
        site.download_bill(_Page(), None, "2023-12-31", Path("x.pdf"), title="2023 W-2")
    assert len(calls) == 1, "one ask per document, ADP blocks an account that asks twice"
    site._PDF_BY_KEY.clear(); site._STATEMENT_BY_KEY.clear(); site.LAST_REFUSAL.clear()


def test_the_app_never_answers_the_check_itself():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "step-up-myadp-pre-auth" not in src.replace("``/events/core/v1/step-up-myadp-pre-auth``", "")
    assert "verification code" not in inspect.getsource(site.open_tax_statement_check)
    assert "view statement" in inspect.getsource(site.open_tax_statement_check).lower()


def test_the_check_is_answered_in_the_browser_and_needs_no_keyboard_here():
    """The control panel runs an app with no stdin at all, so a prompt
    would end the run. The app presses the card's own control, waits, and
    takes the statement the page's own viewer fetches."""
    src = inspect.getsource(site.wait_for_tax_access)
    assert "input(" not in src and "ask(" not in src
    assert "open_tax_statement_check(page)" in src
    docs_src = (Path(site.__file__).parent / "adp_docs.py").read_text(encoding="utf-8")
    i = docs_src.index("except site.StepUpNotDone")
    assert "ask(" not in docs_src[i:i + 1200], "the run must not stop for a prompt"
    assert "_tax_blocked = True" in docs_src[i:i + 1200], "one unanswered check is enough for a run"


def test_the_statement_the_pages_viewer_fetches_is_the_one_taken():
    assert site._TAX_IMAGE_RE.search("/payroll/v1/workers/G0/tax-statements/ABC/images/ABC.pdf")
    assert not site._TAX_IMAGE_RE.search("/payroll/v1/workers/G0/pay-statements/ABC/images/ABC.pdf")
    assert site._STEP_UP_ON_PAGE_RE.search("please authorize this transaction")
    assert site._STEP_UP_ON_PAGE_RE.search("Select how you want to receive your security code.")
    assert not site._STEP_UP_ON_PAGE_RE.search("Pay Details Gross Taxes Take Home")


def test_an_employer_in_capitals_reads_as_a_name_in_a_filename():
    assert site.tidy_employer("SCIENCE APPLICATIONS INT") == "Science Applications Int"
    assert site.tidy_employer("LUNATEK LLC") == "Lunatek LLC"
    assert site.tidy_employer("Acme Co.") == "Acme Co."
    assert site.tidy_employer("  ") == ""
    d = site.tax_statement_doc({**TAX_RECORD, "employerName": "EXAMPLE EMPLOYER INC"})
    assert d.account == "Example Employer INC"


def test_a_tax_statement_is_asked_for_at_one_address_only():
    """ADP blocks an account that is refused a few times, so a tax form
    gets one ask. A pay statement, which has no check, may get two."""
    site._PDF_BY_KEY.clear(); site._STATEMENT_BY_KEY.clear()
    site._PDF_BY_KEY[("2025-12-31", "2025 W-2")] = "https://my.adp.com/myadp_prefix/a/images/b.pdf"
    site._STATEMENT_BY_KEY[("2025-12-31", "2025 W-2")] = "https://my.adp.com/myadp_prefix/a"
    assert len(site._pdf_addresses(("2025-12-31", "2025 W-2"), "2025-12-31")) == 1
    site._PDF_BY_KEY[("2025-06-13", "Pay Statement")] = "https://my.adp.com/myadp_prefix/p/images/q.pdf"
    assert len(site._pdf_addresses(("2025-06-13", "Pay Statement"), "2025-06-13")) == 2
    site._PDF_BY_KEY.clear(); site._STATEMENT_BY_KEY.clear()


def test_tax_forms_are_left_for_last_so_a_check_holds_up_nothing():
    import adp_docs
    docs = [adp_docs.Document(title="2025 W-2", category=doc_types.TAX, date="2025-12-31"),
            adp_docs.Document(title="Pay Statement", category=doc_types.STATEMENT, date="2025-06-13"),
            adp_docs.Document(title="Pay Statement", category=doc_types.STATEMENT, date="2025-06-27"),
            adp_docs.Document(title="2024 W-2", category=doc_types.TAX, date="2024-12-31")]
    docs.sort(key=lambda d: ((d.category == doc_types.TAX), adp_docs._invert(d.date or "0000")))
    assert [d.date for d in docs] == ["2025-06-27", "2025-06-13", "2025-12-31", "2024-12-31"]


def test_the_statement_the_viewer_fetches_during_the_wait_is_caught():
    """The person answers ADP in the browser, ADP's own viewer then
    fetches the PDF, and that answer is the document. No second ask."""
    class _Res:
        url = "https://my.adp.com/myadp_prefix/payroll/v1/workers/G0/tax-statements/A/images/A.pdf"
        headers = {"content-type": "application/pdf"}
        def body(self): return b"%PDF-1.4 a real one"
    class _Ctx:
        def __init__(self): self.fn = None
        def on(self, name, fn): self.fn = fn
        def remove_listener(self, name, fn): pass
    class _Page:
        def __init__(self): self.context = _Ctx(); self.ticks = 0
        def evaluate(self, js, arg=None): return True          # the card's own control
        def wait_for_timeout(self, ms):
            self.ticks += 1
            if self.ticks == 2:
                self.context.fn(_Res())                         # ADP accepted the code
        def locator(self, sel):
            class _L:
                def inner_text(self_, timeout=0): return "Pay Details"
            return _L()
    body = site.wait_for_tax_access(_Page(), "https://my.adp.com/myadp_prefix/x.pdf", None, seconds=5)
    assert body == b"%PDF-1.4 a real one"


def test_adps_own_refusal_is_written_down_and_not_only_printed():
    """He signed out, signed back in, ran Resume twice, saw the lock-out
    message both times, and had nothing in Diagnostics to send. A run
    that reaches a provider's refusal is not a run that failed by its own
    reckoning, so it wrote no file (#46)."""
    from pathlib import Path as _P
    src = (_P(site.__file__).parent / "adp_docs.py").read_text(encoding="utf-8")
    blocked = src.split("except site.TaxAccessBlocked")[1][:900]
    assert "self.write_failure(" in blocked
    not_done = src.split("except site.StepUpNotDone")[1][:900]
    assert "self.write_failure(" in not_done


# -- a pilot that never reached the thing that can fail (#46) ----------------

class _Disc:
    def __init__(self, data):
        self.data = data


def _doc(date, category, title="x"):
    return {"date": date, "category": category, "title": title, "summary": title}


def _app_with(records):
    import adp_docs as docs

    class _A(docs.App):
        def __init__(self):
            self.discovery = _Disc({str(i): r for i, r in enumerate(records)})
            self.args = type("a", (), {"max_docs": None, "year": None,
                                       "start_date": None, "end_date": None,
                                       "type": None})()
            self.config = {"pilot_count": 5}

        def _in_scope(self, d):
            return True
    return _A()


def test_a_pilot_keeps_room_for_a_tax_form():
    """Tax forms sort last so an unanswered identity check holds up no
    pay statement. Taking the first five then meant a pilot was five pay
    statements every time, and the check ADP puts in front of a W-2 was
    the one thing a pilot never exercised."""
    from paperpull_core import doc_types as dt
    records = [_doc("2026-09-%02d" % (d + 1), dt.STATEMENT) for d in range(9)]
    records += [_doc("2025-12-31", dt.TAX, "W-2"), _doc("2024-12-31", dt.TAX, "W-2")]
    chosen = _app_with(records)._pilot_selection(5)
    kinds = [d.category for d in chosen]
    assert kinds.count(dt.TAX) == 1, "one tax form, not five"
    assert len(chosen) == 5
    assert kinds[-1] == dt.TAX, "and it still runs last"


def test_an_account_with_no_tax_forms_pilots_as_before():
    from paperpull_core import doc_types as dt
    records = [_doc("2026-09-%02d" % (d + 1), dt.STATEMENT) for d in range(9)]
    chosen = _app_with(records)._pilot_selection(5)
    assert len(chosen) == 5
    assert all(d.category == dt.STATEMENT for d in chosen)


def test_a_pilot_of_one_still_proves_the_hard_part():
    from paperpull_core import doc_types as dt
    records = [_doc("2026-09-01", dt.STATEMENT), _doc("2025-12-31", dt.TAX, "W-2")]
    chosen = _app_with(records)._pilot_selection(1)
    assert [d.category for d in chosen][-1] == dt.TAX
