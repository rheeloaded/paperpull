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
import nwnatural_site as site  # noqa: E402
import nwnatural_docs as docs  # noqa: E402

PORTAL = "https://ipn2.paymentus.com/cp"
FAKE_ACCOUNT = "9876543-2"
TOKEN = "0000000000000-abc000"
PDF = b"%PDF-1.4 " + b"x" * 3000
HEADS = ["Account", "Due Amount", "Due Date", "Action"]


def view(n):
    return (f"{PORTAL}/view-external-bill.action?&CSRF_TOKEN={TOKEN}&accountId=1&accthid=x"
            f"&accountNumber={FAKE_ACCOUNT}&docRef=000000000{n}/00000&hashedDocRef=h{n}&target=_blank")


def row(due, n):
    return {"cells": [FAKE_ACCOUNT, "$10.00", due, "View"], "views": [view(n)]}


ROWS = [row("Oct 21, 2026", 1), row("Sep 22, 2026", 2), row("Aug 21, 2026", 3)]
HISTORY_LINK = f"{PORTAL}/bills.action?CSRF_TOKEN={TOKEN}&dateFrom.day=1&dateFrom.month=8&dateFrom.year=2026"


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n


class Page:
    """The signed-in portal tab: its Bill History link is read off the page,
    and the history and each bill are fetched through evaluate."""

    def __init__(self, rows=ROWS, url=PORTAL + "/home.action", link=HISTORY_LINK, listing=None,
                 pdf=PDF, pdf_status=200):
        self.url, self.link, self.rows = url, link, rows
        self.listing = listing
        self.pdf, self.pdf_status = pdf, pdf_status
        self.asked = []
        self.moved = []

    def goto(self, *a, **k):
        self.moved.append(a)

    def locator(self, sel):
        return Locator(1 if "password" in sel and "login" in self.url else 0)

    def evaluate(self, js, arg=None):
        if arg is None:
            return self.link
        url = arg[0]
        self.asked.append(url)
        if "bills.action" in url:
            return self.listing or {"status": 200, "table": True, "heads": HEADS, "rows": self.rows}
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "text/html"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}


class Hosts(unittest.TestCase):
    def test_only_the_portal_host_and_nwnatural_over_https(self):
        for u in ("https://ipn2.paymentus.com/cp/bills.action", "https://www.nwnatural.com/"):
            self.assertTrue(site.is_safe_url(u), u)
        for u in ("http://ipn2.paymentus.com/cp/", "https://ipn3.paymentus.com/cp/", "https://paymentus.com/",
                  "https://evil.nwnatural.com/", "https://www.nwnatural.com.evil.test/", "", None):
            self.assertFalse(site.is_safe_url(u), u)

    def test_a_bill_is_one_address_shape(self):
        self.assertTrue(site.is_download_url(view(1)))
        bad = [view(1).replace("view-external-bill", "make-payment"), view(1).replace("CSRF_TOKEN", "X"),
               view(1).replace("&hashedDocRef=h1", ""), view(1).replace("ipn2", "ipn3"), view(1) + "#a"]
        for u in bad:
            self.assertFalse(site.is_download_url(u), u)

    def test_the_history_address_keeps_its_token_and_starts_early(self):
        url = site.history_url(Page())
        self.assertTrue(site.is_history_url(url))
        self.assertIn("dateFrom.year=2000", url)
        self.assertIn(TOKEN, url)
        self.assertEqual(site.history_url(Page(link="")), "")
        self.assertEqual(site.history_url(Page(link=HISTORY_LINK.replace("ipn2", "ipn3"))), "")


class Controls(unittest.TestCase):
    def test_the_bill_link_is_a_document(self):
        for name in ("View", "View Bill", "Download Bill PDF"):
            self.assertTrue(site.is_safe_control(name), name)

    def test_everything_else_is_refused(self):
        for name in ("Pay My Bill", "Make a Payment", "AutoPay", "Equal Pay", "Online Pay History",
                     "Start, Stop or Move Service", "Go Paperless", "Edit profile", "Update payment method",
                     "Sign Out", "", "   "):
            self.assertFalse(site.is_safe_control(name), name)

    def test_credit_is_not_edit(self):
        self.assertIsNone(site.FORBIDDEN_CONTROL_RE.search("Credit Statement"))
        self.assertIsNotNone(site.FORBIDDEN_CONTROL_RE.search("Edit profile"))


