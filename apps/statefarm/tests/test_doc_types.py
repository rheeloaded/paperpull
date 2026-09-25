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
    d, summ, kind, want = ('2026-08-31', 'Monthly Statement', '', '2026-08-31 State Farm Monthly Statement.pdf')
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
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["1 item(s)", {"amount": "number"}], "n": "number"}


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


# -- round three, the Document Center's API --------------------------------

def test_the_document_center_answer_gives_each_document_a_date_a_title_and_its_file():
    body = {"data": {"attributes": [
        {"creationDate": "07/22/2026", "category": "Auto", "type": "Renewal Notice",
         "description": "Renewal Notice - 2019 SEDAN 1HGCM82633A123456", "documentId": "d1",
         "filePathUrl": "/DocumentCenterProxyV1/document/d1", "policyId": "p1"},
        {"creationDate": "09/12/2026", "category": "Billing/Payments", "type": "Payment Receipt",
         "description": "Payment Receipt - Payment Receipt", "documentId": "d2", "filePathUrl": ""},
        {"creationDate": "07/22/2026", "category": "Auto", "type": "ID Card", "description": "ID Card - 2019 SEDAN",
         "documentId": "d3", "filePathUrl": "/x/d3"},
        {"type": "no date"},
    ]}}
    got = site._docs_from_api(body)
    assert [(d["date"], d["title"], d["hint"], d["url"]) for d in got] == [
        ("2026-07-22", "Renewal Notice - Auto", "d1", "/DocumentCenterProxyV1/document/d1"),
        ("2026-09-12", "Payment Receipt - Billing/Payments", "d2", ""),
        ("2026-07-22", "ID Card - Auto", "d3", "/x/d3")]
    assert "1HGCM82633A123456" not in got[0]["desc"], "a VIN in the description is masked"
    assert site._docs_from_api({}) == []


def test_the_year_is_the_only_thing_changed_in_the_metadata_address():
    calls = []
    class _P:
        def evaluate(self, js, url):
            calls.append(url)
            return {"data": {"attributes": [{"creationDate": "01/05/" + url[-4:], "type": "Bill", "category": "Auto"}]}}
    got = site._years_from(_P(), "https://documentcenterproxyv1-prod.statefarm.com/DocumentCenterProxyV1/customerMetadata?commId=null&year=2026", 2026)
    assert calls[0].endswith("year=2025") and all("year=" in c for c in calls)
    assert len(calls) == site.YEARS_BACK and got[0]["date"] == "2025-01-05"
    assert site._years_from(_P(), "https://x.statefarm.com/customerMetadata?commId=null", -1) == []


def test_the_download_takes_a_hint_and_only_fetches_it_on_statefarm():
    import inspect
    assert "hint" in inspect.signature(site.download_bill).parameters
    assert "is_safe_url(target)" in inspect.getsource(site.download_bill)


# -- round four, four found and none saved (#37) ------------------------------

class _YearPage:
    """The Document Center's own call, answering with nothing."""

    url = "https://edocuments.statefarm.com/DocumentCenterUI/"

    def __init__(self, per_year=None):
        self.asked = []
        self._per_year = per_year or {}

    def evaluate(self, js, target=None):
        import re as _re
        m = _re.search(r"year=(\d{4})", target or "")
        year = int(m.group(1)) if m else 0
        self.asked.append(year)
        return self._per_year.get(year, {})


def test_the_year_walk_stops_when_the_history_runs_out():
    """His menu only goes back to 2023 and State Farm keeps two years,
    so asking for seven was five calls for nothing."""
    from datetime import date
    this_year = date.today().year
    url = f"https://edocuments.statefarm.com/DocumentCenterProxyV1/customerMetadata?year={this_year}"
    page = _YearPage()
    site._years_from(page, url, this_year)
    assert len(page.asked) == 2, f"stopped after two empty years, asked {page.asked}"
    assert this_year not in page.asked, "the year the page already loaded is not asked for again"


def test_a_year_with_documents_in_it_does_not_end_the_walk():
    from datetime import date
    this_year = date.today().year
    one = {"data": {"attributes": [{"creationDate": "2026-06-12", "type": "Renewal Notice",
                                    "category": "Auto", "documentId": "abc123",
                                    "filePathUrl": "/docs/abc123.pdf"}]}}
    page = _YearPage({this_year - 1: one, this_year - 2: one})
    url = f"https://edocuments.statefarm.com/DocumentCenterProxyV1/customerMetadata?year={this_year}"
    got = site._years_from(page, url, this_year)
    assert len(page.asked) == 4, page.asked
    assert len(got) == 2


