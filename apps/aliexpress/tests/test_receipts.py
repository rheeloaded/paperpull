"""Synthetic members, orders, invoices and PDFs for the AliExpress app.

Nothing here is from a real account: the member id, order ids, invoice
numbers, products, sellers and dates are made up.
"""
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aliexpress_docs as app_mod
import aliexpress_site as site
from paperpull_core.testkit import text_pdf

MEMBER = "1000000001"
OTHER_MEMBER = "1000000002"
PAID = "9000000000000001"
CANCELLED = "9000000000000002"
OLD = "9000000000000003"
SAME_DAY = "9000000000000004"
DATES = {PAID: "Mar 2, 2032", CANCELLED: "Mar 5, 2032", OLD: "Apr 6, 2020", SAME_DAY: "Mar 2, 2032"}
STATUS = {PAID: "Completed", CANCELLED: "Canceled ", OLD: "Completed", SAME_DAY: "Completed"}


def order_row(order_id, **changes):
    row = {"orderId": order_id, "orderDateText": DATES[order_id], "statusText": STATUS[order_id],
           "totalPriceText": "$12.34", "storeName": "Synthetic Store",
           "orderLines": [{"itemTitle": "Synthetic Soldering Tip"}]}
    row.update(changes)
    return row


def list_answer(rows, has_more, jsonp=True, index=1):
    comps = {f"pc_om_list_order_{r['orderId']}": {"fields": r} for r in rows}
    comps["pc_om_list_body_1"] = {"fields": {"hasMore": has_more, "pageIndex": index, "pageSize": 2}}
    body = json.dumps({"api": site.LIST_API, "ret": ["SUCCESS::ok"], "data": {"data": comps}})
    return f" mtopjsonp1({body})" if jsonp else body


def invoices_for(order_id):
    if order_id == OLD:
        return []
    out = [{"invoiceType": "Invoice", "invoiceStatus": "GENERATED_SUCCESS", "orderId": order_id,
            "invoiceId": f"inv-{order_id}", "invoiceNo": f"T{order_id[-6:]}INV"}]
    if order_id == CANCELLED:
        out.append({"invoiceType": "Credit note", "invoiceStatus": "GENERATED_SUCCESS", "orderId": order_id,
                    "invoiceId": f"crn-{order_id}", "invoiceNo": f"T{order_id[-6:]}CRN"})
    return out


class Response:
    def __init__(self, url, text):
        self.url, self._text, self.gone = url, text, False

    def text(self):
        if self.gone:
            raise RuntimeError("No resource with given identifier found")
        return self._text


class Button:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1 if self.page.list_pages[self.page.list_index - 1:] and self.page.more else 0

    @property
    def first(self):
        return self

    def inner_text(self):
        return self.page.more_label

    def click(self):
        self.page.clicks += 1
        self.page._send_list_page()