class Rows(unittest.TestCase):
    def test_bills_are_dated_by_their_due_date_and_keyed_by_it(self):
        got = site.bills_of(HEADS, ROWS)
        self.assertEqual([d.date_text for d in got], ["2026-10-21", "2026-09-22", "2026-08-21"])
        self.assertEqual([d.document_id for d in got], ["bill-2026-10-21", "bill-2026-09-22", "bill-2026-08-21"])
        self.assertEqual({d.href for d in got}, {site.DOWNLOAD_PATH})
        self.assertEqual(got[1].bill_ref, view(2))

    def test_unreadable_rows_stop_the_list_with_what_was_read(self):
        for broken in ({"cells": [FAKE_ACCOUNT, "$1", "Feb 30, 2026", "View"], "views": [view(9)]},
                       {"cells": [FAKE_ACCOUNT, "$1", "Jul 1, 2026", ""], "views": []},
                       {"cells": [FAKE_ACCOUNT, "$1", "Jul 1, 2026", "View"], "views": [view(8), view(9)]},
                       {"cells": [FAKE_ACCOUNT, "$1", "Jul 1, 2026", "View"],
                        "views": [view(9).replace("view-external-bill", "make-payment")]},
                       row("Oct 21, 2026", 7)):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(HEADS, ROWS + [broken])
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_a_header_with_no_single_due_date_stops(self):
        for heads in (["Account", "Amount", "Date"], ["Due Date", "Due Date"], []):
            with self.assertRaises(site.ListStopped):
                site.bills_of(heads, ROWS)

    def test_rules_classify(self):
        self.assertIsInstance(json.loads((HERE / "document_rules.json").read_text()), dict)


class ListWhole(unittest.TestCase):
    def test_the_history_is_read_from_the_tab_without_moving_it(self):
        page = Page()
        self.assertEqual(len(site.collect_download_docs(page)), 3)
        self.assertEqual(page.moved, [], "the tab is never sent anywhere")
        self.assertTrue(all("dateFrom.year=2000" in u for u in page.asked))

    def test_a_tab_off_the_portal_or_without_its_link_stops(self):
        for page in (Page(url="https://www.nwnatural.com/account"), Page(link="")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)
            self.assertEqual(page.asked, [])

    def test_a_signed_out_portal_is_session_expired(self):
        for listing in ({"status": 302, "redirected": True}, {"status": 200, "table": False},
                        {"status": 200, "table": True, "password": True, "heads": HEADS, "rows": []},
                        {"status": 401}):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(Page(listing=listing))

    def test_goto_documents_and_bill_list_opens(self):
        self.assertTrue(site.goto_documents(Page()))
        self.assertFalse(site.goto_documents(Page(url="https://www.nwnatural.com/")))
        self.assertTrue(site.bill_list_opens(Page()))
        self.assertFalse(site.bill_list_opens(Page(link="")))


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def test_the_bill_of_that_day_is_fetched_by_its_view_address(self):
        page = Page()
        self.assertTrue(site.download_bill(page, None, "2026-09-22", self.out,
                                           href=site.DOWNLOAD_PATH, document_id="bill-2026-09-22"))
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual(page.asked[-1], view(2))

    def test_a_record_that_does_not_match_is_not_fetched(self):
        page = Page()
        for date, doc_id, href in (("2026-09-22", "bill-2026-08-21", site.DOWNLOAD_PATH),
                                   ("2026-01-31", "bill-2026-01-31", site.DOWNLOAD_PATH),
                                   ("2026-09-22", "bill-2026-09-22", "/other")):
            self.assertFalse(site.download_bill(page, None, date, self.out, href=href, document_id=doc_id))
        self.assertFalse(any("view-external-bill" in u for u in page.asked))
        self.assertFalse(self.out.exists())

    def test_refused_and_sign_in_answers_raise_and_save_nothing(self):
        for page in (Page(pdf_status=401), Page(pdf=b"<html><form>sign in</form></html>")):
            with self.assertRaises(site.SessionExpired):
                site.download_bill(page, None, "2026-09-22", self.out,
                                   href=site.DOWNLOAD_PATH, document_id="bill-2026-09-22")
            self.assertFalse(self.out.exists())

    def test_other_non_pdfs_are_refused_without_a_file(self):
        for page in (Page(pdf=b"GIF89a"), Page(pdf_status=500)):
            self.assertFalse(site.download_bill(page, None, "2026-09-22", self.out,
                                                href=site.DOWNLOAD_PATH, document_id="bill-2026-09-22"))
            self.assertFalse(self.out.exists())


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_persisted_record_holds_no_view_address_and_is_keyed_by_the_day(self):
        app = make_app(self.tmp, "--discover")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        text = app.paths.discovery_json.read_text()
        for word in (TOKEN, "hashedDocRef", "docRef", FAKE_ACCOUNT):
            self.assertNotIn(word, text)
        rec = app.discovery.get("id:bill-2026-10-21")
        self.assertEqual((rec["href"], rec["document_id"]), (site.DOWNLOAD_PATH, "bill-2026-10-21"))

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

    def test_pilot_gate(self):
        from paperpull_core.models import State

        class D:
            def __init__(self, k):
                self.key = k
        done = {"a": {"state": State.COMPLETED.value}}
        self.assertFalse(docs.pilot_failed(done, [D("a")]))
        self.assertTrue(docs.pilot_failed({}, [D("a")]))


class Privacy(unittest.TestCase):
    def test_the_account_and_the_token_stay_out_of_logs_stdout_and_files(self):
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
        for word in (FAKE_ACCOUNT, TOKEN, "hashedDocRef"):
            self.assertNotIn(word, seen.getvalue() + written)
        self.assertIn(FAKE_ACCOUNT, site.private_words())
        self.assertEqual(len(list(app.paths.root.rglob("*.pdf"))), 1)


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "nwnatural_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially", "goto"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