def test_a_document_with_no_file_address_says_so_rather_than_writing_an_empty_trace():
    """His download-attempt file had an empty list of responses in it,
    which reads the same as a run that never started."""
    import inspect
    src = inspect.getsource(site.download_bill)
    assert "gave no file address" in src
    assert "no control on the page carries this date" in src
    assert "_control_dates(page)" in src


def test_the_trace_says_which_dates_the_page_did_carry():
    class _NoControls:
        url = "https://edocuments.statefarm.com/DocumentCenterUI/"

        def get_by_role(self, *a, **k):
            class _L:
                def count(self_): return 0
                def nth(self_, i): return self_
                def or_(self_, other): return self_
            return _L()
    assert site._control_dates(_NoControls()) == []


# -- round five, written from the member's recording (#37) --------------------

def test_a_row_keeps_its_documents_folded_away_behind_its_own_button():
    """The recording's second step. Before it there is no document link
    on the page at all, and expand_all does not press this because its
    name is not "view more" or "view all"."""
    for name in ("View Documents", "View Documents2", "view document", "View Documents 3"):
        assert site.VIEW_DOCUMENTS_RE.match(name), name
    for name in ("View Documents & PDFs", "Documents (excludes claims)", "View"):
        assert not site.VIEW_DOCUMENTS_RE.match(name), name
    import inspect
    assert "reveal_documents(page)" in inspect.getsource(site.collect_download_docs)


def test_a_document_named_after_what_it_is_counts_as_a_document():
    """The recording's third step opened "Renewal Notice - <year make
    model>", which every pattern the app had would have walked past."""
    for name in ("Renewal Notice - <year make model>", "Renewal Notice - 2019 Toyota Camry",
                 "Declarations Page", "Policy Documents", "ID Cards", "Billing Statement"):
        assert site.BILL_CONTROL_RE.search(name), name
        assert site.is_safe_control(name), name


def test_widening_it_let_nothing_dangerous_through():
    for name in ("Pay bill", "File a claim", "Report a claim", "Change coverage",
                 "Start a quote", "Add a vehicle", "Cancel policy", "Renew now",
                 "Manage autopay", "Update address", "Contact my agent"):
        assert not site.is_safe_control(name), name


def test_the_reveal_presses_nothing_the_guard_refuses():
    import inspect
    src = inspect.getsource(site.reveal_documents)
    assert "is_safe_control(label)" in src
    assert "VIEW_DOCUMENTS_RE.match(label)" in src


def test_a_document_is_dated_when_it_was_made_not_how_long_it_stays_up():
    """A tester found one filed under 2028, from "Sent by mail. Available
    online until 07/21/2028" under its title, while the page's own
    controls carried 2026 dates for the same documents (#37)."""
    made = {"data": {"attributes": [{
        "creationDate": "2026-07-22", "availableDate": "2028-07-21",
        "type": "Renewal Notice", "category": "Auto"}]}}
    [doc] = site._docs_from_api(made)
    assert doc["date"] == "2026-07-22"


def test_a_document_with_only_an_availability_date_is_left_out_rather_than_misdated():
    """0.34.0 still fell back to availableDate when creationDate was
    missing, which is the 2028 date his next Pilot went looking for (#37).
    A document must never be filed under the wrong date."""
    only = {"data": {"attributes": [{
        "availableDate": "2028-07-21", "type": "Declarations", "category": "Auto"}]}}
    assert site._docs_from_api(only) == []


def test_a_document_dated_in_the_future_is_never_listed():
    """No document is issued in 2028. A date like that came from the wrong
    field, whichever field it was (#37)."""
    from datetime import date, timedelta
    ahead = (date.today() + timedelta(days=400)).isoformat()
    body = {"data": {"attributes": [
        {"creationDate": ahead, "type": "Renewal Notice", "category": "Auto"},
        {"creationDate": "2026-09-12", "type": "Payment Receipt", "category": "Billing/Payments"}]}}
    assert [d["date"] for d in site._docs_from_api(body)] == ["2026-09-12"]
    assert site.is_future(ahead)
    assert not site.is_future(date.today().isoformat())
    assert not site.is_future((date.today() + timedelta(days=1)).isoformat()), "a clock a day apart"
    assert not site.is_future("not a date")


