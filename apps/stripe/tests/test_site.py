"""Stripe, the site layer. The guard, the host allowlist, row reading,
list capture and paging, and the download, all against made-up answers.
No real account, no network."""
import base64
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import stripe_site as site
from paperpull_core import doc_types

ACCT = "https://dashboard.stripe.com/acct_TEST123"
PDF = b"%PDF-1.4 fake"


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Stripe"
    assert storage.SPEC.routes == {"Statement": "statements", "Tax Document": "tax_documents"}
    assert storage.SPEC.config_defaults["document_types"] == ["Statement", "Tax Document"]


@pytest.mark.parametrize("title,category,summary", [
    ("Fee Invoice INV-0042", "Statement", "Fee Invoice"),
    ("1099-K Tax Form 2031", "Tax Document", "1099-K Tax Form"),
    ("Tax Form 2031", "Tax Document", "Tax Form"),
])
def test_the_titles_discovery_writes_classify(title, category, summary):
    got = doc_types.classify_document(title, doc_types.load_rules())
    assert (got[0], got[1]) == (category, summary)


def test_an_invoice_row_is_read_the_way_the_dashboard_reads_it():
    # Jan 1 2031 to Feb 1 2031 exclusive, as unix seconds.
    row = {"token": "tok_a", "description": "Stripe fees", "invoiceNumber": "INV-0042",
           "periodStartInclusive": 1924992000, "periodEndExclusive": 1927670400,
           "created": 1927700000, "type": "VatInvoice", "status": "paid",
           "link": "https://files.stripe.com/links/abc"}
    assert site.invoice_doc(row) == {"kind": "invoice", "id": "tok_a", "date": "2031-01-31",
                                     "title": "Fee Invoice INV-0042",
                                     "link": "https://files.stripe.com/links/abc"}
    snake = {"id": "inv_b", "invoice_number": "INV-7", "period_end_exclusive": 1927670400}
    assert site.invoice_doc(snake)["date"] == "2031-01-31"
    assert site.invoice_doc({"id": "inv_c", "created": 1927700000})["title"] == "Fee Invoice"
    assert site.invoice_doc({"invoiceNumber": "no id"}) is None


def test_a_link_off_stripe_is_never_taken():
    assert site.row_link({"link": "https://evil.test/x.pdf"}) == ""
    assert site.row_link({"link": "http://files.stripe.com/x"}) == ""
    assert site.row_link({"file": {"url": "https://files.stripe.com/f"}}) == "https://files.stripe.com/f"
    assert site.row_link({"pdf": {"download_url": "https://dashboard.stripe.com/d"}}) == \
        "https://dashboard.stripe.com/d"


@pytest.mark.parametrize("row,form,year", [
    ({"id": "td_1", "form_type": "us_1099_k", "tax_year": 2031}, "1099-K", 2031),
    ({"id": "td_2", "type": "1099-MISC", "year": "2030"}, "1099-MISC", 2030),
    ({"id": "td_3", "description": "Form 1099-K for 2029"}, "1099-K", None),
    ({"id": "td_4", "type": "something_else", "tax_year": 1800}, "Tax Form", None),
])
def test_a_tax_form_row_is_read_by_looking_for_its_fields(row, form, year):
    assert site.tax_form_name(row) == form
    assert site.tax_year(row) == year


def test_a_tax_form_is_dated_by_its_year():
    d = site.tax_doc({"id": "td_1", "form_type": "us_1099_k", "tax_year": 2031,
                      "file": {"url": "https://files.stripe.com/t"}})
    assert d == {"kind": "tax", "id": "td_1", "date": "2031-12-31",
                 "title": "1099-K Tax Form 2031", "link": "https://files.stripe.com/t"}


def test_unix_dates_outside_reason_are_refused():
    assert site.iso_from_unix(1927670400) == "2031-02-01"
    assert site.iso_from_unix(12) == ""
    assert site.iso_from_unix("1927670400") == ""
    assert site.iso_from_unix(True) == ""


