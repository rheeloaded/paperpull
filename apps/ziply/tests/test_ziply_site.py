"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import base64
import io
import json
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import ziply_site as site  # noqa: E402
import ziply_docs as docs  # noqa: E402

FAKE_ACCOUNT = "98765432100001234"
FAKE_TOKEN = "Bearer fake-token-not-real-0000"
PDF = b"%PDF-1.4 " + b"x" * 3000


def stmt(day, inv, status="CLOSED"):
    return {"status": status, "date": day, "amount_due": "10", "id": inv,
            "url": f"https://ziplyfiber.com/api/myacc/billinginvoice?invoiceId={inv}", "__typename": "BillStatement"}


ROWS = [stmt("2026-10-13", "50000003", "OPEN"), stmt("2026-09-13", "50000002"), stmt("2026-08-13", "50000001")]


def answer(rows, error=False):
    return {"data": {"billStatements": {"error": error, "APIStatus": 200, "message": None,
                                        "billStatements": rows, "__typename": "BillStatementsResponse"}}}


class Req:
    def __init__(self, op="billingDetails", headers=None):
        self.method = "POST"
        self.url = site.API_URL
        self.post_data = json.dumps({"operationName": op, "variables": {"accountNumber": FAKE_ACCOUNT}, "query": "query x { y }"})
        self._headers = {"authorization": FAKE_TOKEN, "requestid": "r-0", "cookie": "never-taken",
                         "content-type": "application/json"} if headers is None else headers

    def all_headers(self):
        return dict(self._headers)


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n


class Page:
    def __init__(self, rows=ROWS, settled=None, asks=True, headers=None, listing=None, pdf=PDF, pdf_status=200):
        self.rows, self.asks, self.headers, self.listing = rows, asks, headers, listing
        self.settled = settled or site.DOCUMENTS_URL
        self.url = "about:blank"
        self.pdf, self.pdf_status = pdf, pdf_status
        self.handlers, self.asked = [], []

    def on(self, event, h):
        self.handlers.append(h)

    def remove_listener(self, event, h):
        self.handlers.remove(h)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.url = self.settled
        if self.asks:
            for h in list(self.handlers):
                h(Req(headers=self.headers))

    def locator(self, sel):
        return Locator(1 if "password" in sel and "login" in self.settled.lower() else 0)

    def evaluate(self, js, arg=None):
        self.asked.append(arg)
        if arg[0] == site.API_URL:
            return self.listing or {"status": 200, "data": answer(self.rows)}
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "text/html"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}


class Hosts(unittest.TestCase):
    def test_only_ziplyfiber_com_over_https(self):
        self.assertTrue(site.is_safe_url("https://ziplyfiber.com/myaccount/billing"))
        for u in ("http://ziplyfiber.com/", "https://www.ziplyfiber.com/", "https://smetrics.ziplyfiber.com/",
                  "https://ziplyfiber.com.evil.test/", "", None):
            self.assertFalse(site.is_safe_url(u), u)

    def test_a_bill_is_its_invoice_address_only(self):
        self.assertTrue(site.is_download_url(site.invoice_url("50000003")))
        for u in (site.invoice_url("50000003") + "&token=x", site.BASE + "/api/myacc/other?invoiceId=1",
                  site.BASE + site.DOWNLOAD_PATH + "?invoiceId=abc", site.BASE + site.DOWNLOAD_PATH):
            self.assertFalse(site.is_download_url(u), u)
        self.assertEqual(site.invoice_url("12"), "")


class Controls(unittest.TestCase):
    def test_the_bill_link_is_a_document(self):
        for name in ("VIEW PDF", "View Bill"):
            self.assertTrue(site.is_safe_control(name), name)

    def test_everything_else_is_refused(self):
        for name in ("MAKE A PAYMENT", "MANAGE AUTOPAY", "TURN OFF", "Upgrade", "Return equipment",
                     "Edit profile", "Update payment method", "Log out", "", "   "):
            self.assertFalse(site.is_safe_control(name), name)

    def test_credit_is_not_edit(self):
        self.assertIsNone(site.FORBIDDEN_CONTROL_RE.search("Credit Statement"))
        self.assertIsNotNone(site.FORBIDDEN_CONTROL_RE.search("Edit profile"))


