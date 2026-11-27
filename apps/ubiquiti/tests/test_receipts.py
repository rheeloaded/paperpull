"""Synthetic customers, orders, dates and PDFs for the Ubiquiti Store receipt app.

Nothing here is from a real account: the ids, order numbers, products and
dates are made up.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ubiquiti_docs as app_mod
import ubiquiti_site as site
from paperpull_core.testkit import text_pdf

CUSTOMER = "cust-synthetic-0001"
OTHER_CUSTOMER = "cust-synthetic-0002"
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"
THIRD = "00000000-0000-4000-8000-000000000003"
CANCELLED = "00000000-0000-4000-8000-000000000009"
NUMBERS = {FIRST: "US1000001", SECOND: "US1000002", THIRD: "CA2000003", CANCELLED: "US1000009"}
# The first two on one day; the third made at 01:30 UTC, the evening
# before in Toronto, which is the day its invoice prints.
CREATED = {FIRST: "2032-02-06T15:00:00.000Z", SECOND: "2032-02-06T18:00:00.000Z",
           THIRD: "2032-03-02T01:30:00.000Z", CANCELLED: "2032-02-05T12:00:00.000Z"}
PRINTED = {FIRST: "2032/02/06", SECOND: "2032/02/06", THIRD: "2032/03/01", CANCELLED: "2032/02/05"}
STORE = {FIRST: "us", SECOND: "us", THIRD: "ca", CANCELLED: "us"}


def order(order_id, **changes):
    row = {"id": order_id, "orderNumber": NUMBERS[order_id], "createdAt": CREATED[order_id],
           "store": {"id": STORE[order_id]},
           "items": [{"title": "Synthetic Access Point"}, {"title": "Synthetic Cable"}],
           "displayStatus": {"payment": "Cancelled" if order_id == CANCELLED else "Completed"}}
    row.update(changes)
    return row


def receipt(order_id, heading="Ubiquiti Store USA Receipt / Tax Invoice", number=None, printed=None):
    return text_pdf([heading, f"Invoice No.: {number or NUMBERS[order_id]}",
                     f"Invoice Date: {printed or PRINTED[order_id]}", "Payment status: Paid"])


class Response:
    def __init__(self, body, content_type="application/json", status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = {"content-type": content_type}
        self.status = status
        self.disposed = False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


class Page:
    """A store tab whose context answers the store's GraphQL and invoice routes."""

    def __init__(self, customer=CUSTOMER, url="https://store.ui.com/us/en/account"):
        self.url = url
        self.context = SimpleNamespace(request=SimpleNamespace(get=self.get, post=self.post))
        self.customer = customer
        self.orders = [order(FIRST), order(SECOND), order(CANCELLED), order(THIRD)]
        self.page_size = 50
        self.total = None
        self.signed_out = False
        self.graphql_status = 200
        self.historical = 0
        self.pdfs = {i: receipt(i) for i in NUMBERS}
        self.pdf_status = 200
        self.pdf_type = "application/pdf"
        self.posted = []
        self.fetched = []
        self.responses = []

    def wait_for_timeout(self, ms):
        assert ms > 0

    def post(self, url, *, max_redirects, timeout, data, headers):
        parsed = urlsplit(url)
        assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", "ecomm.svc.ui.com", "/graphql")
        assert max_redirects == 0 and timeout > 0
        body = json.loads(data)
        op, variables = body["operationName"], body["variables"]
        self.posted.append((op, variables))
        if op == "GetCustomerId":
            me = None if self.signed_out else {"id": self.customer, "isGuest": False}
            answer = {"data": {"meCustomer": me}}
        elif op == "GetCustomerOrders":
            if self.signed_out:
                answer = {"errors": [{"message": "Must be logged in to access resource",
                                      "extensions": {"code": "FORBIDDEN"}}], "data": None}
            else:
                start = variables["input"]["offset"]
                size = min(variables["input"]["limit"], self.page_size)
                rows = self.orders[start:start + size]
                total = len(self.orders) if self.total is None else self.total
                answer = {"data": {"storefrontOrders": {
                    "pagination": {"limit": size, "offset": start, "total": total},
                    "items": rows}}}
        elif op == "GetCustomerHistoricalOrders":
            answer = {"data": {"storefrontHistoricalOrders": {"pagination": {"total": self.historical}}}}
        else:
            raise AssertionError(f"unexpected operation {op}")
        response = Response(answer, status=self.graphql_status)
        self.responses.append(response)
        return response

    def get(self, url, *, max_redirects, timeout, params, headers):
        parsed = urlsplit(url)
        assert (parsed.scheme, parsed.netloc) == ("https", "ecomm.svc.ui.com")
        assert parsed.path.startswith("/invoice/")
        assert max_redirects == 0 and timeout > 0 and params == {"locale": "en"}
        order_id = parsed.path.rsplit("/", 1)[1]
        self.fetched.append(order_id)
        response = Response(self.pdfs[order_id], self.pdf_type, status=self.pdf_status)
        self.responses.append(response)
        return response


