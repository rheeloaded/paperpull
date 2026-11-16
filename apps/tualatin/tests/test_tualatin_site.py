"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import io
import json
import logging
import re
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import tualatin_site as site  # noqa: E402
import tualatin_docs as docs  # noqa: E402
from paperpull_core import testkit  # noqa: E402

FAKE_ACCOUNT = "987654-321"
HEADS = ["Transaction Date", "Transaction Type", "Description", "Amount", "Balance"]
PRINTED = ("<html><body><h2>Bill Details</h2><p>Billing Date</p><p>8/31/2026</p><p>Due Date</p>"
           "<p>Total Amount Due</p><script>alert(1)</script></body></html>")
# What the print script reads off that page before anything is written in.
SAID = "Bill Details Billing Date 8/31/2026 Due Date Total Amount Due"


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
                 print_type="text/html; charset=utf-8", said=SAID, password=False, dropped=(),
                 extra=None, redirected=False):
        self.rows, self.table = rows, table
        # Whether a print page is answered with a redirect, and how many
        # times Activity was opened.
        self.redirected, self.opened = redirected, 0
        self.said, self.password, self.dropped = said, password, list(dropped)
        # More of what the Activity script returns: a pager, a count, a
        # date filter, a choice of accounts.
        self.extra = extra or {}
        self.settled = settled or site.DOCUMENTS_URL
        self.url = "about:blank"
        self.printed, self.print_status, self.print_type = printed, print_status, print_type
        self.asked = []

    def goto(self, url, **k):
        self.url = self.settled
        self.opened += 1

    def wait_for_timeout(self, ms):
        pass

    def wait_for_function(self, js, **k):
        assert js == site._TABLE_DRAWN_JS
        if not self.table:
            raise TimeoutError("no table")

    def locator(self, sel):
        return Locator(1 if "password" in sel and "login" in self.settled.lower() else 0)

    def evaluate(self, js, arg=None):
        if arg is None:
            return dict({"table": self.table, "heads": HEADS, "rows": self.rows, "account": [FAKE_ACCOUNT]},
                        **self.extra)
        self.asked.append(arg[0])
        if self.redirected:
            return {"status": 0, "redirected": True}
        return {"status": self.print_status, "type": self.print_type, "html": self.printed,
                "said": self.said, "password": self.password, "dropped": self.dropped,
                "inlined": {"css": 1, "img": 0}}


# What one bill's print page can be answered with that reads as a sign-out,
# a 401, a 403, a redirect, and a page asking for a password.
REFUSALS = {"401": {"print_status": 401}, "403": {"print_status": 403},
            "redirect": {"redirected": True}, "password": {"password": True}}


class SignsOutAtTheBill(Page):
    """A session that ends as the bill is asked for. The bill is refused,
    and Activity opened again after it goes to the sign-in page."""

    def evaluate(self, js, arg=None):
        got = super().evaluate(js, arg)
        if arg is not None:
            self.settled = site.BASE + "/LoginRedirect.aspx"
        return got



class ListFailsAfterTheBill(Page):
    """A bill refused while the session still holds, after which Activity
    does not read. "500" draws the portal's error page with no table,
    "timeout" a table that times out as it is read, "malformed" an answer
    that is not the table's, "dead" a tab whose address can no longer be
    read, "empty" an Activity without a bill, and "network" an address that
    does not open, which leaves the tab on Chromium's own error page. None
    of them says the session ended. `refused` is the bill number refused,
    None for every bill asked."""

    dead = False

    def __init__(self, how, refused=None, **kw):
        self.how, self.refused, self.failing = how, refused, False
        super().__init__(**kw)

    @property
    def url(self):
        if self.dead:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._url

    @url.setter
    def url(self, value):
        self._url = value

    def goto(self, url, **k):
        if self.failing and self.how == "network":
            self.url = "chrome-error://chromewebdata/"
            self.opened += 1
            raise RuntimeError("net::ERR_CONNECTION_RESET at made-up-host 4417")
        super().goto(url, **k)

    def wait_for_function(self, js, **k):
        if self.failing and self.how == "500":
            raise TimeoutError("no table")
        super().wait_for_function(js, **k)

    def evaluate(self, js, arg=None):
        if arg is None and self.failing:
            if self.how == "timeout":
                raise TimeoutError("Timeout 30000ms exceeded")
            if self.how == "malformed" and js == site._ROWS_JS:
                return "<html>Service Unavailable</html>"
            if self.how == "empty":
                self.rows = [payment("10/05/2026")]
        if arg is None:
            return super().evaluate(js, arg)
        number = next(n for n in PRINTED_DAYS if arg[0] == site.print_url(n))
        if self.refused is None or number == self.refused:
            self.asked.append(arg[0])
            self.failing = True
            self.dead = self.how == "dead"
            return {"status": 403, "type": "text/html"}
        day = PRINTED_DAYS[number]
        self.asked.append(arg[0])
        return {"status": 200, "type": "text/html; charset=utf-8",
                "html": PRINTED.replace("8/31/2026", day), "said": SAID.replace("8/31/2026", day),
                "password": False, "dropped": [], "inlined": {"css": 1, "img": 0}}