def test_the_account_part_is_read_only_from_the_dashboard():
    assert site.account_path(ACCT + "/settings/documents") == "/acct_TEST123"
    assert site.account_path("https://evil.test/acct_TEST123/x") == ""
    assert site.account_path("https://dashboard.stripe.com/login") == ""


def test_the_next_page_keeps_the_query_and_replaces_the_cursor():
    url = "https://dashboard.stripe.com/v1/x?include_only%5B%5D=data&starting_after=old"
    q = parse_qs(urlparse(site.cursor_url(url, "inv_9")).query)
    assert q == {"include_only[]": ["data"], "starting_after": ["inv_9"]}


class _Req:
    def __init__(self, headers):
        self._h = headers

    def all_headers(self):
        return dict(self._h)


class _Resp:
    def __init__(self, url, body, status=200, headers=None):
        self.url, self._body, self.status = url, body, status
        self.request = _Req(headers or {"stripe-version": "v", "cookie": "secret", "x-stripe-csrf-token": "t"})

    def json(self):
        return self._body


class _Page:
    """A signed-in Dashboard tab. Opening a list page makes it receive the
    scripted answer for that page. Its fetch answers from a script too."""

    def __init__(self, lists, fetches=None):
        self.url = ACCT + "/dashboard"
        self.lists, self.fetches = lists, fetches or {}
        self.listeners, self.fetched = [], []

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        self.url = url
        path = urlparse(url).path.split("/", 2)[2]
        for resp in self.lists.get("/" + path, []):
            for fn in list(self.listeners):
                fn(resp)

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, args):
        url, headers = args
        self.fetched.append((url, headers))
        return self.fetches[url]


INV_API = "https://dashboard.stripe.com" + site.INVOICES_API + "?include_only%5B%5D=data"
TAX_API = "https://dashboard.stripe.com" + site.TAX_API


def _lists(invoices, tax, has_more=False):
    return {site.INVOICES_PATH: [_Resp(INV_API, {"data": invoices, "has_more": has_more})],
            site.TAX_PATH: [_Resp(TAX_API, {"object": "list", "data": tax, "has_more": False})]}


def test_discovery_keeps_what_each_page_received_and_pages_to_the_end():
    first = [{"id": "inv_2", "invoiceNumber": "INV-2", "periodEndExclusive": 1927670400,
              "link": "https://files.stripe.com/2"}]
    second = [{"id": "inv_1", "invoiceNumber": "INV-1", "periodEndExclusive": 1924992000,
               "link": "https://files.stripe.com/1"}]
    page = _Page(_lists(first, [{"id": "td_1", "form_type": "us_1099_k", "tax_year": 2030}], has_more=True),
                 {site.cursor_url(INV_API, "inv_2"): {"status": 200, "url": INV_API,
                                                          "json": {"data": second, "has_more": False}}})
    docs = site.collect_download_docs(page)
    assert [(d.title, d.date_text, d.document_id) for d in docs] == [
        ("Fee Invoice INV-2", "2031-01-31", "inv_2"),
        ("1099-K Tax Form 2030", "2030-12-31", "td_1"),
        ("Fee Invoice INV-1", "2030-12-31", "inv_1"),
    ]
    # The page's own headers went with the next page, the cookie did not.
    sent = page.fetched[0][1]
    assert "cookie" not in sent and sent["x-stripe-csrf-token"] == "t"
    assert page.listeners == []


def test_an_empty_account_lists_nothing_and_says_so_in_diagnose():
    page = _Page(_lists([], []))
    assert site.collect_download_docs(page) == []
    report = site.survey(page)
    assert report["api"]["invoice"]["received"] and report["api"]["invoice"]["rows"] == 0
    assert report["api"]["tax"]["rows"] == 0


def test_diagnose_carries_shapes_never_values():
    row = {"id": "inv_SECRET", "invoiceNumber": "INV-SECRET-99", "link": "https://files.stripe.com/SECRET"}
    page = _Page(_lists([row], []))
    report = site.survey(page)
    assert "SECRET" not in repr(report["api"]["invoice"]["shape"])
    assert report["api"]["invoice"]["rows_with_a_link"] == 1
    assert [d.document_id for d in site.collect_documents(page)] == [""]


