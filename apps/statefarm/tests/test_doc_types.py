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


def test_the_confirmed_status_is_stated_where_a_tester_will_read_it():
    """His full run saved every document State Farm lists for his
    policies (#37)."""
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "STATUS: CONFIRMED on the tester's account" in src.split('"""')[1]
    assert "UNVERIFIED" not in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert readme.split("\n\n")[1].startswith("**Working on the tester's account.**")
    assert "Not yet tested" not in readme


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
        {"creationDate": "03/14/2026", "category": "Auto", "type": "Renewal Notice",
         "description": "Renewal Notice - 2019 SEDAN 1HGCM82633A123456", "documentId": "d1",
         "filePathUrl": "/DocumentCenterProxyV1/document/d1", "policyId": "p1"},
        {"creationDate": "05/08/2026", "category": "Billing/Payments", "type": "Payment Receipt",
         "description": "Payment Receipt - Payment Receipt", "documentId": "d2", "filePathUrl": ""},
        {"creationDate": "03/14/2026", "category": "Auto", "type": "ID Card", "description": "ID Card - 2019 SEDAN",
         "documentId": "d3", "filePathUrl": "/x/d3"},
        {"type": "no date"},
    ]}}
    got = site._docs_from_api(body)
    assert [(d["date"], d["title"], d["hint"], d["url"]) for d in got] == [
        ("2026-03-14", "Renewal Notice - Auto", "d1", "/DocumentCenterProxyV1/document/d1"),
        ("2026-05-08", "Payment Receipt - Billing/Payments", "d2", ""),
        ("2026-03-14", "ID Card - Auto", "d3", "/x/d3")]
    assert "1HGCM82633A123456" not in got[0]["desc"], "a VIN in the description is masked"
    assert site._docs_from_api({}) == []


