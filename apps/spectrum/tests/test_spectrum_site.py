"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import base64
import io
import json
import logging
import os
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import spectrum_site as site  # noqa: E402
import spectrum_docs as docs  # noqa: E402
from paperpull_core import intake
from paperpull_core import pressing  # noqa: E402

HOST = "www.spectrum.net"
GRAPH = site.GRAPH_URL
# Invented account details, which must never leave through a log, the
# console, a record, a file name or a diagnostic. Short and patterned on
# purpose, so none has the shape of a real Spectrum account number.
CUR = "111122223"
PRI = "111144445"
STREET = "Quuxberry"
ADDRESS = "4321 Quuxberry Lane Apt 9B"


def text_pdf(lines) -> bytes:
    """A real one-page PDF whose text pypdf reads back, lines top to bottom."""
    ops = "BT /F1 11 Tf 72 740 Td 14 TL " + " ".join(
        "(%s) Tj T*" % str(t).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for t in lines) + " ET"
    stream = ops.encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def short(day):
    y, m, d = day.split("-")
    return "%s/%s/%s" % (m, d, y[2:])


def spectrum_pdf(day, *extra):
    """An invented Spectrum statement for `day`: its date, a service period
    and a total, with any extra lines."""
    return text_pdf(["Spectrum", "Statement Date %s" % short(day), "Service From %s" % short(day),
                     "Amount Due $80.00 Thank you for choosing us", *extra])


PDF = spectrum_pdf("2026-09-26")
OTHER_PDF = spectrum_pdf("2026-09-26", "another copy")
BLOB_URL = f"blob:https://{HOST}/0b1e-4c2d"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
CUR_DATES = ["2026-09-26", "2026-08-26", "2026-02-26"]
PRI_DATES = ["2026-02-26", "2026-01-26"]
# Invented: a date the two accounts both have a statement of.
TWIN_DAY = "2026-06-17"


def sid(account, day, kind="PDF_DOCUMENT", code="1"):
    return base64.b64encode(f"Account={account}|StatementDate={day}|StatementCode={code}|{kind}".encode()).decode()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def list_answer(cur=CUR_DATES, prior=PRI_DATES, prior_account=PRI):
    transfers = []
    if prior is not None:
        transfers.append({"accountNumber": prior_account, "serviceAddress": {"address1": ADDRESS},
                          "statements": [{"id": sid(prior_account, d), "date": d + "T00:00:00-05:00"} for d in prior]})
    return {"data": {"viewer": {"account": {"statementList": {
        "statements": [{"id": sid(CUR, d), "date": d + "T00:00:00-05:00"} for d in cur],
        "accountTransfers": transfers, "icoms48HourDelayShowMessage": False}}}}}


def row_text(day):
    y, m, d = day.split("-")
    return f"Statement {MONTHS[int(m) - 1]} {int(d)}, {y} {ADDRESS}"


def pdf_answer(data=PDF):
    return {"data": {"viewer": {"account": {"statementPdf": b64(data)}}}}


class Resp:
    def __init__(self, op, variables=None, status=200, answer=None, url=GRAPH, method="POST"):
        body = {"operationName": op, "query": "query x", "variables": variables or {}}
        self.request = SimpleNamespace(url=url, method=method, post_data=json.dumps(body))
        self.status = status
        self._answer = answer if answer is not None else {"data": {}}

    def json(self):
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def blob_result(data=PDF, blobs=1, kind="application/pdf", url=BLOB_URL, opened=None):
    return {"blobs": [{"type": kind, "size": len(data), "url": url}] * blobs,
            "opened": [url] if opened is None else opened, "b64": b64(data) if blobs == 1 else ""}


def day_of(statement_id):
    raw = statement_id + "=" * (-len(statement_id) % 4)
    return re.search(r"StatementDate=([0-9-]+)", base64.b64decode(raw).decode()).group(1)


def good_press(page):
    """What the page does on the press: asks for the PDF of the statement
    it shows and makes one Blob of it."""
    data = spectrum_pdf(day_of(page.detail_sid))
    page.emit("response", Resp(site.PDF_OPERATION, {"statementId": page.detail_sid, "otpCheck": True},
                               answer=pdf_answer(data)))
    page.blob = blob_result(data)


def own_copy(page):
    """As good_press, with a file of its own for each account's statement."""
    data = spectrum_pdf(day_of(page.detail_sid), "transfer" if "Transfer=true" in page.url else "own")
    page.emit("response", Resp(site.PDF_OPERATION, {"statementId": page.detail_sid, "otpCheck": True},
                               answer=pdf_answer(data)))
    page.blob = blob_result(data)


MOB = "222255556"
MOB_PHONE = "555-010-4477"
NB = "\u00a0"
MOBILE_DAYS = ["2026-09-13", "2026-08-13", "2026-07-13"]


def mobile_sid(day):
    return "Zq9" + day.replace("-", "") + "Kx"


def upper_date(day):
    y, m, d = day.split("-")
    return f"{MONTHS[int(m) - 1].upper()} {int(d)}, {y}"


def mobile_row(day):
    y, m, d = day.split("-")
    return NB.join(["Statement", MONTHS[int(m) - 1], f"{int(d)},", y])


def mobile_rows(days=MOBILE_DAYS):
    """The Mobile list as the survey saw it: the statement under way, the
    estimate, the finished statements and an order."""
    return (["Statement October 13 Auto Pay: Oct 30 $78.12", "Your Total So Far Auto Pay: Nov 30 $80.00"]
            + [mobile_row(d) for d in days] + ["Order 1234567 August 13, 2025"])


def spaced(text):
    """Letter-spaced, the way the printed heading reads back from pypdf: one
    space between letters, two between words."""
    return "  ".join(" ".join(word) for word in text.split(" "))


def mobile_print(page):
    """What printing the Mobile statement page gives, in the shape the live
    print of 2026-10-13 read back: the heading's date letter-spaced and first,
    "Mobile" after it, and no "Statement Details" bar."""
    return text_pdf([spaced(upper_date(page.mobile_day)), "Mobile", spaced("AMOUNT DUE"), "61.40",
                     "Previous Balance Payments and Credits Remaining Balance",
                     "Unlimited Plus Lines (2) Phone " + MOB_PHONE, "Included Taxes, Fees & Charges"])


# The live print's first page as pypdf read it, masked, with a made-up
# address in place of the real one.
LIVE_PRINT = ("S E P T E M B E R 1 3, 2 0 2 6 Mobile A M O U N T D U E 60.00 Your Auto Pay is scheduled "
              "for September 30. # # 4321 Quuxberry Lane Account Number: # Previous Activity Auto Pay "
              "Payment - Visa ending in # -# Paid on August 30 Services # $ Account Holder Information "
              "Previous Balance # Payments and Credits -# Remaining Balance # Unlimited Plus Lines (2) #")


def mobile_lands(page, index):
    """What a press of a Mobile list row does: the page moves in place to that
    statement's own page."""
    day = site.mobile_row_day(page.links()[index])
    page.mobile_day = day
    page.where = "mdetail"
    page.url = (f"https://{HOST}{site.MOBILE_DETAIL_PATH}?statementId={mobile_sid(day)}"
                f"&newStatementVersion=true")


def digital(account, day):
    """The page's own unpadded DIGITAL_DOCUMENT id for a statement, with a
    code of its own."""
    return sid(account, day, "DIGITAL_DOCUMENT", code="7").rstrip("=")


def lands(page, index):
    """What a press of a statement row does: the page moves in place to that
    statement's own page, and asks for it and, unless it is the newest, for
    the newest as well."""
    family, account, day = page.order()[index]
    page.detail_sid = digital(account, day)
    page.url = (f"https://{HOST}{site.DETAIL_PATH}?pdfStatementId={page.detail_sid}&isNextBill=false"
                f"&isAccountTransfer={'true' if family == 'prior' else 'false'}")
    current = sorted(d for f, _, d in page.order() if f == "current")
    compare = [] if not current or (family, day) == ("current", current[-1]) else [
        Resp(site.DETAIL_OPERATION, {"statementId": digital(CUR, current[-1])})]
    responses = page.detail(page.detail_sid) if page.detail else (
        [Resp(site.DETAIL_OPERATION, {"statementId": page.detail_sid, "showComparison": True})] + compare)
    for r in responses:
        page.emit("response", r)


class Btn:
    def __init__(self, page, items):
        self.page, self.items = page, items

    def count(self):
        return len(self.items)

    @property
    def first(self):
        return Btn(self.page, self.items[:1])

    def inner_text(self, **kw):
        return self.items[0][0]

    def is_enabled(self, **kw):
        return self.items[0][1]


class Page:
    """Spectrum's billing pages as the survey saw them, with invented values."""

    def __init__(self, answer=None, list_responses=None, rows=None, settle=None, body="",
                 detail=None, buttons=(("View Printable Statement", True),), on_press=good_press,
                 dl_dir=None, on_row=lands, mobile=None, on_link=None, on_mobile_row=mobile_lands,
                 on_expand=None, detail_state=None, mbuttons=(("Expand All", True), ("Print", True)),
                 on_print=mobile_print, sections=None):
        self.answer = list_answer() if answer is None else answer
        self.list_responses = list_responses
        self.rows = rows
        self.settle = settle or {}
        self.body = body
        self.detail = detail
        self.buttons = list(buttons)
        self.on_press = on_press
        self.on_row = on_row
        self.dl_dir = dl_dir
        self.clicks = []           # (css, step, what) of every press
        self.row_presses = []      # the index of each statement row pressed
        self.row_changes = {}      # index: words a row shows when read again
        # The own href of a statement row, by its index, and of a Billing
        # link or a Mobile row, by ("billing" or "mlist", its index). Each
        # reads "javascript:void(0)", as the survey saw them, unless set.
        self.hrefs = {}
        self.fail_wait = None      # page -> True when a wait should raise
        self.fail_on = set()       # events whose listener cannot be added
        self.url = f"https://{HOST}/account-summary"
        self.listeners = {}
        self.gotos, self.presses, self.blob, self.armed = [], 0, {"blobs": [], "opened": []}, False
        self.detail_sid = ""
        self.restored = False
        # The Mobile pages: None for a customer with no Mobile account, else
        # the rows its list draws.
        self.mobile = mobile
        self.on_link, self.on_mobile_row, self.on_expand = on_link, on_mobile_row, on_expand
        self.detail_state = detail_state
        self.mbuttons = list(mbuttons)
        self.on_print = on_print
        self.sections = sections
        self.where = ""
        self.mobile_day = ""
        self.expanded = 0
        self.link_presses, self.mobile_row_presses, self.expands, self.prints = 0, [], 0, 0
        page = self

        class Ctx:
            pages = [page]
        self.context = Ctx()

    # events
    def on(self, event, fn):
        if event in self.fail_on:
            raise RuntimeError("could not listen")
        self.listeners.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        self.listeners[event].remove(fn)

    def emit(self, event, obj):
        for fn in list(self.listeners.get(event, [])):
            fn(obj)

    def live_listeners(self):
        return sum(len(v) for v in self.listeners.values())

    # navigation
    def goto(self, url, **kw):
        self.gotos.append(url)
        path = url.split("?")[0][len(site.BASE):]
        self.url = self.settle.get(path, url)
        self.where = "billing" if path == site.BILLING_HOME_PATH else ""
        if path == site.STATEMENTS_PATH:
            responses = self.list_responses
            if responses is None:
                responses = [Resp(site.LIST_OPERATION, answer=self.answer)]
            for r in responses:
                self.emit("response", r)
        elif path == site.DETAIL_PATH:
            self.detail_sid = dict(re.findall(r"([^?&=]+)=([^&]*)", url.split("?", 1)[1])).get("pdfStatementId", "")
            from urllib.parse import unquote
            self.detail_sid = unquote(self.detail_sid)
            responses = self.detail(self.detail_sid) if self.detail else [
                Resp(site.DETAIL_OPERATION, {"statementId": self.detail_sid, "showComparison": True})]
            for r in responses:
                self.emit("response", r)

    def wait_for_timeout(self, ms):
        if self.fail_wait and self.fail_wait(self):
            raise RuntimeError("Timeout waiting on %s for account %s" % (self.url, CUR))

    def order(self):
        """(family, account, date) of each statement, in the list answer's order."""
        sl = self.answer["data"]["viewer"]["account"]["statementList"]
        out = [("current", CUR, s["date"][:10]) for s in sl["statements"]]
        out += [("prior", t["accountNumber"], s["date"][:10]) for t in sl["accountTransfers"] for s in t["statements"]]
        return out

    def row_texts(self):
        if self.rows is not None:
            return list(self.rows)
        texts = [row_text(d) for _, _, d in self.order()]
        if texts and self.order()[0][0] == "current":
            texts[0] += " Auto Pay: Oct 10 $80.00"
        return texts + ["Make Early Payment"]

    def links(self):
        """The anchors with role=link the page draws where it is."""
        if self.where == "billing":
            out = ["Auto Pay", "Payment Methods", NB.join(["Internet", "Account", "Number:", CUR])]
            if self.mobile is not None:
                out.append(NB.join(["Mobile", "Account", "Number:", MOB]))
            return out + ["Internet", "Mobile", "Manage Mobile Devices"]
        if self.where == "mlist":
            return list(self.mobile)
        return []

    def evaluate(self, js, arg=None):
        if js == site._LINKS_JS:
            assert arg == site.MOBILE_ROW
            return self.links()
        if js == site._DETAIL_JS:
            if self.where != "mdetail":
                return {"dates": [], "details": False, "mobile": False}
            if self.detail_state:
                return self.detail_state(self)
            extra = ["September 2, 2026"] if self.expanded else []
            return {"dates": [upper_date(self.mobile_day)] + extra, "details": True, "mobile": True}
        if js == site._SECTIONS_JS:
            if self.where != "mdetail":
                return {"toggles": 0, "toggle": "", "sections": 0, "open": 0}
            if self.sections:
                return self.sections(self)
            return {"toggles": 1, "toggle": "collapse" if self.expanded else "expand",
                    "sections": 6, "open": 6 if self.expanded else 0}
        if js == site._ROWS_JS:
            return self.row_texts()
        if js == site._ARM_JS:
            self.armed = True
            return None
        if js == site._RESTORE_JS:
            self.restored = self.armed
            self.armed = False
            return True
        if js == site._COUNT_JS:
            return len(self.blob.get("blobs") or [])
        # Run through intake.evaluate, so with the core's reader in front.
        if js == intake.reading(site._RESULT_JS):
            return self.blob
        raise AssertionError("unexpected script")

    def locator(self, sel):
        page = self
        if sel == site.MOBILE_ROW:
            class Links:
                def nth(self, i):
                    return MRow(page, i)
            return Links()
        if sel == site.STATEMENT_ROW:
            class Rows:
                def nth(self, i):
                    return Row(page, i)
            return Rows()

        class L:
            def count(self):
                return 0

            def inner_text(self, **kw):
                return page.body
        return L()

    def get_by_role(self, role, name=None):
        assert role == "button"
        if self.where == "mdetail":
            return Btn(self, [b for b in self.mbuttons if name.search(b[0])])
        return Btn(self, [b for b in self.buttons if name.search(b[0])])

    def title(self):
        return "Spectrum"

    def is_closed(self):
        return False


class Row:
    def __init__(self, page, index):
        self.page, self.index = page, index

    def inner_text(self, **kw):
        return self.page.row_changes.get(self.index, self.page.row_texts()[self.index])

    def get_attribute(self, name, **kw):
        assert name == "href"
        href = self.page.hrefs.get(self.index, "javascript:void(0)")
        if isinstance(href, Exception):
            raise href
        return href


