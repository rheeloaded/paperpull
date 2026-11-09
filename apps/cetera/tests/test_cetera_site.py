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
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import cetera_site as site  # noqa: E402
import cetera_docs as docs  # noqa: E402
from paperpull_core.run_reporting import ListNotRead  # noqa: E402

FAKE_TOKEN = "Bearer fake-token-not-real-0000"
FAKE_SESSION = "fake-session-not-real-1111"
FAKE_ACCOUNT_ID = 90000001
ACCOUNTS = [{"accountNum": "XXXX-1111", "accountType": "BR", "accountId": FAKE_ACCOUNT_ID, "custodian": "BROADRIDGE"},
            {"accountNum": "XXXX-2222", "accountType": "BR", "accountId": 90000002, "custodian": "BROADRIDGE"}]
PDF = b"%PDF-1.4 " + b"x" * 3000


def stmt(acct, day, sid=None, name="Brokerage Statement"):
    return {"accountNum": acct, "accountType": "BR", "statementName": name,
            "statementId": sid or ("Zm" + base64.b64encode(f"{acct}{day}".encode()).decode()),
            "statementDate": "1790000000000", "statementDateFormated": day}


def qpr(sid, day, name="2026 Q3 Example Household"):
    return {"statementName": name, "statementId": sid, "statementDate": "1790000000000",
            "statementDateFormated": day, "accountId": 80000001, "isRia": False}


ROWS = [stmt("XXXX-1111", "09/30/2026"), stmt("XXXX-2222", "09/30/2026"), stmt("XXXX-1111", "08/31/2026")]
QPRS = [qpr("70000002", "09/30/2026"), qpr("70000001", "06/30/2026", "2026 Q2 Example Household")]


class Req:
    def __init__(self, headers=None, accounts=None, path=site.LIST_PATH):
        self.method = "POST"
        self.url = site.BASE + path + "?pageNum=1"
        self.post_data = json.dumps({"accountList": ACCOUNTS if accounts is None else accounts,
                                     "quarter": "q3", "year": "2026"})
        self._headers = {"authorization": FAKE_TOKEN, "x-session-id": FAKE_SESSION, "cookie": "never-taken",
                         "content-type": "application/json"} if headers is None else headers

    def all_headers(self):
        return dict(self._headers)


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n


class Page:
    def __init__(self, rows=ROWS, qprs=QPRS, total=None, settled=None, asks=True, req=None,
                 listing_status=200, pdf=PDF, pdf_status=200, page_size=2):
        self.rows, self.qprs, self.total = rows, qprs, total
        self.asks, self.req, self.listing_status = asks, req, listing_status
        self.settled = settled or site.DOCUMENTS_URL
        self.url = "about:blank"
        self.pdf, self.pdf_status, self.page_size = pdf, pdf_status, page_size
        self.handlers, self.asked = [], []
        self.loads = 0
        # PDF answers to give, one each, before the page's usual one.
        self.pdf_first = []
        # A session that ends refuses the lists too once a PDF is refused.
        self.signs_out_on_refusal = False

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
                h(self.req or Req())

    def locator(self, sel):
        return Locator(0)

    def evaluate(self, js, arg=None):
        self.asked.append(arg)
        url = arg[0]
        path = urlsplit(url).path
        if path == site.LIST_PATH:
            if self.listing_status != 200:
                return {"status": self.listing_status}
            n = int(url.rsplit("=", 1)[1])
            part = self.rows[(n - 1) * self.page_size:n * self.page_size]
            total = len(self.rows) if self.total is None else self.total
            return {"status": 200, "data": {"statementData": part, "totalItems": str(total)}}
        if path == site.QPR_LIST_PATH:
            return {"status": 200, "data": {"statementData": self.qprs, "totalItems": str(len(self.qprs))}}
        refused = self.pdf_first.pop(0) if self.pdf_first else self.pdf_status
        if refused != 200:
            if self.signs_out_on_refusal:
                self.listing_status = refused
            return {"status": refused, "type": "application/json"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}

    def lists_read(self):
        return sum(1 for a in self.asked if urlsplit(a[0]).path == site.LIST_PATH
                   and a[0].endswith("pageNum=1"))