def _orders_asked(page):
    return [v["input"]["offset"] for op, v in page.posted if op == "GetCustomerOrders"]


def test_lists_paid_orders_and_saves_each_receipt(tmp_path):
    page = Page()
    docs = site.collect_download_docs(page)
    assert [d.number for d in docs] == ["US1000001", "US1000002", "CA2000003"]
    assert [d.date_text for d in docs] == ["2032-02-06", "2032-02-06", "2032-03-01"]
    assert len({d.document_id for d in docs}) == 3
    assert docs[0].title == "Ubiquiti Store Receipt US1000001: Synthetic Access Point and 1 more"
    for i, doc in enumerate(docs):
        target = tmp_path / f"{i}.pdf"
        assert site.download_bill(page, doc.date_text, target,
                                  account=doc.account, document_id=doc.document_id)
        assert target.read_bytes().startswith(b"%PDF-")
        assert FIRST not in repr(doc)
    assert page.fetched == [FIRST, SECOND, THIRD]
    assert all(r.disposed for r in page.responses)


def test_cancelled_orders_are_counted_not_listed():
    page = Page()
    docs = site.collect_download_docs(page)
    assert NUMBERS[CANCELLED] not in {d.number for d in docs}
    assert site.unpaid_counts() == {"Cancelled": 1}
    assert CANCELLED not in page.fetched


def test_walks_every_page_of_orders():
    page = Page()
    page.page_size = 2
    docs = site.collect_download_docs(page)
    assert len(docs) == 3
    assert _orders_asked(page) == [0, 2]


def test_a_list_that_ends_before_its_count_is_a_list_stop():
    page = Page()
    page.total = 9
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


@pytest.mark.parametrize("change", [{"id": "not-a-uuid"}, {"orderNumber": "12"},
                                    {"createdAt": "yesterday"}, {"store": None},
                                    {"displayStatus": {}}])
def test_an_unrecognized_order_stops_the_list_rather_than_skipping_it(change):
    page = Page()
    page.orders[1] = order(SECOND, **change)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_signed_out_store_reads_as_signed_out():
    page = Page()
    page.signed_out = True
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)
    assert site.account_tag(page) == ""
    assert site.invoice_list_look(page) == (False, "signed out")


def test_forbidden_order_list_reads_as_signed_out_even_with_a_customer():
    page = Page()
    site.account_tag(page)
    page.signed_out = True
    assert site.invoice_list_look(page) == (False, "signed out")


def test_a_rate_limited_list_is_a_list_stop():
    page = Page()
    site.account_tag(page)
    page.graphql_status = 429
    with pytest.raises(site.ListStopped, match="limiting"):
        site.collect_download_docs(page)


@pytest.mark.parametrize("url", ["https://store.ui.com.attacker.example/us/en/account",
                                 "http://store.ui.com/us/en/account",
                                 "https://example.test/us/en/account"])
def test_requests_nothing_from_a_tab_that_is_not_the_store(url):
    page = Page(url=url)
    assert site.account_tag(page) == ""
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert not page.posted and not page.fetched


def test_any_store_page_will_do():
    assert site.is_invoice_page_url("https://store.ui.com/us/en")
    assert site.is_invoice_page_url("https://store.ui.com/ca/en/category/wifi")
    assert not site.is_invoice_page_url("https://account.ui.com/login")