class MRow:
    """An anchor with role=link, on Billing or the Mobile list."""

    def __init__(self, page, index):
        self.page, self.index = page, index

    def inner_text(self, **kw):
        return self.page.row_changes.get(("m", self.index), self.page.links()[self.index])

    def get_attribute(self, name, **kw):
        assert name == "href"
        href = self.page.hrefs.get((self.page.where, self.index), "javascript:void(0)")
        if isinstance(href, Exception):
            raise href
        return href


def fake_click(page, el, **kw):
    """A spy for pressing.click: records each press and plays the page's
    answer to it."""
    page.clicks.append((kw["css"], kw["step"], kw["what"]))
    if isinstance(el, MRow):
        assert kw["css"] == pressing.LINKS
        if page.where == "billing":
            assert kw["step"] == site.OPEN_MOBILE_STEP
            page.link_presses += 1
            if page.on_link:
                page.on_link(page)
                return
            page.where = "mlist"
            page.url = f"https://{HOST}{site.MOBILE_LIST_PATH}"
            return
        assert page.where == "mlist" and kw["step"] == site.CHOOSE_MOBILE_STEP
        page.mobile_row_presses.append(el.index)
        page.on_mobile_row(page, el.index)
        return
    if kw["step"] == site.EXPAND_STEP:
        assert kw["css"] == pressing.BUTTONS and page.where == "mdetail"
        assert site.is_expand_all(el.inner_text())
        page.expands += 1
        page.expanded = 1
        if page.on_expand:
            page.on_expand(page)
        return
    if isinstance(el, Row):
        assert kw["css"] == pressing.LINKS and kw["step"] == "choose a statement"
        page.row_presses.append(el.index)
        page.on_row(page, el.index)
        return
    assert kw["css"] == pressing.BUTTONS and kw["step"] == "take a statement"
    page.presses += 1
    page.on_press(page)


def fake_print(page, out_path):
    """A spy for receipt_pdf.print_page_to_pdf: what the page prints."""
    page.prints += 1
    data = page.on_print(page)
    if isinstance(data, Exception):
        raise data
    Path(out_path).write_bytes(data)


@contextmanager
def gone_when_read(name):
    """The file called `name` goes the moment anything reads its size, as a
    download the browser deletes or renames can between a listing of its
    folder and the next look."""
    real = Path.stat

    def stat(path, *args, **kwargs):
        if path.name == name:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        return real(path, *args, **kwargs)
    with mock.patch.object(Path, "stat", stat):
        yield


class WithFakeClick(unittest.TestCase):
    def setUp(self):
        self._click = pressing.click
        pressing.click = fake_click
        self._receipt_pdf = site.receipt_pdf
        site.receipt_pdf = SimpleNamespace(print_page_to_pdf=fake_print)
        site._KEPT.clear()
        site._MOBILE_IDS.clear()
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        pressing.click = self._click
        site.receipt_pdf = self._receipt_pdf

    def take(self, page, family="current", day="2026-09-26", dl_dir=""):
        if dl_dir == "":
            dl_dir = self.tmp / "staging"
            dl_dir.mkdir(exist_ok=True)
        out = self.tmp / ("%s-%s.pdf" % (family, day))
        trace = []
        ok = site.download_bill(page, dl_dir, day, out, title=site.TITLE, trace=trace,
                                document_id="%s:%s" % (family, day))
        return ok, out, trace


# ---------------------------------------------------------------------------