class Hosts(unittest.TestCase):
    def test_only_the_client_portal_over_https(self):
        self.assertTrue(site.is_safe_url("https://client.adviceworks.net/my-docs/statements"))
        for u in ("http://client.adviceworks.net/", "https://adviceworks.net/", "https://clientlogin.adviceworks.net/",
                  "https://client.adviceworks.net.evil.test/", "https://www.adviceworks.com/", "", None):
            self.assertFalse(site.is_safe_url(u), u)

    def test_a_document_is_its_own_download_address_only(self):
        sid = ROWS[0]["statementId"]
        self.assertTrue(site.is_download_url(site.statement_url(sid)))
        self.assertTrue(site.is_download_url(site.qpr_url("70000002", False)))
        for u in (site.statement_url(sid) + "&clientId=1", site.qpr_url("70000002", False) + "&x=1",
                  site.BASE + site.API_PATH + "deleteStatement/abc?statementType=STATEMENTS",
                  site.BASE + site.QPR_DOWNLOAD_PATH + "/abc?statementType=QPR&isRiaStatement=false",
                  site.BASE + site.DOWNLOAD_PATH + "/" + "a" * 20 + "?statementType=STATEMENTS",
                  site.BASE + site.DOWNLOAD_PATH):
            self.assertFalse(site.is_download_url(u), u)
        self.assertEqual(site.statement_url("short"), "")
        self.assertEqual(site.qpr_url("12", False), "")

    def test_a_statement_id_is_sent_the_way_the_page_encodes_it(self):
        sid = "ab+cd/ef==" * 3
        url = site.statement_url(sid)
        seg = urlsplit(url).path.rsplit("/", 1)[1]
        self.assertEqual(base64.urlsafe_b64decode(seg).decode(), sid)


class Controls(unittest.TestCase):
    def test_a_document_link_is_a_document(self):
        for name in ("View Statement", "Download statement (PDF)", "View Report"):
            self.assertTrue(site.is_safe_control(name), name)

    def test_everything_else_is_refused(self):
        for name in ("Trade", "Transfer Funds", "My Deposits", "Deposit a check", "eDelivery Settings",
                     "Apply", "Turbo Tax", "Contact Info", "Log out", "Statements", "", "   "):
            self.assertFalse(site.is_safe_control(name), name)


