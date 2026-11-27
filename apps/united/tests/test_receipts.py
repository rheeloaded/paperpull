"""Synthetic members, reservations, tickets and receipts for the United
Airlines receipt app.

Nothing here is from a real account: the MileagePlus numbers, confirmation
numbers, ticket numbers, receipt ids and dates are made up. The receipts
page is a small stand-in DOM with the two tables united.com draws, and the
page's own two answers (the receipt list, and the receipt View receipt
fetches) are handed to the app's listener the way the browser would.
"""
import inspect
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import united_docs as app_mod
import united_site as site
from paperpull_core.testkit import text_pdf

MEMBER = "ZZ000001"
OTHER_MEMBER = "ZZ000002"
SEARCH_URL = "https://www.united.com/en/us/receipts/search"
VIEW_LABEL = "View receipt, opens in a new tab"


def rid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


# Each reservation: confirmation, receipt id, travelers' tickets, issue
# day, booking day, route, and how united.com answers View receipt for it
# ("each": one receipt per traveler, "one": one for everyone).
RESERVATIONS = [
    dict(number="QXA1B2", rid=rid(1), tickets=["0169990000011", "0169990000012"],
         issued="2032-02-06T10:00:00", created="2032-02-06", route=[("ORD", "DEN"), ("DEN", "ORD")],
         answer="each"),
    # Exchanged: booked in December, tickets reissued in March.
    dict(number="QXC3D4", rid=rid(2), tickets=["0169990000021"],
         issued="2032-03-01T09:00:00", created="2031-12-15", route=[("SFO", "EWR")], answer="each"),
    dict(number="QXE5F6", rid=rid(3), tickets=["0169990000031", "0169990000032", "0169990000033"],
         issued="2031-11-20T08:00:00", created="2031-11-20", route=[("IAH", "LAX")], answer="one"),
]
OPTIONS = [
    dict(number="0169990000901", rid=rid(9), docs=["0169990000901", "0169990000902"],
         date="02/07/2032", detail="ECONOMY PLUS SEAT"),
]
LONG_DATE = {"2032-02-06": "Fri, Feb 06, 2032", "2032-03-01": "Mon, Mar 01, 2032",
             "2031-11-20": "Thu, Nov 20, 2031", "2032-02-07": "Sat, Feb 07, 2032"}


def reservation_row(r):
    tvlr = [{"FstNm": f"TRAVELER{i}", "LstNm": "SYNTHETIC", "TktNbr": [t], "DocId": []}
            for i, t in enumerate(r["tickets"], 1)]
    return {"DepartDate": "06/01/2032", "RecordLocator": r["number"], "PnrCreateDt": r["created"],
            "Segments": [{"OriginIATACode": a, "DestinationIATACode": b} for a, b in r["route"]],
            "RcptData": {"RcptId": r["rid"], "RcptTmstmp": r["issued"], "RcptType": "T",
                         "RecLoc": r["number"], "PnrCreateDt": r["created"], "IsMultiRcpt": "N",
                         "Tvlr": tvlr,
                         "Tkt": [{"TktNbr": t, "IssLclDtTm": r["issued"]} for t in r["tickets"]],
                         "Emd": []}}


def option_row(o):
    return {"PurchaseDate": o["date"], "PurchaseDetail": o["detail"], "ReceiptNumber": o["number"],
            "DocCreateDt": o["date"],
            "RcptData": {"RcptId": o["rid"], "RcptTmstmp": "2032-02-07T12:00:00", "RcptType": "D",
                         "RecLoc": "QXA1B2", "PnrCreateDt": "2032-02-06", "IsMultiRcpt": "N",
                         "Tvlr": [], "Tkt": [],
                         "Emd": [{"DocId": d, "DocCreateDt": o["date"]} for d in o["docs"]]}}


def receipt_html(number, purchased, tickets=(), references=()):
    lines = ["Thank you for choosing United.", f"Confirmation Number: {number}"]
    lines += [f"eTicket number: {t}" for t in tickets]
    lines += [f"Economy Plus Seat (Reference Number: {r})" for r in references]
    lines += [f"Date of purchase: {LONG_DATE[purchased]}", "Total: 100.00 USD"]
    return "<html><body>" + "".join(f"<p>{line}</p>" for line in lines) + "</body></html>"