def test_the_year_is_the_only_thing_changed_in_the_metadata_address():
    from datetime import date
    this_year = date.today().year
    calls = []
    class _P:
        def evaluate(self, js, url):
            calls.append(url)
            return {"status": 200, "type": "application/json", "body": {"data": {"attributes": [
                {"creationDate": "01/05/" + url[-4:], "type": "Bill", "category": "Auto"}]}}}
    got = site._years_from(_P(), "https://documentcenterproxyv1-prod.statefarm.com/DocumentCenterProxyV1/"
                                 "customerMetadata?commId=null&year=%d" % this_year, this_year)
    assert calls[0].endswith("year=%d" % (this_year - 1)) and all("year=" in c for c in calls)
    assert len(calls) == site.YEARS_BACK and got[0]["date"] == "%d-01-05" % (this_year - 1)
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
        return {"status": 200, "type": "application/json", "body": self._per_year.get(year, {})}


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
    one = {"data": {"attributes": [{"creationDate": "2026-02-03", "type": "Renewal Notice",
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
    """A tester found one filed under 2028, from the "Available online
    until" line under its title, while the page's own controls carried
    2026 dates for the same documents (#37)."""
    made = {"data": {"attributes": [{
        "creationDate": "2026-03-14", "availableDate": "2028-03-13",
        "type": "Renewal Notice", "category": "Auto"}]}}
    [doc] = site._docs_from_api(made)
    assert doc["date"] == "2026-03-14"


def test_a_document_with_only_an_availability_date_is_left_out_rather_than_misdated():
    """0.34.0 still fell back to availableDate when creationDate was
    missing, which is the 2028 date his next Pilot went looking for (#37).
    A document must never be filed under the wrong date."""
    only = {"data": {"attributes": [{
        "availableDate": "2028-03-13", "type": "Declarations", "category": "Auto"}]}}
    assert site._docs_from_api(only) == []


def test_a_document_dated_in_the_future_is_never_listed():
    """No document is issued in 2028. A date like that came from the wrong
    field, whichever field it was (#37)."""
    from datetime import date, timedelta
    ahead = (date.today() + timedelta(days=400)).isoformat()
    body = {"data": {"attributes": [
        {"creationDate": ahead, "type": "Renewal Notice", "category": "Auto"},
        {"creationDate": "2026-05-08", "type": "Payment Receipt", "category": "Billing/Payments"}]}}
    assert [d["date"] for d in site._docs_from_api(body)] == ["2026-05-08"]
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
        "Statement:2028-02-19:Payment Receipt - Billing/Payments:": {"date": "2028-02-19", "state": "needs_manual_review"},
        "Statement:2026-05-08:Payment Receipt - Billing/Payments:": {"date": "2026-05-08", "state": "discovered"},
        "Insurance:2028-03-13:kept:": {"date": "2028-03-13", "downloaded_ok": True},
    }
    assert statefarm_docs.drop_future_records(records) == 1
    assert sorted(r["date"] for r in records.values()) == ["2026-05-08", "2028-03-13"], \
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
                                     category=doc_types.STATEMENT, date="2028-02-19")
    real = statefarm_docs.Document(title="Payment Receipt - Billing/Payments",
                                   category=doc_types.STATEMENT, date="2026-05-08")
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


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def update(self, key, value, save=True):
        self.data.setdefault(key, {}).update(value)

    def save(self, backup=False):
        pass


def _bare_app():
    """An App with no browser, no files and no config behind it."""
    import types
    import statefarm_docs
    app = statefarm_docs.App.__new__(statefarm_docs.App)
    app.args = types.SimpleNamespace(start_date=None)
    app.config = {}
    app.rules = RULES
    app.stats = {"skipped_out_of_scope": 0}
    app.discovery = _Store()
    return app


def test_discovery_keeps_the_file_address_the_list_gave():
    """Every download-attempt.json he sent said "neither an id nor an
    address" while the list's own shape carried documentId and filePathUrl
    on every entry. Discovery read them and then dropped them, so the
    download never had either (#37)."""
    import statefarm_docs
    app = _bare_app()
    raw = site.RawDoc(title="Renewal Notice - Auto", account="Auto", date_text="2026-03-14",
                      href="/DocumentCenterProxyV1/document/invented-one", kind="statement")
    assert app._record_rawdoc(raw, site.BILLING_URL) == 1
    [rec] = app.discovery.data.values()
    assert rec["href"] == "/DocumentCenterProxyV1/document/invented-one"
    assert statefarm_docs.Document.from_dict(rec).href == rec["href"]
    # A record an earlier version discovered without it gets it on the next Discover.
    rec["href"] = ""
    assert app._record_rawdoc(raw, site.BILLING_URL) == 0
    assert rec["href"] == "/DocumentCenterProxyV1/document/invented-one"


def test_a_fetch_failure_is_traced_as_a_fixed_phrase():
    """The error text can carry the address, which is not for a trace."""
    assert site._fetch_failure(Exception("TypeError: Failed to fetch https://x.statefarm.com/d/abc")) \
        == "the browser could not fetch it"
    assert site._fetch_failure(Exception("Refusing an off-host document request")) \
        == "the address is off statefarm.com"
    assert "statefarm.com/d" not in site._fetch_failure(Exception("boom https://x.statefarm.com/d/abc"))
    assert [site._answer_kind(b) for b in (b"", b"  <html>", b'{"a": 1}', b"%PDF")] == \
        ["nothing", "html", "json", "other"]


def test_the_download_opens_the_wanted_row_once_and_never_every_row():
    """Opening every row and then pressing the wanted row again pressed the
    same button twice, which folds the row away (#37)."""
    import inspect
    src = inspect.getsource(site.download_bill)
    assert "reveal_documents(page)" not in src
    assert "_open_row_then_document(" in src
    opener = inspect.getsource(site._open_row_then_document)
    assert opener.count(".click(") == 1, "the row's button is pressed once"


# -- round eight, repair after review (#37) ------------------------------------

def test_the_year_walk_says_what_each_year_answered():
    """Discovery has found the current year only in every round since
    0.33.0, and the walk wrote why to the log alone. A refusal, a year
    with nothing in it and a fetch the browser would not make now read
    differently, in facts."""
    import json
    from datetime import date
    this_year = date.today().year
    url = f"https://edocuments.statefarm.com/DocumentCenterProxyV1/customerMetadata?year={this_year}"

    class _Refused(_YearPage):
        def evaluate(self, js, target=None):
            super().evaluate(js, target)
            return {"status": 403, "type": "text/html; charset=utf-8"}
    facts = {}
    assert site._years_from(_Refused(), url, this_year, facts) == []
    assert facts["years"] == [
        {"year": this_year - 1, "status": 403, "type": "html", "listed": 0, "kept": 0},
        {"year": this_year - 2, "status": 403, "type": "html", "listed": 0, "kept": 0}]
    assert facts["stopped"] == "two years running with nothing in them"

    class _Blocked(_YearPage):
        def evaluate(self, js, target=None):
            super().evaluate(js, target)
            raise Exception("TypeError: Failed to fetch " + (target or ""))
    facts = {}
    site._years_from(_Blocked(), url, this_year, facts)
    assert [y.get("failed") for y in facts["years"]] == \
        ["the browser could not fetch it"] * site.YEARS_BACK
    assert facts["stopped"] == "asked every year back to the limit"
    assert "customerMetadata" not in json.dumps(facts)

    one_dated = {"data": {"attributes": [
        {"creationDate": "2026-02-03", "type": "Bill", "category": "Auto"}, {"type": "undated"}]}}
    facts = {}
    site._years_from(_YearPage({this_year - 1: one_dated}), url, this_year, facts)
    assert facts["years"][0] == {"year": this_year - 1, "status": 200, "type": "json",
                                 "listed": 2, "kept": 1}

    facts = {}
    site._years_from(_YearPage(), "https://x.statefarm.com/customerMetadata?commId=null", -1, facts)
    assert facts == {"years": [], "stopped": "the list's address carries no year to change"}


def _two_that_share_a_key():
    first = site.RawDoc(title="Renewal Notice - Auto", account="Auto", date_text="2026-03-14",
                        href="/DocumentCenterProxyV1/document/invented-first")
    second = site.RawDoc(title="Renewal Notice - Auto", account="Auto", date_text="2026-03-14",
                         href="/DocumentCenterProxyV1/document/invented-second")
    return first, second


def test_two_documents_that_share_a_key_keep_neither_address():
    """Two renewal notices issued the same day have one key, and the key
    cannot change because it is what remembers a download. Keeping the
    address that came last would fetch one of the two under a record that
    stands for both, so neither is kept and the download says why."""
    import statefarm_docs
    app = _bare_app()
    first, second = _two_that_share_a_key()
    app._begin_discovery_pass()
    assert app._record_rawdoc(first, site.BILLING_URL) == 1
    [key] = list(app.discovery.data)
    assert app._record_rawdoc(second, site.BILLING_URL) == 0
    assert list(app.discovery.data) == [key], "the key does not change"
    rec = app.discovery.data[key]
    assert rec["href"] == "" and rec["shared_key"] is True
    assert statefarm_docs.Document.from_dict(rec).shared_key
    # A third read of the same entry in the same pass does not bring one back.
    app._record_rawdoc(first, site.BILLING_URL)
    assert rec["href"] == ""
    # The next read of the list holds only one of them, which gets its address.
    app._begin_discovery_pass()
    app._record_rawdoc(first, site.BILLING_URL)
    assert rec["href"] == first.href and rec["shared_key"] is False


def test_discover_starts_a_fresh_pass_and_keeps_what_the_list_read_said(monkeypatch):
    app = _bare_app()
    app.page = lambda: object()
    app.check_session = lambda page: None
    first, second = _two_that_share_a_key()
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def collect(page, facts=None):
        facts["page_list_answers"] = 1
        return [first, second]
    monkeypatch.setattr(site, "collect_download_docs", collect)
    app._shared_this_pass = {"a key an earlier read shared"}
    app.cmd_discover(quiet=True)
    assert app._discovery_facts == {"page_list_answers": 1, "found": 2, "sharing_a_key": 1}


def test_the_attempt_file_is_built_from_facts():
    """download-attempt.json is posted on a public issue. Where the page
    ended up is facts about its address, and how the list was read goes
    with it."""
    import json
    import statefarm_docs
    app = _bare_app()
    app._discovery_facts = {"page_list_answers": 1, "stopped": "asked every year back to the limit",
                            "years": [{"year": 2025, "failed": "the browser could not fetch it"}]}

    class _Page:
        url = "https://edocuments.statefarm.com/DocumentInformationUI/view/Jane_Q_Invented?t=abc"
    doc = statefarm_docs.Document(title="Renewal Notice - Auto", date="2026-03-14")
    got = app._attempt_report(doc, _Page(), [{"note": "an entry"}])
    written = json.dumps(got)
    assert "Jane_Q_Invented" not in written and "t=abc" not in written
    assert got["landed_on"]["starts_with"] == "DocumentInformationUI" and got["landed_on"]["has_query"]
    assert got["discovery"]["years"][0]["failed"] == "the browser could not fetch it"
    assert got["date"] == "2026-03-14" and got["responses"] == [{"note": "an entry"}]
    del app._discovery_facts
    assert app._attempt_report(doc, _Page(), [])["discovery"] == \
        {"note": "the list was not read in this command"}


class _CenterPage:
    url = "https://edocuments.statefarm.com/DocumentCenterUI/"


def _downloading_app(tmp_path, monkeypatch):
    """An App whose download_one runs for real against a download_bill that
    only says what it was handed, and records what it would write."""
    import types
    app = _bare_app()
    app.config = {"max_path_length": 240}
    app.paths = types.SimpleNamespace(folder_for=lambda cat: tmp_path, diagnostics=tmp_path)
    app._dl_dir = tmp_path
    app._requests = object()
    app.stats.update({"duplicate_filenames": 0, "manual_review": 0})
    app.check_session = lambda page: None
    app.progress = _Store()
    app.rows, app.failures, app.asked = [], [], []
    app._write_row = lambda doc, status, processing: app.rows.append((status, processing))
    app.write_failure = lambda *a, **k: app.failures.append(a)

    def download_bill(page, dl_dir, iso, out, **kw):
        app.asked.append(kw)
        kw["trace"].append({"note": "an entry"})
        return False
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "download_bill", download_bill)
    return app


def test_the_download_is_handed_the_census_and_the_file_address(monkeypatch, tmp_path):
    """The file address and every press of a document happen while the
    run's census is not listening, so the download has to be handed the
    census, and the address discovery kept."""
    import json
    import statefarm_docs
    app = _downloading_app(tmp_path, monkeypatch)
    doc = statefarm_docs.Document(title="Renewal Notice - Auto", category="Statement", date="2026-03-14",
                                  href="/DocumentCenterProxyV1/document/invented-one")
    app.download_one(_CenterPage(), doc, "invented.pdf")
    [kw] = app.asked
    assert kw["census"] is app._requests and kw["hint"] == doc.href and kw["shared"] is False
    assert kw["twins"] == 0
    attempt = json.loads((tmp_path / "download-attempt.json").read_text(encoding="utf-8"))
    assert attempt["landed_on"]["host"] == "edocuments.statefarm.com"
    assert attempt["responses"] == [{"note": "an entry"}]
    assert app.rows == [("Capture failed", "Needs Manual Review")] and len(app.failures) == 1


def test_a_record_that_stands_for_two_documents_goes_to_manual_review_untouched(monkeypatch, tmp_path):
    """Saving either document under it would mark it done for good and the
    other would never be fetched. Nothing is asked of the page, and since
    nothing on the page went wrong it takes neither download-attempt.json
    nor the run's one failure file from a document that did fail. Run
    twice, the way two Pilots would, its note is written once, because each
    run starts from the discovery record and not from the last note."""
    import statefarm_docs
    from paperpull_core.models import State
    app = _downloading_app(tmp_path, monkeypatch)
    rec = statefarm_docs.Document(title="Renewal Notice - Auto", category="Statement",
                                  date="2026-03-14", shared_key=True).to_dict()
    key = statefarm_docs.Document.from_dict(rec).key
    app.discovery.data[key] = rec
    for _ in range(2):
        app.download_one(_CenterPage(), statefarm_docs.Document.from_dict(app.discovery.data[key]),
                         "invented.pdf")
    assert not app.asked, "download_bill was never called"
    assert not (tmp_path / "download-attempt.json").exists() and not app.failures
    done = app.progress.data[key]
    assert done["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert done["notes"] == statefarm_docs.SHARED_NOTE
    assert app.rows == [("Two documents share this record", "Needs Manual Review")] * 2
    assert app.stats["manual_review"] == 2


def test_the_download_is_told_how_many_documents_share_its_date_and_type(monkeypatch, tmp_path):
    """A Renewal Notice for a car and one for a house on one day have
    different records, and the page's rows cannot say which is which. The
    download is told there is another, from the last Discover when one ran,
    so a record the list no longer holds does not count."""
    import statefarm_docs
    app = _downloading_app(tmp_path, monkeypatch)
    records = [statefarm_docs.Document(title=t, category="Statement", date=d)
               for t, d in (("Renewal Notice - Auto", "2026-03-14"),
                            ("Renewal Notice - Homeowners", "2026-03-14"),
                            ("Payment Receipt - Billing/Payments", "2026-03-14"),
                            ("Renewal Notice - Auto", "2026-03-15"))]
    for r in records:
        app.discovery.data[r.key] = r.to_dict()
    car = records[0]
    app.download_one(_CenterPage(), car, "invented.pdf")
    assert app.asked[-1]["twins"] == 1
    # The last Discover saw only the car's notice, so the house's is gone.
    app._idents_this_pass = {car.key: "invented-id-1", records[2].key: "invented-id-2"}
    app.download_one(_CenterPage(), car, "invented.pdf")
    assert app.asked[-1]["twins"] == 0


def test_what_the_list_gave_in_place_of_an_address_is_named_by_its_kind():
    """Anything without a slash in it used to read as "an id". A path with
    backslashes or a bare file name is not one, and the next repair needs
    to know which it was, without the value."""
    assert site._hint_word("") == "neither an id nor an address"
    assert site._hint_word("0f8e7d6c-1a2b-4c3d") == "an id and no address"
    assert site._hint_word("\\\\invented-share\\Jane_Q_Invented\\a.pdf") == \
        "a path written with backslashes, which this app does not ask for"
    assert site._hint_word("Jane_Q_Invented.pdf") == \
        "a file name with no path, which this app does not ask for"
    assert site._hint_word("Jane Q Invented") == "a value that is neither an id nor an address"


def test_discovery_says_how_the_list_answered_in_counts_and_listed_words():
    """Only the current year has been found in every round. Discover now
    says what each earlier year answered, in lines that can be pasted
    into an issue, so every word in them comes from the site's list."""
    import statefarm_docs
    facts = {"page_list_answers": 1, "page_list_listed": 4, "page_list_kept": 3,
             "years": [{"year": 2025, "status": 403, "type": "html", "listed": 0, "kept": 0},
                       {"year": 2024, "failed": "the browser could not fetch it"},
                       {"year": 2023, "status": 200, "type": "json", "listed": 2, "kept": 0,
                        "answer": "not readable as json"}],
             "stopped": "two years running with nothing in them", "sharing_a_key": 1}
    assert statefarm_docs.discovery_lines(facts) == [
        "The page's own read of State Farm's list listed 4 and kept 3, in 1 answer(s).",
        "Year 2025 answered with status 403 and html, listed 0, kept 0.",
        "Year 2024 failed, the browser could not fetch it.",
        "Year 2023 answered with status 200 and json, listed 2, kept 0, not readable as json.",
        "The year walk ended because two years running with nothing in them.",
        "1 record(s) stand for two documents in the list, so neither is saved."]
    assert "No earlier year was asked for." in statefarm_docs.discovery_lines({"page_list_answers": 1})
    odd = {"page_list_listed": "Jane", "stopped": "jane q invented moved away",
           "years": [{"year": "Jane", "status": "403", "type": "application/json; name=jane",
                      "failed": "", "answer": "jane"},
                     {"year": 2025, "failed": "https://edocuments.statefarm.com/Jane_Q_Invented"}]}
    written = " ".join(statefarm_docs.discovery_lines(odd)).lower()
    assert "jane" not in written and "http" not in written and "name=" not in written, written
    assert statefarm_docs.discovery_lines({}) == [] and statefarm_docs.discovery_lines(None) == []


def test_every_word_the_year_walk_writes_is_on_the_list():
    """A phrase added to the walk and not to the list would print as
    "another word" and say nothing."""
    import re as _re
    src = __import__("inspect").getsource(site._years_from)
    for phrase in _re.findall(r'stopped = "([^"]+)"', src) + _re.findall(r'"answer"\] = "([^"]+)"', src):
        assert phrase in site.FACT_WORDS, phrase
    for e in (Exception("Refusing an off-host request"), Exception("Failed to fetch"), Exception("x")):
        assert site._fetch_failure(e) in site.FACT_WORDS
    for ct in ("application/json", "application/pdf", "text/html", "text/xml", "text/plain",
               "image/png", "application/octet-stream", "application/x-invented", ""):
        assert site._kind_of(ct) in site.FACT_WORDS, ct


def test_discover_prints_how_the_list_answered(monkeypatch, capsys):
    app = _bare_app()
    app.page = lambda: object()
    app.check_session = lambda page: None
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def collect(page, facts=None):
        facts.update({"page_list_answers": 1, "page_list_listed": 1, "page_list_kept": 1,
                      "years": [{"year": 2025, "status": 403, "type": "html", "listed": 0, "kept": 0}],
                      "stopped": "two years running with nothing in them"})
        return [site.RawDoc(title="Renewal Notice - Auto", account="Auto", date_text="2026-03-14",
                            href="/DocumentCenterProxyV1/document/invented-one")]
    monkeypatch.setattr(site, "collect_download_docs", collect)
    app.cmd_discover()
    out = capsys.readouterr().out
    assert "Year 2025 answered with status 403 and html, listed 0, kept 0." in out, out
    assert "The year walk ended because two years running with nothing in them." in out, out


def _entry(doc_id, address):
    return {"creationDate": "03/14/2026", "category": "Auto", "type": "Renewal Notice",
            "documentId": doc_id, "filePathUrl": address}


def _read_list(monkeypatch, *entries):
    monkeypatch.setattr(site, "_capture_docs",
                        lambda page: ([{"data": {"attributes": list(entries)}}], [], []))
    return site.collect_download_docs(object())


def _recorded(docs):
    app = _bare_app()
    app._begin_discovery_pass()
    for r in docs:
        app._record_rawdoc(r, site.BILLING_URL)
    [rec] = app.discovery.data.values()
    return rec


def test_one_document_is_one_and_two_documents_are_two(monkeypatch):
    """A document is told from another by its document id, else by its
    address. Folding on the date and title alone hid two documents that
    share them. Folding on the address as well split one document whose
    address differed between two reads, and a record split that way is
    refused for good."""
    one = _read_list(monkeypatch, _entry("invented-id-1", "/DocumentCenterProxyV1/document/a"),
                     _entry("invented-id-1", "/DocumentCenterProxyV1/document/b"))
    assert len(one) == 1
    rec = _recorded(one + one)
    assert rec["shared_key"] is False and rec["href"] == "/DocumentCenterProxyV1/document/a"

    no_ids = _read_list(monkeypatch, _entry("", "/DocumentCenterProxyV1/document/a"),
                        _entry("", "/DocumentCenterProxyV1/document/b"))
    assert len(no_ids) == 2
    rec = _recorded(no_ids)
    assert rec["shared_key"] is True and rec["href"] == ""

    # Two ids and one address is still two documents, and the one address
    # would be fetched for a record that stands for both.
    one_address = _read_list(monkeypatch, _entry("invented-id-1", "/DocumentCenterProxyV1/document/a"),
                             _entry("invented-id-2", "/DocumentCenterProxyV1/document/a"))
    assert len(one_address) == 2
    rec = _recorded(one_address)
    assert rec["shared_key"] is True and rec["href"] == ""


# -- round nine, his 0.37.1 Pilot (#37) ------------------------------------------

_LIST = "https://edocuments.statefarm.com/DocumentCenterProxyV1/customerMetadata"


def test_the_year_in_the_list_address_is_set_whatever_it_held():
    """His Discover said the list's address carries no year to change, while
    his census showed the page's own call carrying year in its query. It
    held something other than four digits, and only four digits used to be
    changed. Whatever it holds is set now, and nothing else in the address
    changes."""
    for held in ("", "0", "12", "-1", "2026", "recent"):
        assert site._with_year(_LIST + "?year=" + held, 2025) == _LIST + "?year=2025", held
    assert site._with_year(_LIST + "?commId=null&year=&v=2", 2024) == _LIST + "?commId=null&year=2024&v=2"
    assert site._with_year(_LIST + "?year=#rows", 2023) == _LIST + "?year=2023#rows"
    assert site._with_year(_LIST + "?commId=null", 2025) is None
    assert site._with_year(_LIST + "?year=1&year=2", 2025) is None, "two years cannot say which is meant"
    assert site._with_year(_LIST + "?fiscalyear=2026", 2025) is None
    assert site._four_digit_year(_LIST + "?year=2026") == 2026
    assert site._four_digit_year(_LIST + "?year=") == site._four_digit_year(_LIST) == -1


def test_what_the_year_held_is_said_in_a_fixed_phrase_and_never_as_itself():
    """The census keeps only the parameter's name and the recording masked
    its value, so no file has said what the page sends. A phrase from the
    list says which kind of value it was."""
    for query, word in (("?year=", "left empty"), ("?year=0", "a number that is not a four digit year"),
                        ("?year=2026", "a four digit year"), ("?year=Jane%20Q", "some other value"),
                        ("?commId=null", "not there"), ("?year=1&year=2", "there more than once")):
        assert site._year_word(_LIST + query) == word, query
        assert word in site.FACT_WORDS, word


def test_only_the_pages_own_get_of_its_list_on_statefarm_is_asked_for_another_year():
    """The reload for an older document changes the year of the page's own
    list call and nothing else. The list is only ever read, so nothing but
    a GET is changed, and never to an address off statefarm.com."""
    assert site._list_call_for_year("GET", _LIST + "?year=", 2025) == _LIST + "?year=2025"
    assert site._list_call_for_year("get", _LIST + "?year=0", 2024) == _LIST + "?year=2024"
    assert site._list_call_for_year("POST", _LIST + "?year=", 2025) is None
    assert site._list_call_for_year("GET", _LIST + "?commId=null", 2025) is None
    assert site._list_call_for_year("GET", _LIST + "?year=1&year=2", 2025) is None
    assert site._list_call_for_year(
        "GET", "https://statefarm.com.evil.test/DocumentCenterProxyV1/customerMetadata?year=", 2025) is None
    assert site._list_call_for_year("GET", _LIST.replace("https:", "http:") + "?year=", 2025) is None


def test_a_download_asks_the_list_for_an_older_documents_year_first():
    """Every document found so far has been in the page's own period, which
    a document from this year keeps first. One from an earlier year is in
    the list of its own year, where the walk finds it."""
    from datetime import date
    this_year = date.today().year
    assert site._years_to_show("%d-03-14" % this_year) == [None, this_year]
    assert site._years_to_show("%d-10-16" % (this_year - 1)) == [this_year - 1, None]
    assert site._years_to_show("") == [None] and site._years_to_show("not a date") == [None]


def test_a_year_that_is_not_four_digits_is_walked_from_this_year_back():
    """The walk stopped before its first year, since there were no four
    digits to change. It asks for this year as well now, since the page's
    own period may not be the whole of it."""
    from datetime import date
    this_year = date.today().year
    one = {"data": {"attributes": [{"creationDate": "01/01/%d" % (this_year - 1), "type": "Renewal Notice",
                                    "category": "Auto", "documentId": "invented"}]}}
    page = _YearPage({this_year: one, this_year - 1: one})
    facts = {}
    got = site._years_from(page, _LIST + "?year=", -1, facts)
    assert page.asked == [this_year, this_year - 1, this_year - 2, this_year - 3], page.asked
    assert len(got) == 2 and facts["stopped"] == "two years running with nothing in them", facts


def test_discovery_says_what_the_year_held_and_what_the_list_gave_as_addresses(monkeypatch):
    """The one document tried in his 0.37.1 file had "an id and no address",
    which an empty filePathUrl and one with no slash in it both give. The
    facts count each kind, and say what the year in the page's own address
    held, with none of their values."""
    import json
    from datetime import date
    this_year = date.today().year
    entries = [{"creationDate": "01/01/%d" % this_year, "type": kind, "category": "Auto",
                "documentId": doc_id, "filePathUrl": address}
               for kind, doc_id, address in (
                   ("Renewal Notice", "invented-1", "/DocumentCenterProxyV1/document/Jane_Q_Invented"),
                   ("ID Card", "invented-2", "Jane_Q_Invented"),
                   ("Declarations Page", "invented-3", ""))]
    monkeypatch.setattr(site, "_capture_docs",
                        lambda page: ([{"data": {"attributes": entries}}], [_LIST + "?year="], [{}]))
    facts = {}
    docs = site.collect_download_docs(_YearPage(), facts)
    assert len(docs) == 3
    assert facts["year_in_address"] is False and facts["year_value"] == "left empty", facts
    assert (facts["with_a_file_address"], facts["with_a_file_address_that_is_not_a_path"],
            facts["with_no_file_address"]) == (1, 1, 1), facts
    assert [y["year"] for y in facts["years"]][:1] == [this_year], facts
    assert "Jane" not in json.dumps(facts)


def test_discover_says_what_the_year_held_and_how_many_came_with_an_address():
    import statefarm_docs
    facts = {"page_list_answers": 1, "page_list_listed": 4, "page_list_kept": 4,
             "year_in_address": False, "year_value": "left empty",
             "years": [{"year": 2026, "status": 200, "type": "json", "listed": 4, "kept": 4}],
             "stopped": "two years running with nothing in them",
             "with_a_file_address": 0, "with_a_file_address_that_is_not_a_path": 1,
             "with_no_file_address": 3}
    lines = statefarm_docs.discovery_lines(facts)
    assert lines[1] == "The year in the page's own list address was left empty.", lines
    assert ("Of the documents the list gave, 0 came with a file address, 1 with one that is not a "
            "path, and 3 with none.") in lines, lines
    odd = dict(facts, year_value="Jane_Q_Invented", with_no_file_address="Jane")
    written = " ".join(statefarm_docs.discovery_lines(odd))
    assert "Jane" not in written and "was another word." in written, written