# Each listed bill's Billing Date as its print page says it.
PRINTED_DAYS = {"10000003": "9/30/2026", "10000002": "8/31/2026", "10000001": "7/31/2026"}
UNREAD = ("500", "timeout", "malformed", "dead", "empty", "network")


def drawn(page, html, out_path, base=None):
    """The inert render, drawing the page's text as a real PDF."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    words = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    Path(out_path).write_bytes(testkit.text_pdf(textwrap.wrap(words, 80) or [""], min_bytes=2000))


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

    def test_a_row_of_a_type_it_does_not_know_stops_the_list_and_is_named(self):
        """Named through the app's words, so a name in it never prints."""
        for kind, named in (("Late Fee", "'Late Fee'"), ("Final Bill", "'aaaaa Bill'"),
                            ("Refund to Dana Smith", "'Refund to aaaa aaaaa'"), ("$9 <b>", "")):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(HEADS, ROWS + [{"cells": ["06/30/2026", kind, "", "$1", "$1"], "bills": []}])
            self.assertEqual(len(stop.exception.docs), 3, kind)
            self.assertIn("a type%s this app" % (" " + named if named else ""), str(stop.exception))

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

    def test_anything_saying_activity_is_not_whole_stops(self):
        for extra in ({"pager": True}, {"dated": True}, {"accounts": 2}, {"count": 6}, {"count": 4},
                      {"filtered": True}, {"tables": 2}):
            with self.assertRaises(site.ListStopped, msg=extra):
                site.collect_download_docs(Page(extra=extra))
        whole = {"pager": False, "dated": False, "accounts": 1, "count": 5, "filtered": False, "tables": 1}
        self.assertEqual(len(site.collect_download_docs(Page(extra=whole))), 3)

    def test_an_activity_with_no_bills_stops(self):
        for rows in ([], [payment("10/05/2026")]):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(Page(rows=rows))

    def test_what_diagnose_says_of_the_table(self):
        facts = site.table_facts(Page(extra={"dated": True, "accounts": 3}))
        self.assertEqual(facts, {"heads": HEADS, "rows": 5, "pager": False, "count": None,
                                 "date_filter": True, "account_choices": 3, "filtered": False,
                                 "tables": 0})

    def test_a_table_that_never_draws_stops(self):
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(table=False))

    def test_bill_list_opens(self):
        self.assertTrue(site.bill_list_opens(Page()))
        self.assertFalse(site.bill_list_opens(Page(table=False)))


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def save(self, page, number="10000002", date="2026-08-31", href=None, trace=None):
        with mock.patch("paperpull_core.receipt_pdf.print_html_inert_to_pdf", side_effect=drawn) as draw:
            ok = site.download_bill(page, None, date, self.out, href=href or f"/secure/MyBill/{number}",
                                    document_id=number, trace=trace)
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

    def test_a_list_that_cannot_be_read_again_stops(self):
        """The list read for a bill is the list every bill after it reads
        too, so a list that stops is raised to the run, never this bill's
        False."""
        page = Page(extra={"pager": True})
        with self.assertRaises(site.ListStopped):
            self.save(page)
        self.assertEqual(page.asked, [], "no bill is asked for")
        self.assertFalse(self.out.exists())

    def test_a_page_that_is_not_a_bill_is_not_drawn(self):
        for page in (Page(said="Something else"), Page(print_status=500),
                     Page(print_type="application/json"), Page(said=SAID.replace("8/31", "7/31")),
                     Page(said=SAID.replace("Billing Date 8/31/2026", "Billing Date"))):
            ok, draw = self.save(page)
            self.assertFalse(ok)
            draw.assert_not_called()
            self.assertFalse(self.out.exists())

    def test_a_bill_refused_while_the_list_still_reads_fails_alone(self):
        """A 401, a 403, a redirect or a page asking for a password where one
        bill's print page should be was read as a sign-out, so every run
        stopped at that bill and Continue stopped there again (#124).
        Activity is read again with the read that proves a session, and a
        list that still reads leaves the refusal that bill's own."""
        for how, kw in REFUSALS.items():
            page = Page(**kw)
            trace = []
            ok, draw = self.save(page, trace=trace)
            self.assertFalse(ok, how)
            draw.assert_not_called()
            self.assertFalse(self.out.exists(), how)
            # The bill is asked for once, and Activity is opened for it and
            # once more after the refusal.
            self.assertEqual(page.asked, [site.print_url("10000002")], how)
            self.assertEqual(page.opened, 2, how)
            self.assertIn({"note": "refused, the list still reads"}, trace, how)

    def test_a_bill_refused_and_a_list_refused_after_it_is_a_sign_out(self):
        """A session that ended sends Activity to the sign-in page too, and
        only that stops the run as signed out."""
        for how, kw in REFUSALS.items():
            page = SignsOutAtTheBill(**kw)
            with self.assertRaises(site.SessionExpired, msg=how):
                self.save(page)
            self.assertEqual(page.asked, [site.print_url("10000002")], how)
            self.assertEqual(page.opened, 2, how)
            self.assertFalse(self.out.exists(), how)

    def test_a_list_that_does_not_read_after_a_refusal_is_unread_not_a_sign_out(self):
        """A 500, a timeout, an answer that is not the table, a tab that
        cannot be read or an Activity with no bill, after one bill's
        refusal, says nothing of the session. Each stops the run with the
        list unread, never as signed out and never as that bill's own
        failure, and the bill is asked for once."""
        for how in UNREAD:
            page = ListFailsAfterTheBill(how)
            with self.assertRaises(site.ListStopped, msg=how):
                self.save(page)
            self.assertEqual(page.asked, [site.print_url("10000002")], how)
            self.assertEqual(page.opened, 2, how)
            self.assertFalse(self.out.exists(), how)

    def test_a_list_that_stops_after_a_refusal_reaches_the_run(self):
        class PagerAfter(Page):
            def evaluate(self, js, arg=None):
                got = super().evaluate(js, arg)
                if arg is not None:
                    self.extra = {"pager": True}
                return got
        page = PagerAfter(print_status=403)
        with self.assertRaises(site.ListStopped):
            self.save(page)
        self.assertEqual(page.asked, [site.print_url("10000002")])
        self.assertFalse(self.out.exists())

    def test_a_password_rule_in_a_stylesheet_is_not_a_sign_in_page(self):
        css = "<style>input[type=\"password\"] { border: 1px }</style>"
        ok, draw = self.save(Page(printed=PRINTED.replace("<body>", "<body>" + css)))
        self.assertTrue(ok)
        draw.assert_called_once()

    def test_the_type_is_read_whatever_its_case(self):
        ok, _ = self.save(Page(print_type="TEXT/HTML; charset=utf-8"))
        self.assertTrue(ok)

    def test_what_was_left_out_of_the_page_is_in_the_trace(self):
        trace = []
        with mock.patch("paperpull_core.receipt_pdf.print_html_inert_to_pdf", side_effect=drawn):
            ok = site.download_bill(Page(dropped=[{"kind": "stylesheet", "why": "over the budget"}]), None,
                                    "2026-08-31", self.out, trace=trace, href="/secure/MyBill/10000002",
                                    document_id="10000002")
        self.assertTrue(ok)
        self.assertIn({"note": "left out", "kind": "stylesheet", "why": "over the budget"}, trace)


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


    def _run_with(self, page):
        """A Run All's downloads over the three listed bills, with what it
        printed and logged."""
        app = make_app(tempfile.mkdtemp(), "--all")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda p: None
        app._on_its_site = lambda: page
        app._delay = lambda *a, **k: None
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        ended = None
        try:
            with redirect_stdout(seen), mock.patch("paperpull_core.receipt_pdf.print_html_inert_to_pdf",
                                                   side_effect=drawn):
                app.process(app._select())
        except SystemExit as e:
            ended = e
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        return app, ended, seen.getvalue()

    def test_one_bill_refused_and_a_list_that_does_not_read_stop_the_run_unread(self):
        """The list read again after a refusal answered with an error page,
        timed out, answered with something else, could not be read or held
        no bill. That proves no session and no sign-out, so the run stops
        with the list unread, nothing is recorded against the refused bill,
        and a run that lists first takes it again. A list that failed this
        way was recorded as that bill's failure, and the run went on with
        no session shown."""
        from paperpull_core.run_reporting import ListNotRead
        for how in UNREAD:
            page = ListFailsAfterTheBill(how, refused="10000002")
            app, ended, said = self._run_with(page)
            self.assertIsInstance(ended, ListNotRead, (how, said))
            states = {k: v["state"] for k, v in app.progress.data.items()}
            self.assertEqual(states, {"id:10000003": "Completed"}, how)
            self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0, how)
            text = " ".join(said.split())
            self.assertIn("so this run stops here", text, how)
            self.assertNotIn("signed out", text, how)
            self.assertEqual(page.asked, [site.print_url("10000003"), site.print_url("10000002")], how)


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