def receipt_answer(rid_):
    for r in RESERVATIONS:
        if r["rid"] == rid_:
            day = r["issued"][:10]
            if r["answer"] == "one":
                return [{"PaxNm": "TRAVELER1 SYNTHETIC",
                         "Html": receipt_html(r["number"], day, r["tickets"])}]
            return [{"PaxNm": f"TRAVELER{i} SYNTHETIC", "Html": receipt_html(r["number"], day, [t])}
                    for i, t in enumerate(r["tickets"], 1)]
    for o in OPTIONS:
        if o["rid"] == rid_:
            return [{"PaxNm": "TRAVELER1 SYNTHETIC",
                     "Html": receipt_html("QXA1B2", "2032-02-07", references=o["docs"])}]
    raise AssertionError(rid_)


# -- a stand-in DOM -----------------------------------------------------------

class El:
    def __init__(self, tag, attrs=None, text="", children=()):
        self.tag, self.attrs, self.text = tag, dict(attrs or {}), text
        self.children, self.parent, self.hidden = [], None, False
        for c in children:
            self.add(c)

    def add(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def walk(self):
        for c in self.children:
            if c.hidden:
                continue
            yield c
            yield from c.walk()

    def inner_text(self):
        own = [self.text] if self.text else []
        return " ".join(own + [c.inner_text() for c in self.children if not c.hidden]).strip()


_PART = re.compile(r"^([a-z0-9]*)(?:\[([\w-]+)='([^']*)'\])?$")


def _parts(css):
    return re.findall(r"[a-z0-9]*\[[^\]]*\]|[a-z0-9]+", css)


def _matches(el, part):
    tag, attr, value = _PART.match(part).groups()
    return (not tag or el.tag == tag) and (not attr or el.attrs.get(attr) == value)


def _select(root, css):
    parts = _parts(css)
    found = []
    for el in root.walk():
        if not _matches(el, parts[-1]):
            continue
        rest, up = parts[:-1], el.parent
        while rest and up is not None:
            if _matches(up, rest[-1]):
                rest = rest[:-1]
            up = up.parent
        if not rest:
            found.append(el)
    return found


class Loc:
    def __init__(self, find, css=""):
        self._find, self.css = find, css

    def _els(self):
        return self._find()

    def locator(self, css):
        return Loc(lambda: [e for root in self._els() for e in _select(root, css)], css)

    def filter(self, has=None, has_text=None):
        def keep(e):
            if has is not None and not _select(e, has.css):
                return False
            return has_text is None or has_text in e.inner_text()
        return Loc(lambda: [e for e in self._els() if keep(e)], self.css)

    def count(self):
        return len(self._els())

    def nth(self, i):
        return Loc(lambda: self._els()[i:i + 1], self.css)

    @property
    def first(self):
        return self.nth(0)

    def inner_text(self):
        (el,) = self._els()
        return el.inner_text()

    def get_attribute(self, name):
        (el,) = self._els()
        return el.attrs.get(name)


SHOWN = 2  # rows a table shows before "Load more results"


def build_dom(reservations, options):
    main = El("main")
    for kind, rows in (("T", reservations), ("D", options)):
        label = "Confirmation number" if kind == "T" else "Receipt number"
        tbody = El("tbody")
        section = main.add(El("section", children=[
            El("h2", text="Travel Reservations" if kind == "T" else
               "Travel options and inflight purchases"),
            El("table", children=[tbody])]))
        for i, row in enumerate(rows):
            number = row["number"]
            tr = tbody.add(El("tr", children=[
                El("td", {"data-label": "Date"}, "1/1/2032"),
                El("td", {"data-label": label}, number),
                El("td", {"data-label": "View receipt"}, children=[
                    El("button", {"id": f"email-receipt-{number}"}, "Email receipt"),
                    El("button", {"aria-label": VIEW_LABEL}, "View receipt")])]))
            tr.hidden = i >= SHOWN
        if len(rows) > SHOWN:
            section.add(El("div", children=[El("button", {}, "Load more results")]))
    return El("html", children=[El("body", children=[main])])


# -- the page ------------------------------------------------------------------

class Response:
    def __init__(self, url, sent, body, status=200):
        self.url, self.status = url, status
        self.request = SimpleNamespace(method="POST", post_data=json.dumps(sent))
        self.headers = {"content-type": "application/json"}
        self._body = json.dumps(body).encode()

    def body(self):
        return self._body


class Tab:
    def __init__(self, context):
        self.url, self.context, self.closed = "about:blank", context, False

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True
        self.context.pages.remove(self)


class Page:
    """A united.com tab whose receipts page lists the synthetic receipts."""

    def __init__(self, member=MEMBER, url="https://www.united.com/en/us"):
        self.url, self.member = url, member
        self.context = SimpleNamespace(pages=[self])
        self.reservations = [dict(r) for r in RESERVATIONS]
        self.options = [dict(o) for o in OPTIONS]
        self.signed_out = False
        self.list_status = 200
        self.receipt_status = 200
        self.answers = {}
        self.query = None
        self.handlers = {}
        self.loads = 0
        self.pressed = []
        self.dom = None

    def is_closed(self):
        return False

    # events
    def on(self, event, fn):
        # Playwright marks each handler, or a bound method's object, with
        # an attribute of its own, which a built-in such as list.append
        # cannot take (playwright/_impl/_impl_to_api_mapping.py).
        if inspect.ismethod(fn):
            setattr(fn.__self__, "_pw_impl_instance_" + fn.__name__, None)
        else:
            fn._pw_impl_instance_ = None
        self.handlers.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        self.handlers[event].remove(fn)

    def _fire(self, event, value):
        for fn in list(self.handlers.get(event, [])):
            fn(value)

    def wait_for_timeout(self, ms):
        assert ms > 0

    def goto(self, url, wait_until=None, timeout=None):
        assert url == site.RECEIPTS_URL
        self.loads += 1
        if self.signed_out:
            self.url = "https://www.united.com/en/us/receipts"
            return
        self.url = SEARCH_URL
        self.dom = build_dom(self.reservations, self.options)
        sent = {"Client": "CustomerPortal", "QueryArchive": "N", "SumOnly": "Y",
                "QueryParam": self.query or {"QueryByPnr": None, "QueryByCC": None, "QueryByTkt": None,
                                             "QueryByDoc": None, "QueryByFqtv": {"FqtvNbr": self.member}}}
        body = {"Data": {"Reservations": [reservation_row(r) for r in self.reservations],
                         "TravelOptions": [option_row(o) for o in self.options]}}
        self._fire("response", Response("https://www.united.com" + site.LIST_PATH, sent, body,
                                        self.list_status))

    def locator(self, css):
        return Loc(lambda: _select(self.dom, css) if self.dom else [], css)

    # what pressing.click does, as the page would answer it
    def press(self, locator, css):
        (el,) = locator._els()
        assert _matches(el, _parts(css)[-1])
        label = el.attrs.get("aria-label") or el.inner_text()
        assert site.is_safe_control(label), label
        self.pressed.append(label)
        if el.inner_text() == "Load more results":
            section = el.parent.parent
            for tr in [c for c in section.children[1].children[0].children]:
                tr.hidden = False
            el.parent.hidden = True
            return
        tr = el.parent.parent
        number = tr.children[1].text
        row = next(r for r in self.reservations + self.options if r["number"] == number)
        rcpt = (reservation_row(row) if "tickets" in row else option_row(row))["RcptData"]
        items = self.answers.get(number, None)
        if items is None:
            items = receipt_answer(row["rid"])
        body = {"Data": {"GetRcptHTMLResp": {"Rcpt": items}}}
        self._fire("response", Response("https://www.united.com" + site.RECEIPT_PATH,
                                        {"RcptData": rcpt}, body, self.receipt_status))
        popup = Tab(self.context)
        self.context.pages.append(popup)
        self._fire("popup", popup)


class Printer:
    """Prints each HTML receipt as a PDF of its text."""
    printed = []

    def __init__(self, context):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def print(self, html):
        Printer.printed.append(html)
        lines = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<p>.*?</p>", html)]
        return text_pdf(lines)


@pytest.fixture(autouse=True)
def stand_ins(monkeypatch):
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        assert what and words
        page.press(locator, css)
    monkeypatch.setattr(site.pressing, "click", click)
    monkeypatch.setattr(site, "_PrintTab", Printer)
    Printer.printed = []
    site._RUN.clear()
    yield
    site._RUN.clear()


def save_all(page, tmp_path):
    docs = site.collect_download_docs(page)
    saved = {}
    for doc in docs:
        target = tmp_path / f"{doc.number}.pdf"
        assert site.download_bill(page, doc.date_text, target,
                                  account=doc.account, document_id=doc.document_id), doc
        saved[doc.number] = target
    return docs, saved


# -- the list -----------------------------------------------------------------

def test_lists_every_reservation_and_purchase_and_presses_nothing():
    page = Page()
    docs = site.collect_download_docs(page)
    assert [d.number for d in docs] == ["QXA1B2", "QXC3D4", "QXE5F6", "0169990000901"]
    assert [d.date_text for d in docs] == ["2032-02-06", "2032-03-01", "2031-11-20", "2032-02-07"]
    assert docs[0].title == "United Airlines Flight Receipt QXA1B2: ORD-DEN, DEN-ORD"
    assert docs[3].title == "United Airlines Purchase Receipt 0169990000901: Economy Plus Seat"
    assert len({d.document_id for d in docs}) == 4
    assert len({d.account for d in docs}) == 1 and MEMBER not in docs[0].account
    assert page.pressed == [] and page.loads == 1


def test_an_exchanged_ticket_is_filed_under_its_issue_day_and_may_print_its_booking_day():
    page = Page()
    site.collect_download_docs(page)
    held = {r.number: r for r in site._RUN["receipts"].values()}
    assert held["QXC3D4"].date == "2032-03-01"
    assert "2031-12-15" in held["QXC3D4"].dates


def test_a_list_asked_by_anything_but_the_member_is_a_list_stop():
    page = Page()
    page.query = {"QueryByPnr": {"Pnr": "QXA1B2"}, "QueryByFqtv": {"FqtvNbr": MEMBER}}
    with pytest.raises(site.ListStopped, match="MileagePlus"):
        site.collect_download_docs(page)


def test_the_archive_is_never_taken_for_the_list():
    sent = {"QueryArchive": "Y", "QueryParam": {"QueryByFqtv": {"FqtvNbr": MEMBER}}}
    assert site._member_of(sent) == ""
    sent["QueryArchive"] = "N"
    assert site._member_of(sent) == MEMBER


def test_signed_out_the_receipts_page_reads_as_signed_out():
    page = Page()
    page.signed_out = True
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)
    assert site.account_tag(page) == ""
    assert site.invoice_list_look(page) == (False, "signed out")