class Hosts(unittest.TestCase):
    def test_only_the_site_over_https(self):
        for u in [f"https://{HOST}/", site.STATEMENTS_URL, f"https://{HOST}/billing/bill-details?x=1"]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["https://spectrum.net/", "https://apis.spectrum.net/selfservice/graph", "https://id.spectrum.net/login",
                  f"http://{HOST}/", f"https://{HOST}:8443/", f"https://u@{HOST}/", f"https://{HOST}.evil.test/",
                  f"https://{HOST}@evil.test/", f"blob:https://{HOST}/x", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_blob_origin(self):
        self.assertTrue(site.is_download_url(BLOB_URL))
        for u in ["blob:https://apis.spectrum.net/x", f"blob:http://{HOST}/x", f"blob:https://{HOST}:8443/x",
                  f"https://{HOST}/x.pdf", "blob:null/x", f"blob:https://u@{HOST}/x", "", None]:
            self.assertFalse(site.is_download_url(u), repr(u))

    def test_the_statement_route_is_one_exact_shape(self):
        good = sid(CUR, "2026-09-26")
        url = site.detail_url(good, False)
        self.assertTrue(url.startswith(f"https://{HOST}/billing/bill-details?pdfStatementId="))
        self.assertTrue(site.is_detail_url(url, good))
        self.assertTrue(site.is_detail_url(site.detail_url(good, True), good))
        self.assertFalse(site.is_detail_url(url, sid(CUR, "2026-08-26")), "another statement's id")
        base = f"https://{HOST}/billing/bill-details"
        q = f"pdfStatementId={good}&isNextBill=false&isAccountTransfer=false"
        for bad in [f"http://{HOST}/billing/bill-details?{q}", f"https://{HOST}:443x/billing/bill-details?{q}",
                    f"https://{HOST}:8443/billing/bill-details?{q}", f"https://u:p@{HOST}/billing/bill-details?{q}",
                    f"{base}?{q}#frag", f"{base}/?{q}", f"https://{HOST}/billing/statements?{q}",
                    f"https://apis.spectrum.net/billing/bill-details?{q}", f"{base}?{q}&extra=1",
                    f"{base}?{q}&isNextBill=false", f"{base}?pdfStatementId={good}&isNextBill=false",
                    f"{base}?pdfStatementId={good}&isNextBill=true&isAccountTransfer=false",
                    f"{base}?pdfStatementId={good}&isNextBill=false&isAccountTransfer=maybe",
                    f"{base}?pdfStatementId=notbase64!&isNextBill=false&isAccountTransfer=false",
                    f"{base}?pdfStatementId={sid(CUR, '2026-09-26', 'DIGITAL_DOCUMENT')}&isNextBill=false&isAccountTransfer=false",
                    base, ""]:
            self.assertFalse(site.is_detail_url(bad), bad)
        # Padding "=" in an id survives the address both ways (the id's
        # text is ASCII digits, letters, "=" and "|", so its base64 never
        # holds "+" or "/").
        padded = next(sid(CUR[:n], "2026-09-26") for n in range(4, 17) if sid(CUR[:n], "2026-09-26").endswith("="))
        self.assertTrue(site.is_detail_url(site.detail_url(padded, True), padded))
        self.assertEqual(site.detail_url("", False), "")
        self.assertEqual(site.detail_url("bad id", False), "")

    def test_sign_in_shapes(self):
        for u in [f"https://{HOST}/login", f"https://{HOST}/login?loggedOut=true", "https://id.spectrum.net/x",
                  f"https://{HOST}/error/session-expired"]:
            p = Page()
            p.url = u
            self.assertTrue(site.looks_signed_out(p), u)
        p = Page()
        p.url = site.STATEMENTS_URL
        self.assertFalse(site.looks_signed_out(p))


class Guard(unittest.TestCase):
    def test_only_the_one_label(self):
        for label in ["View Printable Statement", "view printable statement", "  View   Printable\nStatement "]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_everything_else_is_refused(self):
        for label in ["View Printable Statement and Pay", "View Printable Statement | Make Early Payment",
                      "Make Early Payment | View Printable Statement", "View Printable Statements",
                      "Print Statement", "View Statement", "Download Statement", "Statement", "Internet Statement",
                      "Expand All", "Back", "Make Early Payment", "Auto Pay", "Payment Methods", "Go Paperless",
                      "Enroll", "Settings", "Manage Mobile Devices", "Upgrade", "Add for $5/mo", "Change Plan",
                      "Cancel Service", "Services", "Schedule Appointment", "Chat with Spectrum", "Sign Out",
                      "Log Out", "Send one-time code", "Verify", "Enter Code", "Order now", "Shop Deals",
                      "Call 1-800", "", "   ", None]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Ids(unittest.TestCase):
    def test_decoding(self):
        self.assertEqual(site.decode_statement_id(sid(CUR, "2026-09-26")), (CUR, "2026-09-26"))

    def test_anything_else_stops_without_saying_the_id(self):
        for bad in ["", None, "not base64!", sid(CUR, "2026-09-26")[:-1], b64(b"Account=1|PDF_DOCUMENT"),
                    sid(CUR, "2026-09-26", "DIGITAL_DOCUMENT"), sid(CUR, "2026-02-30"), sid("12ab", "2026-09-26"),
                    sid(CUR, "2026-09-26", code="x"), sid(CUR, "2026-09-26") + "&x"]:
            with self.assertRaises(site.ListStopped) as stop:
                site.decode_statement_id(bad)
            self.assertNotIn(CUR, str(stop.exception))
            self.assertNotIn("Account", str(stop.exception))

    def test_day_of_the_answer(self):
        self.assertEqual(site.iso_day("2026-09-26T00:00:00-05:00"), "2026-09-26")
        self.assertEqual(site.iso_day("2026-09-26"), "2026-09-26")
        for bad in ["2026-02-30T00:00:00-05:00", "Sep 26, 2026", "2026-09-26x", "", None]:
            self.assertIsNone(site.iso_day(bad), repr(bad))
        self.assertEqual(site.row_day("Statement September 26, 2026 Auto Pay: Oct 1"), "2026-09-26")
        self.assertIsNone(site.row_day("Statement Sept 26, 2026"))


class Families(unittest.TestCase):
    def entries(self, answer):
        return site.entries_of(site.statement_list_of(answer))

    def test_current_and_prior(self):
        got = self.entries(list_answer())
        self.assertEqual([e.document_id for e in got],
                         ["current:2026-09-26", "current:2026-08-26", "current:2026-02-26",
                          "prior:2026-02-26", "prior:2026-01-26"])
        self.assertNotIn(CUR, repr(got), "an entry's repr carries no id")
        docs_ = site.raw_docs(got)
        self.assertEqual({(d.title, d.account, d.kind, d.href) for d in docs_},
                         {(site.TITLE, "Internet", "statement", ""),
                          (site.TITLE, "Internet (prior account)", "statement", "")})
        blob = json.dumps([d.__dict__ for d in docs_])
        for word in (CUR, PRI, STREET, sid(CUR, "2026-09-26")):
            self.assertNotIn(word, blob)

    def test_private_words_are_registered(self):
        self.entries(list_answer())
        words = site.private_words()
        for word in (CUR, PRI, STREET, "4321", sid(CUR, "2026-09-26"), sid(PRI, "2026-01-26")):
            self.assertIn(word, words)
        self.assertNotIn("Apt", words, "a short address part is not a word")
        self.assertIn("CAPTCHA", site.redact("CAPTCHA Statement"))

    def test_what_stops_the_list(self):
        same_twice = list_answer(cur=["2026-09-26", "2026-09-26"])
        prior_twice = list_answer(prior=["2026-01-26", "2026-01-26"])
        mismatch = list_answer()
        mismatch["data"]["viewer"]["account"]["statementList"]["statements"][0]["date"] = "2026-09-25T00:00:00-05:00"
        other_acct = list_answer(prior_account=PRI)
        other_acct["data"]["viewer"]["account"]["statementList"]["accountTransfers"][0]["accountNumber"] = "111177778"
        two_accts = list_answer()
        two_accts["data"]["viewer"]["account"]["statementList"]["statements"][1]["id"] = sid(PRI, "2026-08-26")
        digital = list_answer()
        digital["data"]["viewer"]["account"]["statementList"]["statements"][0]["id"] = sid(CUR, "2026-09-26", "DIGITAL_DOCUMENT")
        bad_date = list_answer()
        bad_date["data"]["viewer"]["account"]["statementList"]["statements"][0]["date"] = "September 26"
        for name, answer in [("same date twice in current", same_twice), ("same date twice in prior", prior_twice),
                             ("id date differs", mismatch), ("transfer names another account", other_acct),
                             ("current names two accounts", two_accts), ("digital id", digital),
                             ("bad date", bad_date), ("no statementList", {"data": {"viewer": {}}}),
                             ("not an object", [])]:
            with self.assertRaises(site.ListStopped, msg=name) as stop:
                self.entries(answer)
            for word in (CUR, PRI, STREET):
                self.assertNotIn(word, str(stop.exception), name)

    def test_errors_in_the_answer_are_a_signed_out_session(self):
        with self.assertRaises(site.SessionExpired):
            self.entries({"errors": [{"message": "token " + CUR}], "data": None})

    def test_one_date_across_families_is_two_statements(self):
        got = self.entries(list_answer(cur=["2026-02-26"], prior=["2026-02-26"]))
        self.assertEqual([e.document_id for e in got], ["current:2026-02-26", "prior:2026-02-26"])

    def test_an_empty_list_is_empty(self):
        self.assertEqual(self.entries(list_answer(cur=[], prior=None)), [])


class Listing(unittest.TestCase):
    def test_reads_the_one_answer_and_takes_nothing_off_the_page(self):
        page = Page()
        got = site.collect_download_docs(page, mobile=False)
        self.assertEqual(len(got), 5)
        self.assertEqual(page.gotos, [site.STATEMENTS_URL])
        self.assertEqual(page.live_listeners(), 0, "the listener is taken off")

    def test_cardinality(self):
        other = Resp("fetchAccountGlobal", answer={"data": {}})
        wrong_host = Resp(site.LIST_OPERATION, answer=list_answer(), url="https://apis.spectrum.net/selfservice/graphauxiliary")
        get = Resp(site.LIST_OPERATION, answer=list_answer(), method="GET")
        for name, responses in [("none", []), ("only other operations", [other]),
                                ("two", [Resp(site.LIST_OPERATION, answer=list_answer())] * 2),
                                ("another address", [wrong_host]), ("a GET", [get]),
                                ("not JSON", [Resp(site.LIST_OPERATION, answer=ValueError("x"))]),
                                ("a 500", [Resp(site.LIST_OPERATION, status=500)])]:
            page = Page(list_responses=responses)
            with self.assertRaises(site.ListStopped, msg=name):
                site.read_statement_list(page)
            self.assertEqual(page.live_listeners(), 0, name)

    def test_signed_out_answers(self):
        for name, page in [
                ("401", Page(list_responses=[Resp(site.LIST_OPERATION, status=401)])),
                ("401 on another operation", Page(list_responses=[Resp("fetchAccountGlobal", status=401),
                                                                   Resp(site.LIST_OPERATION, answer=list_answer())])),
                ("errors", Page(list_responses=[Resp(site.LIST_OPERATION, answer={"errors": [{"m": 1}]})])),
                ("session check", Page(list_responses=[
                    Resp("x", url="https://apis.spectrum.net/auth/oauth/v2/validateSession?ts=1", method="GET",
                         answer={"isValidSession": False}),
                    Resp(site.LIST_OPERATION, answer=list_answer())])),
                ("sign-in page", Page(settle={site.STATEMENTS_PATH: f"https://{HOST}/login"})),
                ("id host", Page(settle={site.STATEMENTS_PATH: "https://id.spectrum.net/x"})),
                ("idle dialog", Page(body="Your session is about to expire. Stay signed in?"))]:
            with self.assertRaises(site.SessionExpired, msg=name):
                site.read_statement_list(page)
            self.assertEqual(page.live_listeners(), 0, name)

    def test_a_passcode_prompt(self):
        page = Page(body="Enter the one-time passcode we sent")
        with self.assertRaises(site.OtpRequired):
            site.read_statement_list(page)

    def test_the_drawn_rows_must_agree(self):
        for rows in ([row_text(d) for d in CUR_DATES + PRI_DATES[:1]],
                     [row_text(d) for d in CUR_DATES + ["2026-01-27", "2026-02-26"]],
                     [row_text(d) for d in CUR_DATES + PRI_DATES] + ["Statement soon"]):
            with self.assertRaises(site.ListStopped):
                site.read_statement_list(Page(rows=rows))

    def test_settled_elsewhere(self):
        with self.assertRaises(site.ListStopped):
            site.read_statement_list(Page(settle={site.STATEMENTS_PATH: f"https://{HOST}/account-summary"}))


class Binding(WithFakeClick):
    def test_success_saves_the_one_statement(self):
        page = Page()
        ok, out, trace = self.take(page)
        self.assertTrue(ok)
        self.assertEqual(out.read_bytes(), PDF)
        self.assertEqual(page.presses, 1)
        self.assertTrue(page.restored, "the page's own window.open and createObjectURL are back")
        self.assertFalse(page.armed)
        self.assertEqual(page.live_listeners(), 0)
        self.assertTrue(site.is_detail_url(page.gotos[-1], sid(CUR, "2026-09-26")))
        self.assertEqual(page.row_presses, [], "the newest is opened by its address, no row pressed")

    def test_no_single_entry_means_no_press(self):
        for family, day in [("current", "2026-09-25"), ("prior", "2026-09-26")]:
            page = Page()
            ok, out, _ = self.take(page, family, day)
            self.assertFalse(ok)
            self.assertEqual(page.presses, 0)
            self.assertEqual(page.gotos, [site.STATEMENTS_URL])
        real = site.read_statement_list
        e = site.Entry("current", "2026-09-26", sid(CUR, "2026-09-26"))
        site.read_statement_list = lambda page: [e, e]
        try:
            page = Page()
            ok, out, _ = self.take(page)
        finally:
            site.read_statement_list = real
        self.assertFalse(ok)
        self.assertEqual(page.presses, 0)

    def test_a_record_that_is_not_one_is_refused(self):
        page = Page()
        out = self.tmp / "x.pdf"
        for doc_id, day in [("current:2026-09-26", "2026-09-25"), (sid(CUR, "2026-09-26"), "2026-09-26"),
                            ("", "2026-09-26"), ("other:2026-09-26", "2026-09-26")]:
            self.assertFalse(site.download_bill(page, None, day, out, document_id=doc_id))
        self.assertEqual(page.gotos, [])

    def test_the_page_must_ask_for_this_statement(self):
        cases = {
            "another statement": lambda s: [Resp(site.DETAIL_OPERATION, {"statementId": sid(CUR, "2026-08-26")})],
            "none": lambda s: [],
            "twice": lambda s: [Resp(site.DETAIL_OPERATION, {"statementId": s})] * 2,
        }
        for name, detail in cases.items():
            page = Page(detail=detail)
            ok, out, _ = self.take(page)
            self.assertFalse(ok, name)
            self.assertEqual(page.presses, 0, name)
            self.assertFalse(out.exists(), name)
            self.assertEqual(page.live_listeners(), 0, name)

    def test_the_statement_page_signed_out(self):
        page = Page(detail=lambda s: [Resp(site.DETAIL_OPERATION, {"statementId": s}, status=401)])
        with self.assertRaises(site.SessionExpired):
            self.take(page)
        self.assertEqual(page.presses, 0)
        page = Page(detail=lambda s: [Resp(site.DETAIL_OPERATION, {"statementId": s}, answer={"errors": [1]})])
        with self.assertRaises(site.SessionExpired):
            self.take(page)
        page = Page(settle={site.DETAIL_PATH: f"https://{HOST}/login"})
        with self.assertRaises(site.SessionExpired):
            self.take(page)
        self.assertEqual(page.presses, 0)

    def test_the_button_must_be_one_enabled_exact_label(self):
        for buttons in [(), (("View Printable Statement", True),) * 2, (("View Printable Statement", False),),
                        (("View Printable Statement and Pay", True),), (("View Printable Statements", True),)]:
            page = Page(buttons=buttons)
            ok, out, _ = self.take(page)
            self.assertFalse(ok, buttons)
            self.assertEqual(page.presses, 0, buttons)


class Acceptance(WithFakeClick):
    def stops(self, on_press, dl_dir="", **kw):
        page = Page(on_press=on_press, **kw)
        with self.assertRaises(pressing.Stop) as stop:
            self.take(page, dl_dir=dl_dir)
        self.assertTrue(stop.exception.after_a_press)
        self.assertEqual(page.presses, 1)
        self.assertEqual(page.live_listeners(), 0)
        self.assertTrue(page.restored, "the hook is taken off after a refusal too")
        self.assertFalse(list(self.tmp.glob("*.pdf")))
        for word in (CUR, PRI, STREET):
            self.assertNotIn(word, " ".join(stop.exception.lines))
        return stop.exception

    def test_the_matrix(self):
        def answer_only(p):
            p.emit("response", Resp(site.PDF_OPERATION, {"statementId": p.detail_sid}, answer=pdf_answer()))

        def blob_only(p):
            p.blob = blob_result()

        def bytes_differ(p):
            good_press(p)
            p.blob = blob_result(OTHER_PDF)

        def two_blobs(p):
            good_press(p)
            p.blob = blob_result(blobs=2)

        def two_answers(p):
            good_press(p)
            p.emit("response", Resp(site.PDF_OPERATION, {"statementId": p.detail_sid}, answer=pdf_answer()))

        def other_statement(p):
            p.emit("response", Resp(site.PDF_OPERATION, {"statementId": sid(CUR, "2026-08-26")}, answer=pdf_answer()))
            p.blob = blob_result()

        def not_a_pdf(p):
            p.emit("response", Resp(site.PDF_OPERATION, {"statementId": p.detail_sid}, answer=pdf_answer(b"<html>")))
            p.blob = blob_result(b"<html>")

        def wrong_type(p):
            good_press(p)
            p.blob = blob_result(kind="text/html")

        def wrong_origin(p):
            good_press(p)
            p.blob = blob_result(url="blob:https://apis.spectrum.net/x")

        def opened_elsewhere(p):
            good_press(p)
            p.blob = blob_result(opened=["https://www.spectrum.net/billing"])

        def new_page(p):
            good_press(p)
            p.context.pages.append(SimpleNamespace(close=lambda: None))

        def popup(p):
            good_press(p)
            p.emit("popup", object())

        def left_route(p):
            good_press(p)
            p.url = f"https://{HOST}/billing"

        for f in (answer_only, blob_only, bytes_differ, two_blobs, two_answers, other_statement, not_a_pdf,
                  wrong_type, wrong_origin, opened_elsewhere, new_page, popup, left_route):
            self.stops(f)

    def test_a_download_event_stops_the_run_and_is_dropped_unread(self):
        class Download:
            def __init__(self):
                self.dropped = []

            def cancel(self):
                self.dropped.append("cancel")

            def delete(self):
                self.dropped.append("delete")

            def __getattr__(self, name):
                raise AssertionError("the download's %s was read" % name)
        seen = Download()

        def download(p):
            good_press(p)
            p.emit("download", seen)
        self.stops(download)
        self.assertEqual(seen.dropped, ["cancel", "delete"])

    def test_a_file_in_the_folder_stops_the_run_and_is_removed(self):
        dl = self.tmp / "dl"
        dl.mkdir()
        (dl / "Statement.pdf").write_bytes(b"left from before")
        import os
        os.utime(dl / "Statement.pdf", ns=(1, 1))

        def new_file(p):
            good_press(p)
            (dl / "Other.pdf.crdownload").write_bytes(b"x")

        def same_name(p):
            good_press(p)
            (dl / "Statement.pdf").write_bytes(b"written over by the press")
        self.stops(new_file, dl_dir=dl)
        self.assertEqual(sorted(x.name for x in dl.iterdir()), ["Statement.pdf"])
        self.stops(same_name, dl_dir=dl)
        self.assertEqual(list(dl.iterdir()), [], "nothing a download left stays in the folder")

    def test_an_unreadable_folder_stops_the_run(self):
        self.stops(good_press, dl_dir=self.tmp / "no such folder")

    def test_a_file_the_browser_deletes_as_the_folder_is_read_is_no_download(self):
        """The browser deletes a download it was told to drop in its own
        time, so a file can be listed and gone before its size is read. It
        is not in the folder then. The whole folder used to count as
        unreadable, and a press that brought exactly its statement stopped
        the run as though it had begun a download."""
        dl = self.tmp / "dl"
        dl.mkdir()
        (dl / "Earlier.pdf.crdownload").write_bytes(b"x")
        with gone_when_read("Earlier.pdf.crdownload"):
            ok, out, _trace = self.take(Page(), dl_dir=dl)
        self.assertTrue(ok)
        self.assertEqual(out.read_bytes(), PDF)
        self.assertEqual(list(dl.iterdir()), [])

    def test_a_file_the_press_brought_that_goes_as_it_is_read_stops_the_run(self):
        """A file that came with the press and went before its size was
        read, as the browser renames a download it finished, still came."""
        dl = self.tmp / "dl"
        dl.mkdir()

        def comes(p):
            good_press(p)
            (dl / "Other.pdf.crdownload").write_bytes(b"x")
        with gone_when_read("Other.pdf.crdownload"):
            self.stops(comes, dl_dir=dl)
        self.assertEqual(list(dl.iterdir()), [])

    def test_a_passcode_after_the_press(self):
        def otp(p):
            p.body = "We sent a one-time passcode to your phone"
        page = Page(on_press=otp)
        with self.assertRaises(site.OtpRequired):
            self.take(page)
        self.assertEqual(page.live_listeners(), 0)
        self.assertTrue(page.restored, "the hook is taken off when the press raises")

    def test_a_button_turned_off_at_the_press_leaves_the_statement(self):
        def turned_off(page, el, **kw):
            raise pressing.TurnedOff("take a statement", "the control is turned off", ["off"])
        pressing.click = turned_off
        page = Page()
        ok, out, trace = self.take(page)
        self.assertFalse(ok)
        self.assertFalse(out.exists())
        self.assertEqual(trace[-1], {"note": "the button is turned off"})
        self.assertTrue(page.restored)
        self.assertEqual(page.live_listeners(), 0)

    def test_the_hook_is_taken_off_when_the_press_itself_stops(self):
        def covered(page, el, **kw):
            raise pressing.Covered("take a statement", "covered", ["covered"])
        pressing.click = covered
        page = Page()
        with self.assertRaises(pressing.Stop):
            self.take(page)
        self.assertTrue(page.restored)
        self.assertEqual(page.live_listeners(), 0)

    def test_a_sign_out_after_the_press(self):
        def expired(p):
            p.emit("response", Resp(site.PDF_OPERATION, {"statementId": p.detail_sid}, status=401))
        with self.assertRaises(site.SessionExpired):
            self.take(Page(on_press=expired))

    def test_accept_alone(self):
        ok = dict(new_pages=0, popups=0, downloads=0, on_route=True)
        self.assertEqual(site.accept([(True, PDF)], blob_result(), **ok), (PDF, ""))
        self.assertEqual(site.accept([(True, PDF)], blob_result(kind="application/pdf;base64"), **ok)[0], PDF)
        for pdfs, res, kw in [([], blob_result(), ok), ([(True, PDF)], {}, ok), ([(False, PDF)], blob_result(), ok),
                              ([(True, b"")], blob_result(), ok), ([(True, PDF)], blob_result(OTHER_PDF), ok),
                              ([(True, PDF)], blob_result(), {**ok, "downloads": 1}),
                              ([(True, PDF)], blob_result(), {**ok, "new_pages": 1}),
                              ([(True, PDF)], blob_result(), {**ok, "popups": 1}),
                              ([(True, PDF)], blob_result(), {**ok, "on_route": False})]:
            data, why = site.accept(pdfs, res, **kw)
            self.assertEqual(data, b"")
            self.assertTrue(why)


class InPage(WithFakeClick):
    """An older statement is chosen by pressing its own row, so the page
    prints that one and not the newest."""

    def test_an_older_statement_is_chosen_by_its_row(self):
        page = Page()
        ok, out, trace = self.take(page, "current", "2026-08-26")
        self.assertTrue(ok, trace)
        self.assertEqual(out.read_bytes(), spectrum_pdf("2026-08-26"))
        self.assertEqual(page.gotos, [site.STATEMENTS_URL], "the statement's page is never opened by address")
        self.assertEqual(page.row_presses, [1])
        self.assertEqual([c[1] for c in page.clicks], ["choose a statement", "take a statement"])
        self.assertEqual(page.clicks[0][2], "the statement row dated 2026-08-26")
        self.assertTrue(page.restored)
        self.assertEqual(page.live_listeners(), 0)

    def test_a_prior_account_statement_is_chosen_by_its_row(self):
        page = Page()
        ok, out, trace = self.take(page, "prior", "2026-01-26")
        self.assertTrue(ok, trace)
        self.assertEqual(page.row_presses, [4])
        self.assertIn("isAccountTransfer=true", page.url)

    def test_with_no_current_statement_every_statement_goes_by_its_row(self):
        page = Page(answer=list_answer(cur=[]))
        ok, out, trace = self.take(page, "prior", "2026-02-26")
        self.assertTrue(ok, trace)
        self.assertEqual(page.row_presses, [0])
        self.assertIsNone(site.newest([site.Entry("prior", "2026-02-26", sid(PRI, "2026-02-26"))]))

    def twins(self, **kw):
        """Two accounts with a statement each on one date, two rows of it
        drawn at 1 and 2, the current account's first."""
        answer = list_answer(cur=["2026-09-17", TWIN_DAY], prior=[TWIN_DAY, "2026-05-17"])
        return Page(answer=answer, **kw)

    def statement_reads(self, page):
        return page.gotos.count(site.STATEMENTS_URL)

    def test_the_first_row_of_a_shared_date_is_kept_when_it_is_this_statements(self):
        page = self.twins()
        ok, out, trace = self.take(page, "current", TWIN_DAY)
        self.assertTrue(ok, trace)
        self.assertEqual(page.row_presses, [1])
        self.assertEqual(self.statement_reads(page), 1)
        self.assertIn("isAccountTransfer=false", page.url)
        self.assertEqual(page.presses, 1)

    def test_the_other_accounts_page_sends_it_back_for_the_second_row(self):
        page = self.twins()
        ok, out, trace = self.take(page, "prior", TWIN_DAY)
        self.assertTrue(ok, trace)
        self.assertEqual(page.row_presses, [1, 2])
        self.assertEqual(self.statement_reads(page), 2, "Statements is read again before the second press")
        self.assertIn("isAccountTransfer=true", page.url)
        self.assertEqual(page.presses, 1, "View Printable Statement is pressed only on its own page")
        self.assertEqual(out.read_bytes()[:5], b"%PDF-")

    def test_rows_drawn_the_other_way_round_still_reach_each_statement(self):
        def swapped(page, index):
            lands(page, {1: 2, 2: 1}.get(index, index))
        for family, presses in (("current", [1, 2]), ("prior", [1])):
            page = self.twins(on_row=swapped, on_press=own_copy)
            ok, out, trace = self.take(page, family, TWIN_DAY)
            self.assertTrue(ok, trace)
            self.assertEqual(page.row_presses, presses, family)
            self.assertIn("isAccountTransfer=%s" % ("true" if family == "prior" else "false"), page.url)

    def test_both_statements_of_a_date_are_saved_in_one_run(self):
        """Each under its own account, in either order, whichever row each
        account's statement is drawn on."""
        def swapped(page, index):
            lands(page, {1: 2, 2: 1}.get(index, index))
        for on_row in (lands, swapped):
            for first, second in (("current", "prior"), ("prior", "current")):
                site._KEPT.clear()
                for leftover in self.tmp.glob("*.pdf"):
                    leftover.unlink()
                page = self.twins(on_press=own_copy, on_row=on_row)
                taken = {family: self.take(page, family, TWIN_DAY) for family in (first, second)}
                for family, own in (("current", "own"), ("prior", "transfer")):
                    ok, out, trace = taken[family]
                    self.assertTrue(ok, trace)
                    self.assertEqual(out.read_bytes(), spectrum_pdf(TWIN_DAY, own), (family, first))

    def test_the_other_accounts_statement_printed_on_a_page_is_never_kept(self):
        """The page a row opens names its account, and so must the PDF the
        page asks for. One that answers with the other account's statement
        of that date stops the run and saves nothing, whichever is taken."""
        def other(page):
            prior = "isAccountTransfer=true" in page.url
            data = spectrum_pdf(TWIN_DAY, "own" if prior else "transfer")
            page.emit("response", Resp(site.PDF_OPERATION,
                                       {"statementId": sid(CUR if prior else PRI, TWIN_DAY), "otpCheck": True},
                                       answer=pdf_answer(data)))
            page.blob = blob_result(data)
        for family in ("current", "prior"):
            page = self.twins(on_press=other)
            with self.assertRaises(pressing.Stop):
                self.take(page, family, TWIN_DAY)
            self.assertEqual(page.presses, 1)
            self.assertEqual(list(self.tmp.glob("*.pdf")), [], family)

    def test_one_file_printed_for_both_accounts_is_kept_once(self):
        """The two statements of a date are two files. The same bytes for the
        second stop the run rather than save the first account's twice."""
        page = self.twins()
        ok, out, trace = self.take(page, "current", TWIN_DAY)
        self.assertTrue(ok, trace)
        with self.assertRaises(pressing.Stop):
            self.take(page, "prior", TWIN_DAY)
        self.assertFalse((self.tmp / ("prior-%s.pdf" % TWIN_DAY)).exists())

    def test_a_second_press_that_opens_the_other_statement_again_stops_the_run(self):
        page = self.twins(on_row=lambda page, index: lands(page, 2))
        with self.assertRaises(pressing.Stop):
            self.take(page, "current", TWIN_DAY)
        self.assertEqual(page.row_presses, [1, 2])
        self.assertEqual(page.presses, 0)
        self.assertFalse((self.tmp / ("current-%s.pdf" % TWIN_DAY)).exists())

    def test_a_shared_date_row_that_opens_a_third_statement_stops_the_run(self):
        page = self.twins(on_row=lambda page, index: lands(page, 3))
        with self.assertRaises(pressing.Stop):
            self.take(page, "prior", TWIN_DAY)
        self.assertEqual(page.row_presses, [1])
        self.assertEqual(page.presses, 0)

    def test_a_shared_date_needs_a_row_for_each_statement(self):
        page = self.twins(rows=[row_text("2026-09-17"), row_text(TWIN_DAY), row_text("2026-05-17")])
        entries = [site.Entry(*e) for e in (("current", TWIN_DAY, sid(CUR, TWIN_DAY)),
                                            ("prior", TWIN_DAY, sid(PRI, TWIN_DAY)))]
        index, _, why = site.row_for(page, entries[0], entries)
        self.assertEqual(index, -1)
        self.assertIn("1 rows carry the statement's date, not 2", why)

    def test_the_row_guard(self):
        day = "2026-08-26"
        self.assertTrue(site.is_safe_row(row_text(day), day))
        self.assertTrue(site.is_safe_row("Statement August 26, 2026", day))
        for text in ["Pay Bill", "Make Early Payment", "Statement August 26, 2026 Auto Pay: Sep 10 $80.00",
                     "Statement August 26, 2026 AutoPay", "Statement August 26, 2026 Go Paperless",
                     "Statement August 26, 2026 Equipment", "Statement August 26, 2026 Settings",
                     "Statement August 26, 2026 Sign Out", "Statement August 26, 2026 1 Mobile Ave",
                     "Statement August 26, 2026 Manage", "Statement August 26, 2026 Order now",
                     "Statement August 26, 2026 Enroll", "Statement August 26, 2026 Sign in",
                     "Statement August 25, 2026", "Statement Aug 26, 2026", "Statements", "", None]:
            self.assertFalse(site.is_safe_row(text, day), text)
        self.assertFalse(site.is_safe_row(row_text(day), "2026-02-30"))

    def test_a_row_the_guard_refuses_is_not_pressed(self):
        rows = [row_text(d) for d in ["2026-09-26"]] + ["Statement August 26, 2026 1 Mobile Ave"] + [
            row_text(d) for d in ["2026-02-26", "2026-02-26", "2026-01-26"]]
        page = Page(rows=rows)
        ok, out, trace = self.take(page, "current", "2026-08-26")
        self.assertFalse(ok)
        self.assertEqual(page.clicks, [])

    def test_the_row_address_guard(self):
        mine = digital(CUR, "2026-08-26")
        for href in (None, "", "  ", "javascript:void(0)", "javascript:void(0);", "JavaScript:void(0)",
                     f"/billing/bill-details?pdfStatementId={mine}&isNextBill=false&isAccountTransfer=false",
                     f"https://{HOST}/billing/statements", "/billing/bill-details"):
            self.assertTrue(site.is_safe_href(href), repr(href))
        for href in ("/billing/autopay", "/billing/auto-pay", "/billing/makePayment", "/billing/make-payment",
                     "/billing/pay-bill", "/billing/paperless", "/account/settings", "/support/equipment",
                     "/services/upgrade", "/plan/change", "/logout", "/sign-out", "/id/signin",
                     "/billing/statements?action=pay", "/billing/statements?autoPay=1",
                     "/billing/statements?next=%2Fbilling%2Fpayment", "/billing/statements?x",
                     "/billing/mobile-statements", "/billing/statements#pay", "#", "#/billing/payment",
                     "billing/statements", "./payment", "//evil.test/billing", "/\\evil.test/billing",
                     "/\t/evil.test/billing", "https://evil.test/billing/statements", f"http://{HOST}/billing",
                     f"https://{HOST}:8443/billing", f"https://u@{HOST}/billing",
                     f"https://{HOST}.evil.test/billing", "javascript:void(0);pay()", "javascript:autoPay()",
                     "mailto:someone@example.com", 7):
            self.assertFalse(site.is_safe_href(href), repr(href))
        # A Mobile link or row is pressed only with the address the survey saw.
        for href in (None, "", "javascript:void(0)"):
            self.assertTrue(site.is_void_href(href), repr(href))
        for href in ("/billing/statements", f"https://{HOST}/billing/mobile-statements", "#", "/billing/autopay"):
            self.assertFalse(site.is_void_href(href), repr(href))

    def test_a_row_whose_address_is_refused_is_not_pressed(self):
        for href in ("/billing/autopay", "https://evil.test/statement", "#/billing/payment", OSError("gone")):
            page = Page()
            page.hrefs = {1: href}
            ok, out, trace = self.take(page, "current", "2026-08-26")
            self.assertFalse(ok, href)
            self.assertEqual(page.clicks, [], href)
            self.assertFalse(out.exists())
            self.assertNotIn("autopay", json.dumps(trace))
        mine = digital(CUR, "2026-08-26")
        page = Page()
        page.hrefs = {1: f"/billing/bill-details?pdfStatementId={mine}&isNextBill=false&isAccountTransfer=false"}
        ok, out, trace = self.take(page, "current", "2026-08-26")
        self.assertTrue(ok, trace)
        self.assertEqual(page.row_presses, [1])
        self.assertNotIn(mine, json.dumps(trace))

    def test_a_row_that_changed_before_the_press_is_not_pressed(self):
        for words in ("Statement August 26, 2026 Make a Payment", "Statement July 26, 2026", ""):
            page = Page()
            page.row_changes = {1: words}
            ok, out, _ = self.take(page, "current", "2026-08-26")
            self.assertFalse(ok, words)
            self.assertEqual(page.clicks, [], words)

    def test_a_row_turned_off_leaves_the_statement(self):
        def off(page, el, **kw):
            raise pressing.TurnedOff("choose a statement", "the control is turned off", ["off"])
        pressing.click = off
        page = Page()
        ok, out, trace = self.take(page, "current", "2026-08-26")
        self.assertFalse(ok)
        self.assertEqual(page.presses, 0)
        self.assertEqual(page.live_listeners(), 0)

    def test_no_row_press_without_the_download_folder(self):
        page = Page()
        with self.assertRaises(pressing.NotPressed):
            self.take(page, "current", "2026-08-26", dl_dir=None)
        self.assertEqual(page.clicks, [])

    def stops_after_the_row(self, on_row, **kw):
        page = Page(on_row=on_row, **kw)
        with self.assertRaises(pressing.Stop) as stop:
            self.take(page, "current", "2026-08-26")
        self.assertTrue(stop.exception.after_a_press)
        self.assertEqual(stop.exception.step, "choose a statement")
        self.assertEqual(page.presses, 0, "View Printable Statement is not pressed")
        self.assertEqual(page.live_listeners(), 0)
        self.assertFalse(list(self.tmp.glob("*.pdf")))
        for word in (CUR, PRI, STREET):
            self.assertNotIn(word, " ".join(stop.exception.lines))
        return page

    def test_anything_unexpected_after_the_row_press_stops_the_run(self):
        def other_statement(p, i):
            lands(p, 0)

        def off_the_page(p, i):
            lands(p, i)
            p.url = f"https://{HOST}/billing"

        def wrong_transfer_flag(p, i):
            lands(p, i)
            p.url = p.url.replace("isAccountTransfer=false", "isAccountTransfer=true")

        def extra_query(p, i):
            lands(p, i)
            p.url += "&autoAddOffer=1"

        def tab(p, i):
            lands(p, i)
            p.context.pages.append(SimpleNamespace(close=lambda: None))

        def popup(p, i):
            lands(p, i)
            p.emit("popup", object())

        def download(p, i):
            lands(p, i)
            p.emit("download", SimpleNamespace(cancel=lambda: None, delete=lambda: None))
        for f in (other_statement, off_the_page, wrong_transfer_flag, extra_query, tab, popup, download):
            self.stops_after_the_row(f)

    def test_the_page_must_ask_for_the_chosen_statement_once_and_only_known_ones(self):
        mine = digital(CUR, "2026-08-26")
        cases = {
            "none": [],
            "twice": [Resp(site.DETAIL_OPERATION, {"statementId": mine})] * 2,
            "only the newest": [Resp(site.DETAIL_OPERATION, {"statementId": digital(CUR, "2026-09-26")})],
            "a statement not listed": [Resp(site.DETAIL_OPERATION, {"statementId": mine}),
                                       Resp(site.DETAIL_OPERATION, {"statementId": digital(CUR, "2025-01-26")})],
            "an id that does not read": [Resp(site.DETAIL_OPERATION, {"statementId": mine}),
                                         Resp(site.DETAIL_OPERATION, {"statementId": "x!"})],
            "the comparison failed": [Resp(site.DETAIL_OPERATION, {"statementId": mine}),
                                      Resp(site.DETAIL_OPERATION, {"statementId": digital(CUR, "2026-09-26")},
                                           status=500)],
            "this one failed": [Resp(site.DETAIL_OPERATION, {"statementId": mine}, status=500)],
        }
        for name, responses in cases.items():
            self.stops_after_the_row(lands, detail=lambda s, r=responses: r)

    def test_a_comparison_with_errors_is_a_signed_out_session(self):
        mine = digital(CUR, "2026-08-26")
        page = Page(detail=lambda s: [Resp(site.DETAIL_OPERATION, {"statementId": mine}),
                                      Resp(site.DETAIL_OPERATION, {"statementId": digital(CUR, "2026-09-26")},
                                           answer={"errors": [1]})])
        with self.assertRaises(site.SessionExpired):
            self.take(page, "current", "2026-08-26")
        self.assertEqual(page.presses, 0)

    def test_signed_out_after_the_row_press(self):
        def to_login(p, i):
            p.url = f"https://{HOST}/login"
        page = Page(on_row=to_login)
        with self.assertRaises(site.SessionExpired):
            self.take(page, "current", "2026-08-26")
        self.assertEqual(page.presses, 0)

    def test_no_printable_button_after_the_row_press_stops_the_run(self):
        for buttons in [(), (("View Printable Statement", True),) * 2, (("View Printable Statement and Pay", True),)]:
            self.stops_after_the_row(lands, buttons=buttons)


class BoundToTheStatement(WithFakeClick):
    """The PDF the press brings is kept only when it is the chosen
    statement's, beyond the page's own request having named it."""

    def stops(self, data, before=None):
        def press(p):
            p.emit("response", Resp(site.PDF_OPERATION, {"statementId": p.detail_sid}, answer=pdf_answer(data)))
            p.blob = blob_result(data)
        if before:
            before()
        page = Page(on_press=press)
        with self.assertRaises(pressing.Stop) as stop:
            self.take(page, "current", "2026-08-26")
        self.assertEqual(stop.exception.step, "take a statement")
        self.assertTrue(stop.exception.after_a_press)
        self.assertFalse((self.tmp / "current-2026-08-26.pdf").exists())
        self.assertEqual(page.live_listeners(), 0)
        return stop.exception

    def test_the_newest_in_its_place_is_refused(self):
        self.stops(spectrum_pdf("2026-09-26"))

    def test_a_pdf_without_the_date_or_without_text_is_refused(self):
        self.stops(text_pdf(["Spectrum", "Amount Due $80.00", "Thank you for choosing Spectrum Internet"]))
        self.assertIn("no text", self.stops(text_pdf([])).lines[0])

    def test_the_newest_printing_this_date_as_its_previous_one_is_caught_by_its_bytes(self):
        # The newest may print this statement's date as its previous
        # statement. The text check then ties, which keeps a file, so the
        # newest saved by an earlier run is what refuses it, beside the
        # page's own request having to name this statement.
        newest = text_pdf(["Statement Date 09/26/26", "Previous statement 08/26/26",
                           "Service From 09/26/26 through 10/25/26"])
        entries = site.entries_of(site.statement_list_of(list_answer()))
        e = [x for x in entries if x.document_id == "current:2026-08-26"][0]
        self.assertEqual(site.bind(newest, e, entries, self.tmp / "x.pdf"), "", "the text alone cannot tell")
        self.stops(newest, before=lambda: (self.tmp / "2026-09-26 Spectrum Internet Statement.pdf").write_bytes(newest))

    def test_bytes_already_saved_are_refused_even_from_an_earlier_run(self):
        data = spectrum_pdf("2026-08-26")
        self.stops(data, before=lambda: (self.tmp / "2026-09-26 Spectrum Internet Statement.pdf").write_bytes(data))

    def test_a_download_again_may_meet_its_own_copy(self):
        data = spectrum_pdf("2026-08-26")
        mine = self.tmp / "2026-08-26 Spectrum Internet Statement.pdf"
        mine.write_bytes(data)
        (self.tmp / "staging").mkdir()
        out = self.tmp / "current-2026-08-26.pdf"
        ok = site.download_bill(Page(), self.tmp / "staging", "2026-08-26", out,
                                document_id="current:2026-08-26", own_files=[str(mine)])
        self.assertTrue(ok)
        self.assertEqual(out.read_bytes(), data)
        site._KEPT.clear()
        out.unlink()
        with self.assertRaises(pressing.Stop):
            site.download_bill(Page(), self.tmp / "staging", "2026-08-26", out,
                               document_id="current:2026-08-26",
                               own_files=[str(self.tmp / "another.pdf")])

    def test_bytes_kept_for_another_statement_in_this_run_are_refused(self):
        import hashlib
        data = spectrum_pdf("2026-08-26")
        self.stops(data, before=lambda: site._KEPT.update({hashlib.sha256(data).hexdigest(): "current:2026-09-26"}))

    def test_the_statement_kept_is_remembered(self):
        ok, out, _ = self.take(Page(), "current", "2026-08-26")
        self.assertTrue(ok)
        self.assertIn("current:2026-08-26", site._KEPT.values())

    def test_nothing_of_the_text_reaches_the_trace(self):
        ok, out, trace = self.take(Page(), "current", "2026-08-26")
        said = json.dumps(trace)
        for word in ("08/26/26", "Amount Due", "Service From", "80.00"):
            self.assertNotIn(word, said)


class Addresses(unittest.TestCase):
    def test_a_plus_in_a_query_value_stays_a_plus(self):
        self.assertEqual(site._query_pairs("a=b+c%2Bd&e="), [("a", "b+c+d"), ("e", "")])
        for bad in ("a", "=b", "a=b&&c=d"):
            with self.assertRaises(ValueError):
                site._query_pairs(bad)

    def test_lands_on_takes_the_pages_own_spelling_and_family(self):
        e = site.Entry("current", "2026-08-26", sid(CUR, "2026-08-26"))
        base = f"https://{HOST}{site.DETAIL_PATH}?pdfStatementId=%s&isNextBill=false&isAccountTransfer=%s"
        self.assertTrue(site.lands_on(base % (digital(CUR, "2026-08-26"), "false"), e))
        self.assertTrue(site.lands_on(base % (sid(CUR, "2026-08-26"), "false"), e))
        self.assertFalse(site.lands_on(base % (digital(CUR, "2026-08-26"), "true"), e))
        self.assertFalse(site.lands_on(base % (digital(PRI, "2026-08-26"), "false"), e))
        self.assertFalse(site.lands_on(base % (digital(CUR, "2026-07-26"), "false"), e))
        p = site.Entry("prior", "2026-01-26", sid(PRI, "2026-01-26"))
        self.assertTrue(site.lands_on(base % (digital(PRI, "2026-01-26"), "true"), p))
        self.assertFalse(site.lands_on(base % (digital(PRI, "2026-01-26"), "false"), p))
        self.assertFalse(site.lands_on(f"https://{HOST}/billing/statements", e))


class AfterAPress(WithFakeClick):
    """A failure of any kind once a press was made stops the run, and the
    page is left with no listener and no hook of ours."""

    def test_a_read_that_fails_after_the_row_press_stops_the_run(self):
        page = Page()
        page.fail_wait = lambda p: bool(p.row_presses)
        with self.assertRaises(pressing.Stop) as stop:
            self.take(page, "current", "2026-08-26")
        self.assertEqual(stop.exception.step, "choose a statement")
        self.assertTrue(stop.exception.after_a_press)
        self.assertEqual(page.presses, 0)
        self.assertEqual(page.live_listeners(), 0)
        self.assertNotIn(CUR, " ".join(stop.exception.lines))
        self.assertNotIn("pdfStatementId", " ".join(stop.exception.lines))

    def test_a_read_that_fails_after_the_printable_press_stops_the_run(self):
        for family, day in (("current", "2026-09-26"), ("current", "2026-08-26")):
            page = Page()
            page.fail_wait = lambda p: p.presses > 0
            with self.assertRaises(pressing.Stop) as stop:
                self.take(page, family, day)
            self.assertEqual(stop.exception.step, "take a statement")
            self.assertTrue(page.restored)
            self.assertEqual(page.live_listeners(), 0)
            self.assertFalse(list(self.tmp.glob("*.pdf")))
            self.assertNotIn(CUR, " ".join(stop.exception.lines))

    def test_a_statement_that_cannot_be_written_stops_the_run(self):
        page = Page()
        out = self.tmp / "a file" / "x.pdf"
        (self.tmp / "a file").write_bytes(b"not a folder")
        with self.assertRaises(pressing.Stop) as stop:
            site.download_bill(page, self.tmp, "2026-09-26", out, document_id="current:2026-09-26")
        self.assertEqual(stop.exception.step, "take a statement")

    def test_a_listener_that_cannot_be_added_leaves_none(self):
        for event in ("response", "popup", "download"):
            for day in ("2026-09-26", "2026-08-26"):
                page = Page()
                page.fail_on = {event} if event != "response" else set()
                if event == "response":
                    real = page.on

                    def on(ev, fn, real=real, page=page):
                        if ev == "response" and page.gotos and page.url.startswith(site.BASE + site.DETAIL_PATH):
                            raise RuntimeError("could not listen")
                        real(ev, fn)
                    page.on = on
                try:
                    self.take(page, "current", day)
                except (RuntimeError, pressing.Stop):
                    pass
                self.assertEqual(page.live_listeners(), 0, (event, day))
                self.assertFalse(page.armed, (event, day))

    def test_every_answer_is_read_before_it_is_counted(self):
        mine = digital(CUR, "2026-08-26")
        err = {"errors": [1]}
        for responses in ([Resp(site.DETAIL_OPERATION, {"statementId": mine})] * 2
                          + [Resp(site.DETAIL_OPERATION, {"statementId": mine}, answer=err)],
                          [Resp(site.DETAIL_OPERATION, {"statementId": digital(CUR, "2026-09-26")}, answer=err)],
                          [Resp(site.DETAIL_OPERATION, {"statementId": "x!"}, status=401)]):
            page = Page(detail=lambda s, r=responses: r)
            with self.assertRaises(site.SessionExpired):
                self.take(page, "current", "2026-08-26")
            self.assertEqual(page.presses, 0)

    def test_the_docs_layer_keeps_no_words_of_a_failure_and_stops_at_a_press(self):
        app = make_app(self.tmp, "--all")
        for r in site.raw_docs(site.entries_of(site.statement_list_of(list_answer()))):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        app._staged = True
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise RuntimeError("at %s for %s %s" % (sid(CUR, "2026-09-26"), CUR, ADDRESS))
        original = site.download_bill
        site.download_bill = boom
        try:
            with redirect_stdout(seen):
                app.process(app._select(limit=1))
        finally:
            site.download_bill = original
            root.removeHandler(handler)
        written = seen.getvalue()
        for p in app.paths.root.rglob("*"):
            if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"):
                written += p.read_text(encoding="utf-8", errors="ignore")
        for word in (CUR, STREET, sid(CUR, "2026-09-26")):
            self.assertNotIn(word, written, word)
        calls.clear()

        def stop(*a, **k):
            calls.append(1)
            raise pressing.no_answer("take a statement", "the press made something other than one statement", "x")
        site.download_bill = stop
        try:
            with redirect_stdout(io.StringIO()), self.assertRaises(pressing.Stop):
                app.process(app._select())
        finally:
            site.download_bill = original
        self.assertEqual(calls, [1], "nothing after the stop is touched")


# ---------------------------------------------------------------------------

def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(WithFakeClick):
    def listed(self, app):
        for r in site.raw_docs(site.entries_of(site.statement_list_of(list_answer()))):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()

    def test_records_and_names(self):
        app = make_app(self.tmp, "--discover")
        self.listed(app)
        text = app.paths.discovery_json.read_text()
        for word in (CUR, PRI, STREET, "Account=", "pdfStatementId", "?"):
            self.assertNotIn(word, text)
        cur = app.discovery.get("id:Internet:current:2026-02-26")
        pri = app.discovery.get("id:Internet (prior account):prior:2026-02-26")
        self.assertEqual((cur["summary"], cur["href"]), ("Internet Statement", ""))
        self.assertEqual(pri["summary"], "Internet Statement Prior Account")
        names = {docs.build_pdf_filename(r["date"], r["summary"], "", record=docs.Document.from_dict(r))
                 for r in (cur, pri)}
        self.assertEqual(len(names), 2, "two statements of one day get two names")
        for n in names:
            self.assertNotRegex(n, r"\d{6,}")
        self.assertEqual(docs.told_apart_by(cur), "current account")
        self.assertEqual(docs.told_apart_by(pri), "prior account")
        self.assertEqual(app.config["pilot_count"], 1)

    def test_mobile_records_and_names(self):
        app = make_app(self.tmp, "--discover")
        for r in site.raw_docs([site.Entry(site.MOBILE, "2026-08-13")]):
            app._record_rawdoc(r, site.BILLING_URL)
        rec = app.discovery.get("id:Mobile:mobile:2026-08-13")
        self.assertEqual((rec["category"], rec["summary"], rec["document_id"]),
                         ("Statement", "Mobile Statement", "mobile:2026-08-13"))
        self.assertEqual(docs.build_pdf_filename(rec["date"], rec["summary"], "", record=docs.Document.from_dict(rec)),
                         "2026-08-13 Spectrum Mobile Statement.pdf")
        self.assertEqual(docs.told_apart_by(rec), "mobile account")
        self.assertEqual(docs.family_summary("Mobile Statement", "mobile:2026-08-13"), "Mobile Statement")

    def test_discovery_lists_mobile_and_keeps_internet_when_mobile_stops(self):
        app = make_app(self.tmp, "--discover")
        app._staged = True
        app._dl_dir.mkdir(parents=True)
        page = Page(mobile=mobile_rows())
        app.page = lambda: page
        with redirect_stdout(io.StringIO()):
            app.cmd_discover()
        self.assertEqual(sum(1 for k in app.discovery.data if k.startswith("id:Mobile:")), 3)
        self.assertEqual(page.clicks[0][2], "the Mobile Account Number link")
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--discover")
        app._staged = True
        app._dl_dir.mkdir(parents=True)
        page = Page(mobile=mobile_rows(["2026-08-13", "2026-08-13"]))
        app.page = lambda: page
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(len(app.discovery.data), 5)
        self.assertIn("stopped partway", said.getvalue())
        # Without the confirmed folder nothing is pressed for Mobile, the
        # Internet statements are kept, and the list is not called whole.
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--discover")
        page = Page(mobile=mobile_rows())
        app.page = lambda: page
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(page.clicks, [])
        self.assertEqual(len(app.discovery.data), 5)
        self.assertIn("stopped partway", said.getvalue())

    def test_a_discovery_that_left_mobile_unread_is_never_called_whole(self):
        """Resume carries on from a listing called whole as if it held every
        statement, so one whose Mobile list was never read, or never settled,
        stays noted as one that stopped."""
        from paperpull_core import listing

        def never_drawn(p):
            p.where, p.url, p.mobile = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}", []
        for staged, page in ((False, Page(mobile=mobile_rows())),
                             (True, Page(mobile=mobile_rows(), on_link=never_drawn))):
            app = make_app(tempfile.mkdtemp(), "--discover")
            app._staged = staged
            app._dl_dir.mkdir(parents=True)
            app.page = lambda page=page: page
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                app.cmd_discover()
            self.assertEqual(listing.last(app), listing.STOPPED, staged)
            self.assertEqual(len(app.discovery.data), 5, "the Internet statements are kept")

    def test_discovery_opens_statements_before_it_asks_about_the_session(self):
        """With no Spectrum tab of the person's open, page() hands over a new
        blank tab of the run's own. Discover opens Statements in it first,
        rather than stop on the blank tab as one that left Spectrum."""
        from paperpull_core import tabs
        app = make_app(self.tmp, "--discover")
        app._staged = True
        app._dl_dir.mkdir(parents=True)
        page = Page()
        page.url = "about:blank"
        tab = tabs.new_tab(SimpleNamespace(new_page=lambda: page))
        app.page = lambda: tab
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_discover()
        self.assertNotIn("left Spectrum", said.getvalue())
        self.assertEqual(len(app.discovery.data), 5)
        self.assertEqual(page.gotos[0], site.STATEMENTS_URL)
        self.assertEqual(page.clicks, [], "Billing lists no Mobile account here")

    def run_process(self, app, raises):
        self.listed(app)
        app._staged = True
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def boom(*a, **k):
            raise raises
        original = site.download_bill
        site.download_bill = boom
        try:
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                app.process(app._select())
        finally:
            site.download_bill = original
        self.assertEqual(app.progress.data, {})
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)
        self.assertFalse(list(app.paths.diagnostics.glob("*failure*")))
        return said.getvalue()

    def test_a_signed_out_session_stops_and_records_nothing(self):
        said = self.run_process(make_app(self.tmp, "--all"), site.SessionExpired("x"))
        self.assertIn("signed out", said)

    def test_a_passcode_stops_and_records_nothing(self):
        said = self.run_process(make_app(self.tmp, "--all"), site.OtpRequired("x"))
        self.assertIn("one-time passcode", said)
        self.assertNotIn("Press Enter", said)

    def test_discovery_boundaries(self):
        for page, words in [(Page(settle={site.STATEMENTS_PATH: f"https://{HOST}/login"}), "signed out"),
                            (Page(list_responses=[Resp(site.LIST_OPERATION, status=401)]), "signed out"),
                            (Page(body="enter the code we sent"), "one-time passcode")]:
            tmp = tempfile.mkdtemp()
            app = make_app(tmp, "--discover")
            app.page = lambda page=page: page
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit):
                app.cmd_discover()
            self.assertEqual(app.discovery.data, {})
            self.assertIn(words, out.getvalue())
            self.assertNotIn("Press Enter", out.getvalue())
            self.assertFalse(list(app.paths.diagnostics.glob("*failure*")))

    def test_resume_meets_the_same_boundary(self):
        app = make_app(self.tmp, "--resume")
        self.listed(app)
        from paperpull_core import listing
        listing.read_whole(app)
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None
        app._staged = True
        original = site.download_bill
        site.download_bill = lambda *a, **k: (_ for _ in ()).throw(site.OtpRequired("x"))
        try:
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                app.cmd_resume()
        finally:
            site.download_bill = original
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)

    def test_nothing_is_pressed_without_the_download_folder(self):
        page = Page()
        with self.assertRaises(pressing.NotPressed) as stop:
            self.take(page, dl_dir=None)
        self.assertEqual(page.presses, 0)
        self.assertFalse(page.armed)
        self.assertIn("download folder", stop.exception.lines[0])
        app = make_app(self.tmp, "--all")
        self.listed(app)
        app._delay = lambda *a, **k: None
        page = Page()
        app._on_its_site = lambda: page
        self.assertFalse(app._staged, "unconfirmed until the browser accepts the folder")
        with redirect_stdout(io.StringIO()), self.assertRaises(pressing.Stop):
            app.process(app._select(limit=1))
        self.assertEqual(page.presses, 0)
        self.assertEqual(app.progress.data, {})

    def test_the_census_describes_only_the_sites_own_answers(self):
        """The request census every app keeps, started on the run's page and
        bound to this app's own host. The page's GraphQL answers come from
        apis.spectrum.net and are only counted, never described."""
        from paperpull_core.api_census import Requests
        app = make_app(self.tmp, "--all")
        page = Page()
        app._work_page = page
        census = app.requests
        self.assertIsInstance(census, Requests)
        self.assertIs(app.requests, census, "made once")
        self.assertEqual(len(page.listeners.get("response", [])), 1)

        def answer(url, body):
            return SimpleNamespace(url=url, status=200, headers={"content-type": "application/json"},
                                   request=SimpleNamespace(method="POST"), json=lambda: body)
        page.emit("response", answer(GRAPH, list_answer()))
        page.emit("response", answer(f"https://{HOST}/api/billing/summary", {"accountNumber": CUR}))
        report = census.report()
        self.assertEqual((report["counts"]["provider"], report["counts"]["elsewhere"]), (1, 1))
        self.assertEqual([e["path"] for e in report["seen"]], ["/api/billing/summary"])
        self.assertNotIn(CUR, json.dumps(report))
        self.assertNotIn("Account=", json.dumps(report))

    def test_a_download_again_hands_over_the_statements_own_copy(self):
        app = make_app(self.tmp, "--all", "--redownload")
        self.listed(app)
        app._staged = True
        app._delay = lambda *a, **k: None
        app._on_its_site = lambda: Page()
        doc = [d for d in app._select() if d.date == "2026-08-26"][0]
        app.progress.update(doc.key, {**doc.to_dict(), "pdf_path": "/saved/before.pdf", "downloaded_ok": True})
        got = {}

        def spy(*a, **k):
            got.update(k)
            return False
        original = site.download_bill
        site.download_bill = spy
        try:
            with redirect_stdout(io.StringIO()):
                app.download_one(Page(), doc, "x.pdf")
        finally:
            site.download_bill = original
        self.assertEqual(got["own_files"], ["/saved/before.pdf"])

    def test_pilot_gate(self):
        from paperpull_core.models import State

        class D:
            def __init__(self, k):
                self.key = k
        self.assertFalse(docs.pilot_failed({"a": {"state": State.COMPLETED.value}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({}, [D("a")]))


class Privacy(WithFakeClick):
    """Nothing that names the account reaches a log line, the console, a
    record, a trace, a failure file or a file name, on success and on a
    refused press."""

    def test_success_and_failure_paths(self):
        app = make_app(self.tmp, "--all")
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(seen):
                app._dl_dir.mkdir(parents=True)   # as set_download_dir makes it
                for r in site.collect_download_docs(Page(mobile=mobile_rows()), dl_dir=app._dl_dir):
                    app._record_rawdoc(r, site.BILLING_URL)
                app.discovery.save()
                from paperpull_core import listing
                listing.read_whole(app)
                app._delay = lambda *a, **k: None
                app._staged = True
                app._on_its_site = lambda: Page(mobile=mobile_rows())
                # The newest Internet statement, then the newest Mobile one.
                app.process(app._select(limit=2))
                # A Mobile statement left for review writes what the site
                # answered, with the address it landed on.
                mobile_doc = [d for d in app._select() if d.document_id == "mobile:2026-08-13"]
                app._on_its_site = lambda: Page(mobile=mobile_rows(), mbuttons=(("Print", True),))
                app.process(mobile_doc)
                with self.assertRaises(site.ListStopped) as stop:
                    site.read_statement_list(Page(answer=list_answer(cur=["2026-09-26", "2026-09-26"])))
                self.assertNotIn(CUR, str(stop.exception))
                # A refused press: the run stops through main's own path.
                app._on_its_site = lambda: Page(on_press=lambda p: p.emit(
                    "response", Resp(site.PDF_OPERATION, {"statementId": p.detail_sid}, answer=pdf_answer())))
                todo = [d for d in app._select() if not app._already_done(d)][:1]
                with self.assertRaises(pressing.Stop) as press_stop:
                    app.process(todo)
                with self.assertRaises(SystemExit):
                    pressing.stop_run(app, press_stop.exception)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        out = app.paths.root
        written = seen.getvalue()
        for p in out.rglob("*"):
            if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"):
                written += p.read_text(encoding="utf-8", errors="ignore")
        names = " ".join(p.name for p in out.rglob("*"))
        self.assertTrue(list(app.paths.diagnostics.glob("*")), "the stop wrote its failure file")
        self.assertIn("www.spectrum.net/mobile-billing/statement-history",
                      (app.paths.diagnostics / "download-attempt.json").read_text())
        for word in (CUR, PRI, STREET, ADDRESS, sid(CUR, "2026-09-26"), sid(PRI, "2026-02-26"),
                     "Account=", "pdfStatementId", MOB, MOB_PHONE, mobile_sid("2026-09-13"),
                     mobile_sid("2026-08-13"), "statementId", "61.40"):
            self.assertNotIn(word, written, word)
            self.assertNotIn(word, names, word)
        pdfs = sorted(p.name for p in out.rglob("*.pdf"))
        self.assertEqual(pdfs, ["2026-09-13 Spectrum Mobile Statement.pdf",
                                "2026-09-26 Spectrum Internet Statement.pdf"])


class MobileGuards(unittest.TestCase):
    def test_the_mobile_account_link(self):
        for label in (NB.join(["Mobile", "Account", "Number:", MOB]), "Mobile Account Number: ****5555",
                      "Mobile Account Number: \u2022\u2022\u2022\u20225555"):
            self.assertTrue(site.is_mobile_account_link(label), label)
        for label in ("", "Mobile", "Manage Mobile Devices", "Internet Account Number: 1234",
                      "Mobile Account Number", "Mobile Account Number: ", "Mobile Account Number: - .",
                      "Mobile Account Number: 1234 Make a Payment", "Mobile Account Number Settings",
                      "Change Mobile Account Number: 1234"):
            self.assertFalse(site.is_mobile_account_link(label), label)
        self.assertEqual(site.mobile_account_number(NB.join(["Mobile", "Account", "Number:", MOB])), MOB)

    def test_expand_all_exactly(self):
        for label in ("Expand All", "Expand" + NB + "All", "  expand all "):
            self.assertTrue(site.is_expand_all(label), label)
        for label in ("", "Print", "Collapse All", "Expand All Payments", "Expand", "Make a Payment"):
            self.assertFalse(site.is_expand_all(label), label)

    def test_the_mobile_row_guard(self):
        self.assertTrue(site.is_safe_mobile_row(mobile_row("2026-08-13"), "2026-08-13"))
        self.assertTrue(site.is_safe_mobile_row("Statement August 13, 2026 $61.40", "2026-08-13"))
        for text, day in [(mobile_row("2026-08-13"), "2026-07-13"),
                          ("Statement October 13 Auto Pay: Oct 30 $78.12", "2026-10-13"),
                          ("Your Total So Far Auto Pay: Nov 30 $80.00", "2026-11-30"),
                          ("Order 1234567 August 13, 2025", "2025-08-13"),
                          ("Statement August 13, 2026 Make a Payment", "2026-08-13"),
                          ("Statement August 13, 2026 Print", "2026-08-13"),
                          ("Statement August 13, 2026", "not a day"), ("", "2026-08-13")]:
            self.assertFalse(site.is_safe_mobile_row(text, day), text)

    def test_which_rows_are_finished_statements(self):
        self.assertEqual(site.mobile_days(mobile_rows()), MOBILE_DAYS)
        self.assertEqual(site.mobile_days(mobile_rows([])), [])
        with self.assertRaises(site.ListStopped):
            site.mobile_days(mobile_rows(["2026-08-13", "2026-08-13"]))
        with self.assertRaises(site.ListStopped):
            site.mobile_days(["Statement of something new"])
        with self.assertRaises(site.ListStopped):
            site.mobile_days(["Statement February 30, 2026"])

    def test_the_mobile_statement_address(self):
        good = f"https://{HOST}{site.MOBILE_DETAIL_PATH}?statementId=Zq9&newStatementVersion=true"
        self.assertEqual(site._mobile_detail_query(good)["statementId"], "Zq9")
        for url in (good.replace("https://", "http://"), good.replace(HOST, "evil.example"),
                    good + "#x", good + "&statementId=Zq8", good + "&other=1",
                    f"https://{HOST}{site.MOBILE_DETAIL_PATH}?statementId=",
                    f"https://{HOST}{site.MOBILE_LIST_PATH}?statementId=Zq9",
                    f"https://{HOST}:8443{site.MOBILE_DETAIL_PATH}?statementId=Zq9"):
            self.assertIsNone(site._mobile_detail_query(url), url)

    def test_the_heading(self):
        state = {"dates": ["AUGUST 13, 2026"], "details": True, "mobile": True}
        self.assertEqual(site.heading_says(state, "2026-08-13", only=True), "")
        self.assertTrue(site.heading_says(state, "2026-07-13", only=True))
        self.assertTrue(site.heading_says({**state, "mobile": False}, "2026-08-13", only=True))
        self.assertTrue(site.heading_says({**state, "details": False}, "2026-08-13", only=True))
        two = {**state, "dates": ["AUGUST 13, 2026", "July 13, 2026"]}
        self.assertTrue(site.heading_says(two, "2026-08-13", only=True))
        self.assertEqual(site.heading_says(two, "2026-08-13", only=False), "")
        self.assertTrue(site.heading_says({}, "2026-08-13", only=False))


LIVE_TILE = ("Statement October 13 Auto Pay: Oct 30 $78.12 Looking for your next bill? "
             "This info is currently not available. Please try again later.")


class BenignMessages(unittest.TestCase):
    def test_the_next_bill_tile_is_not_rate_limiting(self):
        self.assertIsNone(site.detect_security_challenge(Page(body=LIVE_TILE)))
        self.assertIsNone(site.detect_security_challenge(Page(body=LIVE_TILE.replace(" ", "\n  "))))

    def test_the_phrase_elsewhere_still_is(self):
        for body in ("Too many attempts. Please try again later.", LIVE_TILE + " Too many requests",
                     LIVE_TILE + " Something went wrong, try again later.",
                     "This info is currently not available. Please wait, then try again later.",
                     "This info is currently not available Please try again later"):
            self.assertIn("rate limiting", site.detect_security_challenge(Page(body=body)) or "", body)
        self.assertIn("Security challenge",
                      site.detect_security_challenge(Page(body=LIVE_TILE + " Are you a robot?")) or "")

    def test_the_run_goes_on_past_the_tile(self):
        app = make_app(tempfile.mkdtemp(), "--discover")
        page = Page(body=LIVE_TILE)
        with redirect_stdout(io.StringIO()) as said:
            app.check_session(page)
        self.assertNotIn("rate limiting", said.getvalue())


class MobileListing(WithFakeClick):
    def test_the_finished_statements_are_listed_after_one_link_press(self):
        page = Page(mobile=mobile_rows())
        got = site.collect_download_docs(page, dl_dir=self.tmp)
        mobile = [r for r in got if r.document_id.startswith("mobile:")]
        self.assertEqual(len(got), 5 + 3)
        self.assertEqual([r.document_id for r in mobile], ["mobile:" + d for d in MOBILE_DAYS])
        self.assertEqual({(r.title, r.account) for r in mobile}, {(site.MOBILE_TITLE, "Mobile")})
        self.assertEqual(page.gotos, [site.STATEMENTS_URL, site.BILLING_HOME_URL])
        self.assertEqual([c[1] for c in page.clicks], [site.OPEN_MOBILE_STEP])
        self.assertIn(MOB, site.private_words())
        self.assertEqual(page.live_listeners(), 0)

    def test_without_the_folder_the_list_stops_holding_the_internet_statements(self):
        page = Page(mobile=mobile_rows())
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page, dl_dir=None)
        self.assertEqual(len(stop.exception.docs), 5)
        self.assertEqual((page.clicks, page.gotos), ([], [site.STATEMENTS_URL]))
        self.assertIn("download folder", str(stop.exception))

    def test_a_mobile_list_that_never_settles_is_not_read(self):
        """Rows that never draw, or keep changing, are a list not read, never
        a list of no statements."""
        def never_drawn(p):
            p.where, p.url, p.mobile = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}", []

        def growing(p):
            p.where, p.url = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}"
            grown = []

            def rows():
                from datetime import date, timedelta
                grown.append(mobile_row((date(2020, 1, 13) + timedelta(days=len(grown))).isoformat()))
                return list(grown)
            p.links = lambda: rows() if p.where == "mlist" else []

        def only_under_way(p):
            p.where, p.url = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}"
            p.mobile = mobile_rows([])[:1]
        for on_link in (never_drawn, growing):
            page = Page(mobile=mobile_rows(), on_link=on_link)
            with self.assertRaises(site.ListStopped) as stop:
                site.collect_download_docs(page, dl_dir=self.tmp)
            self.assertEqual(len(stop.exception.docs), 5, on_link.__name__)
            self.assertEqual(page.live_listeners(), 0)
        # A list that settles with only the statement under way has no
        # finished statement yet, which is a whole list.
        got = site.collect_download_docs(Page(mobile=mobile_rows(), on_link=only_under_way), dl_dir=self.tmp)
        self.assertEqual(len(got), 5)

    def test_no_mobile_account_is_no_mobile_statement(self):
        page = Page()
        got = site.collect_download_docs(page, dl_dir=self.tmp)
        self.assertEqual(len(got), 5)
        self.assertEqual(page.clicks, [])

    def test_what_stops_the_mobile_list_keeps_the_internet_statements(self):
        two = Page(mobile=mobile_rows())
        two.links = lambda: [NB.join(["Mobile", "Account", "Number:", MOB]),
                             "Mobile Account Number: 222288889"] if two.where == "billing" else []
        blank = Page(mobile=mobile_rows())
        blank.links = lambda: []
        elsewhere = Page(mobile=mobile_rows(), on_link=lambda p: setattr(p, "url", f"https://{HOST}/billing"))
        odd = Page(mobile=mobile_rows())
        odd.links = lambda: ["Internet Account Number: 1234", "Mobile Account Number: 1234 (Primary Line)"] \
            if odd.where == "billing" else []
        cases = [(odd, self.tmp, 0),
                 (Page(mobile=mobile_rows(["2026-08-13", "2026-08-13"])), self.tmp, 1),
                 (Page(mobile=["Statement of a kind not seen"]), self.tmp, 1),
                 (two, self.tmp, 0), (blank, self.tmp, 0), (elsewhere, self.tmp, 1)]
        for page, dl_dir, presses in cases:
            with self.assertRaises(site.ListStopped) as stop:
                site.collect_download_docs(page, dl_dir=dl_dir)
            self.assertEqual(len(stop.exception.docs), 5)
            self.assertEqual(page.link_presses, presses)
            self.assertNotIn(MOB, str(stop.exception))
            self.assertEqual(page.live_listeners(), 0)

    def test_a_mobile_link_whose_address_is_refused_is_not_pressed(self):
        for href in ("/billing/auto-pay", f"https://{HOST}/billing/mobile-statements", "https://evil.test/x",
                     ValueError("gone")):
            page = Page(mobile=mobile_rows())
            page.hrefs = {("billing", 3): href}
            with self.assertRaises(site.ListStopped) as stop:
                site.collect_download_docs(page, dl_dir=self.tmp)
            self.assertEqual(len(stop.exception.docs), 5)
            self.assertEqual(page.link_presses, 0, href)
            self.assertEqual(page.live_listeners(), 0)

    def test_a_tab_or_a_download_after_the_link_press_stops_the_run(self):
        def tab(p):
            p.context.pages.append(SimpleNamespace(close=lambda: None))
            p.where, p.url = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}"

        def download(p):
            p.emit("download", SimpleNamespace(cancel=lambda: None, delete=lambda: None))
            p.where, p.url = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}"
        for on_link in (tab, download):
            page = Page(mobile=mobile_rows(), on_link=on_link)
            with self.assertRaises(pressing.NoAnswer):
                site.collect_download_docs(page, dl_dir=self.tmp)
            self.assertEqual(page.live_listeners(), 0)

    def test_a_signed_out_answer_after_the_link_press(self):
        def out(p):
            p.emit("response", Resp("fetchCmsAlerts", status=401))
            p.where, p.url = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}"
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(Page(mobile=mobile_rows(), on_link=out), dl_dir=self.tmp)