class Page:
    """An AliExpress tab whose context answers the order list, the tax
    module's API and its print."""

    def __init__(self, member=MEMBER, url="https://www.aliexpress.us/p/order/index.html"):
        self.url = url
        self.member = member
        self.context = SimpleNamespace(cookies=self.cookies)
        self.list_pages = [[order_row(PAID), order_row(CANCELLED)], [order_row(OLD), order_row(SAME_DAY)]]
        self.list_index = 0
        self.more = True
        self.more_label = "View orders"
        self.listeners = []
        self.clicks = 0
        self.signed_out = False
        self.ret = None
        self.invoice_files = {}
        for oid in (PAID, CANCELLED, SAME_DAY):
            for inv in invoices_for(oid):
                heading = "Credit Memo" if inv["invoiceType"] == "Credit note" else "Invoice"
                self.invoice_files[inv["invoiceId"]] = {
                    "content": base64.b64encode(text_pdf([heading, f"Invoice No. {inv['invoiceNo']}",
                                                          "Total amount in CNY 88.00"])).decode(),
                    "fileName": f"Invoice20320302{oid}.pdf"}
        self.receipt_text = {oid: ["Summary", f"Order ID: {oid}", f"Order time: {DATES[oid]}",
                                   "Total: $12.34"] for oid in (PAID, CANCELLED, SAME_DAY)}
        self.calls = []
        self.printed = []

    # -- the browser's side ---------------------------------------------
    def cookies(self, urls):
        if self.signed_out:
            return []
        return [{"name": "aep_usuc_f", "value": f"site=usa&region=US&b_locale=en_US&x_alimid={self.member}"}]

    def on(self, event, fn):
        assert event == "response"
        self.listeners.append(fn)

    def remove_listener(self, event, fn):
        self.listeners.remove(fn)

    def _send_list_page(self):
        rows = self.list_pages[self.list_index]
        self.list_index += 1
        self.more = self.list_index < len(self.list_pages)
        response = Response(f"https://acs.aliexpress.us/h5/{site.LIST_API}/1.0/?jsv=2.5.1",
                            list_answer(rows, self.more, jsonp=self.list_index == 1, index=self.list_index))
        for fn in list(self.listeners):
            fn(response)

    def goto(self, url, wait_until=None, timeout=None):
        if url == "about:blank":
            self.url = url
            return
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and parsed.hostname in site.HOSTS, url
        if self.signed_out:
            self.url = "https://login.aliexpress.com/?return_url=x"
            return
        self.url = url
        if parsed.path == "/p/order/index.html":
            self.list_index = 0
            self._send_list_page()

    def get_by_role(self, role, name, exact):
        assert (role, name, exact) == ("button", "View orders", True)
        return Button(self)

    def wait_for_timeout(self, ms):
        assert ms > 0

    def wait_for_function(self, script, arg=None, timeout=None):
        if "lib.mtop" in script:
            assert "/p/tax-ui/" in self.url
            return True
        order_id = parse_qs(urlsplit(self.url).query)["orderId"][0]
        assert arg == order_id
        if order_id not in self.receipt_text:
            raise TimeoutError("nothing drawn")
        return True

    def wait_for_load_state(self, state, timeout=None):
        return None

    def title(self):
        return "Receipt"

    def evaluate(self, script, args):
        api, data = args
        assert api in site.READ_APIS and "applyInvoiceToSeller" not in api
        self.calls.append((api, dict(data)))
        if self.ret:
            return {"ret": [self.ret]}
        order_id = data["orderId"]
        if api == site.RECEIPT_API:
            info = {"orderId": order_id, "orderTotal": "$12.34"} if order_id in self.receipt_text else None
            return {"ret": ["SUCCESS::ok"], "data": {"succeeded": True, "data": info}}
        if api == site.INVOICE_LIST_API:
            assert data["invoiceType"] == "INVOICE"
            return {"ret": ["SUCCESS::ok"], "data": {"succeeded": True,
                                                      "data": {"invoiceInfoDTOList": invoices_for(order_id)}}}
        f = self.invoice_files[data["invoiceId"]]
        return {"ret": ["SUCCESS::ok"], "data": {"succeeded": True, "data": dict(f)}}


@pytest.fixture(autouse=True)
def fake_print(monkeypatch):
    def printed(page, out_path):
        order_id = parse_qs(urlsplit(page.url).query)["orderId"][0]
        page.printed.append(order_id)
        Path(out_path).write_bytes(text_pdf(page.receipt_text[order_id]))
    monkeypatch.setattr(site.receipt_pdf, "print_page_to_pdf", printed)


def by_number(docs):
    out = {}
    for d in docs:
        out.setdefault(d.number, []).append(d)
    return out


def test_lists_every_page_of_orders_and_each_orders_papers():
    page = Page()
    docs = site.collect_download_docs(page)
    assert page.clicks == 1
    grouped = by_number(docs)
    assert set(grouped) == {PAID, CANCELLED, SAME_DAY}
    kinds = sorted(d.title.split(" " + CANCELLED)[0] for d in grouped[CANCELLED])
    assert kinds == ["AliExpress Receipt", "AliExpress Seller Tax Credit Note", "AliExpress Seller Tax Invoice"]
    assert {d.date_text for d in grouped[PAID]} == {"2032-03-02"}
    assert "(Canceled)" in next(d.title for d in grouped[CANCELLED] if "Receipt" in d.title)
    assert len({d.document_id for d in docs}) == len(docs) == 7
    assert site.listing_notes() == ["1 order too old for AliExpress's receipt has no receipt to save."]


def test_saves_receipts_invoices_and_credit_notes(tmp_path):
    page = Page()
    docs = site.collect_download_docs(page)
    for i, doc in enumerate(docs):
        target = tmp_path / f"{i}.pdf"
        assert site.download_bill(page, doc.date_text, target, account=doc.account,
                                  document_id=doc.document_id), doc.title
        assert target.read_bytes().startswith(b"%PDF-")
    assert sorted(page.printed) == sorted([PAID, CANCELLED, SAME_DAY])


def test_never_asks_a_seller_for_an_invoice():
    assert "applyInvoiceToSeller" not in " ".join(site.READ_APIS)
    with pytest.raises(ValueError):
        site._mtop(Page(), "mtop.global.finance.taxation.invoice.applyInvoiceToSeller", PAID)


