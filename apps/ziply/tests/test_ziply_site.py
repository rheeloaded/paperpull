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
from paperpull_core import testkit  # noqa: E402
from paperpull_core.run_reporting import ListNotRead  # noqa: E402

FAKE_ACCOUNT = "98765432100001234"
OTHER_ACCOUNT = "98765432100005678"
FAKE_TOKEN = "Bearer fake-token-not-real-0000"
PDF = b"%PDF-1.4 " + b"x" * 3000


def stmt(day, inv, status="CLOSED"):
    return {"status": status, "date": day, "amount_due": "10", "id": inv,
            "url": f"https://ziplyfiber.com/api/myacc/billinginvoice?invoiceId={inv}", "__typename": "BillStatement"}


ROWS = [stmt("2026-10-13", "50000003", "OPEN"), stmt("2026-09-13", "50000002"), stmt("2026-08-13", "50000001")]


def answer(rows, error=False, status=200, message=None):
    return {"data": {"billStatements": {"error": error, "APIStatus": status, "message": message,
                                        "billStatements": rows, "__typename": "BillStatementsResponse"}}}


class Req:
    def __init__(self, op="billingDetails", headers=None, account=FAKE_ACCOUNT):
        self.method = "POST"
        self.url = site.API_URL
        self.post_data = json.dumps({"operationName": op, "variables": {"accountNumber": account}, "query": "query x { y }"})
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
    def __init__(self, rows=ROWS, settled=None, asks=True, headers=None, listing=None, pdf=PDF, pdf_status=200,
                 accounts=(FAKE_ACCOUNT,), pdf_answer=None):
        self.rows, self.asks, self.headers, self.listing = rows, asks, headers, listing
        self.settled = settled or site.DOCUMENTS_URL
        self.url = "about:blank"
        self.pdf, self.pdf_status, self.pdf_answer = pdf, pdf_status, pdf_answer
        self.accounts = accounts
        self.handlers, self.asked = [], []
        self.loads = 0

    def on(self, event, h):
        self.handlers.append(h)

    def remove_listener(self, event, h):
        self.handlers.remove(h)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.loads += 1
        self.url = self.settled
        if self.asks:
            for h in list(self.handlers):
                for account in self.accounts:
                    h(Req(headers=self.headers, account=account))

    def locator(self, sel):
        return Locator(1 if "password" in sel and "login" in self.settled.lower() else 0)

    def evaluate(self, js, arg=None):
        self.asked.append(arg)
        if arg[0] == site.API_URL:
            return self.listing or {"status": 200, "data": answer(self.rows)}
        if self.pdf_answer is not None:
            return dict(self.pdf_answer)
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "text/html"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}

    def lists_asked(self):
        return sum(1 for a in self.asked if a[0] == site.API_URL)

    def bills_asked(self):
        return [a[0] for a in self.asked if a[0] != site.API_URL]


# What one bill's PDF can be answered with that read as a sign-out, a 401, a
# 403, a redirect, and a page where the PDF should be.
REFUSALS = {
    "401": {"pdf_status": 401},
    "403": {"pdf_status": 403},
    "redirect": {"pdf_answer": {"status": 0, "redirected": True}},
    "page": {"pdf": b"<!doctype html><title>Sign in</title><p>made-up page words 4417</p>"},
}


class SignsOutAtTheBill(Page):
    """A session that ends as the bill is asked for. The bill is refused
    and so is the list read after it, by the sign-in page or by the API."""

    def __init__(self, how="sign-in page", **kw):
        super().__init__(**kw)
        self.how = how

    def evaluate(self, js, arg=None):
        got = super().evaluate(js, arg)
        if arg[0] != site.API_URL:
            if self.how == "sign-in page":
                self.settled, self.asks = "https://ziplyfiber.com/login", False
            else:
                self.listing = {"status": 401}
        return got


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
        for name in ("VIEW PDF", "View Bill", "View Internet Bill"):
            self.assertTrue(site.is_safe_control(name), name)

    def test_everything_else_is_refused(self):
        for name in ("MAKE A PAYMENT", "MANAGE AUTOPAY", "TURN OFF", "Upgrade", "Return equipment",
                     "Edit profile", "Update payment method", "Log out", "View Utility Bill", "", "   "):
            self.assertFalse(site.is_safe_control(name), name)

    def test_credit_is_not_edit(self):
        self.assertIsNone(site.FORBIDDEN_CONTROL_RE.search("Credit Statement"))
        self.assertIsNotNone(site.FORBIDDEN_CONTROL_RE.search("Edit profile"))


