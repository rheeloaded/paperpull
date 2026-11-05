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
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "text/html"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}


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
                       stmt("XXXX-1111", "09/30/2026", sid="Zmother-id-0000000"), stmt("XXXX-1111", "07/31/2026", sid="x"),
                       "not a row"):
            with self.assertRaises(site.ListStopped) as stop:
                site.statements_of(ROWS + [broken], 4, ACCOUNTS)
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_fewer_rows_than_the_list_holds_stops(self):
        with self.assertRaises(site.ListStopped) as stop:
            site.statements_of(ROWS, 4, ACCOUNTS)
        self.assertEqual(len(stop.exception.docs), 3)

    def test_an_odd_statement_name_is_not_kept(self):
        got = site.statements_of([stmt("XXXX-1111", "09/30/2026", name="<b>x</b> 1234")], 1, ACCOUNTS)
        self.assertEqual(got[0].title, "Cetera Statement 2026-09-30")

    def test_reports_say_their_quarter_and_never_the_household(self):
        got = site.reports_of(QPRS, 2)
        self.assertEqual([d.document_id for d in got], ["qpr-70000002", "qpr-70000001"])
        self.assertEqual(got[0].title, "Cetera Quarterly Performance Report 2026 Q3 2026-09-30")
        self.assertNotIn("Household", " ".join(d.title + d.text for d in got))
        for broken in (qpr("x1", "09/30/2025"), qpr("70000009", "13/01/2025"), qpr("70000002", "03/31/2026"),
                       dict(qpr("70000009", "03/31/2026"), accountId="x")):
            with self.assertRaises(site.ListStopped):
                site.reports_of(QPRS + [broken], 3)

    def test_rules_classify(self):
        self.assertIsInstance(json.loads((HERE / "document_rules.json").read_text()), dict)


class ListWhole(unittest.TestCase):
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
            self.assertFalse(site.download_bill(page, None, day, self.out, href=href, document_id=doc_id))
            self.assertFalse(any("/download" in str(a[0]) for a in page.asked))
            self.assertFalse(self.out.exists())

    def test_refused_and_sign_in_answers_raise_and_save_nothing(self):
        for page in (Page(pdf_status=401), Page(pdf_status=403), Page(pdf=b"<html>sign in</html>"),
                     Page(pdf=b'{"statusCode": 401}')):
            with self.assertRaises(site.SessionExpired):
                site.download_bill(page, None, "2026-09-30", self.out, href=site.DOWNLOAD_PATH,
                                   document_id="statement-1111-20260930")
            self.assertFalse(self.out.exists())


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


class Privacy(unittest.TestCase):
    def test_the_headers_and_account_ids_stay_out_of_logs_stdout_and_files(self):
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