class Rows(unittest.TestCase):
    def test_statements_are_known_by_account_and_date(self):
        got = site.statements_of(ROWS, 3, ACCOUNTS)
        self.assertEqual([d.document_id for d in got],
                         ["statement-1111-20260930", "statement-2222-20260930", "statement-1111-20260831"])
        self.assertEqual([d.account for d in got], ["XXXX-1111", "XXXX-2222", "XXXX-1111"])
        self.assertEqual(got[0].title, "Cetera Brokerage Statement 2026-09-30")

    def test_unreadable_statements_stop_the_list_with_what_was_read(self):
        for broken in (stmt("XXXX-3333", "07/31/2026"), stmt("1234", "07/31/2026"), stmt("XXXX-1111", "02/30/2026"),
                       stmt("XXXX-1111", "07/31/2026", sid="x"), "not a row"):
            with self.assertRaises(site.ListStopped) as stop:
                site.statements_of(ROWS + [broken], 4, ACCOUNTS)
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_fewer_rows_than_the_list_holds_stops(self):
        with self.assertRaises(site.ListStopped) as stop:
            site.statements_of(ROWS, 4, ACCOUNTS)
        self.assertEqual(len(stop.exception.docs), 3)

    def test_a_history_with_no_statements_is_never_whole(self):
        """totalItems 0 with no rows was read as a whole history with
        nothing in it."""
        with self.assertRaises(site.ListStopped):
            site.statements_of([], 0, ACCOUNTS)

    def test_two_statements_of_one_account_and_date_leave_that_date_alone(self):
        """A corrected statement, or two accounts sharing a last four,
        stopped the whole list on every run."""
        rows = ROWS + [stmt("XXXX-1111", "09/30/2026", sid="Zmother-id-0000000")]
        got = site.statements_of(rows, 4, ACCOUNTS)
        self.assertEqual(len(got), 4)
        self.assertEqual(site.colliding_dates(got), ["2026-09-30"])
        self.assertEqual(site.colliding_dates(site.statements_of(ROWS, 3, ACCOUNTS)), [])

    def test_a_statement_id_that_comes_back_twice_stops_the_list(self):
        """Pages asked over a sort that moves can give one row twice and
        leave another out with the count still right, and the list was
        called whole without the statement it left out."""
        rows = [ROWS[0], ROWS[1], ROWS[1]]
        with self.assertRaises(site.ListStopped) as stop:
            site.statements_of(rows, 3, ACCOUNTS)
        self.assertIn("two statements carry one id", str(stop.exception))
        self.assertEqual(len(stop.exception.docs), 2)

    def test_a_statement_name_is_kept_safe_for_a_file_name(self):
        """A name with a digit or a mark was read as "Statement", so a
        confirmation or a tax form was filed as an account statement and
        skip_patterns never saw its name."""
        for name, title in (("Form 1099-DIV", "Cetera Form 1099-DIV 2026-09-30"),
                            ("Trade Confirmation #4411", "Cetera Trade Confirmation #4411 2026-09-30"),
                            ("Statement: 09/30 <draft>?", "Cetera Statement 0930 draft 2026-09-30"),
                            ("  Brokerage   Statement ", "Cetera Brokerage Statement 2026-09-30"),
                            ("", "Cetera Statement 2026-09-30"), (None, "Cetera Statement 2026-09-30")):
            got = site.statements_of([stmt("XXXX-1111", "09/30/2026", name=name)], 1, ACCOUNTS)
            self.assertEqual(got[0].title, title, name)
            # The name never moves the key a saved statement is known by.
            self.assertEqual(got[0].document_id, "statement-1111-20260930", name)

    def test_reports_say_their_quarter_and_never_the_household(self):
        got = site.reports_of(QPRS, 2)
        self.assertEqual([d.document_id for d in got], ["qpr-70000002", "qpr-70000001"])
        self.assertEqual(got[0].title, "Cetera Quarterly Performance Report 2026 Q3 2026-09-30")
        self.assertNotIn("Household", " ".join(d.title + d.text for d in got))
        for broken in (qpr("x1", "09/30/2025"), qpr("70000009", "13/01/2025"), qpr("70000002", "03/31/2026"),
                       dict(qpr("70000009", "03/31/2026"), accountId="x")):
            with self.assertRaises(site.ListStopped):
                site.reports_of(QPRS + [broken], 3)

    def test_a_report_whose_isria_is_not_true_or_false_stops(self):
        """Anything but a JSON true asked isRiaStatement=false without a
        word."""
        self.assertTrue(site.reports_of([dict(QPRS[0], isRia=True)], 1)[0].is_ria)
        for flag in ("true", "Y", 1, None):
            with self.assertRaises(site.ListStopped, msg=flag):
                site.reports_of([dict(QPRS[0], isRia=flag)], 1)

    def test_rules_classify(self):
        self.assertIsInstance(json.loads((HERE / "document_rules.json").read_text()), dict)