def test_an_invoice_not_yet_issued_is_counted_not_listed(monkeypatch):
    page = Page()
    original = invoices_for

    def pending(order_id):
        rows = original(order_id)
        for row in rows:
            if order_id == PAID:
                row["invoiceStatus"] = "APPLYING"
        return rows
    monkeypatch.setattr(sys.modules[__name__], "invoices_for", pending)
    docs = site.collect_download_docs(page)
    assert not [d for d in docs if d.number == PAID and "Invoice" in d.title]
    assert "1 seller invoice not yet issued is listed but not saved." in site.listing_notes()


@pytest.mark.parametrize("which, change", [
    ("receipt", ["Summary", f"Order ID: {SAME_DAY}", "Order time: Mar 2, 2032", "Total: $12.34"]),
    ("receipt", ["Summary", f"Order ID: {PAID}", "Order time: Mar 9, 2032", "Total: $12.34"]),
    ("invoice", "another-number"),
    ("invoice", "heading"),
    ("invoice", "file name"),
])
def test_refuses_a_pdf_that_is_not_this_orders_paper(tmp_path, which, change):
    page = Page()
    docs = site.collect_download_docs(page)
    if which == "receipt":
        doc = next(d for d in docs if d.number == PAID and "Receipt" in d.title)
        page.receipt_text[PAID] = change
    else:
        doc = next(d for d in docs if d.number == PAID and "Invoice" in d.title)
        f = page.invoice_files[f"inv-{PAID}"]
        if change == "another-number":
            f["content"] = base64.b64encode(text_pdf(["Invoice", "Invoice No. T999999INV"])).decode()
        elif change == "heading":
            f["content"] = base64.b64encode(text_pdf(["Credit Memo", f"Invoice No. T{PAID[-6:]}INV"])).decode()
        else:
            f["fileName"] = f"Invoice20320302{SAME_DAY}.pdf"
    target = tmp_path / "x.pdf"
    assert not site.download_bill(page, doc.date_text, target, account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "wrong"
    assert not target.exists()


def test_an_invoice_that_is_not_a_pdf_is_unreadable(tmp_path):
    page = Page()
    doc = next(d for d in site.collect_download_docs(page) if d.number == PAID and "Invoice" in d.title)
    page.invoice_files[f"inv-{PAID}"]["content"] = base64.b64encode(b"<html>no</html>").decode()
    assert not site.download_bill(page, doc.date_text, tmp_path / "x.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "unreadable"


def test_an_order_page_that_draws_nothing_is_refused(tmp_path):
    page = Page()
    doc = next(d for d in site.collect_download_docs(page) if d.number == PAID and "Receipt" in d.title)
    del page.receipt_text[PAID]
    assert not site.download_bill(page, doc.date_text, tmp_path / "x.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "refused"


@pytest.mark.parametrize("ret, error, match", [
    ("FAIL_SYS_SESSION_EXPIRED::expired", site.SessionExpired, None),
    ("FAIL_SYS_USER_VALIDATE::check", site.SecurityCheck, "check"),
    ("FAIL_SYS_FLOW_LIMIT::busy", site.ListStopped, "limiting"),
    ("FAIL_BIZ_SOMETHING::else", site.ListStopped, "did not answer"),
])
def test_an_api_refusal_stops_the_list_as_what_it_is(ret, error, match):
    page = Page()
    page.ret = ret
    with pytest.raises(error, match=match):
        site.collect_download_docs(page)


def test_a_list_answer_the_browser_no_longer_holds_is_passed_over():
    page = Page()
    stale = Response(f"https://acs.aliexpress.us/h5/{site.LIST_API}/1.0/", "")
    stale.gone = True
    original_goto = page.goto

    def goto(url, **kw):
        if urlsplit(url).path == "/p/order/index.html":
            for fn in list(page.listeners):
                fn(stale)
        original_goto(url, **kw)
    page.goto = goto
    docs = site.collect_download_docs(page)
    assert len(by_number(docs)) == 3


def test_a_list_that_says_more_with_no_button_stops():
    page = Page()
    page.list_pages[0] = [order_row(PAID)]
    page.list_pages.append([order_row(CANCELLED)])
    original = Button.count
    Button.count = lambda self: 0
    try:
        with pytest.raises(site.ListStopped, match="View orders"):
            site.collect_download_docs(page)
    finally:
        Button.count = original


@pytest.mark.parametrize("change", [{"orderId": "12"}, {"orderDateText": "yesterday"}])
def test_an_unrecognized_order_stops_the_list(change):
    page = Page()
    page.list_pages[0][0] = order_row(PAID, **change)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_signed_out_reads_as_signed_out():
    page = Page()
    page.signed_out = True
    assert site.account_tag(page) == ""
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)
    assert site.looks_signed_out(SimpleNamespace(url="https://login.aliexpress.com/?x=1"))
    assert not site.looks_signed_out(SimpleNamespace(url="https://www.aliexpress.com/p/order/index.html"))


@pytest.mark.parametrize("url", ["https://www.aliexpress.com.attacker.example/p/order/index.html",
                                 "http://www.aliexpress.com/p/order/index.html",
                                 "https://example.test/p/order/index.html"])
def test_requests_nothing_from_a_tab_that_is_not_aliexpress(url):
    page = Page(url=url)
    assert site.account_tag(page) == ""
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert not page.calls and page.list_index == 0


def test_will_not_download_another_members_order(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    other = Page(OTHER_MEMBER)
    with pytest.raises(site.ListStopped):
        site.download_bill(other, doc.date_text, tmp_path / "x.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert not other.calls and not (tmp_path / "x.pdf").exists()


def test_the_guard_presses_only_view_orders():
    assert site.is_safe_control("View orders")
    for name in ("Pay now", "Confirm received", "Delete", "Add to cart", "Send email",
                 "Write a review", "Apply for invoice", "Returns/refunds", "Contact seller"):
        assert not site.is_safe_control(name), name


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


def test_app_files_receipts_and_tax_papers_apart_and_resumes_cleanly(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    assert app.cmd_discover(quiet=True) == 7
    assert "too old for AliExpress's receipt" in capsys.readouterr().out
    app.process(app._select())
    saved = sorted((Path(r["pdf_path"]).parent.name, Path(r["pdf_path"]).name)
                   for r in app.progress.data.values())
    assert saved == sorted([
        ("Receipts", f"2032-03-02 AliExpress Receipt {PAID}.pdf"),
        ("Receipts", f"2032-03-02 AliExpress Receipt {SAME_DAY}.pdf"),
        ("Receipts", f"2032-03-05 AliExpress Receipt {CANCELLED}.pdf"),
        ("Seller Tax Invoices", f"2032-03-02 AliExpress Seller Tax Invoice {PAID}.pdf"),
        ("Seller Tax Invoices", f"2032-03-02 AliExpress Seller Tax Invoice {SAME_DAY}.pdf"),
        ("Seller Tax Invoices", f"2032-03-05 AliExpress Seller Tax Invoice {CANCELLED}.pdf"),
        ("Seller Tax Invoices", f"2032-03-05 AliExpress Credit Note {CANCELLED}.pdf"),
    ])
    assert all(r["order_number"] for r in app.progress.data.values())
    printed = list(page.printed)
    app.cmd_resume()
    assert page.printed == printed
    assert app._select(pending_only=True) == []


def test_login_needs_a_member_and_an_answering_list():
    page = Page()
    assert site.invoice_list_look(page) == (True, "ready")
    page.signed_out = True
    assert site.invoice_list_look(page) == (False, "signed out")
    assert site.invoice_list_look(Page(url="https://example.test/")) == (False, "stopped")
    quiet = Page()
    quiet._send_list_page = lambda: None
    quiet.wait_for_timeout = lambda ms: None
    assert site.invoice_list_look(quiet) == (False, "stopped")


def test_a_sign_in_address_on_aliexpress_reads_as_signed_out():
    assert site.looks_signed_out(SimpleNamespace(url="https://www.aliexpress.com/login"))
    assert site.looks_signed_out(SimpleNamespace(url="https://login.aliexpress.us/"))
    assert not site.looks_signed_out(SimpleNamespace(url="https://example.test/login"))


def test_a_more_button_whose_words_are_not_view_orders_is_not_pressed():
    page = Page()
    page.more_label = "View orders and pay now"
    with pytest.raises(site.ListStopped, match="may press"):
        site.collect_download_docs(page)
    assert page.clicks == 0


def test_an_answer_for_another_page_of_the_list_is_passed_over():
    """A late answer of page 1, from a load the tab has left, arriving after
    the press for page 2 is not read as page 2, and no page is lost."""
    page = Page()
    real_click = Button.click

    def click_then_echo(self):
        late = Response(f"https://acs.aliexpress.us/h5/{site.LIST_API}/1.0/",
                        list_answer([order_row(PAID)], True, index=1))
        for fn in list(self.page.listeners):
            fn(late)
        real_click(self)
    Button.click = click_then_echo
    try:
        docs = site.collect_download_docs(page)
    finally:
        Button.click = real_click
    assert set(by_number(docs)) == {PAID, CANCELLED, SAME_DAY}