@pytest.mark.parametrize("status", [428, 429])
def test_a_refused_list_is_a_list_stop(status):
    page = Page()
    page.list_status = status
    with pytest.raises(site.ListStopped, match="refusing"):
        site.collect_download_docs(page)


@pytest.mark.parametrize("change", [{"number": "TOOLONG1"}, {"rid": "not-a-uuid"},
                                    {"issued": "yesterday", "created": "soon"}, {"tickets": []},
                                    {"tickets": ["12"]}])
def test_an_unrecognized_reservation_stops_the_list_rather_than_skipping_it(change):
    page = Page()
    page.reservations[1].update(change)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_a_purchase_whose_receipt_number_is_not_among_its_documents_stops_the_list():
    page = Page()
    page.options[0]["docs"] = ["0169990000902"]
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


@pytest.mark.parametrize("url", ["https://www.united.com.attacker.example/en/us/receipts",
                                 "http://www.united.com/en/us/receipts",
                                 "https://example.test/en/us/receipts"])
def test_opens_nothing_from_a_tab_that_is_not_uniteds(url):
    page = Page(url=url)
    assert site.account_tag(page) == ""
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert page.loads == 0


def test_a_sign_in_address_reads_as_signed_out():
    assert site.looks_signed_out(SimpleNamespace(url="https://www.united.com/en/us/login?return=x"))
    assert not site.looks_signed_out(SimpleNamespace(url=SEARCH_URL))
    assert not site.looks_signed_out(SimpleNamespace(url="https://example.test/login"))