class Rows(unittest.TestCase):
    def test_statements_are_known_by_account_and_invoice_and_dated(self):
        got = site.bills_of(answer(ROWS), FAKE_ACCOUNT)
        self.assertEqual([d.date_text for d in got], ["2026-10-13", "2026-09-13", "2026-08-13"])
        self.assertEqual([d.document_id for d in got],
                         ["bill-1234-50000003", "bill-1234-50000002", "bill-1234-50000001"])
        self.assertEqual({d.account for d in got}, {"XXXX-1234"})

    def test_unreadable_statements_stop_the_list_with_what_was_read(self):
        for broken in (stmt("2026-07-13", "x1"), dict(stmt("2026-07-13", "50000009"), url="https://evil.test/x.pdf"),
                       stmt("2026-02-30", "50000009"), stmt("2026-07-13", "50000003")):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(answer(ROWS + [broken]), FAKE_ACCOUNT)
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_a_list_as_long_as_asked_for_or_an_error_stops(self):
        many = [stmt("2020-01-01", str(60000000 + i)) for i in range(site.BILLS_ASKED)]
        many = [dict(r, date=f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-13") for i, r in enumerate(many)]
        for a in (answer(many), answer(ROWS, error=True), {"data": {}}, []):
            with self.assertRaises(site.ListStopped):
                site.bills_of(a, FAKE_ACCOUNT)
        with self.assertRaises(site.SessionExpired):
            site.bills_of({"errors": [{"message": "Unauthorized"}]}, FAKE_ACCOUNT)

    def test_an_empty_or_failed_list_is_never_whole(self):
        """A list with no bills, or one the API marks as failed in its own
        block, was read as a whole history with nothing in it."""
        for a in (answer([]), answer([], status=500), answer(ROWS, status=500), answer(ROWS, status="ERR"),
                  answer(ROWS, message="Account is being migrated"), answer([], error=True, status=200)):
            with self.assertRaises(site.ListStopped, msg=a):
                site.bills_of(a, FAKE_ACCOUNT)
        for said in (None, "", "Success", "OK"):
            self.assertEqual(len(site.bills_of(answer(ROWS, message=said), FAKE_ACCOUNT)), 3, said)

    def test_a_block_that_says_the_session_ended_is_signed_out(self):
        for a in (answer([], error=True, status=401, message="Token expired"),
                  answer([], status=403),
                  answer([], error=True, status=500, message="Invalid token"),
                  {"errors": [{"message": "Invalid token"}]}):
            with self.assertRaises(site.SessionExpired, msg=a):
                site.bills_of(a, FAKE_ACCOUNT)

    def test_rules_classify(self):
        self.assertIsInstance(json.loads((HERE / "document_rules.json").read_text()), dict)


class ListWhole(unittest.TestCase):
    def setUp(self):
        site._RUN.clear()

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

    def test_a_page_that_asks_about_two_accounts_stops_and_lists_nothing(self):
        """Only the first account the page asked about was read, and the
        list was called whole."""
        page = Page(accounts=(FAKE_ACCOUNT, OTHER_ACCOUNT))
        with self.assertRaises(site.SeveralAccounts) as stop:
            site.collect_download_docs(page)
        self.assertEqual((stop.exception.count, stop.exception.docs), (2, []))
        self.assertEqual(page.lists_asked(), 0)
        self.assertIn(OTHER_ACCOUNT, site.private_words())
        # The same account asked about twice is one account.
        self.assertEqual(len(site.collect_download_docs(Page(accounts=(FAKE_ACCOUNT, FAKE_ACCOUNT)))), 3)

    def test_a_signed_out_site_or_a_refused_list_is_session_expired(self):
        for page in (Page(asks=False, settled="https://ziplyfiber.com/login"), Page(listing={"status": 401})):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)

    def test_a_list_the_page_could_not_ask_stops_rather_than_raise_its_own_error(self):
        class Gone(Page):
            def evaluate(self, js, arg=None):
                raise RuntimeError("Execution context was destroyed")
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Gone())
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(Gone(settled="https://ziplyfiber.com/login", asks=False))


