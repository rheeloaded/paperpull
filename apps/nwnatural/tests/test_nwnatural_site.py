"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import base64
import io
import json
import logging
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import nwnatural_site as site  # noqa: E402
import nwnatural_docs as docs  # noqa: E402
from paperpull_core.run_reporting import ListNotRead  # noqa: E402

PORTAL = "https://ipn2.paymentus.com/cp"
FAKE_ACCOUNT = "9876543-2"
TOKEN = "0000000000000-abc000"
PDF = b"%PDF-1.4 " + b"x" * 3000
HEADS = ["Account", "Due Amount", "Due Date", "Action"]


def view(n):
    return (f"{PORTAL}/view-external-bill.action?&CSRF_TOKEN={TOKEN}&accountId=1&accthid=x"
            f"&accountNumber={FAKE_ACCOUNT}&docRef=000000000{n}/00000&hashedDocRef=h{n}&target=_blank")


def row(due, n, account=None):
    return {"cells": [account or FAKE_ACCOUNT, "$10.00", due, "View"], "views": [view(n)]}


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
                 pdf=PDF, pdf_status=200, pdfs=None, extra=None):
        self.url, self.link, self.rows = url, link, rows
        self.listing = listing
        self.pdf, self.pdf_status = pdf, pdf_status
        # The PDF answers in turn, when they differ from one ask to the next.
        self.pdfs = pdfs
        # More of what the list script returns: a pager, a count.
        self.extra = extra or {}
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
            return self.listing or dict({"status": 200, "table": True, "heads": HEADS, "rows": self.rows},
                                        **self.extra)
        if self.pdfs:
            got = self.pdfs.pop(0)
            if isinstance(got, dict):
                return got
            return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(got).decode()}
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
                       {"cells": ["", "$1", "Jul 1, 2026", "View"], "views": [view(9)]},
                       {"cells": [FAKE_ACCOUNT, "$1"], "views": [view(9)]}):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(HEADS, ROWS + [broken])
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_a_header_with_no_single_due_date_or_account_stops(self):
        for heads in (["Account", "Amount", "Date"], ["Account", "Due Date", "Due Date"], [],
                      ["Due Amount", "Due Date", "Action"], ["Account", "Account", "Due Date"]):
            with self.assertRaises(site.ListStopped):
                site.bills_of(heads, ROWS)

    def test_bills_of_more_than_one_account_list_nothing(self):
        other = {"cells": ["1234567-8", "$12.00", "Jul 21, 2026", "View"], "views": [view(9)]}
        with self.assertRaises(site.SeveralAccounts) as stop:
            site.bills_of(HEADS, ROWS + [other])
        self.assertEqual((stop.exception.count, stop.exception.docs), (2, []))
        self.assertIsInstance(stop.exception, site.ListStopped)

    def test_two_bills_of_one_due_date_are_both_listed_and_that_date_named(self):
        got = site.bills_of(HEADS, ROWS + [row("Sep 22, 2026", 7)])
        self.assertEqual(len(got), 4)
        self.assertEqual(site.colliding_dates(got), ["2026-09-22"])
        self.assertEqual(site.colliding_dates(site.bills_of(HEADS, ROWS)), [])

    def test_told_apart_by_the_whole_due_date(self):
        self.assertEqual(docs.told_apart_by({"document_id": "bill-2026-10-21"}), "20261021")
        self.assertEqual(docs.told_apart_by({}), "")

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

    def test_an_empty_history_a_pager_or_a_count_that_disagrees_stops(self):
        for page in (Page(rows=[]), Page(extra={"pager": True}), Page(extra={"count": 4}),
                     Page(extra={"count": 2})):
            with self.assertRaises(site.ListStopped, msg=page.extra or "empty"):
                site.collect_download_docs(page)
        self.assertEqual(len(site.collect_download_docs(Page(extra={"count": 3, "pager": False}))), 3)

    def test_what_diagnose_says_of_the_table(self):
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(extra={"pager": True}))
        self.assertEqual(site.list_facts(), {"heads": HEADS, "rows": 3, "pager": True, "count": None})

    def test_the_bot_protection_is_not_a_sign_out(self):
        with self.assertRaises(site.Challenged):
            site.collect_download_docs(Page(listing={"status": 403, "challenge": True}))

    def test_a_signed_out_portal_is_session_expired(self):
        for listing in ({"status": 302, "redirected": True}, {"status": 200, "table": False},
                        {"status": 200, "table": True, "password": True, "heads": HEADS, "rows": []},
                        {"status": 401}, {"status": 403}):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(Page(listing=listing))

    def test_goto_documents_and_bill_list_opens(self):
        self.assertTrue(site.goto_documents(Page()))
        self.assertFalse(site.goto_documents(Page(url="https://www.nwnatural.com/")))
        self.assertTrue(site.bill_list_opens(Page()))
        self.assertFalse(site.bill_list_opens(Page(link="")))


