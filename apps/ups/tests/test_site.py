"""UPS Billing Center, the site layer. The guard, the host allowlist, the
list capture, the download body the page builds, and the download, all
against made-up answers. No real account, no network."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import ups_site as site
from paperpull_core import doc_types

PDF = b"%PDF-1.4 fake"


def _row(i, date, amount=2.73, code="100", unit="EBS", country="US", **kw):
    row = {"id": f"row{i}", "accountNumber": "A1B2C3", "invoiceNumber": f"0000000INV{i:05d}",
           "invoiceDate": f"{date}T00:00:00.000Z", "invoiceAmount": amount, "invoiceType": code,
           "businessUnit": unit, "countryCode": country, "recordType": "ACCOUNT",
           "planNumber": None, "planInvoiceNumber": None}
    row.update(kw)
    return row


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "UPS"
    assert storage.SPEC.routes == {"Statement": "statements"}
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


def test_the_title_discovery_writes_classifies():
    got = doc_types.classify_document("Shipping Invoice", doc_types.load_rules())
    assert (got[0], got[1]) == ("Statement", "Shipping Invoice")


@pytest.mark.parametrize("unit,country,code,word", [
    ("EBS", "US", "100", "EXPORT"), ("EBS", "CA", "121", "EXPORT"),
    ("EBS", "US", "210", "IMPORT"), ("EBS", "US", "200", "IMPORT"),
    ("EBS", "DE", "100", "100"), ("EBS", "US", "400", "400"),
    ("SCS", "US", "700", "Air"), ("SCS", "US", "850", "Ocean"),
    ("SCS", "US", "950", "Brokerage"), ("SCS", "US", "450", "Mail Innovations"),
    ("SCS", "US", "100", "100"),
])
def test_the_type_code_becomes_the_word_the_download_wants(unit, country, code, word):
    assert site.type_word({"businessUnit": unit, "countryCode": country, "invoiceType": code}) == word


def test_the_download_body_is_built_the_way_the_page_builds_it():
    body = site.download_body(_row(1, "2031-02-14"))
    assert body == {"locale": "en-US", "invoices": [{
        "countryCode": "US", "languageCode": "EN", "invoiceDate": "14/02/31",
        "invoiceAmount": "2.73", "businessUnit": "EBS", "recordType": "ACCOUNT",
        "accountNumber": "A1B2C3", "planNumber": None, "invoiceType": "EXPORT",
        "invoiceNumber": "0000000INV00001"}]}
    plan = site.download_body(_row(2, "2031-02-14", planInvoiceNumber="P9"))["invoices"][0]
    assert plan["planInvoiceNumber"] == "P9"


@pytest.mark.parametrize("value,text", [(2.73, "2.73"), (27.0, "27"), (27, "27"), (10.5, "10.5"),
                                        (-3.1, "-3.1"), (None, "")])
def test_amounts_are_written_the_way_javascript_writes_them(value, text):
    assert site.js_number(value) == text


def test_a_row_is_read_by_its_id_and_its_calendar_day():
    d = site.invoice_doc(_row(1, "2031-02-14"))
    assert (d["id"], d["date"], d["title"]) == ("row1", "2031-02-14", "Shipping Invoice")
    assert site.invoice_doc({**_row(1, "2031-02-14"), "id": ""}) is None
    assert site.invoice_doc({**_row(1, "2031-02-14"), "invoiceDate": "soon"}) is None


def test_the_invoice_number_never_reaches_a_title():
    """It carries the account number inside it."""
    d = site.invoice_doc(_row(7, "2031-02-14"))
    assert "INV" not in d["title"] and "0000000" not in d["title"]


class _Req:
    def __init__(self, url, post, headers):
        self.url, self.post_data, self._h = url, post, headers
        self.headers = headers

    def all_headers(self):
        return dict(self._h)


class _Resp:
    def __init__(self, url, post, body, status=200):
        self.url, self._body, self.status = url, body, status
        self.request = _Req(url, post, {"x-csrf-token": "c", "x-sub-token": "s", "instance-id": "i",
                                        "cookie": "secret", "content-type": "application/json"})

    def json(self):
        return self._body


class _Page:
    """A signed-in Billing Center tab. Opening My Invoices makes it receive
    the scripted list answers. Its fetch answers from a script too."""

    def __init__(self, rows, pdf=None):
        self.url = site.BASE + "/home"
        self.rows, self.pdf = rows, pdf
        self.listeners, self.posted = [], []

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        self.url = url
        if url == site.INVOICES_PAGE:
            for resp in [_Resp(site.LIST_API, '{"invoiceStatus":["OPEN"]}', []),
                         _Resp(site.LIST_API, "{}", self.rows)]:
                for fn in list(self.listeners):
                    fn(resp)

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, args):
        url, headers, body = args
        self.posted.append((url, headers, body))
        return self.pdf


def _fresh():
    site._captured.update(at=0.0, rows=None, headers={})


def test_discovery_keeps_the_all_invoices_answer_not_the_filtered_one():
    _fresh()
    page = _Page([_row(1, "2031-01-24", 27.03), _row(2, "2031-02-14")])
    docs = site.collect_download_docs(page)
    assert [(d.title, d.date_text, d.document_id) for d in docs] == [
        ("Shipping Invoice", "2031-02-14", "row2"), ("Shipping Invoice", "2031-01-24", "row1")]
    assert page.listeners == []
    assert "cookie" not in site._captured["headers"]
    assert site._captured["headers"]["x-csrf-token"] == "c"


def test_the_download_sends_the_page_headers_and_writes_only_a_pdf(tmp_path):
    _fresh()
    page = _Page([_row(1, "2031-02-14")],
                 {"status": 200, "ct": "application/pdf", "url": site.DOWNLOAD_API,
                  "b64": base64.b64encode(PDF).decode()})
    out = tmp_path / "i.pdf"
    assert site.download_bill(page, None, "2031-02-14", out, document_id="row1")
    assert out.read_bytes() == PDF
    url, headers, body = page.posted[-1]
    assert url == site.DOWNLOAD_API and headers["x-sub-token"] == "s"
    assert body["invoices"][0]["invoiceType"] == "EXPORT"


def test_an_error_answer_is_not_saved(tmp_path):
    _fresh()
    page = _Page([_row(1, "2031-02-14")],
                 {"status": 400, "ct": "application/json", "url": site.DOWNLOAD_API,
                  "json": {"error": {"errorCode": "download.request.failed"}}})
    out = tmp_path / "i.pdf"
    assert not site.download_bill(page, None, "2031-02-14", out, document_id="row1")
    assert not out.exists()


def test_a_record_whose_invoice_is_gone_or_redated_is_not_fetched(tmp_path):
    _fresh()
    page = _Page([_row(1, "2031-02-14")], {"status": 200})
    assert not site.download_bill(page, None, "2031-02-14", tmp_path / "a.pdf", document_id="gone")
    assert not site.download_bill(page, None, "2031-02-15", tmp_path / "b.pdf", document_id="row1")
    assert not site.download_bill(page, None, "2031-02-14", tmp_path / "c.pdf")
    assert page.posted == []


def test_a_sign_in_answer_stops_the_run(tmp_path):
    _fresh()
    page = _Page([_row(1, "2031-02-14")], {"status": 401, "url": site.DOWNLOAD_API})
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="row1")
    page = _Page([])
    page.url = "https://www.ups.com/lasso/login"
    page.goto = lambda url, **_: None
    with pytest.raises(site.SessionExpired):
        site.capture_list(page)


def test_diagnose_carries_shapes_and_codes_never_values():
    _fresh()
    page = _Page([_row(1, "2031-02-14")])
    report = site.survey(page)
    inv = report["api"]["invoices"]
    assert inv["rows"] == 1 and inv["readable"] == 1 and inv["type_codes"] == ["100"]
    text = json.dumps(inv)
    assert "A1B2C3" not in text and "INV00001" not in text and "row1" not in text
    assert [d.document_id for d in site.collect_documents(page)] == [""]


def test_the_fetch_refuses_any_other_host():
    with pytest.raises(ValueError):
        site._post(_Page([]), "https://evil.test/api/v1/bc/invoice/download", {}, {})


def test_paying_and_account_controls_are_never_safe():
    for name in ["Pay Now", "Pay Bill", "My Automatic Payments", "Dispute & Refund History",
                 "My Plans", "Email Invoice", "More actions for Invoice Number 1",
                 "Add Account", "Log Out", "Change password", "Settings", "Payment Activity"]:
        assert not site.is_safe_control(name), name


def test_reading_an_invoice_is_safe():
    for name in ["My Invoices", "Download PDF", "View invoice", "Download"]:
        assert site.is_safe_control(name), name


def test_only_ups_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://billing.ups.com/ups/billing/invoice")
    assert site.is_safe_url("https://www.ups.com/lasso/login")
    assert not site.is_safe_url("http://billing.ups.com/")
    assert not site.is_safe_url("https://ups.com.example/")
    assert not site.is_safe_url("https://notups.com/")
    assert not site.is_safe_url("https://ups-help-support.paymentus.net/")
    assert not site.is_safe_url("https://user:pw@billing.ups.com/")