def test_the_sign_in_page_reads_as_signed_out():
    assert site.looks_signed_out(SimpleNamespace(url="https://account.ui.com/login?redirect=x"))
    assert not site.looks_signed_out(SimpleNamespace(url="https://store.ui.com/us/en/account"))
    assert not site.looks_signed_out(SimpleNamespace(url="https://example.test/login"))


@pytest.mark.parametrize("pdf", [
    receipt(FIRST, heading="Ubiquiti Store USA Unpaid Invoice"),
    receipt(FIRST, number="US1000002"),
    receipt(FIRST, printed="2032/02/09"),
])
def test_refuses_a_pdf_that_is_not_this_orders_receipt(tmp_path, pdf):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdfs[FIRST] = pdf
    target = tmp_path / "r.pdf"
    assert not site.download_bill(page, doc.date_text, target,
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "wrong"
    assert not target.exists()


def test_a_receipt_printed_on_the_utc_day_is_still_its_own(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[2]
    page.pdfs[THIRD] = receipt(THIRD, printed="2032/03/02")
    assert site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                              account=doc.account, document_id=doc.document_id)


def test_the_order_number_is_found_only_on_its_own():
    assert site._printed_number("Invoice No.: US1000001", "US1000001")
    assert not site._printed_number("Invoice No.: US10000012", "US1000001")
    assert not site._printed_number("Invoice No.: XUS1000001", "US1000001")


def test_a_rate_limited_receipt_stops_without_another_request(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdf_status = 429
    asked = len(page.posted)
    with pytest.raises(site.ListStopped, match="limiting"):
        site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert page.fetched == [FIRST] and len(page.posted) == asked


@pytest.mark.parametrize("status, content_type", [(200, "text/html"), (403, "application/pdf")])
def test_a_refused_receipt_reads_the_list_again_and_is_said_as_refused(tmp_path, status, content_type):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdf_status, page.pdf_type = status, content_type
    assert not site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "refused"


def test_a_receipt_refused_while_signed_out_stops_as_signed_out(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdf_type = "text/html"
    page.signed_out = True
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                           account=doc.account, document_id=doc.document_id)


def test_will_not_download_another_customers_order(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    other = Page(OTHER_CUSTOMER)
    with pytest.raises(site.ListStopped):
        site.download_bill(other, doc.date_text, tmp_path / "r.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert not other.fetched and not (tmp_path / "r.pdf").exists()


def test_an_order_gone_from_the_list_is_said_as_gone(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    reopened = Page()
    reopened.orders = [order(SECOND)]
    assert not site.download_bill(reopened, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "gone"


def test_a_stopped_list_leaves_no_counts_of_an_earlier_one():
    page = Page()
    page.historical = 2
    site.collect_download_docs(page)
    assert site.legacy_count() == 2 and site.unpaid_counts() == {"Cancelled": 1}
    page.total = 99
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert site.legacy_count() == 0 and site.unpaid_counts() == {}


def _app(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic Owner", "output_dir": str(tmp_path), "min_pdf_bytes": 100,
    }), encoding="utf-8")
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(config)]))
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    return app


def test_app_names_each_receipt_by_its_order_number_and_resumes_cleanly(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    page.historical = 1
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    assert app.cmd_discover(quiet=True) == 3
    said = capsys.readouterr().out
    assert "1 order marked Cancelled has no receipt" in said, said
    assert "1 older Ubiquiti Store order" in said, said
    app.process(app._select())
    saved = sorted(Path(rec["pdf_path"]).name for rec in app.progress.data.values())
    assert saved == ["2032-02-06 Ubiquiti Receipt US1000001.pdf",
                     "2032-02-06 Ubiquiti Receipt US1000002.pdf",
                     "2032-03-01 Ubiquiti Receipt CA2000003.pdf"]
    assert all(Path(rec["pdf_path"]).parent.name == "Receipts" for rec in app.progress.data.values())
    assert all(rec["order_number"] for rec in app.progress.data.values())
    fetched = list(page.fetched)
    app.cmd_resume()
    assert page.fetched == fetched
    assert app._select(pending_only=True) == []


def test_another_customers_records_are_not_resumed(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    app.cmd_discover(quiet=True)
    other = Page(OTHER_CUSTOMER)
    other.orders = []
    monkeypatch.setattr(app, "_on_its_site", lambda: other)
    app._billing_account = ""
    app.cmd_discover(quiet=True)
    assert app._select() == []