class ListFailsAfterTheRefusal(Page):
    """Every bill is refused, and the history read again after the first
    refusal answers 500, shows no bill, or times out in the page, so the
    browser raises its own error. None of them says the session ended, and
    none says it still holds."""

    def __init__(self, how, **kw):
        kw.setdefault("pdf_status", 403)
        super().__init__(**kw)
        self.how, self.gone = how, False

    def evaluate(self, js, arg=None):
        if self.gone and arg is not None and "bills.action" in arg[0]:
            if self.how == "500":
                self.listing = {"status": 500}
            elif self.how == "empty":
                self.rows = []
            else:
                self.asked.append(arg[0])
                raise TimeoutError("Timeout 30000ms exceeded")
        got = super().evaluate(js, arg)
        if arg is not None and "view-external-bill" in arg[0]:
            self.gone = True
        return got

    def bills_asked(self):
        return [u for u in self.asked if "view-external-bill" in u]


class RefusesSome(Page):
    """Refuses the bills whose View address carries one of `refused`'s
    numbers, and serves the others."""

    def __init__(self, refused=(), **kw):
        super().__init__(**kw)
        self.refused, self.refused_asks, self.served = set(refused), set(), 0

    def evaluate(self, js, arg=None):
        if arg is not None and "view-external-bill" in arg[0]:
            n = int(arg[0].split("docRef=")[1].split("/")[0])
            if n in self.refused:
                self.asked.append(arg[0])
                self.refused_asks.add(n)
                return {"status": 403, "type": "text/html"}
            self.served += 1
        return super().evaluate(js, arg)


UNREAD = ("500", "timeout", "empty")


def fetch(page, out, date="2026-09-22"):
    return site.download_bill(page, None, date, out, href=site.DOWNLOAD_PATH, document_id=f"bill-{date}")