class ListWhole(unittest.TestCase):
    def setUp(self):
        site._RUN.clear()

    def test_every_page_of_every_quarter_and_the_reports_are_asked_with_the_pages_headers(self):
        rows = ROWS + [stmt("XXXX-2222", "08/31/2026"), stmt("XXXX-1111", "07/31/2026")]
        page = Page(rows=rows)
        got = site.collect_download_docs(page)
        self.assertEqual(len(got), 7)
        lists = [a for a in page.asked if urlsplit(a[0]).path == site.LIST_PATH]
        self.assertEqual([a[0].rsplit("=", 1)[1] for a in lists], ["1", "2", "3"])
        url, method, headers, body = lists[0]
        self.assertEqual((method, set(headers)), ("POST", {"authorization", "x-session-id"}))
        self.assertEqual(body, {"accountList": ACCOUNTS, "quarter": "All", "year": "All"})
        q = [a for a in page.asked if urlsplit(a[0]).path == site.QPR_LIST_PATH][0]
        self.assertEqual((q[0], q[1], q[3]), (site.QPR_LIST_URL, "GET", None))

    def test_a_list_short_of_its_total_stops(self):
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(Page(total=5))
        self.assertEqual(len(stop.exception.docs), 3)

    def test_a_page_that_repeats_a_row_and_drops_another_stops(self):
        """Page two gives page one's second row again in place of its own,
        so the count comes to totalItems with one statement never seen."""
        page = Page(rows=[ROWS[0], ROWS[1], ROWS[1]], total=3)
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(page)
        self.assertEqual(site._RUN, {})

    def test_a_page_that_never_asks_carries_no_authorization_or_odd_accounts_stops(self):
        for page in (Page(asks=False), Page(req=Req(headers={"content-type": "application/json"})),
                     Page(req=Req(accounts=[dict(ACCOUNTS[0], extra="x")])),
                     Page(req=Req(accounts=[dict(ACCOUNTS[0], accountNum="123456789")])),
                     Page(req=Req(path=site.API_PATH + "other")),
                     Page(settled="https://client.adviceworks.net/dashboard")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)

    def test_a_signed_out_site_or_a_refused_list_is_session_expired(self):
        for page in (Page(asks=False, settled="https://clientlogin.adviceworks.net/x/B2C_1A_OIDC/oauth2"),
                     Page(listing_status=403), Page(listing_status=401)):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)