def test_a_sign_in_page_stops_the_run():
    page = _Page({})
    page.url = "https://dashboard.stripe.com/login"
    with pytest.raises(site.SessionExpired):
        site.capture_list(page, site.INVOICES_PATH, site.INVOICES_API)
    page = _Page({site.INVOICES_PATH: [_Resp(INV_API, {"error": {}}, status=401)]})
    with pytest.raises(site.SessionExpired):
        site.capture_list(page, site.INVOICES_PATH, site.INVOICES_API)


def test_the_download_fetches_a_fresh_link_and_writes_only_a_pdf(tmp_path):
    row = {"id": "inv_1", "periodEndExclusive": 1927670400, "link": "https://files.stripe.com/new"}
    page = _Page(_lists([row], []), {"https://files.stripe.com/new": {
        "status": 200, "ct": "application/pdf", "url": "https://files.stripe.com/new",
        "b64": base64.b64encode(PDF).decode()}})
    site._cache.update(at=0.0, docs=[])
    out = tmp_path / "i.pdf"
    assert site.download_bill(page, None, "2031-01-31", out, href="https://files.stripe.com/old",
                              document_id="inv_1")
    assert out.read_bytes() == PDF
    assert page.fetched[-1][0] == "https://files.stripe.com/new"


def test_something_that_is_not_a_pdf_is_not_saved(tmp_path):
    page = _Page(_lists([], []), {"https://files.stripe.com/x": {
        "status": 200, "ct": "text/html", "url": "https://files.stripe.com/x"}})
    site._cache.update(at=0.0, docs=[])
    out = tmp_path / "x.pdf"
    assert not site.download_bill(page, None, "2031-01-31", out, href="https://files.stripe.com/x")
    assert not out.exists()


def test_a_tax_id_step_is_never_answered(tmp_path):
    page = _Page(_lists([], []), {"https://dashboard.stripe.com/v1/tax_documents/td_1/download": {
        "status": 200, "ct": "application/json", "url": "https://dashboard.stripe.com/v1/tax_documents/td_1/download",
        "json": {"challenge": {"type": "tin"}}}})
    site._cache.update(at=0.0, docs=[])
    with pytest.raises(site.NeedsPerson):
        site.download_bill(page, None, "2031-12-31", tmp_path / "t.pdf",
                           href="https://dashboard.stripe.com/v1/tax_documents/td_1/download")


def test_a_form_with_no_link_goes_to_the_person(tmp_path):
    page = _Page(_lists([], [{"id": "td_9", "form_type": "us_1099_k", "tax_year": 2031}]))
    site._cache.update(at=0.0, docs=[])
    with pytest.raises(site.NeedsPerson):
        site.download_bill(page, None, "2031-12-31", tmp_path / "t.pdf", document_id="td_9")


def test_the_fetch_refuses_any_other_host():
    with pytest.raises(ValueError):
        site._get(_Page({}), "https://evil.test/v1/files")


def test_moving_money_and_account_controls_are_never_safe():
    for name in ["Pay out funds", "Payouts", "New payout", "Create payment", "Refund", "Create",
                 "Regenerate PDF", "Reveal live key", "API keys", "Developers", "Add bank account",
                 "Enter your TIN", "Verify tax ID", "Settings", "Close account", "Invite team member",
                 "Switch to sandbox", "Log out", "Change password", "Top-ups"]:
        assert not site.is_safe_control(name), name


def test_reading_a_document_is_safe():
    for name in ["Download", "Invoice history", "Download PDF", "Tax forms", "View document"]:
        assert site.is_safe_control(name), name


def test_only_stripe_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://dashboard.stripe.com/acct_x/settings/documents")
    assert site.is_safe_url("https://files.stripe.com/links/abc")
    assert not site.is_safe_url("http://dashboard.stripe.com/")
    assert not site.is_safe_url("https://stripe.com.example/")
    assert not site.is_safe_url("https://notstripe.com/")
    assert not site.is_safe_url("https://api.hcaptcha.com/")
    assert not site.is_safe_url("https://user:pw@dashboard.stripe.com/")