def lists(page):
    return sum(1 for u in page.asked if "bills.action" in u)


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"
        site._RUN.clear()

    def test_the_list_is_read_once_a_run(self):
        page = Page()
        site.collect_download_docs(page)
        for date in ("2026-10-21", "2026-09-22", "2026-08-21"):
            self.assertTrue(fetch(page, self.out, date))
        self.assertEqual(lists(page), 1)

    def test_a_bill_not_answered_with_a_pdf_reads_the_list_again_once(self):
        html = {"status": 200, "type": "text/html", "b64": base64.b64encode(b"<html>x</html>").decode()}
        for first in (html, {"status": 401}, {"status": 500}):
            site._RUN.clear()
            page = Page(pdfs=[first, PDF])
            site.collect_download_docs(page)
            self.assertTrue(fetch(page, self.out), first)
            self.assertEqual(lists(page), 2, first)

    def test_an_html_answer_fails_that_bill_alone(self):
        page = Page(pdf=b"<html><body>Something went wrong</body></html>")
        site.collect_download_docs(page)
        self.assertFalse(fetch(page, self.out))
        self.assertFalse(self.out.exists())
        self.assertEqual(lists(page), 2)

    def test_the_bot_protection_stops_without_reading_again(self):
        page = Page(pdfs=[{"status": 403, "challenge": True}])
        site.collect_download_docs(page)
        with self.assertRaises(site.Challenged):
            fetch(page, self.out)
        self.assertEqual(lists(page), 1)

    def test_a_date_two_bills_carry_is_refused_and_the_rest_are_taken(self):
        page = Page(rows=ROWS + [row("Sep 22, 2026", 7)])
        site.collect_download_docs(page)
        self.assertFalse(fetch(page, self.out))
        self.assertFalse(any("view-external-bill" in u for u in page.asked))
        self.assertTrue(fetch(page, self.out, "2026-10-21"))

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

    def test_a_refusal_right_after_a_list_that_answered_fails_that_bill_alone(self):
        """The list just answered 200, so the session works. A Resume that
        stopped on this bill would stop on it every time."""
        for status in (401, 403):
            for kept in (False, True):
                site._RUN.clear()
                page = Page(pdf_status=status)
                if kept:
                    site.collect_download_docs(page)
                self.assertFalse(fetch(page, self.out), (status, kept))
                self.assertFalse(self.out.exists())
                self.assertEqual(lists(page), 2 if kept else 1, (status, kept))

    def test_a_list_read_again_after_a_refusal_that_does_not_answer_stops_unread(self):
        """A bill refused on a list read earlier has the list read again.
        A history that answers 500, shows nothing, or times out there is
        neither a sign-out nor this bill's own failure. A timeout reached the
        run as the bill's failure, so the run went on with no session shown,
        and the kept list stays as it was."""
        for how in UNREAD:
            site._RUN.clear()
            page = ListFailsAfterTheRefusal(how)
            kept = site.collect_download_docs(page)
            with self.assertRaises(site.ListStopped, msg=how):
                fetch(page, self.out)
            self.assertIs(site._RUN.get("bills"), kept, how)
            self.assertEqual(len(page.bills_asked()), 1, how)
            self.assertFalse(self.out.exists(), how)

    def test_the_bot_protection_on_the_list_read_again_stays_the_bot_protection(self):
        """The check asks the account holder to look at the browser, which
        a list left unread would not say."""
        page = Page(pdf_status=403)
        site.collect_download_docs(page)
        page.listing = {"status": 403, "challenge": True}
        with self.assertRaises(site.Challenged):
            fetch(page, self.out)
        self.assertEqual(lists(page), 2)

    def test_refusals_in_a_row_stop_the_run_and_a_bill_taken_starts_the_count_again(self):
        """One bill refused right after a list that answered fails alone.
        REFUSED_IN_A_ROW of them with no bill taken between is the portal
        refusing every bill, so the run stops once."""
        dates = ["2026-10-21", "2026-09-22", "2026-08-21"]
        page = Page(pdf_status=403)
        site.collect_download_docs(page)
        for i in range(site.REFUSED_IN_A_ROW - 1):
            self.assertFalse(fetch(page, self.out, dates[i % 3]))
        page.pdf_status = 200
        self.assertTrue(fetch(page, self.out, dates[0]))
        page.pdf_status = 403
        for i in range(site.REFUSED_IN_A_ROW - 1):
            self.assertFalse(fetch(page, self.out, dates[i % 3]))
        with self.assertRaises(site.BillsRefused):
            fetch(page, self.out, dates[2])

    def test_a_signed_out_list_read_for_a_bill_ends_the_session(self):
        page = Page(pdf_status=403)
        site.collect_download_docs(page)
        page.listing = {"status": 200, "redirected": True}
        with self.assertRaises(site.SessionExpired):
            fetch(page, self.out)

    def test_a_list_that_stops_for_a_bill_goes_to_the_run_and_the_kept_list_stays(self):
        for stopped in ({"status": 500}, {"status": 200, "table": True, "heads": HEADS, "rows": []},
                        {"status": 200, "table": True, "heads": HEADS,
                         "rows": ROWS + [row("Jul 21, 2026", 9, account="1234567-8")]}):
            site._RUN.clear()
            page = Page(pdf=b"<html>x</html>")
            kept = site.collect_download_docs(page)
            page.listing = stopped
            with self.assertRaises(site.ListStopped):
                fetch(page, self.out)
            self.assertIs(site._RUN.get("bills"), kept, stopped)
        site._RUN.clear()
        with self.assertRaises(site.ListStopped):
            fetch(Page(listing={"status": 500}), self.out)

    def test_a_date_two_bills_carry_is_not_read_for_again(self):
        page = Page(rows=ROWS + [row("Sep 22, 2026", 7)])
        site.collect_download_docs(page)
        self.assertFalse(fetch(page, self.out))
        self.assertEqual(lists(page), 1)

    def test_other_non_pdfs_are_refused_without_a_file(self):
        for page in (Page(pdf=b"GIF89a"), Page(pdf_status=500)):
            site._RUN.clear()
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

    def test_the_portal_tab_is_taken_by_its_parsed_host(self):
        """A tab on nwnatural.com naming the portal in its address is not the
        portal tab, whichever comes first."""
        class Tab:
            def __init__(self, url):
                self.url = url

            def is_closed(self):
                return False

        main = Tab("https://www.nwnatural.com/account?next=https://ipn2.paymentus.com/cp/")
        portal = Tab(PORTAL + "/home.action")
        for order in ([main, portal], [portal, main]):
            app = make_app(self.tmp, "--discover")
            app.browser = lambda: types.SimpleNamespace(pages=order)
            app._cdp_mode, app._requests = True, object()
            self.assertIs(app.page(), portal)

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

    def test_one_bill_refused_and_a_list_that_does_not_answer_stop_the_run_unread(self):
        """Nothing is recorded against the bill, so the next run that lists
        takes it again, and the run is not called signed out."""
        for how in UNREAD:
            site._RUN.clear()
            app = make_app(tempfile.mkdtemp(), "--all")
            for r in site.bills_of(HEADS, ROWS):
                app._record_rawdoc(r, site.BILLING_URL)
            page = ListFailsAfterTheRefusal(how)
            # The list Discover read, kept for the run as a Run All keeps it.
            site.collect_download_docs(page)
            app.check_session = lambda p: None
            app._on_its_site = lambda: page
            app._delay = lambda *a, **k: None
            ended = None
            try:
                with redirect_stdout(io.StringIO()) as out:
                    app.process(app._select())
            except SystemExit as e:
                ended = e
            said = " ".join(out.getvalue().split())
            self.assertIsInstance(ended, ListNotRead, (how, said))
            self.assertEqual(app.progress.data, {}, how)
            self.assertEqual(app.stats["failed"], 0, how)
            self.assertNotIn("signed out", said, how)
            self.assertNotIn("Timeout 30000ms", said, how)
            self.assertEqual(len(page.bills_asked()), 1, how)

    def test_bills_that_failed_on_an_earlier_run_do_not_count_toward_the_stop(self):
        """The three newest bills failed before and are refused again, the
        two older ones are served. Bills retried newest first would
        otherwise stop every run and every Continue at the third, and the
        older bills would never be asked for. So only a bill with no failure
        recorded before counts, as core not_shown counts only a page that
        had not shown nothing before."""
        site._RUN.clear()
        rows = [row(d, n) for n, d in enumerate(
            ("Dec 21, 2026", "Nov 21, 2026", "Oct 21, 2026", "Sep 22, 2026", "Aug 21, 2026"), 1)]
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(HEADS, rows):
            app._record_rawdoc(r, site.BILLING_URL)
        selected = app._select()
        for doc in selected[:3]:
            app._record(doc, docs.State.FAILED, notes="Could not capture the document PDF")
        page = RefusesSome(rows=rows, refused=(1, 2, 3))
        app.check_session = lambda p: None
        app._on_its_site = lambda: page
        app._delay = lambda *a, **k: None

        with redirect_stdout(io.StringIO()) as out:
            app.process(app._select())

        said = " ".join(out.getvalue().split())
        self.assertNotIn("refused bills one after another", said)
        # Each of the two older bills is asked for and served.
        self.assertEqual(page.served, 2, said)
        states = [app.progress.get(d.key)["state"] for d in selected]
        self.assertEqual(states[:3], [docs.State.FAILED.value] * 3, said)
        self.assertNotIn(docs.State.FAILED.value, states[3:], said)

    def test_a_continue_after_the_stop_takes_up_bills_not_asked_before(self):
        """Every bill is refused. The run stopped at the third, so the first
        two failed alone. A Continue asks those two again, each alone, then
        stops at the third bill never refused before, the fifth, so each
        Continue moves on and none loops on one bill."""
        site._RUN.clear()
        rows = [row(d, n) for n, d in enumerate(
            ("Dec 21, 2026", "Nov 21, 2026", "Oct 21, 2026", "Sep 22, 2026", "Aug 21, 2026"), 1)]
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(HEADS, rows):
            app._record_rawdoc(r, site.BILLING_URL)
        selected = app._select()
        for doc in selected[:2]:
            app._record(doc, docs.State.FAILED, notes="Could not capture the document PDF")
        page = RefusesSome(rows=rows, refused=(1, 2, 3, 4, 5))
        app.check_session = lambda p: None
        app._on_its_site = lambda: page
        app._delay = lambda *a, **k: None

        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            app.process(app._select())

        said = " ".join(out.getvalue().split())
        self.assertIn("refused bills one after another", said)
        self.assertEqual(page.refused_asks, {1, 2, 3, 4, 5}, said)
        self.assertEqual(app.progress.get(selected[2].key)["state"], docs.State.FAILED.value, said)
        self.assertEqual(app.progress.get(selected[3].key)["state"], docs.State.FAILED.value, said)
        self.assertIsNone(app.progress.get(selected[4].key), said)

    def test_bills_refused_in_a_row_stop_the_run_and_record_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def refused(*a, **k):
            raise site.BillsRefused("3 bills in a row were refused")
        original = site.download_bill
        site.download_bill = refused
        try:
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                app.process(app._select())
        finally:
            site.download_bill = original
        self.assertIn("refused bills one after another", " ".join(said.getvalue().split()))
        self.assertNotIn("signed out", said.getvalue())
        self.assertEqual(app.progress.data, {})

    def test_discover_names_several_accounts_and_lists_nothing(self):
        app = make_app(self.tmp, "--discover")
        other = {"cells": ["1234567-8", "$12.00", "Jul 21, 2026", "View"], "views": [view(9)]}
        app._on_its_site = lambda: Page(rows=ROWS + [other])
        app.check_session = lambda page: None
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit) as ended:
            app.cmd_discover()
        self.assertEqual(ended.exception.code, 1)
        self.assertIn("lists the bills of 2 accounts", said.getvalue())
        self.assertEqual(app.discovery.data, {})

    def test_discover_names_a_colliding_date(self):
        app = make_app(self.tmp, "--discover")
        app._on_its_site = lambda: Page(rows=ROWS + [row("Sep 22, 2026", 7)])
        app.check_session = lambda page: None
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_discover()
        self.assertIn("Two bills carry the due date 2026-09-22", said.getvalue())
        self.assertEqual(len(app.discovery.data), 3)

    def test_a_tab_on_nwnatural_com_stops_the_run_once(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._delay = lambda *a, **k: None
        main_site = Page(url="https://www.nwnatural.com/account")
        original = docs.tabs.on_its_site
        docs.tabs.on_its_site = lambda *a, **k: main_site
        try:
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit) as ended:
                app.process(app._select())
        finally:
            docs.tabs.on_its_site = original
        self.assertEqual(ended.exception.code, 0)
        self.assertIn("not its payment portal", said.getvalue())
        self.assertEqual(said.getvalue().count("not its payment portal"), 1)
        self.assertEqual(main_site.asked, [])
        self.assertEqual(app.progress.data, {})
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)

    def test_the_bot_protection_stops_the_run_once_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(HEADS, ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._delay = lambda *a, **k: None
        site._RUN.clear()
        app._on_its_site = lambda: Page(pdfs=[{"status": 403, "challenge": True}])
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.process(app._select())
        self.assertIn("asked to check the browser", said.getvalue())
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