class Download(unittest.TestCase):
    def setUp(self):
        site._RUN.clear()
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def test_the_bill_with_that_id_and_date_is_fetched(self):
        page = Page()
        self.assertTrue(site.download_bill(page, None, "2026-09-13", self.out,
                                           href=site.DOWNLOAD_PATH, document_id="bill-1234-50000002"))
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual(page.asked[-1][0], site.invoice_url("50000002"))

    def test_the_list_this_run_read_is_used_for_each_bill(self):
        """Each bill opened Billing and asked the whole list again."""
        page = Page()
        site.collect_download_docs(page)
        for inv, day in (("50000003", "2026-10-13"), ("50000002", "2026-09-13")):
            self.assertTrue(site.download_bill(page, None, day, self.out, href=site.DOWNLOAD_PATH,
                                               document_id=f"bill-1234-{inv}"))
        self.assertEqual((page.loads, page.lists_asked()), (1, 1))
        # A bill the kept list does not hold reads it once more.
        self.assertFalse(site.download_bill(page, None, "2026-07-13", self.out, href=site.DOWNLOAD_PATH,
                                            document_id="bill-1234-50000000"))
        self.assertEqual((page.loads, page.lists_asked()), (2, 2))

    def test_a_record_that_does_not_match_is_not_fetched(self):
        for doc_id, day, href in (("bill-1234-50000002", "2026-08-13", site.DOWNLOAD_PATH),
                                  ("bill-1234-50000099", "2026-09-13", site.DOWNLOAD_PATH),
                                  ("bill-1234-50000002", "2026-09-13", "/other"),
                                  ("50000002", "2026-09-13", site.DOWNLOAD_PATH)):
            page = Page()
            site._RUN.clear()
            self.assertFalse(site.download_bill(page, None, day, self.out, href=href, document_id=doc_id))
            self.assertFalse(any("billinginvoice" in str(a[0]) for a in page.asked))
            self.assertFalse(self.out.exists())

    def test_a_bill_of_another_account_stops_the_run_once(self):
        """With the page on another account every recorded bill went to
        Manual Review, one after another."""
        page = Page(accounts=(OTHER_ACCOUNT,))
        with self.assertRaises(site.OtherAccountShown) as shown:
            site.download_bill(page, None, "2026-09-13", self.out, href=site.DOWNLOAD_PATH,
                               document_id="bill-1234-50000002")
        self.assertEqual((shown.exception.wanted, shown.exception.shown), ("1234", "5678"))
        self.assertFalse(any("billinginvoice" in str(a[0]) for a in page.asked))

    def test_a_list_that_stops_while_bills_download_reaches_the_run(self):
        for page in (Page(rows=[]), Page(listing={"status": 200, "data": answer(ROWS, status=500)}),
                     Page(accounts=(FAKE_ACCOUNT, OTHER_ACCOUNT))):
            site._RUN.clear()
            with self.assertRaises(site.ListStopped):
                site.download_bill(page, None, "2026-09-13", self.out, href=site.DOWNLOAD_PATH,
                                   document_id="bill-1234-50000002")
            self.assertFalse(self.out.exists())

    def _take(self, page, inv="50000002", day="2026-09-13", trace=None):
        return site.download_bill(page, None, day, self.out, href=site.DOWNLOAD_PATH,
                                  document_id=f"bill-1234-{inv}", trace=trace)

    def test_a_bill_refused_while_the_list_still_reads_fails_alone(self):
        """A 401, a 403, a redirect or a page for one bill was read as a
        sign-out, so every run stopped at that bill and Continue stopped
        there again (#124). The list is read again with the call that proves
        a session, and a list that still reads leaves the refusal that
        bill's own."""
        for how, kw in REFUSALS.items():
            for kept in (False, True):
                site._RUN.clear()
                page = Page(**kw)
                if kept:
                    site.collect_download_docs(page)
                trace = []
                self.assertFalse(self._take(page, trace=trace), (how, kept))
                self.assertFalse(self.out.exists(), (how, kept))
                # The list is read once more after the refusal, and the bill
                # is asked for once, never a second time.
                self.assertEqual((page.loads, page.lists_asked()), (2, 2), (how, kept))
                self.assertEqual(page.bills_asked(), [site.invoice_url("50000002")], (how, kept))
                self.assertIn({"note": "refused, the list still reads"}, trace, (how, kept))
                self.assertNotIn("made-up page words", json.dumps(trace))

    def test_the_list_read_after_a_refusal_serves_the_next_bill(self):
        page = Page(pdf_status=403)
        site.collect_download_docs(page)
        self.assertFalse(self._take(page))
        page.pdf_status = 200
        self.assertTrue(self._take(page, inv="50000001", day="2026-08-13"))
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual((page.loads, page.lists_asked()), (2, 2))

    def test_a_bill_refused_and_a_list_refused_after_it_is_a_sign_out(self):
        """A session that ended refuses the list too, and only that stops
        the run as signed out."""
        for how in ("sign-in page", "401"):
            for kept in (False, True):
                site._RUN.clear()
                page = SignsOutAtTheBill(how, pdf_status=401)
                if kept:
                    site.collect_download_docs(page)
                with self.assertRaises(site.SessionExpired, msg=(how, kept)):
                    self._take(page)
                self.assertFalse(self.out.exists())
                self.assertEqual(len(page.bills_asked()), 1, (how, kept))

    def test_a_list_read_after_a_refusal_that_stops_or_shows_another_account_reaches_the_run(self):
        page = Page(pdf_status=403)
        site.collect_download_docs(page)
        page.rows = []
        with self.assertRaises(site.ListStopped):
            self._take(page)
        site._RUN.clear()
        page = Page(pdf_status=403)
        site.collect_download_docs(page)
        page.accounts = (OTHER_ACCOUNT,)
        with self.assertRaises(site.OtherAccountShown) as shown:
            self._take(page)
        self.assertEqual((shown.exception.wanted, shown.exception.shown), ("1234", "5678"))
        self.assertFalse(self.out.exists())
        self.assertEqual(len(page.bills_asked()), 1)

    def test_a_json_answer_fails_that_bill_alone(self):
        """A JSON error for one bill was read as a sign-out, which stopped
        every run at that bill."""
        for body in (b'{"error": true, "message": "Invoice not available"}', b"[]"):
            site._RUN.clear()
            self.assertFalse(site.download_bill(Page(pdf=body), None, "2026-09-13", self.out,
                                                href=site.DOWNLOAD_PATH, document_id="bill-1234-50000002"))
            self.assertFalse(self.out.exists())


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def setUp(self):
        site._RUN.clear()

    def test_persisted_record_is_keyed_by_the_account_and_invoice_and_named_for_the_account(self):
        app = make_app(tempfile.mkdtemp(), "--discover")
        for r in site.bills_of(answer(ROWS), FAKE_ACCOUNT):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        rec = app.discovery.get("id:XXXX-1234:bill-1234-50000003")
        self.assertEqual((rec["href"], rec["document_id"], rec["summary"], rec["account"]),
                         (site.DOWNLOAD_PATH, "bill-1234-50000003", "Internet Bill XXXX-1234", "XXXX-1234"))
        self.assertEqual(docs.told_apart_by(rec), "50000003")

    def _listed_then(self, page):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--resume")
        for r in site.bills_of(answer(ROWS), FAKE_ACCOUNT):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        app.check_session = lambda p: None
        app._on_its_site = lambda: page
        return app

    def test_a_list_that_stops_while_bills_download_stops_the_run_once_unread(self):
        page = Page(rows=[])
        app = self._listed_then(page)
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(ListNotRead):
            app.process(app._select())
        self.assertEqual(page.loads, 1)
        self.assertNotIn("Nothing was saved", out.getvalue())
        self.assertEqual(app.progress.data, {})

    def _run_with(self, page):
        """A Run All's downloads over the three listed bills, with what it
        printed and logged."""
        app = self._listed_then(page)
        app._delay = lambda *a, **k: None
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        ended = None
        try:
            with redirect_stdout(seen):
                app.process(app._select())
        except SystemExit as e:
            ended = e
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        return app, ended, seen.getvalue()

    def test_one_bill_refused_while_the_list_reads_fails_alone_and_the_rest_are_saved(self):
        """The refused bill stopped the run before, so the bills after it
        were never asked for, and every later run stopped at it again."""
        class RefusesOne(Page):
            def evaluate(self, js, arg=None):
                if arg[0] == site.invoice_url("50000002"):
                    self.asked.append(arg)
                    return {"status": 200, "type": "text/html",
                            "b64": base64.b64encode(REFUSALS["page"]["pdf"]).decode()}
                return super().evaluate(js, arg)
        page = RefusesOne(pdf=testkit.text_pdf(["Ziply Fiber made-up bill"]))
        app, ended, said = self._run_with(page)
        self.assertIsNone(ended, said)
        states = {k: v["state"] for k, v in app.progress.data.items()}
        self.assertEqual(states, {"id:XXXX-1234:bill-1234-50000003": "Completed",
                                  "id:XXXX-1234:bill-1234-50000002": "Failed",
                                  "id:XXXX-1234:bill-1234-50000001": "Completed"})
        self.assertEqual((app.stats["failed"], len(app.stats["new_files"])), (1, 2))
        self.assertEqual(said.count("Nothing was saved, and the next run tries it again"), 1)
        self.assertNotIn("signed out", said)
        self.assertEqual(page.bills_asked().count(site.invoice_url("50000002")), 1)
        written = "".join(p.read_text(errors="ignore") for p in app.paths.root.rglob("*")
                          if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"))
        self.assertIn("refused, the list still reads", written)
        for word in ("made-up page words", "4417", FAKE_ACCOUNT, FAKE_TOKEN):
            self.assertNotIn(word, said + written)

    def test_one_bill_refused_and_the_list_after_it_stop_the_run_as_signed_out(self):
        page = SignsOutAtTheBill(pdf_status=403)
        app, ended, said = self._run_with(page)
        self.assertIsInstance(ended, SystemExit)
        self.assertNotIsInstance(ended, ListNotRead)
        self.assertIn("answered as signed out", " ".join(said.split()))
        self.assertNotIn("Nothing was saved", said)
        self.assertEqual(app.progress.data, {})
        self.assertEqual(len(page.bills_asked()), 1)

    def test_a_page_on_another_account_stops_the_run_once_and_names_it(self):
        page = Page(accounts=(OTHER_ACCOUNT,))
        app = self._listed_then(page)
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ended:
            app.process(app._select())
        self.assertNotIsInstance(ended.exception, ListNotRead)
        said = " ".join(out.getvalue().split())
        self.assertIn("the account ending 5678", said)
        self.assertIn("Choose the account ending 1234", said)
        self.assertEqual(page.loads, 1)
        self.assertEqual(app.progress.data, {})


class Privacy(unittest.TestCase):
    def test_the_account_and_authorization_stay_out_of_logs_stdout_and_files(self):
        site._RUN.clear()
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
