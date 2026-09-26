"""FedEx Billing Online, the site layer. The guard, the host allowlist,
reading invoice rows out of answers of unknown shape, the connect-account
stop, and the download, all against made-up answers. No real account, no
network."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import fedex_site as site
from paperpull_core import doc_types

PDF = b"%PDF-1.4 fake"
API = "https://api.fedex.com"


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "FedEx"
    assert storage.SPEC.routes == {"Statement": "statements"}
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


def test_the_title_discovery_writes_classifies():
    got = doc_types.classify_document("Shipping Invoice", doc_types.load_rules())
    assert (got[0], got[1]) == ("Statement", "Shipping Invoice")


@pytest.mark.parametrize("value,iso", [
    ("2031-02-14", "2031-02-14"), ("2031-02-14T00:00:00Z", "2031-02-14"),
    ("02/14/2031", "2031-02-14"), ("2/30/2031", None), ("soon", None),
])
def test_dates_in_the_shapes_an_api_might_use(value, iso):
    assert site.parse_date(value) == iso


def test_unix_dates_in_seconds_or_milliseconds():
    assert site.iso_from_unix(1928534400) == "2031-02-11"
    assert site.iso_from_unix(1928534400000) == "2031-02-11"
    assert site.iso_from_unix(5) == ""
    assert site.iso_from_unix(True) == ""


def test_invoice_rows_are_found_however_deep_the_answer_nests_them():
    answers = [
        {"path": "/bill/v1/accounts/balancesummaries/retrieve", "status": 200,
         "body": {"output": {"balances": [{"amount": 3}]}}},
        {"path": "/bill/v1/invoices/retrieve", "status": 200,
         "body": {"output": {"invoices": [
             {"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14",
              "pdfUrl": "https://www.fedex.com/doc/INV-2.pdf"},
             {"invoiceNumber": "INV-1", "invoiceDate": "01/24/2031"},
             {"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14"},
             {"invoiceNumber": "INV-9", "invoiceDate": "someday"}]}}},
    ]
    docs = site.invoices_in(answers)
    assert [(d["id"], d["date"], d["link"]) for d in docs] == [
        ("INV-2", "2031-02-14", "https://www.fedex.com/doc/INV-2.pdf"),
        ("INV-1", "2031-01-24", "")]
    assert all(d["title"] == "Shipping Invoice" for d in docs)


def test_a_row_that_does_not_look_like_an_invoice_is_left_alone():
    assert site.invoice_doc({"trackingNumber": "1", "shipDate": "2031-02-14"}) is None
    assert site.invoice_doc({"invoiceNumber": "INV-1"}) is None


def test_a_link_off_fedex_is_never_taken():
    assert site.row_link({"pdfUrl": "https://evil.test/x.pdf"}) == ""
    assert site.row_link({"pdfUrl": "http://www.fedex.com/x.pdf"}) == ""
    assert site.row_link({"document": {"url": "https://documentapi.prod.fedex.com/d"}}) == ""
    assert site.row_link({"documentUrl": {"url": "https://documentapi.prod.fedex.com/d"}}) == \
        "https://documentapi.prod.fedex.com/d"


def test_only_billing_answers_from_the_api_are_kept():
    assert site.is_billing_answer(API + "/bill/v1/invoices/retrieve")
    assert not site.is_billing_answer(API + "/user/v2/login")
    assert not site.is_billing_answer("https://www.fedex.com/bill/v1/x")


class _Resp:
    def __init__(self, url, body, status=200):
        self.url, self._body, self.status = url, body, status

    def json(self):
        return self._body


class _Page:
    """A signed-in fedex.com tab. Opening the invoices page makes it
    receive the scripted answers, or land on the connect-account form."""

    def __init__(self, answers, connect=False, fetch=None):
        self.url = "https://www.fedex.com/en-us/logged-in-home.html"
        self.answers, self.connect, self.fetch = answers, connect, fetch or {}
        self.listeners, self.fetched = [], []

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        if url == site.INVOICES_PAGE and self.connect:
            self.url = "https://www.fedex.com/register/connect-account/ean?linkApp=fbo"
            return
        self.url = url
        for u, body in self.answers:
            for fn in list(self.listeners):
                fn(_Resp(u, body))

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, url):
        self.fetched.append(url)
        return self.fetch[url]


INVOICES = [(API + "/bill/v1/invoices/retrieve",
             {"invoices": [{"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14",
                            "pdfUrl": "https://www.fedex.com/doc/INV-2.pdf"}]}),
            ("https://www.fedex.com/etc/other.json", {"invoices": [{"invoiceNumber": "X", "invoiceDate": "2031-01-01"}]})]


def _fresh():
    site._captured.update(at=0.0, answers=[])


def test_discovery_keeps_only_billing_answers_the_page_received():
    _fresh()
    page = _Page(INVOICES)
    docs = site.collect_download_docs(page)
    assert [(d.document_id, d.date_text) for d in docs] == [("INV-2", "2031-02-14")]
    assert page.listeners == []


def test_an_unconnected_account_stops_and_is_never_connected():
    _fresh()
    with pytest.raises(site.NeedsPerson):
        site.collect_download_docs(_Page([], connect=True))


def test_the_download_takes_the_rows_own_link_and_writes_only_a_pdf(tmp_path):
    _fresh()
    link = "https://www.fedex.com/doc/INV-2.pdf"
    page = _Page(INVOICES, fetch={link: {"status": 200, "ct": "application/pdf", "url": link,
                                         "b64": base64.b64encode(PDF).decode()}})
    out = tmp_path / "i.pdf"
    assert site.download_bill(page, None, "2031-02-14", out, document_id="INV-2")
    assert out.read_bytes() == PDF
    page.fetch[link] = {"status": 200, "ct": "text/html", "url": link}
    _fresh()
    assert not site.download_bill(page, None, "2031-02-14", tmp_path / "j.pdf", document_id="INV-2")
    assert not (tmp_path / "j.pdf").exists()


def test_an_invoice_without_a_link_goes_to_the_person(tmp_path):
    _fresh()
    page = _Page([(API + "/bill/v1/invoices/retrieve",
                   {"invoices": [{"invoiceNumber": "INV-1", "invoiceDate": "2031-01-24"}]})])
    with pytest.raises(site.NeedsPerson):
        site.download_bill(page, None, "2031-01-24", tmp_path / "i.pdf", document_id="INV-1")


def test_a_sign_in_answer_stops_the_run(tmp_path):
    _fresh()
    link = "https://www.fedex.com/doc/INV-2.pdf"
    page = _Page(INVOICES, fetch={link: {"status": 401, "url": link}})
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="INV-2")


def test_diagnose_carries_shapes_never_values():
    _fresh()
    page = _Page([(API + "/bill/v1/accounts/123456789/invoices",
                   {"invoices": [{"invoiceNumber": "SECRET-1", "invoiceDate": "2031-02-14"}]})])
    report = site.survey(page)
    text = json.dumps(report["api"])
    assert "SECRET" not in text and "123456789" not in text
    assert report["api"]["invoices"] == {"rows": 1, "with_a_link": 0}
    assert site.survey(_Page([], connect=True))["api"]["not_connected"]


def test_the_fetch_refuses_any_other_host():
    with pytest.raises(ValueError):
        site._fetch_file(_Page([]), "https://evil.test/doc.pdf")


def test_paying_shipping_and_account_controls_are_never_safe():
    for name in ["Pay Now", "Make a payment", "Dispute", "Set up autopay", "CONTINUE",
                 "Connect account", "JOIN FOR FREE TODAY", "SHIP A PACKAGE", "SCHEDULE A PICKUP",
                 "RATE & SHIP", "REDIRECT A PACKAGE", "CHANGE ACCOUNT", "Log out", "Settings"]:
        assert not site.is_safe_control(name), name


def test_reading_an_invoice_is_safe():
    for name in ["Invoices", "Download PDF", "View invoice", "Download"]:
        assert site.is_safe_control(name), name


def test_only_fedex_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.fedex.com/online/billing/cbs/invoices")
    assert site.is_safe_url("https://api.fedex.com/bill/v1/x")
    assert not site.is_safe_url("http://www.fedex.com/")
    assert not site.is_safe_url("https://fedex.com.example/")
    assert not site.is_safe_url("https://notfedex.com/")
    assert not site.is_safe_url("https://cdn.appdynamics.com/x.js")
    assert not site.is_safe_url("https://user:pw@www.fedex.com/")