# -- round seven, his 0.34.0 Pilot (#37) --------------------------------------

def test_records_an_older_version_dated_2028_are_forgotten_on_discovery():
    """0.33.0 left documents in discovery.json under their 2028 availability
    date. They sorted newest, so his 0.34.0 Pilot tried them first and went
    looking for 2028 on a page that only carries 2026 (#37)."""
    import statefarm_docs
    records = {
        "Statement:2028-06-12:Payment Receipt - Billing/Payments:": {"date": "2028-06-12", "state": "needs_manual_review"},
        "Statement:2026-09-12:Payment Receipt - Billing/Payments:": {"date": "2026-09-12", "state": "discovered"},
        "Insurance:2028-07-21:kept:": {"date": "2028-07-21", "downloaded_ok": True},
    }
    assert statefarm_docs.drop_future_records(records) == 1
    assert sorted(r["date"] for r in records.values()) == ["2026-09-12", "2028-07-21"], \
        "a record that was ever downloaded is kept, so a deleted file never comes back"


def test_a_future_date_is_never_selected_for_download():
    """Resume reads discovery.json without discovering first, so the stale
    2028 records have to be refused where documents are chosen too (#37)."""
    import types
    import statefarm_docs
    app = statefarm_docs.App.__new__(statefarm_docs.App)
    app.args = types.SimpleNamespace(type=None, year=None, start_date=None, end_date=None)
    app.config = {}
    future = statefarm_docs.Document(title="Payment Receipt - Billing/Payments",
                                     category=doc_types.STATEMENT, date="2028-06-12")
    real = statefarm_docs.Document(title="Payment Receipt - Billing/Payments",
                                   category=doc_types.STATEMENT, date="2026-09-12")
    assert app._in_scope(real)
    assert not app._in_scope(future)


def test_a_revealed_document_is_recognized_by_its_name():
    """His Pilot pressed "View Documents1" and "Payment Receipt - Payment
    Receipt" appeared, and nothing pressed it (#37). The recording showed
    "Renewal Notice - <year make model>" in the same place."""
    for name in ("Payment Receipt - Payment Receipt", "Renewal Notice - 2019 Toyota Camry",
                 "Renewal Notice - <year make model>", "Auto ID Card - 2019 SEDAN",
                 "Declarations Page - Homeowners"):
        assert site.is_revealed_document(name), name
    for name in ("View Documents 1", "View Documents1", "Payment Receipt",
                 "Documents (excludes claims)", "View documents & PDFs", ""):
        assert not site.is_revealed_document(name), name


def test_a_revealed_control_that_pays_or_changes_anything_is_refused():
    for name in ("Pay Now - Payment Receipt", "Make a payment - Auto", "File a claim - Auto",
                 "Change coverage - Auto", "Cancel policy - Auto", "Autopay - Enroll",
                 "Update address - Home", "Contact my agent - Auto", "Sign in - Auto",
                 "Insurance Card - Replace"):
        assert not site.is_revealed_document(name), name


def test_the_document_pressed_is_the_one_of_the_wanted_type():
    """A row can hold several documents, and pressing the wrong one would
    save it under this document's name and date."""
    assert site._type_key("Payment Receipt - Billing/Payments") == site._type_key(
        "Payment Receipt - Payment Receipt") == "paymentreceipt"

    class _Nothing:
        def get_by_role(self, *a, **k):
            raise AssertionError("nothing is looked for when the choice is not clear")
        locator = get_by_role

    two = {"Renewal Notice - 2019 SEDAN", "Renewal Notice - 2020 COUPE"}
    el, _, why = site._revealed_document(_Nothing(), two, "Renewal Notice - Auto")
    assert el is None and "2 revealed" in why
    el, _, why = site._revealed_document(_Nothing(), {"ID Card - 2019 SEDAN"}, "Renewal Notice - Auto")
    assert el is None and "0 revealed" in why
    el, _, why = site._revealed_document(_Nothing(), set(), "Renewal Notice - Auto")
    assert el is None and "nothing" in why


def test_the_download_opens_the_wanted_row_once_and_never_every_row():
    """Opening every row and then pressing the wanted row again pressed the
    same button twice, which folds the row away (#37)."""
    import inspect
    src = inspect.getsource(site.download_bill)
    assert "reveal_documents(page)" not in src
    assert "_open_row_then_document(" in src
    opener = inspect.getsource(site._open_row_then_document)
    assert opener.count(".click(") == 1, "the row's button is pressed once"
