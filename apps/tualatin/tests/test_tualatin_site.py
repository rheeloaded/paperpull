"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import io
import json
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import tualatin_site as site  # noqa: E402
import tualatin_docs as docs  # noqa: E402

FAKE_ACCOUNT = "987654-321"
HEADS = ["Transaction Date", "Transaction Type", "Description", "Amount", "Balance"]
PRINTED = ("<html><body><h2>Bill Details</h2><p>Billing Date</p><p>Due Date</p>"
           "<p>Total Amount Due</p><script>alert(1)</script></body></html>")


def billing(day, number):
    return {"cells": [day, "Billing", "", "$10.00", "$10.00"], "bills": [f"/secure/MyBill/{number}"]}


def payment(day):
    return {"cells": [day, "Payment", "Online payment", "($10.00)", "$0.00"], "bills": []}


ROWS = [payment("10/05/2026"), billing("09/30/2026", "10000003"), payment("09/05/2026"),
        billing("08/31/2026", "10000002"), billing("07/31/2026", "10000001")]


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n


class Page:
    def __init__(self, rows=ROWS, settled=None, table=True, printed=PRINTED, print_status=200,
                 print_type="text/html; charset=utf-8"):
        self.rows, self.table = rows, table
        self.settled = settled or site.DOCUMENTS_URL
        self.url = "about:blank"
        self.printed, self.print_status, self.print_type = printed, print_status, print_type
        self.asked = []

    def goto(self, url, **k):
        self.url = self.settled

    def wait_for_selector(self, *a, **k):
        if not self.table:
            raise TimeoutError("no table")

    def locator(self, sel):
        return Locator(1 if "password" in sel and "login" in self.settled.lower() else 0)

    def evaluate(self, js, arg=None):
        if arg is None:
            return {"table": self.table, "heads": HEADS, "rows": self.rows, "account": [FAKE_ACCOUNT]}
        self.asked.append(arg[0])
        return {"status": self.print_status, "type": self.print_type, "html": self.printed}


def drawn(page, html, out_path, base=None):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(b"%PDF-1.4 drawn " + b"x" * 2000)


class Hosts(unittest.TestCase):
    def test_only_the_portal_host_over_https(self):
        self.assertTrue(site.is_safe_url("https://tualatin.merchanttransact.com/secure/Activity"))
        for u in ("http://tualatin.merchanttransact.com/", "https://other.merchanttransact.com/",
                  "https://tualatin.merchanttransact.com.evil.test/", "https://tualatinoregon.gov/", "", None):
            self.assertFalse(site.is_safe_url(u), u)

    def test_a_bill_is_its_print_page_only(self):
        self.assertTrue(site.is_download_url(site.print_url("10000003")))
        for u in (site.BASE + "/secure/MyBill/10000003", site.BASE + "/secure/MyBill/abc/Print",
                  site.print_url("10000003") + "?x=1", site.BASE + "/api/agency/bill-attachments/x.pdf"):
            self.assertFalse(site.is_download_url(u), u)
        self.assertEqual(site.print_url("../../x"), "")


class Controls(unittest.TestCase):
    def test_the_bill_links_are_documents(self):
        for name in ("Billing", "Print My Bill"):
            self.assertTrue(site.is_safe_control(name), name)

    def test_everything_else_is_refused(self):
        for name in ("Pay Now", "Make a Payment", "AutoPay", "My Wallet", "Excel", "CSV", "Go Paperless",
                     "Edit profile", "Update payment method", "Sign Out", "", "   "):
            self.assertFalse(site.is_safe_control(name), name)

    def test_credit_is_not_edit(self):
        self.assertIsNone(site.FORBIDDEN_CONTROL_RE.search("Credit Statement"))
        self.assertIsNotNone(site.FORBIDDEN_CONTROL_RE.search("Edit profile"))