class Download(unittest.TestCase):
    def setUp(self):
        site._RUN.clear()
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "doc.pdf"

    def test_the_statement_with_that_account_and_date_is_fetched(self):
        page = Page()
        self.assertTrue(site.download_bill(page, None, "2026-09-30", self.out,
                                           href=site.DOWNLOAD_PATH, document_id="statement-2222-20260930"))
        self.assertEqual(self.out.read_bytes(), PDF)
        url, headers, _ = page.asked[-1]
        self.assertEqual(url, site.statement_url(ROWS[1]["statementId"]))
        self.assertEqual(set(headers), {"authorization", "x-session-id"})

    def test_a_report_is_fetched_with_its_account_header(self):
        page = Page()
        self.assertTrue(site.download_bill(page, None, "2026-06-30", self.out,
                                           href=site.QPR_DOWNLOAD_PATH, document_id="qpr-70000001"))
        url, headers, _ = page.asked[-1]
        self.assertEqual(url, site.qpr_url("70000001", False))
        self.assertEqual(headers["accountId"], "80000001")

    def test_a_record_that_does_not_match_is_not_fetched(self):
        for doc_id, day, href in (("statement-2222-20260930", "2026-08-31", site.DOWNLOAD_PATH),
                                  ("statement-3333-20260930", "2026-09-30", site.DOWNLOAD_PATH),
                                  ("statement-2222-20260930", "2026-09-30", site.QPR_DOWNLOAD_PATH),
                                  ("qpr-70000001", "2026-06-30", site.DOWNLOAD_PATH),
                                  ("statement-2222-20260930", "2026-09-30", "/other"),
                                  ("anything", "2026-09-30", site.DOWNLOAD_PATH)):
            page = Page()
            site._RUN.clear()
            self.assertFalse(site.download_bill(page, None, day, self.out, href=href, document_id=doc_id))
            self.assertFalse(any("/download" in str(a[0]) for a in page.asked))
            self.assertFalse(self.out.exists())

    def test_a_refusal_with_the_lists_refused_too_is_a_sign_out(self):
        for status in (401, 403):
            page = Page(pdf_status=status)
            page.signs_out_on_refusal = True
            site._RUN.clear()
            with self.assertRaises(site.SessionExpired):
                site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                   document_id="statement-1111-20260930")
            self.assertFalse(self.out.exists())

    def test_one_pdf_refused_while_the_lists_answer_fails_alone(self):
        """One document the portal refuses with a 401 or 403, fresh headers
        and all, stopped every run at that document for good."""
        for status in (401, 403):
            page = Page(pdf_status=status)
            site._RUN.clear()
            trace = []
            self.assertFalse(site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                                document_id="statement-1111-20260930", trace=trace))
            self.assertFalse(self.out.exists())
            # Read for the document, then once more after its refusal.
            self.assertEqual(page.lists_read(), 2, status)
            self.assertIn("the lists still answer", json.dumps(trace))

    def test_an_answer_that_is_not_a_pdf_fails_that_document_alone(self):
        """A 200 JSON or page for one statement was read as a sign-out, so
        every run stopped at that statement for good, nothing recorded."""
        for body in (b'{"message":"Statement not available"}', b"<html>error</html>", b"[]"):
            site._RUN.clear()
            self.assertFalse(site.download_bill(Page(pdf=body), None, "2026-09-30", self.out,
                                                href=site.DOWNLOAD_PATH, document_id="statement-1111-20260930"))
            self.assertFalse(self.out.exists())

    def test_the_lists_this_run_read_are_used_for_each_document(self):
        """Each document opened the page again and read every page of its
        list."""
        page = Page()
        site.collect_download_docs(page)
        for doc_id, day, href in (("statement-1111-20260930", "2026-09-30", site.DOWNLOAD_PATH),
                                  ("statement-2222-20260930", "2026-09-30", site.DOWNLOAD_PATH),
                                  ("qpr-70000001", "2026-06-30", site.QPR_DOWNLOAD_PATH)):
            self.assertTrue(site.download_bill(page, None, day, self.out, href=href, document_id=doc_id))
        self.assertEqual((page.loads, page.lists_read()), (1, 1))

    def test_headers_kept_from_an_earlier_reading_are_taken_again_once(self):
        page = Page()
        site.collect_download_docs(page)
        page.pdf_first = [401]
        self.assertTrue(site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                           document_id="statement-1111-20260930"))
        self.assertEqual((page.loads, page.lists_read()), (2, 2))
        # Refused again right after the page gave fresh ones, while the
        # lists still answer, the document fails alone.
        page.pdf_first = [401, 401]
        self.assertFalse(site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                            document_id="statement-1111-20260930"))
        self.assertEqual((page.loads, page.lists_read()), (4, 4))
        # And with the lists refused too, the session has ended.
        page.pdf_first = [401, 401]
        page.signs_out_on_refusal = True
        with self.assertRaises(site.SessionExpired):
            site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                               document_id="statement-1111-20260930")

    def test_a_list_that_stops_while_documents_download_reaches_the_run(self):
        for page in (Page(rows=[]), Page(listing_status=500), Page(total=5)):
            site._RUN.clear()
            with self.assertRaises(site.ListStopped):
                site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                   document_id="statement-1111-20260930")
            self.assertFalse(self.out.exists())

    def test_two_statements_of_one_account_and_date_are_never_fetched(self):
        page = Page(rows=ROWS + [stmt("XXXX-1111", "09/30/2026", sid="Zmother-id-0000000")])
        self.assertFalse(site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                            document_id="statement-1111-20260930"))
        self.assertFalse(any("/download" in str(a[0]) for a in page.asked))


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def test_records_are_keyed_by_account_and_id_and_named_for_their_account(self):
        app = make_app(tempfile.mkdtemp(), "--discover")
        for r in site.statements_of(ROWS, 3, ACCOUNTS) + site.reports_of(QPRS, 2):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        rec = app.discovery.get("id:XXXX-2222:statement-2222-20260930")
        self.assertEqual((rec["href"], rec["summary"]), (site.DOWNLOAD_PATH, "Brokerage Statement XXXX-2222"))
        rec = app.discovery.get("id:qpr-70000002")
        self.assertEqual((rec["href"], rec["summary"], rec["category"]),
                         (site.QPR_DOWNLOAD_PATH, "Quarterly Performance Report", "Statement"))

    def test_a_confirmation_or_tax_form_in_the_list_is_never_filed_as_a_statement(self):
        """Both were titled "Cetera Statement" and saved as account
        statements, though this app reads neither."""
        app = make_app(tempfile.mkdtemp(), "--discover")
        rows = [stmt("XXXX-1111", "09/30/2026"),
                stmt("XXXX-1111", "08/15/2026", name="Trade Confirmation #4411"),
                stmt("XXXX-2222", "02/15/2026", name="Form 1099-DIV"),
                stmt("XXXX-2222", "02/16/2026", name="Consolidated 1099 Tax Statement")]
        for r in site.statements_of(rows, 4, ACCOUNTS):
            app._record_rawdoc(r, site.BILLING_URL)
        self.assertEqual(list(app.discovery.data), ["id:XXXX-1111:statement-1111-20260930"])
        self.assertEqual(app.stats["skipped_out_of_scope"], 3)
        # Left out by their own names, whatever document_types holds.
        rules = app.rules
        for title in ("Cetera Trade Confirmation #4411 2026-08-15", "Cetera Form 1099-DIV 2026-02-15",
                      "Cetera Consolidated 1099 Tax Statement 2026-02-16", "Cetera Form 5498 2026-05-31"):
            self.assertTrue(docs.doc_types.should_skip(title, rules), title)
        for title in ("Cetera Brokerage Statement 2026-09-30",
                      "Cetera Quarterly Performance Report 2026 Q3 2026-09-30"):
            self.assertFalse(docs.doc_types.should_skip(title, rules), title)

    def test_a_file_is_told_apart_by_its_account_and_date_or_its_report(self):
        """The last six characters of statement-1111-20260930 are its date,
        which every account's statement of that day shares."""
        self.assertEqual(docs.told_apart_by({"document_id": "statement-1111-20260930"}), "1111-20260930")
        self.assertEqual(docs.told_apart_by({"document_id": "qpr-70000002"}), "70000002")

    def test_a_list_that_stops_while_documents_download_stops_the_run_once_unread(self):
        site._RUN.clear()
        app = make_app(tempfile.mkdtemp(), "--resume")
        for r in site.statements_of(ROWS, 3, ACCOUNTS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        page = Page(listing_status=500)
        app.check_session = lambda p: None
        app._on_its_site = lambda: page
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(ListNotRead):
            app.process(app._select())
        self.assertEqual(page.loads, 1)
        self.assertNotIn("Nothing was saved", out.getvalue())
        self.assertEqual(app.progress.data, {})


class Privacy(unittest.TestCase):
    def test_the_headers_and_account_ids_stay_out_of_logs_stdout_and_files(self):
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
                app.process(app._select(limit=2))
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        written = "".join(p.read_text(errors="ignore") for p in app.paths.root.rglob("*")
                          if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"))
        for word in (FAKE_TOKEN, "fake-token", FAKE_SESSION, str(FAKE_ACCOUNT_ID), ROWS[0]["statementId"]):
            self.assertNotIn(word, seen.getvalue() + written)
        self.assertIn(str(FAKE_ACCOUNT_ID), site.private_words())


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "cetera_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