class MobileTaking(WithFakeClick):
    def take(self, page, day="2026-08-13", dl_dir="", own_files=()):
        if dl_dir == "":
            dl_dir = self.tmp / "staging"
            dl_dir.mkdir(exist_ok=True)
        out = self.tmp / ("%s Spectrum Mobile Statement.pdf" % day)
        trace = []
        ok = site.download_bill(page, dl_dir, day, out, title=site.MOBILE_TITLE, trace=trace,
                                document_id="mobile:" + day, own_files=own_files)
        return ok, out, trace

    def test_success_presses_the_link_the_row_and_expand_all_then_prints(self):
        page = Page(mobile=mobile_rows())
        ok, out, trace = self.take(page)
        self.assertTrue(ok)
        self.assertEqual(out.read_bytes()[:5], b"%PDF-")
        self.assertEqual(site.printed_header_day(site.pdf_text(out.read_bytes())), "2026-08-13")
        self.assertEqual([c[1] for c in page.clicks],
                         [site.OPEN_MOBILE_STEP, site.CHOOSE_MOBILE_STEP, site.EXPAND_STEP])
        self.assertEqual(page.mobile_row_presses, [3])
        self.assertFalse(any("Print" in c[2] for c in page.clicks))
        self.assertEqual((page.prints, page.presses), (1, 0))
        self.assertEqual(page.gotos, [site.BILLING_HOME_URL], "the Internet list is not read")
        self.assertFalse(list(self.tmp.glob("*.part")))
        self.assertIn(mobile_sid("2026-08-13"), site.private_words())
        self.assertEqual(page.live_listeners(), 0)
        for t in trace:
            self.assertNotIn(MOB, json.dumps(t))
            self.assertNotIn(mobile_sid("2026-08-13"), json.dumps(t))

    def test_a_statement_not_in_the_list_is_not_pressed(self):
        for page in (Page(mobile=mobile_rows(["2026-09-13"])), Page()):
            ok, out, _ = self.take(page)
            self.assertFalse(ok)
            self.assertEqual(page.mobile_row_presses, [])
            self.assertFalse(out.exists())

    def test_a_mobile_list_that_cannot_be_read_again_stops_the_run(self):
        """The Mobile list read again for a statement is the list every
        Mobile statement after it reads too, so one that cannot be read
        whole, here two statements of one date, is raised to the run."""
        page = Page(mobile=mobile_rows(["2026-08-13", "2026-08-13"]))
        with self.assertRaises(site.ListStopped):
            self.take(page)
        self.assertEqual(page.mobile_row_presses, [])
        self.assertFalse((self.tmp / "2026-08-13 Spectrum Mobile Statement.pdf").exists())

    def test_nothing_is_pressed_without_the_download_folder(self):
        page = Page(mobile=mobile_rows())
        with self.assertRaises(pressing.NotPressed):
            self.take(page, dl_dir=None)
        self.assertEqual(page.clicks, [])

    def test_a_row_that_changed_or_is_turned_off_is_left(self):
        # Billing's Mobile link reads otherwise by the time it is pressed,
        # which every Mobile statement meets, so the run stops.
        page = Page(mobile=mobile_rows())
        page.row_changes[("m", 3)] = "Statement August 13, 2026 Make a Payment"
        with self.assertRaises(site.ListStopped):
            self.take(page)
        self.assertEqual(page.mobile_row_presses, [])

        def off(p, i):
            raise pressing.TurnedOff("choose a Mobile statement", "turned off", ["turned off"])
        page = Page(mobile=mobile_rows(), on_mobile_row=off)
        ok, out, trace = self.take(page)
        self.assertFalse(ok)
        self.assertEqual(page.prints, 0)
        self.assertIn({"note": "the Mobile row is turned off"}, trace)
        self.assertEqual(page.live_listeners(), 0)

    def test_a_mobile_row_whose_address_is_refused_is_not_pressed(self):
        for href in ("/billing/autopay", "https://evil.test/x", "/mobile-billing/statement-history?statementId=Zq9",
                     ValueError("gone")):
            page = Page(mobile=mobile_rows())
            page.hrefs = {("mlist", 3): href}
            ok, out, trace = self.take(page)
            self.assertFalse(ok, href)
            self.assertEqual(page.link_presses, 1)
            self.assertEqual((page.mobile_row_presses, page.prints), ([], 0), href)
            self.assertFalse(out.exists())
            self.assertEqual(page.live_listeners(), 0)

    def stops(self, **kw):
        page = Page(mobile=mobile_rows(), **kw)
        with self.assertRaises(pressing.Stop):
            self.take(page)
        self.assertFalse((self.tmp / "2026-08-13 Spectrum Mobile Statement.pdf").exists())
        self.assertFalse(list(self.tmp.glob("*.part")))
        self.assertEqual(page.live_listeners(), 0)
        return page

    def test_anything_unexpected_after_the_row_press_stops_the_run(self):
        def other_day(p, i):
            mobile_lands(p, i)
            p.mobile_day = "2026-07-13"

        def off_path(p, i):
            mobile_lands(p, i)
            p.url = f"https://{HOST}{site.MOBILE_LIST_PATH}?statementId=Zq9"

        def tab(p, i):
            mobile_lands(p, i)
            p.context.pages.append(SimpleNamespace(close=lambda: None))

        def download(p, i):
            mobile_lands(p, i)
            p.emit("download", SimpleNamespace(cancel=lambda: None, delete=lambda: None))
        for on_row in (other_day, off_path, tab, download):
            page = self.stops(on_mobile_row=on_row)
            self.assertEqual(page.expands + page.prints, 0, on_row.__name__)
        for state in ({"dates": ["AUGUST 13, 2026"], "details": True, "mobile": False},
                      {"dates": ["AUGUST 13, 2026", "JULY 13, 2026"], "details": True, "mobile": True},
                      {"dates": ["AUGUST 13, 2026"], "details": False, "mobile": True}):
            page = self.stops(detail_state=lambda p, state=state: state)
            self.assertEqual(page.prints, 0)

    def test_two_dates_never_share_one_page(self):
        def same_page(p, i):
            mobile_lands(p, i)
            p.url = p.url.replace(mobile_sid(p.mobile_day), mobile_sid("2026-08-13"))
        page = Page(mobile=mobile_rows(), on_mobile_row=same_page)
        self.assertTrue(self.take(page)[0])
        page = Page(mobile=mobile_rows(), on_mobile_row=same_page)
        with self.assertRaises(pressing.Stop):
            self.take(page, day="2026-07-13")

    def test_without_one_enabled_expand_all_nothing_is_printed(self):
        for buttons in ((("Print", True),), (("Expand All", False), ("Print", True)),
                        (("Expand All", True), ("Expand All", True))):
            page = Page(mobile=mobile_rows(), mbuttons=buttons)
            ok, out, _ = self.take(page)
            self.assertFalse(ok)
            self.assertEqual((page.expands, page.prints), (0, 0))
            self.assertFalse(out.exists())

    def test_anything_unexpected_after_expand_all_stops_the_run(self):
        def moved(p):
            p.url += "&x=1"

        def tab(p):
            p.context.pages.append(SimpleNamespace(close=lambda: None))
        for on_expand in (moved, tab):
            self.assertEqual(self.stops(on_expand=on_expand).prints, 0)
        gone = self.stops(detail_state=lambda p: {"dates": [upper_date(p.mobile_day)] if not p.expanded else [],
                                                  "details": True, "mobile": True})
        self.assertEqual(gone.prints, 0)

    def test_a_print_that_is_not_this_statement_stops_the_run(self):
        wrong = text_pdf(["Statement Details", "JULY 13, 2026", "Mobile", "Previous Balance Payments and Credits",
                          "Remaining Balance Unlimited Plus Lines", "Included Taxes, Fees & Charges"])
        self.stops(on_print=lambda p: wrong)
        self.stops(on_print=lambda p: b"not a pdf at all")

    def test_bytes_kept_for_another_statement_or_already_saved_are_refused(self):
        same = text_pdf(["AUGUST 13, 2026 Mobile", "JULY 13, 2026",
                         "Previous Balance Payments and Credits Remaining Balance Unlimited Plus Lines"])
        self.assertTrue(self.take(Page(mobile=mobile_rows(), on_print=lambda p: same))[0])
        with self.assertRaises(pressing.Stop):
            self.take(Page(mobile=mobile_rows(), on_print=lambda p: same), day="2026-07-13")
        site._KEPT.clear()
        site._MOBILE_IDS.clear()
        with self.assertRaises(pressing.Stop):
            self.take(Page(mobile=mobile_rows(), on_print=lambda p: same), day="2026-07-13")
        own = self.tmp / "2026-08-13 Spectrum Mobile Statement.pdf"
        site._KEPT.clear()
        self.assertTrue(self.take(Page(mobile=mobile_rows(), on_print=lambda p: same), own_files=[own])[0],
                        "a Download again may meet its own copy")

    def test_the_printed_header_must_read_the_date_not_just_mention_it(self):
        incidental = text_pdf(["Statement Details", "JULY 13, 2026", "Mobile", "Payment received August 13, 2026",
                               "Previous Balance Payments and Credits Remaining Balance Unlimited Plus Lines"])
        self.stops(on_print=lambda p: incidental)
        self.assertEqual(site.printed_header_day("Statement Details Espanol AUGUST 13, 2026 Mobile AMOUNT"),
                         "2026-08-13")
        self.assertIsNone(site.printed_header_day("Statement Details AUGUST 13, 2026 Internet"))
        self.assertIsNone(site.printed_header_day("AUGUST 13, 2026 Phone 555-010-4477 and then Mobile"))
        self.assertIsNone(site.printed_header_day(""))

    def test_the_live_print_as_the_apps_own_pdf_text_reads_it(self):
        # pdf_text of the live print, 2026-10-14, digits made up.
        live = ("S E P T E M B E R  1 3,  2 0 2 6\nMobile\nA M O U N T  D U E\n61.40\nYour Auto Pay is "
                "scheduled for September 30.\nCredit ends April 12, 2027.\n-$10.00")
        self.assertEqual(site.printed_header_day(live), "2026-09-13")
        self.assertEqual(site.printed_header_day(live.replace("  ", " ")), "2026-09-13")
        self.assertEqual(site.printed_header_day(live.replace("\nMobile", " Mobile")), "2026-09-13")
        self.assertEqual(site.printed_header_day(live.replace("  ", "\u00a0\u00a0").replace("\n", " \n ")),
                         "2026-09-13")
        self.assertIsNone(site.printed_header_day(live.replace("\nMobile", "\nAutomobile")))
        self.assertIsNone(site.printed_header_day(live.replace("\nMobile", "\nMobiles")))
        later = live.replace("\nMobile", "\nInternet").replace("April 12, 2027.", "April 12, 2027 Mobile.")
        self.assertIsNone(site.printed_header_day(later), "a later date is never taken for the heading")
        self.assertIsNone(site.printed_header_day(live.replace("\nMobile", "\nMobile_account")))
        self.assertEqual(site.printed_header_day(live.replace("S E P T E M B E R", "A U G U S T")), "2026-08-13")
        out = self.tmp / "y" / "2026-09-13 Spectrum Mobile Statement.pdf"
        out.parent.mkdir()
        pdf = text_pdf(live.split("\n"))
        self.assertEqual(site.printed_header_day(site.pdf_text(pdf)), "2026-09-13")
        self.assertEqual(site.bind_mobile(pdf, "2026-09-13", out), "")
        self.assertIn("header", site.bind_mobile(pdf, "2026-04-12", out))

    def test_the_live_print_shape(self):
        self.assertEqual(site.printed_header_day(LIVE_PRINT), "2026-09-13")
        self.assertEqual(site.printed_header_day(LIVE_PRINT.replace("1 3,", "1 4,")), "2026-09-14")
        wrong = LIVE_PRINT.replace("S E P T E M B E R", "A U G U S T")
        self.assertEqual(site.printed_header_day(wrong), "2026-08-13")
        # Read back from a real PDF of that shape, it binds to its own date only.
        out = self.tmp / "x" / "2026-09-13 Spectrum Mobile Statement.pdf"
        out.parent.mkdir()
        self.assertEqual(site.bind_mobile(text_pdf([LIVE_PRINT]), "2026-09-13", out), "")
        self.assertIn("header", site.bind_mobile(text_pdf([wrong]), "2026-09-13", out))
        self.assertIn("header", site.bind_mobile(text_pdf([LIVE_PRINT]), "2026-08-13", out))
        # "Mobile" must be its own word right after the date.
        auto = LIVE_PRINT.replace(" Mobile ", " Automobile ")
        self.assertIsNone(site.printed_header_day(auto))
        self.assertIn("header", site.bind_mobile(text_pdf([auto]), "2026-09-13", out))
        self.assertIsNone(site.printed_header_day(LIVE_PRINT.replace(" Mobile ", " Mobiles ")))
        self.assertIsNone(site.printed_header_day(LIVE_PRINT.replace(" Mobile ", " Internet ")))

    def test_a_page_that_changes_while_it_prints_stops_the_run(self):
        def moves(p):
            p.url = f"https://{HOST}{site.MOBILE_LIST_PATH}"
            return mobile_print(p)

        def other_day(p):
            data = mobile_print(p)
            p.mobile_day = "2026-07-13"
            return data

        def errors(p):
            p.emit("response", Resp("fetchMobileHistoricalStatement", answer={"errors": [{"message": "x"}]}))
            return mobile_print(p)
        for on_print in (moves, other_day, errors):
            self.stops(on_print=on_print)

    def test_a_failed_answer_of_the_statement_stops_the_run(self):
        for resp in (Resp("fetchMobileHistoricalStatement", answer={"errors": [{"message": "x"}]}),
                     Resp("fetchMobileHistoricalStatement", status=500),
                     Resp("fetchMobileHistoricalStatement", answer=ValueError("not json"))):
            def on_row(p, i, resp=resp):
                mobile_lands(p, i)
                p.emit("response", resp)
            page = self.stops(on_mobile_row=on_row)
            self.assertEqual(page.expands, 0)

            def on_expand(p, resp=resp):
                p.emit("response", resp)
            page = self.stops(on_expand=on_expand)
            self.assertEqual(page.prints, 0)
        self.stops(on_print=lambda p: (p.emit("response", Resp("fetchMobileHistoricalStatement", status=503)),
                                       mobile_print(p))[1])
        # The Mobile list's own statements answer failing stops the list.
        page = Page(mobile=mobile_rows(), on_link=lambda p: (
            p.emit("response", Resp("fetchMobileDigitalStatementsForBillPresentment",
                                    answer={"errors": [{"message": "x"}]})),
            setattr(p, "where", "mlist"), setattr(p, "url", f"https://{HOST}{site.MOBILE_LIST_PATH}")))
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(page, dl_dir=self.tmp)
        # A 401 from any operation is a signed-out session.
        page = Page(mobile=mobile_rows(), on_expand=lambda p: p.emit("response", Resp("fetchCmsAlerts", status=401)))
        with self.assertRaises(site.SessionExpired):
            self.take(page)

    def test_another_operations_failed_answer_is_only_logged(self):
        bad = {"errors": [{"message": "Account %s not found" % MOB}]}
        others = ("fetchMobileBillPresentmentCurrentStatement", "fetchMobileInsuranceInfo", "fetchCmsAlerts",
                  "somethingNew", "fetchMobile_" + MOB, "not a name; " + MOB)

        def on_row(p, i):
            mobile_lands(p, i)
            for op in others:
                p.emit("response", Resp(op, answer=bad))
            p.emit("response", Resp("fetchMobileAccountInfoSpecMob", status=500))

        def on_link(p):
            p.emit("response", Resp("fetchMobileBillPresentmentCurrentStatement", answer=bad))
            p.where, p.url = "mlist", f"https://{HOST}{site.MOBILE_LIST_PATH}"
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        logging.getLogger().addHandler(handler)
        old = logging.getLogger().level
        logging.getLogger().setLevel(logging.INFO)
        try:
            page = Page(mobile=mobile_rows(), on_mobile_row=on_row, on_link=on_link,
                        on_expand=lambda p: p.emit("response", Resp("fetchCmsAlerts", answer=bad)))
            ok, out, trace = self.take(page)
        finally:
            logging.getLogger().removeHandler(handler)
            logging.getLogger().setLevel(old)
        self.assertTrue(ok, "an unrelated answer's errors do not stop the statement")
        self.assertEqual(page.prints, 1)
        self.assertIn("fetchMobileInsuranceInfo", seen.getvalue())
        self.assertNotIn(MOB, seen.getvalue())
        self.assertNotIn("not found", seen.getvalue())
        self.assertIn("fetchMobile_[name]", seen.getvalue(), "an operation name is redacted")

    def test_sections_that_do_not_all_expand_are_not_printed(self):
        def shape(toggles=1, toggle="expand", sections=6, open_=0):
            return {"toggles": toggles, "toggle": toggle, "sections": sections, "open": open_}
        cases = [
            # nothing to read before the press: not pressed
            (lambda p: shape(sections=0), 0),
            (lambda p: shape(toggles=2), 0),
            (lambda p: shape(toggles=0, toggle=""), 0),
            # pressed, then not every section opens
            (lambda p: shape(toggle="collapse", open_=5) if p.expanded else shape(), 1),
            # pressed, every section opens but the toggle still reads Expand All
            (lambda p: shape(open_=6) if p.expanded else shape(), 1),
            # fewer sections than any statement has: a page still drawing
            (lambda p: shape(sections=5), 0),
            (lambda p: shape(toggle="collapse", sections=5, open_=5), 0),
            # the count changed with the press
            (lambda p: shape(toggle="collapse", sections=7, open_=7) if p.expanded else shape(), 1),
        ]
        for sections, presses in cases:
            page = Page(mobile=mobile_rows(), sections=sections)
            ok, out, trace = self.take(page)
            self.assertFalse(ok)
            self.assertEqual((page.expands, page.prints), (presses, 0))
            self.assertFalse(out.exists())
            seen = [t for t in trace if t.get("note") == "sections before Expand All"]
            self.assertEqual(len(seen), 1, "the trace keeps the counts it saw")
            self.assertEqual(set(seen[0]) - {"note"}, {"toggles", "toggle", "sections", "open"})
        polls = []

        def slow(p):
            if p.expanded:
                polls.append(1)
                if len(polls) > 3:
                    return shape(toggle="collapse", open_=6)
            return shape()
        ok, out, trace = self.take(Page(mobile=mobile_rows(), sections=slow))
        self.assertTrue(ok, "a slow expand is waited for")
        self.assertIn({"note": "Expand All pressed", "strays": False, "toggles": 1, "toggle": "collapse",
                       "sections": 6, "open": 6}, trace)

    def test_a_section_drawn_late_is_never_printed_as_whole(self):
        def shape(sections, open_):
            return {"toggles": 1, "toggle": "collapse", "sections": sections, "open": open_}
        # Already open, then a seventh section arrives closed: not pressed,
        # not printed.
        reads = []

        def late_closed(p):
            reads.append(1)
            return shape(6, 6) if len(reads) < 3 else shape(7, 6)
        page = Page(mobile=mobile_rows(), sections=late_closed)
        self.assertFalse(self.take(page)[0])
        self.assertEqual((page.expands, page.prints), (0, 0))
        # Pressed and steady, then a section closed just before the print.
        page = Page(mobile=mobile_rows(), sections=lambda p: (
            {"toggles": 1, "toggle": "expand", "sections": 6, "open": 0} if not p.expanded
            else shape(6, 6) if len(p.reads) < 4 else shape(7, 6)))
        page.reads = []
        original = page.sections

        def counting(p):
            if p.expanded:
                p.reads.append(1)
            return original(p)
        page.sections = counting
        self.stops_page(page)
        self.assertEqual(page.prints, 0)
        # A section drawn while the page printed.
        page = Page(mobile=mobile_rows(), sections=lambda p: (
            {"toggles": 1, "toggle": "expand", "sections": 6, "open": 0} if not p.expanded
            else shape(7, 7) if p.prints else shape(6, 6)))
        self.stops_page(page)
        self.assertEqual(page.prints, 1)

    def stops_page(self, page):
        with self.assertRaises(pressing.Stop):
            self.take(page)
        self.assertFalse((self.tmp / "2026-08-13 Spectrum Mobile Statement.pdf").exists())
        self.assertFalse(list(self.tmp.glob("*.part")))

    def test_a_statement_already_showing_every_section_is_not_pressed(self):
        page = Page(mobile=mobile_rows(), sections=lambda p: {"toggles": 1, "toggle": "collapse",
                                                               "sections": 6, "open": 6})
        ok, out, trace = self.take(page)
        self.assertTrue(ok)
        self.assertEqual((page.expands, page.prints), (0, 1))
        self.assertNotIn(site.EXPAND_STEP, [c[1] for c in page.clicks])

    def test_a_print_that_fails_leaves_the_statement(self):
        page = Page(mobile=mobile_rows(), on_print=lambda p: RuntimeError("Timeout for " + MOB))
        ok, out, trace = self.take(page)
        self.assertFalse(ok)
        self.assertFalse(out.exists())
        self.assertFalse(list(self.tmp.glob("*.part")))
        self.assertNotIn(MOB, json.dumps(trace))

    def test_signed_out_after_the_row_press(self):
        def login(p, i):
            p.url = f"https://{HOST}/login"

        def answer_401(p, i):
            mobile_lands(p, i)
            p.emit("response", Resp("fetchMobileHistoricalStatement", status=401))

        def passcode(p, i):
            mobile_lands(p, i)
            p.body = "Enter the code we sent"
        for on_row, kind in ((login, site.SessionExpired), (answer_401, site.SessionExpired),
                             (passcode, site.OtpRequired)):
            page = Page(mobile=mobile_rows(), on_mobile_row=on_row)
            with self.assertRaises(kind):
                self.take(page)
            self.assertEqual(page.prints, 0)
            self.assertEqual(page.live_listeners(), 0)