class Rows(unittest.TestCase):
    def test_statements_are_known_by_invoice_and_dated(self):
        got = site.bills_of(answer(ROWS))
        self.assertEqual([d.date_text for d in got], ["2026-10-13", "2026-09-13", "2026-08-13"])
        self.assertEqual([d.document_id for d in got], ["50000003", "50000002", "50000001"])

    def test_unreadable_statements_stop_the_list_with_what_was_read(self):
        for broken in (stmt("2026-07-13", "x1"), dict(stmt("2026-07-13", "50000009"), url="https://evil.test/x.pdf"),
                       stmt("2026-02-30", "50000009"), stmt("2026-07-13", "50000003")):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(answer(ROWS + [broken]))
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_a_list_as_long_as_asked_for_or_an_error_stops(self):
        many = [stmt("2020-01-01", str(60000000 + i)) for i in range(site.BILLS_ASKED)]
        many = [dict(r, date=f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-13") for i, r in enumerate(many)]
        for a in (answer(many), answer(ROWS, error=True), {"data": {}}, []):
            with self.assertRaises(site.ListStopped):
                site.bills_of(a)
        with self.assertRaises(site.SessionExpired):
            site.bills_of({"errors": [{"message": "Unauthorized"}]})

    def test_rules_classify(self):
        self.assertIsInstance(json.loads((HERE / "document_rules.json").read_text()), dict)


class ListWhole(unittest.TestCase):
    def test_the_pages_own_query_is_asked_with_more_bills_and_its_headers(self):
        page = Page()
        self.assertEqual(len(site.collect_download_docs(page)), 3)
        url, headers, body = page.asked[0]
        self.assertEqual(url, site.API_URL)
        self.assertEqual(set(headers), {"authorization", "requestid"})
        self.assertEqual(body["operationName"], "billStatements")
        self.assertEqual(body["variables"], {"billsRequired": site.BILLS_ASKED, "isCurrentBill": False,
                                             "accountNumber": FAKE_ACCOUNT})
        self.assertTrue(body["query"].startswith("query billStatements"))

    def test_a_page_that_never_asks_or_carries_no_authorization_stops(self):
        for page in (Page(asks=False), Page(headers={"content-type": "application/json"}),
                     Page(settled="https://ziplyfiber.com/myaccount")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)

    def test_a_signed_out_site_or_a_refused_list_is_session_expired(self):
        for page in (Page(asks=False, settled="https://ziplyfiber.com/login"), Page(listing={"status": 401})):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def test_the_bill_with_that_id_and_date_is_fetched(self):
        page = Page()
        self.assertTrue(site.download_bill(page, None, "2026-09-13", self.out,
                                           href=site.DOWNLOAD_PATH, document_id="50000002"))
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual(page.asked[-1][0], site.invoice_url("50000002"))

    def test_a_record_that_does_not_match_is_not_fetched(self):
        for inv, day, href in (("50000002", "2026-08-13", site.DOWNLOAD_PATH), ("50000099", "2026-09-13", site.DOWNLOAD_PATH),
                               ("50000002", "2026-09-13", "/other")):
            page = Page()
            self.assertFalse(site.download_bill(page, None, day, self.out, href=href, document_id=inv))
            self.assertFalse(any("billinginvoice" in str(a[0]) for a in page.asked))
            self.assertFalse(self.out.exists())

    def test_refused_and_sign_in_answers_raise_and_save_nothing(self):
        for page in (Page(pdf_status=401), Page(pdf=b"<html>sign in</html>")):
            with self.assertRaises(site.SessionExpired):
                site.download_bill(page, None, "2026-09-13", self.out, href=site.DOWNLOAD_PATH, document_id="50000002")
            self.assertFalse(self.out.exists())


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def test_persisted_record_is_keyed_by_the_invoice(self):
        app = make_app(tempfile.mkdtemp(), "--discover")
        for r in site.bills_of(answer(ROWS)):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        rec = app.discovery.get("id:50000003")
        self.assertEqual((rec["href"], rec["document_id"]), (site.DOWNLOAD_PATH, "50000003"))


class Privacy(unittest.TestCase):
    def test_the_account_and_authorization_stay_out_of_logs_stdout_and_files(self):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(seen):
                for r in site.collect_download_docs(Page()):
                    app._record_rawdoc(r, site.BILLING_URL)
                app.discovery.save()
                app.check_session = lambda p: None
                app._delay = lambda *a, **k: None
                app._on_its_site = lambda: Page()
                app.process(app._select(limit=1))
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        written = "".join(p.read_text(errors="ignore") for p in app.paths.root.rglob("*")
                          if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"))
        for word in (FAKE_ACCOUNT, FAKE_TOKEN, "fake-token"):
            self.assertNotIn(word, seen.getvalue() + written)
        self.assertIn(FAKE_ACCOUNT, site.private_words())


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "ziply_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