def test_opening_the_receipts_page_reads_the_list_once_for_the_run():
    page = Page()
    site.open_receipts_page(page)
    assert site.account_tag(page)
    assert len(site.collect_download_docs(page)) == 4
    assert page.loads == 1


# -- the guard -----------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "View receipt, opens in a new tab View receipt", "Load more results",
    "View receipt for a credit card purchase"])
def test_the_guard_lets_the_receipt_controls_through(label):
    assert site.is_safe_control(label)


@pytest.mark.parametrize("label", [
    "Email receipt", "View receipt and email it", "Find receipt",
    "Search another Confirmation, eTicket or Credit card", "Change flight", "Cancel trip",
    "Check-in", "Upgrade", "Request a refund", "Pay now", "Select seats", "Edit profile",
    "Add bags", "View trip", "Sign out"])
def test_the_guard_refuses_everything_else(label):
    assert not site.is_safe_control(label)


# -- one receipt ----------------------------------------------------------------

def test_saves_each_receipt_presses_only_view_receipt_and_closes_its_tab(tmp_path):
    page = Page()
    docs, saved = save_all(page, tmp_path)
    assert set(saved) == {"QXA1B2", "QXC3D4", "QXE5F6", "0169990000901"}
    assert all(p.read_bytes().startswith(b"%PDF-") for p in saved.values())
    assert not any("Email" in p for p in page.pressed)
    assert page.pressed.count("Load more results") == 1
    assert page.pressed.count(VIEW_LABEL) == 4
    assert page.context.pages == [page]