LIVE_SECTIONS = """<!doctype html><meta charset="utf-8"><body>
<nav><button aria-expanded="false">Expand Account</button>
<button aria-expanded="false">Expand Funds &amp; Wallet</button></nav>
<button id="accord-5-button-0" class="kite-accordion-row__button" aria-expanded="false">Account Holder Information</button>
<button class="kite-button" id="toggle">Expand&nbsp;All</button>
<button id="accord-2-button-0" class="kite-accordion-row__button" aria-expanded="false">Previous Balance</button>
<button id="accord-6-button-0" class="kite-accordion-row__button" aria-expanded="false">Payments and Credits</button>
<button id="accord-3-button-0" class="kite-accordion-row__button" aria-expanded="false">Remaining Balance</button>
<button id="accord-4-button-0" class="kite-accordion-row__button" aria-expanded="false">Unlimited Plus Lines (2)</button>
<button id="accord-1-button-0" class="kite-accordion-row__button" aria-expanded="false">Included Taxes, Fees &amp; Charges</button>
<button>Print</button>
<button id="accord-9-button-1" class="kite-accordion-row__button" aria-expanded="false">Another row</button>
<button id="accord-8-button-0" aria-expanded="false">An accordion of another kind</button>
<button class="kite-accordion-row__button" aria-expanded="false">An accordion with no id</button>
<script>document.getElementById('toggle').onclick = () => setTimeout(() => {
  document.querySelectorAll('%s').forEach(b => b.setAttribute('aria-expanded', 'true'));
  document.getElementById('toggle').innerHTML = 'Collapse&nbsp;All'; }, 300);</script></body>"""