class Rows(unittest.TestCase):
    def test_billing_rows_only_dated_and_known_by_number(self):
        got = site.bills_of(HEADS, ROWS)
        self.assertEqual([d.date_text for d in got], ["2026-09-30", "2026-08-31", "2026-07-31"])
        self.assertEqual([d.document_id for d in got], ["10000003", "10000002", "10000001"])
        self.assertEqual(got[0].href, "/secure/MyBill/10000003")

    def test_unreadable_rows_stop_the_list_with_what_was_read(self):
        for broken in ({"cells": ["06/30/2026", "Billing", "", "$1", "$1"], "bills": []},
                       {"cells": ["06/30/2026", "Billing", "", "$1", "$1"], "bills": ["/secure/MyBill/1/2"]},
                       {"cells": ["02/30/2026", "Billing", "", "$1", "$1"], "bills": ["/secure/MyBill/10000009"]},
                       billing("06/30/2026", "10000003")):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(HEADS, ROWS + [broken])
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_a_header_without_its_columns_stops(self):
        for heads in (["Date", "Type"], ["Transaction Date", "Transaction Date", "Transaction Type"], []):
            with self.assertRaises(site.ListStopped):
                site.bills_of(heads, ROWS)

    def test_rules_classify(self):
        self.assertIsInstance(json.loads((HERE / "document_rules.json").read_text()), dict)


class ListReady(unittest.TestCase):
    def test_activity_is_read(self):
        self.assertEqual(len(site.collect_download_docs(Page())), 3)
        self.assertIn(FAKE_ACCOUNT, site.private_words())

    def test_a_signed_out_or_moved_portal_is_session_expired(self):
        for page in (Page(settled="https://tualatin.merchanttransact.com/LoginRedirect.aspx"),
                     Page(settled="https://tualatin.merchanttransact.com/secure/MyBill")):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)

    def test_a_table_that_never_draws_stops(self):
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(table=False))

    def test_bill_list_opens(self):
        self.assertTrue(site.bill_list_opens(Page()))
        self.assertFalse(site.bill_list_opens(Page(table=False)))


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def save(self, page, number="10000002", date="2026-08-31", href=None):
        with mock.patch("paperpull_core.receipt_pdf.print_html_inert_to_pdf", side_effect=drawn) as draw:
            ok = site.download_bill(page, None, date, self.out, href=href or f"/secure/MyBill/{number}",
                                    document_id=number)
        return ok, draw

    def test_the_print_page_of_that_bill_is_drawn_inert(self):
        page = Page()
        ok, draw = self.save(page)
        self.assertTrue(ok)
        self.assertEqual(page.asked, [site.print_url("10000002")])
        self.assertEqual(draw.call_args.kwargs.get("base"), site.BASE + "/")
        self.assertEqual(self.out.read_bytes()[:5], b"%PDF-")

    def test_a_record_that_does_not_match_is_not_fetched(self):
        for number, date, href in (("10000002", "2026-07-31", None), ("10000099", "2026-08-31", None),
                                   ("10000002", "2026-08-31", "/other"), ("12/34", "2026-08-31", None)):
            page = Page()
            ok, draw = self.save(page, number, date, href)
            self.assertFalse(ok)
            self.assertEqual(page.asked, [])
            draw.assert_not_called()

    def test_a_page_that_is_not_a_bill_is_not_drawn(self):
        for page in (Page(printed="<html><body>Something else</body></html>"), Page(print_status=500),
                     Page(print_type="application/json")):
            ok, draw = self.save(page)
            self.assertFalse(ok)
            draw.assert_not_called()
            self.assertFalse(self.out.exists())

    def test_refused_and_sign_in_answers_raise(self):
        for page in (Page(print_status=401), Page(printed="<form><input type='password'></form>")):
            with self.assertRaises(site.SessionExpired):
                self.save(page)


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_persisted_record_is_keyed_by_the_bill_number(self):
        app = make_app(self.tmp, "--discover")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        rec = app.discovery.get("id:10000003")
        self.assertEqual((rec["href"], rec["document_id"]), ("/secure/MyBill/10000003", "10000003"))
        self.assertNotIn(FAKE_ACCOUNT, app.paths.discovery_json.read_text())

    def test_an_expired_session_stops_the_run_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def expired(*a, **k):
            raise site.SessionExpired("signed out")
        original = site.download_bill
        site.download_bill = expired
        try:
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                app.process(app._select())
        finally:
            site.download_bill = original
        self.assertIn("signed out", said.getvalue())
        self.assertEqual(app.progress.data, {})


class Privacy(unittest.TestCase):
    def test_the_account_stays_out_of_logs_stdout_and_files(self):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(seen), \
                    mock.patch("paperpull_core.receipt_pdf.print_html_inert_to_pdf", side_effect=drawn):
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
        self.assertNotIn(FAKE_ACCOUNT, seen.getvalue() + written)


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "tualatin_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