def test_every_travelers_receipt_is_filed_together(tmp_path):
    page = Page()
    _docs, saved = save_all(page, tmp_path)
    from paperpull_core import pdf_reader
    text = " ".join(pdf_reader.page_texts(saved["QXA1B2"].read_bytes()))
    assert "0169990000011" in text and "0169990000012" in text
    together = [h for h in Printer.printed if site.PAGE_BREAK in h]
    assert len(together) == 1 and together[0].count(site.PAGE_BREAK) == 1
    assert together[0].index("0169990000011") < together[0].index(site.PAGE_BREAK) \
        < together[0].index("0169990000012")
    # One receipt for all three travelers is saved as printed, with no break.
    assert "0169990000033" in " ".join(pdf_reader.page_texts(saved["QXE5F6"].read_bytes()))


def test_travelers_receipts_print_as_one_document_under_the_first_ones_head():
    first = "<html><head><style>p{color:red}</style></head><body class='x'><p>ONE</p></body></html>"
    second = "<html><head><style>ignored</style></head><BODY><p>TWO</p></BODY></html>"
    html = site._together([first, second])
    assert html.count("<body>") == 1 and "p{color:red}" in html and "ignored" not in html
    assert html.index("ONE") < html.index(site.PAGE_BREAK) < html.index("TWO")
    assert site._together([first]) == first
    assert "<p>THREE</p>" in site._together([first, "<p>THREE</p>"])