class LiveSectionsShape(unittest.TestCase):
    """_SECTIONS_JS in a real browser, on the page shape seen live on
    2026-10-13: six accordion buttons without aria-controls, the first above
    Expand All, navigation buttons with aria-expanded of their own, and the
    toggle reading Collapse All once every section is open."""

    def run_page(self, opens):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("no Playwright")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as e:
                self.skipTest("no browser: %s" % e)
            try:
                page = browser.new_page()
                page.set_content(LIVE_SECTIONS % opens)
                before = page.evaluate(site._SECTIONS_JS)
                page.click("#toggle")
                page.wait_for_timeout(800)
                after = page.evaluate(site._SECTIONS_JS)
            finally:
                browser.close()
        return before, after

    def test_every_section_opens_and_the_toggle_reads_collapse_all(self):
        before, after = self.run_page(".kite-accordion-row__button")
        self.assertEqual(before, {"toggles": 1, "toggle": "expand", "sections": 6, "open": 0})
        self.assertFalse(site.all_open(before))
        self.assertEqual(after, {"toggles": 1, "toggle": "collapse", "sections": 6, "open": 6})
        self.assertTrue(site.all_open(after), "the navigation's own aria-expanded is not counted")

    def test_a_section_left_closed_is_seen(self):
        _, after = self.run_page("[id^=accord-2], [id^=accord-6], [id^=accord-3], [id^=accord-4], [id^=accord-1]")
        self.assertEqual((after["sections"], after["open"]), (6, 5))
        self.assertFalse(site.all_open(after))


class Source(unittest.TestCase):
    def test_each_press_only_through_pressing_click_under_its_own_guard(self):
        tree = ast.parse((HERE / "spectrum_site.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        presses = [n for n in calls if n.func.attr == "click"]
        for n in presses:
            self.assertEqual(ast.unparse(n.func), "pressing.click")
        # (function, css, the guard that function calls before its press)
        expected = {("choose_in_page", "pressing.LINKS", "is_safe_row"),
                    ("_press_for_statement", "pressing.BUTTONS", None),
                    ("open_mobile_list", "pressing.LINKS", "is_mobile_account_link"),
                    ("choose_mobile", "pressing.LINKS", "is_safe_mobile_row"),
                    ("expand_statement", "pressing.BUTTONS", "is_expand_all")}
        found = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            mine = [n for n in presses if n in list(ast.walk(fn))]
            if not mine:
                continue
            self.assertEqual(len(mine), 1, fn.name)
            css = next(ast.unparse(k.value) for k in mine[0].keywords if k.arg == "css")
            called = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            guard = next((g for f, c, g in expected if f == fn.name), "missing")
            if guard:
                self.assertIn(guard, called, fn.name)
            found.add((fn.name, css, guard))
        self.assertEqual(found, expected)
        self.assertEqual(len(presses), 5)
        # Each anchor's own href is read and guarded before its press.
        for name, guard in (("choose_in_page", "is_safe_href"), ("open_mobile_list", "is_void_href"),
                            ("choose_mobile", "is_void_href")):
            fn = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name)
            self.assertIn(guard, {c.func.id for c in ast.walk(fn)
                                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}, name)
        # The View Printable Statement press is guarded by its caller.
        take = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "take_statement")
        self.assertIn("is_safe_control", {c.func.id for c in ast.walk(take)
                                          if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)})
        # The page's own Print is never named as something to press.
        self.assertFalse(site.is_expand_all("Print") or site.is_safe_control("Print")
                         or site.is_safe_mobile_row("Print", "2026-08-13"))
        for verb in ("dblclick", "tap", "fill", "type", "press", "select_option", "check", "uncheck",
                     "set_input_files", "dispatch_event", "press_sequentially", "press_once", "submit"):
            self.assertNotIn(verb, {n.func.attr for n in calls}, verb)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for raw in ("mouse", "keyboard", "touchscreen", "storage_state", "cookies",
                    "all_headers", "headers", "header_value", "body", "text"):
            self.assertNotIn(raw, attrs, raw)
        scripts = (site._ARM_JS + site._RESULT_JS + site._ROWS_JS + site._COUNT_JS + site._RESTORE_JS
                   + site._LINKS_JS + site._DETAIL_JS + site._SECTIONS_JS)
        for word in (".click(", "localStorage", "sessionStorage", "document.cookie", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(word, scripts, word)

    def test_the_docs_module_presses_nothing(self):
        tree = ast.parse((HERE / "spectrum_docs.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "fill", "type", "press", "select_option", "check"):
            self.assertNotIn(verb, called, verb)

    def test_no_value_reaches_a_log_or_trace(self):
        src = (HERE / "spectrum_site.py").read_text()
        for line in src.splitlines():
            if ("log." in line or "_note(" in line) and re.search(
                    r"page\.url|statement_id|\.request|post_data|detail_url\(|answer_of\(|\.json\(", line):
                self.fail("a value reaches a log or trace: " + line.strip()[:100])

    def test_rules(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        self.assertEqual(doc_types.classify_document(site.TITLE, rules)[:2], ("Statement", "Internet Statement"))
        self.assertEqual(doc_types.classify_document(site.MOBILE_TITLE, rules)[:2], ("Statement", "Mobile Statement"))
        self.assertFalse(doc_types.should_skip(site.MOBILE_TITLE, rules))
        for title in ("Your Total So Far", "Order 1234567"):
            self.assertTrue(doc_types.should_skip(title, rules), title)

    def test_no_file_holds_a_value_shaped_like_a_real_account_number(self):
        """A Spectrum account number is a long run of digits. The invented
        ones here are short and patterned, and no comment shows one."""
        for path in [HERE / "spectrum_site.py", HERE / "spectrum_docs.py", Path(__file__), HERE / "README.md"]:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(?<!\d)\d{13,}(?!\d)", text), path.name)
            if path != Path(__file__):
                self.assertIsNone(re.search(r"Account Number:? ?\d", text), path.name)

    def test_the_docs_keep_the_house_style(self):
        """No semicolon in the README, the CHANGELOG bullets or the PROVIDERS
        row, and canceled spelled the American way."""
        repo = HERE.parent.parent
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        # The app came after 0.51.0, so its bullets are above that heading,
        # in Unreleased or the version it became.
        newer = changelog.split("## [0.51.0]", 1)[0]
        bullets = [b for b in re.split(r"\n- ", newer) if b.startswith("**Spectrum")]
        self.assertGreaterEqual(len(bullets), 2)
        row = [line for line in (repo / "PROVIDERS.md").read_text(encoding="utf-8").splitlines()
               if line.startswith("| [`spectrum`]")]
        self.assertEqual(len(row), 1)
        for name, text in [("README", (HERE / "README.md").read_text(encoding="utf-8")),
                           ("CHANGELOG", "\n".join(bullets)), ("PROVIDERS", row[0])]:
            self.assertNotIn(";", text, name)
        for path in (HERE / "spectrum_site.py", HERE / "spectrum_docs.py", HERE / "README.md"):
            self.assertNotIn("cancelled", path.read_text(encoding="utf-8"), path.name)

    def test_config(self):
        config = json.loads((HERE / "config.example.json").read_text())
        self.assertEqual(config["cdp_url"], "http://127.0.0.1:9291")
        self.assertEqual((config["pilot_count"], config["owner"]), (1, ""))


if __name__ == "__main__":
    unittest.main()


def test_a_pdf_id_and_a_digital_id_of_one_statement_are_the_same_statement():
    import base64
    mk = lambda kind, code="1", date="2026-09-26": base64.b64encode(
        f"Account=123456789012|StatementDate={date}|StatementCode={code}|{kind}_DOCUMENT".encode()).decode()
    assert site.same_statement(mk("PDF"), mk("DIGITAL"))
    assert site.same_statement(mk("PDF"), mk("DIGITAL").rstrip("="))  # the page's id comes unpadded
    assert site.same_statement(mk("PDF"), mk("PDF"))
    assert site.same_statement(mk("PDF"), mk("DIGITAL", code="2")), "the code is the document's, not the statement's"
    assert not site.same_statement(mk("PDF"), mk("DIGITAL", date="2026-08-26"))
    assert not site.same_statement(mk("PDF"), "not base64!")
    assert not site.same_statement(None, mk("PDF"))
    # the list's own ids stay PDF_DOCUMENT only
    import unittest
    with unittest.TestCase().assertRaises(site.ListStopped):
        site.decode_statement_id(mk("DIGITAL"))