def test_a_receipt_missing_a_travelers_ticket_is_wrong(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.answers["QXA1B2"] = receipt_answer(rid(1))[:1]
    target = tmp_path / "r.pdf"
    assert not site.download_bill(page, doc.date_text, target,
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "wrong" and not target.exists()


@pytest.mark.parametrize("html", [
    receipt_html("QXZZZZ", "2032-02-06", ["0169990000011", "0169990000012"]),
    receipt_html("QXA1B2", "2031-11-20", ["0169990000011", "0169990000012"]),
    "<html><body><p>Confirmation Number: QXA1B2</p><p>0169990000011 0169990000012</p></body></html>",
])
def test_refuses_a_receipt_that_is_not_this_reservations(tmp_path, html):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.answers["QXA1B2"] = [{"PaxNm": "X", "Html": html}]
    target = tmp_path / "r.pdf"
    assert not site.download_bill(page, doc.date_text, target,
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "wrong" and not target.exists()


def test_an_empty_receipt_is_said_as_unavailable(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[1]
    page.answers["QXC3D4"] = [{}]
    assert not site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "unavailable"
    assert page.context.pages == [page]


def test_a_refused_receipt_reads_the_list_again_and_is_said_as_refused(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.receipt_status = 500
    loads = page.loads
    assert not site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "refused"
    assert page.loads == loads + 1


@pytest.mark.parametrize("status", [401, 403])
def test_a_receipt_refused_as_unauthorized_alone_fails_alone(tmp_path, status):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.receipt_status = status
    assert not site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "refused"


@pytest.mark.parametrize("status", [403, 500])
def test_a_receipt_refused_while_signed_out_stops_as_signed_out(tmp_path, status):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.receipt_status = status
    page.signed_out = True
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                           account=doc.account, document_id=doc.document_id)


@pytest.mark.parametrize("status", [428, 429])
def test_a_bot_check_on_a_receipt_stops_the_run(tmp_path, status):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.receipt_status = status
    with pytest.raises(site.ListStopped, match="refusing"):
        site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert page.context.pages == [page]


def test_will_not_save_another_members_receipt(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    other = Page(OTHER_MEMBER)
    with pytest.raises(site.ListStopped):
        site.download_bill(other, doc.date_text, tmp_path / "r.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert other.pressed == [] and not (tmp_path / "r.pdf").exists()


def test_a_receipt_gone_from_the_list_is_said_as_gone(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    reopened = Page()
    reopened.reservations = reopened.reservations[1:]
    assert not site.download_bill(reopened, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "gone" and reopened.pressed == []


def test_a_row_missing_from_the_page_is_gone_and_nothing_is_pressed(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.dom = build_dom(page.reservations[1:], page.options)
    assert not site.download_bill(page, doc.date_text, tmp_path / "r.pdf",
                                  account=doc.account, document_id=doc.document_id)
    assert site.last_refusal() == "gone"
    assert VIEW_LABEL not in page.pressed


def test_the_number_is_found_only_on_its_own():
    assert site._printed_number("Confirmation Number: QXA1B2", "QXA1B2")
    assert not site._printed_number("Confirmation Number: QXA1B2X", "QXA1B2")
    assert not site._printed_number("eTicket 10169990000011", "0169990000011")


def test_a_ligature_in_the_printed_text_does_not_hide_the_date():
    receipt = site.Receipt("T", "QXA1B2", rid(1), "2032-02-06", ("2032-02-06",), ("QXA1B2",), ())
    text = "Thank you for choosing United. Conﬁrmation Number: QXA1B2 Date of purchase: Fri, Feb 06, 2032"
    assert site.checks_out(text, receipt)


# -- the app -------------------------------------------------------------------

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


def test_app_names_each_receipt_by_its_number_and_resumes_cleanly(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    assert app.cmd_discover(quiet=True) == 4
    app.process(app._select())
    saved = sorted(Path(rec["pdf_path"]).name for rec in app.progress.data.values())
    assert saved == ["2031-11-20 United Flight Receipt QXE5F6.pdf",
                     "2032-02-06 United Flight Receipt QXA1B2.pdf",
                     "2032-02-07 United Purchase Receipt 0169990000901.pdf",
                     "2032-03-01 United Flight Receipt QXC3D4.pdf"]
    assert all(Path(rec["pdf_path"]).parent.name == "Receipts" for rec in app.progress.data.values())
    pressed = list(page.pressed)
    app.cmd_resume()
    assert page.pressed == pressed
    assert app._select(pending_only=True) == []


def test_an_unavailable_receipt_is_left_for_the_next_run(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    page.answers["QXC3D4"] = [{}]
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    said = capsys.readouterr().out
    assert "united.com could not show this receipt" in said
    left = [d.order_number for d in app._select(pending_only=True)]
    assert left == ["QXC3D4"]


def test_another_members_records_are_not_resumed(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    app.cmd_discover(quiet=True)
    other = Page(OTHER_MEMBER)
    other.reservations, other.options = [], []
    monkeypatch.setattr(app, "_on_its_site", lambda: other)
    app._billing_account = ""
    app.cmd_discover(quiet=True)
    assert app._select() == []
