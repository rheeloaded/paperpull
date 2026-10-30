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
import portlandgeneral_site as site  # noqa: E402
import portlandgeneral_docs as docs  # noqa: E402

FAKE_ACCOUNT = "9876500012"
OTHER_ACCOUNT = "9876500034"
FAKE_NAME = "Zyxwvut, Qponmlk"
FAKE_STREET = "Wvutsrq"
FAKE_TOKEN = "Bearer fake-token-not-real-0000"
PDF = b"%PDF-1.4 " + b"x" * 3000


def bill(day, ref):
    return {"date": f"{day}T00:00:00.000Z", "amountDue": 0, "amountPaid": 0.0,
            "encryptedBillId": ref, "billingPeriodStartDate": "", "billingPeriodEndDate": "",
            "kwh": 1, "type": "Bill", "__typename": "PaymentHistoryDetail"}


def payment(day):
    return {"date": f"{day}T00:00:00.000Z", "amountDue": 0, "amountPaid": 10.0,
            "encryptedBillId": "", "billingPeriodStartDate": "", "billingPeriodEndDate": "",
            "kwh": 0, "type": "Payment", "__typename": "PaymentHistoryDetail"}


ROWS = [bill("2026-09-30", "ref+A1"), payment("2026-09-20"), bill("2026-08-31", "ref/B2"),
        payment("2026-08-20"), bill("2026-07-31", "ref=C3")]


def answer(rows, total=None, accounts=1, number=FAKE_ACCOUNT):
    acct = {"accountNumber": number, "mainCustomerName": FAKE_NAME,
            "coCustomerNames": [], "premiseInfo": [{"addressLine1": f"100 {FAKE_STREET} St",
                                                    "city": "Portland", "postal": "97201",
                                                    "description": "Main House"}],
            "paymentHistory": {"paymentHistoryDetails": rows,
                               "totalDetailsRecords": len(rows) if total is None else total}}
    return {"data": {"getAccountDetails": [acct] * accounts}}


def history_body(limit=2, offset=0):
    return {"operationName": "getAccountDetails",
            "query": "query getAccountDetails($params: X) { getAccountDetails { x } }",
            "variables": {"params": {"accountNumberList": [{"accountNumber": FAKE_ACCOUNT}]},
                          "paymentHistoryParams": {"pagingParams": {"limit": limit, "offset": offset}}}}


class Req:
    def __init__(self, body, headers=None):
        self.method = "POST"
        self.url = site.GRAPHQL_URL
        self.post_data = json.dumps(body)
        self._headers = {"authorization": FAKE_TOKEN, "aws_graphql_server": "x",
                         "content-type": "application/json", "cookie": "never-taken"} \
            if headers is None else headers

    def all_headers(self):
        return dict(self._headers)


def info_body():
    return {"operationName": "getAccountInfo",
            "query": "query getAccountInfo($params: X) { getAccountInfo { x } }",
            "variables": {"params": {}}}


def info_answer(total):
    return {"data": {"getAccountInfo": {"accountMeta": {"totalAccounts": total,
                                                        "hasInactiveAccounts": False}}}}


class Resp:
    def __init__(self, data, status=200, body=None, headers=None):
        self.status = status
        self.url = site.GRAPHQL_URL
        self.request = Req(body or history_body(), headers)
        self.headers = {}
        self._data = data

    def body(self):
        return json.dumps(self._data).encode()


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n


class Page:
    """The signed-in history page: the first page of rows comes with the
    page's own request, further pages and PDFs are asked through evaluate."""

    def __init__(self, rows=ROWS, limit=2, settled=None, first=None, pdf=PDF, pdf_status=200,
                 pages=None, headers=None, accounts=None, number=FAKE_ACCOUNT, pdfs=None):
        self.rows, self.limit = rows, limit
        self.accounts, self.number = accounts, number
        # The PDF answers in turn, when they differ from one ask to the next.
        self.pdfs = pdfs
        self.opened = 0
        self.url = "about:blank"
        self.settled = settled or site.DOCUMENTS_URL
        self.first = first
        self.pdf, self.pdf_status = pdf, pdf_status
        self.pages = pages
        self.headers = headers
        self.asked = []
        self.handlers = []
        self.context = self

    def on(self, event, handler):
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        self.handlers.remove(handler)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.url = self.settled
        self.opened += 1
        if self.accounts is not None:
            for h in list(self.handlers):
                h(Resp(info_answer(self.accounts), body=info_body()))
        resp = self.first if self.first is not None else Resp(
            answer(self.rows[:self.limit], total=len(self.rows), number=self.number),
            body=history_body(self.limit), headers=self.headers)
        if resp != "none":
            for h in list(self.handlers):
                h(resp)

    def locator(self, sel):
        return Locator(1 if "password" in sel and "sign" in self.settled.lower() else 0)

    def evaluate(self, js, arg=None):
        url, headers, body = arg[0], arg[1], arg[2]
        self.asked.append((url, dict(headers), body))
        if url == site.GRAPHQL_URL:
            off = body["variables"]["paymentHistoryParams"]["pagingParams"]["offset"]
            if self.pages is not None:
                return self.pages.pop(0)
            return {"status": 200, "data": answer(self.rows[off:off + self.limit], total=len(self.rows),
                                                  number=self.number)}
        if self.pdfs:
            status, data = self.pdfs.pop(0)
            if status != 200:
                return {"status": status, "type": "application/json"}
            return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(data).decode()}
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "application/json"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}


class Hosts(unittest.TestCase):
    def test_only_the_site_and_its_api_over_https(self):
        ok = ["https://portlandgeneral.com/secure/payment/billing-payment-history",
              "https://api.portlandgeneral.com/pge-graphql"]
        bad = ["http://portlandgeneral.com/", "https://evil.portlandgeneral.com/",
               "https://portlandgeneral.com.evil.test/", "https://cdn-cookieyes.com/x",
               "javascript:alert(1)", "", None]
        for u in ok:
            self.assertTrue(site.is_safe_url(u), u)
        for u in bad:
            self.assertFalse(site.is_safe_url(u), u)

    def test_a_bill_is_asked_from_one_address_only(self):
        self.assertTrue(site.is_download_url(site.PDF_URL))
        for u in [site.PDF_URL + "?x=1", site.PDF_URL + "#a", "https://portlandgeneral.com" + site.DOWNLOAD_PATH,
                  "https://api.portlandgeneral.com/pge-bill-api/pdf/other"]:
            self.assertFalse(site.is_download_url(u), u)


class Controls(unittest.TestCase):
    def test_the_bill_links_are_documents(self):
        for name in ("Simplified Bill (PDF)", "Detailed Bill (PDF)", "View Bill Online"):
            self.assertTrue(site.is_safe_control(name), name)

    def test_everything_else_is_refused(self):
        for name in ("Pay Bill", "Pay Now", "AutoPay", "Equal Pay", "Time of Day", "Enroll in Green Future",
                     "Peak Time Rebates", "Smart Battery", "Start, Stop or Move Service", "Go Paperless",
                     "Edit profile", "Update payment method", "Sign Out", "", "   "):
            self.assertFalse(site.is_safe_control(name), name)

    def test_credit_is_not_edit(self):
        self.assertIsNone(site.FORBIDDEN_CONTROL_RE.search("Credit Statement"))
        self.assertIsNotNone(site.FORBIDDEN_CONTROL_RE.search("Edit profile"))


class Challenge(unittest.TestCase):
    class Shown:
        def __init__(self, url, text, sign_out=True):
            self.url, self.text, self.sign_out = url, text, sign_out

        def get_by_role(self, role, name=None):
            return Locator(1 if self.sign_out and name is site.SIGN_OUT_RE else 0)

        def title(self):
            return ""

        def locator(self, sel):
            page = self

            class Body:
                def inner_text(self, timeout=0):
                    return page.text
            return Body()

    BANNER = "Sign out\nProtect your account even more by enabling Two-Step Authentication."

    def test_a_signed_in_page_inviting_two_step_is_not_a_challenge(self):
        self.assertIsNone(site.detect_security_challenge(
            self.Shown("https://portlandgeneral.com/secure/account/summary", self.BANNER)))

    def test_a_real_prompt_or_an_ended_session_still_is(self):
        for page in (self.Shown("https://portlandgeneral.com/auth/sign-in", "Enter the code we sent"),
                     self.Shown("https://portlandgeneral.com/secure/account/summary", self.BANNER,
                                sign_out=False),
                     self.Shown("https://portlandgeneral.com/secure/account/summary",
                                "Sign out\nYour session has expired.")):
            self.assertIsNotNone(site.detect_security_challenge(page), page.url)


class HistoryRequest(unittest.TestCase):
    def test_the_pages_own_query_is_recognized(self):
        self.assertTrue(site.is_history_request("POST", site.GRAPHQL_URL, json.dumps(history_body())))

    def test_anything_else_is_not(self):
        b = history_body()
        mutation = dict(b, query="mutation getAccountDetails { x }")
        no_paging = json.loads(json.dumps(b)); del no_paging["variables"]["paymentHistoryParams"]
        other_op = dict(b, operationName="getAccountInfo")
        for method, url, data in [("GET", site.GRAPHQL_URL, json.dumps(b)),
                                  ("POST", "https://evil.test/pge-graphql", json.dumps(b)),
                                  ("POST", site.GRAPHQL_URL, json.dumps(mutation)),
                                  ("POST", site.GRAPHQL_URL, json.dumps(no_paging)),
                                  ("POST", site.GRAPHQL_URL, json.dumps(other_op)),
                                  ("POST", site.GRAPHQL_URL, "not json"),
                                  ("POST", site.GRAPHQL_URL, None)]:
            self.assertFalse(site.is_history_request(method, url, data), (method, url, data))


class Rows(unittest.TestCase):
    def test_bills_only_dated_and_keyed_by_their_account_and_day(self):
        got = site.bills_of(ROWS, FAKE_ACCOUNT)
        self.assertEqual([d.date_text for d in got], ["2026-09-30", "2026-08-31", "2026-07-31"])
        self.assertEqual([d.document_id for d in got],
                         ["bill-0012-2026-09-30", "bill-0012-2026-08-31", "bill-0012-2026-07-31"])
        self.assertEqual({d.href for d in got}, {site.DOWNLOAD_PATH})
        self.assertEqual(got[1].bill_ref, "ref/B2")
        self.assertNotIn(FAKE_ACCOUNT, repr(got))

    def test_unreadable_rows_stop_the_list_with_what_was_read(self):
        for broken in (dict(bill("2026-06-30", ""), encryptedBillId=""),
                       dict(bill("2026-06-30", "r"), date="2026-02-30T00:00:00.000Z"),
                       dict(bill("2026-06-30", "r"), date="June 30"),
                       "not a row"):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(ROWS + [broken], FAKE_ACCOUNT)
            self.assertEqual(len(stop.exception.docs), 3, broken)

    def test_a_row_of_a_type_it_does_not_know_stops_the_list_and_is_named(self):
        for kind, named in (("Rebill", "'Rebill'"), ("Corrected Bill", "'Corrected Bill'"),
                            (None, "type this"), ("<b>x</b>", "type this")):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(ROWS + [dict(bill("2026-06-30", "r"), type=kind)], FAKE_ACCOUNT)
            self.assertEqual(len(stop.exception.docs), 3)
            self.assertIn(named, str(stop.exception))
        self.assertNotIn("<b>", str(stop.exception))

    def test_two_bills_of_one_date_refuse_that_date_alone(self):
        got = site.bills_of(ROWS + [bill("2026-09-30", "again")], FAKE_ACCOUNT)
        self.assertEqual(len(got), 4)
        self.assertEqual(site.colliding_dates(got), ["2026-09-30"])
        self.assertEqual(site.colliding_dates(site.bills_of(ROWS, FAKE_ACCOUNT)), [])

    def test_an_answer_for_other_than_one_account_stops(self):
        for a in (answer(ROWS, accounts=2), answer(ROWS, accounts=0), {"data": {}}, [], {"data": {"getAccountDetails": [{}]}}):
            with self.assertRaises(site.ListStopped):
                site.history_page(a)
        for number in ("", "12-34", None, "x" * 10):
            with self.assertRaises(site.ListStopped):
                site.account_of(answer(ROWS, number=number))
        self.assertEqual(site.account_of(answer(ROWS)), FAKE_ACCOUNT)

    def test_accounts_held_is_read_from_account_info_only(self):
        self.assertEqual(site.accounts_held(info_answer(3)), 3)
        for a in ({}, {"data": {"getAccountInfo": {}}}, info_answer("3"), info_answer(True), info_answer(-1)):
            self.assertIsNone(site.accounts_held(a))
        self.assertTrue(site.is_account_info_request("POST", site.GRAPHQL_URL, json.dumps(info_body())))
        self.assertFalse(site.is_account_info_request("POST", site.GRAPHQL_URL, json.dumps(history_body())))

    def test_errors_saying_the_session_ended_are_session_expired(self):
        with self.assertRaises(site.SessionExpired):
            site.history_page({"errors": [{"message": "Unauthorized"}]})
        with self.assertRaises(site.ListStopped):
            site.history_page({"errors": [{"message": "Something else"}]})

    def test_rules_classify(self):
        rules = json.loads((HERE / "document_rules.json").read_text())
        self.assertIsInstance(rules, dict)


class ListWhole(unittest.TestCase):
    def test_every_page_is_read_with_the_pages_own_headers(self):
        page = Page(limit=2)
        got = site.collect_download_docs(page)
        self.assertEqual(len(got), 3)
        offsets = [b["variables"]["paymentHistoryParams"]["pagingParams"]["offset"] for _, _, b in page.asked]
        self.assertEqual(offsets, [2, 4])
        for _, headers, _ in page.asked:
            self.assertEqual(set(headers), {"authorization", "aws_graphql_server"}, "no cookie, nothing else")

    def test_a_short_or_changing_history_stops(self):
        short = Page(limit=2, pages=[{"status": 200, "data": answer([], total=5)}])
        changed = Page(limit=2, pages=[{"status": 200, "data": answer(ROWS[2:4], total=6)}])
        moved = Page(limit=2, pages=[{"status": 200, "data": answer(ROWS[2:4], total=5,
                                                                    number=OTHER_ACCOUNT)}])
        for page in (short, changed, moved):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)

    def test_a_page_that_repeats_rows_stops_whatever_their_type(self):
        # Paging that did not move on gives the first page again, payment
        # and all, with fresh bill ids.
        again = [dict(ROWS[0], encryptedBillId="fresh"), ROWS[1]]
        page = Page(limit=2, pages=[{"status": 200, "data": answer(again, total=5)}])
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page)
        self.assertIn("earlier page", str(stop.exception))
        payments = [payment("2026-09-20"), payment("2026-09-20"), bill("2026-08-31", "b")]
        self.assertEqual(len(site.collect_download_docs(Page(rows=payments, limit=2))), 1,
                         "two payments alike on one page are a person's, not paging")

    def test_a_walk_that_does_not_start_at_the_first_row_stops(self):
        page = Page(limit=2, first=Resp(answer(ROWS[:2], total=5), body=history_body(2, offset=2)))
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(page)

    def test_other_accounts_are_counted_from_the_pages_own_answer(self):
        for accounts, others in ((None, 0), (1, 0), (3, 2)):
            site.collect_download_docs(Page(accounts=accounts))
            self.assertEqual(site.other_accounts(), others, accounts)

    def test_a_refused_page_is_session_expired(self):
        page = Page(limit=2, pages=[{"status": 401}])
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(page)

    def test_a_page_that_never_asks_or_settles_elsewhere_stops(self):
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(first="none"))
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(settled="https://portlandgeneral.com/secure/account/summary"))

    def test_a_list_request_with_no_authorization_stops(self):
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(headers={"content-type": "application/json"}))

    def test_a_signed_out_site_is_session_expired(self):
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(Page(first="none", settled="https://portlandgeneral.com/auth/sign-in"))

    def test_bill_list_opens(self):
        self.assertTrue(site.bill_list_opens(Page()))
        self.assertFalse(site.bill_list_opens(Page(first="none")))


AUG = "bill-0012-2026-08-31"


def fetch(page, out, date="2026-08-31", doc_id=AUG, href=site.DOWNLOAD_PATH):
    return site.download_bill(page, None, date, out, href=href, document_id=doc_id)


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"
        site._RUN.clear()

    def test_the_detailed_bill_of_that_day_is_asked_for_and_saved(self):
        page = Page(limit=10)
        self.assertTrue(fetch(page, self.out))
        self.assertEqual(self.out.read_bytes(), PDF)
        url, headers, body = page.asked[-1]
        self.assertEqual(url, site.PDF_URL)
        self.assertEqual(body, {"encryptedBillId": "ref/B2", "isSummary": False, "isNonDetailed": False})
        self.assertEqual(set(headers), {"authorization", "aws_graphql_server"})

    def test_the_list_is_read_once_a_run(self):
        page = Page(limit=2)
        site.collect_download_docs(page)
        for date, doc_id in (("2026-09-30", "bill-0012-2026-09-30"), ("2026-08-31", AUG),
                             ("2026-07-31", "bill-0012-2026-07-31")):
            self.assertTrue(fetch(page, self.out, date, doc_id))
        self.assertEqual(page.opened, 1)
        self.assertEqual([u for u, _, _ in page.asked].count(site.GRAPHQL_URL), 2)

    def test_a_refused_pdf_reads_the_list_again_once(self):
        for first in ((500, b""), (401, b""), (200, b'{"error":"expired"}')):
            page = Page(limit=10, pdfs=[first, (200, PDF)])
            site.collect_download_docs(page)
            self.assertTrue(fetch(page, self.out), first)
            self.assertEqual(page.opened, 2, first)

    def test_a_record_that_does_not_match_is_not_fetched(self):
        page = Page(limit=10)
        for date, doc_id, href in (("2026-08-31", "bill-0012-2026-07-31", site.DOWNLOAD_PATH),
                                   ("2026-01-31", "bill-0012-2026-01-31", site.DOWNLOAD_PATH),
                                   ("2026-08-31", "bill-2026-08-31", site.DOWNLOAD_PATH),
                                   ("2026-08-31", AUG, "/other")):
            self.assertFalse(fetch(page, self.out, date, doc_id, href))
        self.assertFalse(any(u == site.PDF_URL for u, _, _ in page.asked))
        self.assertFalse(self.out.exists())

    def test_a_bill_of_another_account_is_never_fetched(self):
        # Discover listed account ...0012; the page now shows ...0034, which
        # has a bill of the same date.
        page = Page(limit=10, number=OTHER_ACCOUNT)
        site.collect_download_docs(page)
        self.assertFalse(fetch(page, self.out))
        self.assertFalse(any(u == site.PDF_URL for u, _, _ in page.asked))
        self.assertFalse(self.out.exists())

    def test_a_date_two_bills_carry_is_refused_and_the_rest_are_taken(self):
        page = Page(rows=ROWS + [bill("2026-08-31", "again")], limit=10)
        site.collect_download_docs(page)
        self.assertFalse(fetch(page, self.out))
        self.assertFalse(self.out.exists())
        self.assertTrue(fetch(page, self.out, "2026-09-30", "bill-0012-2026-09-30"))

    def test_a_refusal_on_a_list_just_read_ends_the_session(self):
        for page in (Page(limit=10, pdf_status=401), Page(limit=10, pdf_status=403)):
            with self.assertRaises(site.SessionExpired):
                fetch(page, self.out)
            self.assertFalse(self.out.exists())

    def test_other_non_pdfs_fail_that_bill_alone(self):
        for page in (Page(limit=10, pdf=b"GIF89a"), Page(limit=10, pdf_status=500),
                     Page(limit=10, pdf=b'{"error":"no such bill"}'), Page(limit=10, pdf=b"<html>")):
            site._RUN.clear()
            self.assertFalse(fetch(page, self.out))
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

    def test_persisted_record_holds_no_bill_ref_and_is_keyed_by_the_day(self):
        app = make_app(self.tmp, "--discover")
        for r in site.bills_of(ROWS, FAKE_ACCOUNT):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        text = app.paths.discovery_json.read_text()
        for ref in ("ref+A1", "ref/B2", "ref=C3", FAKE_ACCOUNT):
            self.assertNotIn(ref, text)
        rec = app.discovery.get("id:bill-0012-2026-09-30")
        self.assertEqual((rec["href"], rec["document_id"], rec["account"]),
                         (site.DOWNLOAD_PATH, "bill-0012-2026-09-30", ""))

    def test_bills_of_two_accounts_on_one_date_are_two_records(self):
        app = make_app(self.tmp, "--discover")
        for account in (FAKE_ACCOUNT, OTHER_ACCOUNT):
            for r in site.bills_of(ROWS, account):
                app._record_rawdoc(r, site.BILLING_URL)
        self.assertEqual(len(app.discovery.data), 6)
        self.assertEqual(docs.told_apart_by({"document_id": "bill-0034-2026-09-30"}), "0034")

    def test_discover_names_a_colliding_date_and_other_accounts(self):
        app = make_app(self.tmp, "--discover")
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page(rows=ROWS + [bill("2026-08-31", "again")], limit=10, accounts=2)
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_discover()
        out = " ".join(said.getvalue().split())
        self.assertIn("Two bills carry the date 2026-08-31", out)
        self.assertIn("holds 1 other account", out)
        self.assertEqual(len(app.discovery.data), 3)

    def test_an_expired_session_stops_the_run_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(ROWS, FAKE_ACCOUNT):
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
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)

    def test_a_tab_that_left_the_site_still_stops_the_run_unread(self):
        read = []

        class Moved:
            url = "https://www.elsewhere.example/inbox"

            def __getattr__(self, name):
                read.append(name)
                raise AssertionError("the tab off the site was asked for %s" % name)

        app = make_app(self.tmp, "--discover")
        app._on_its_site = lambda: Moved()
        for step in (lambda: app.check_session(Moved()), app.cmd_discover):
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit) as end:
                step()
            self.assertEqual(end.exception.code, 0)
            self.assertIn("left portlandgeneral.com", said.getvalue())
        self.assertEqual(read, [])
        self.assertEqual(app.discovery.data, {})

    def test_pilot_gate(self):
        from paperpull_core.models import State

        class D:
            def __init__(self, k):
                self.key = k
        done = {"a": {"state": State.COMPLETED.value}}
        self.assertFalse(docs.pilot_failed(done, [D("a")]))
        self.assertTrue(docs.pilot_failed({"a": {"state": State.FAILED.value}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({}, [D("a")]))
        self.assertTrue(docs.pilot_failed(done, []))


class Privacy(unittest.TestCase):
    """Nothing that names the account, and never the authorization, reaches
    a log line, the console or a file the run writes."""

    def test_account_details_and_headers_stay_out_of_logs_stdout_and_files(self):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(seen):
                for r in site.collect_download_docs(Page(limit=10)):
                    app._record_rawdoc(r, site.BILLING_URL)
                app.discovery.save()
                app.check_session = lambda p: None
                app._delay = lambda *a, **k: None
                app._on_its_site = lambda: Page(limit=10)
                app.process(app._select(limit=1))
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        written = "".join(p.read_text(errors="ignore") for p in app.paths.root.rglob("*")
                          if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"))
        out = seen.getvalue() + written
        for word in (FAKE_ACCOUNT, FAKE_STREET, "Zyxwvut", FAKE_TOKEN, "fake-token"):
            self.assertNotIn(word, out)
        for word in (FAKE_ACCOUNT, FAKE_STREET, "Zyxwvut", "Qponmlk"):
            self.assertIn(word, site.private_words())
        for word in ("Portland", "97201", "Main", "House"):
            self.assertNotIn(word, site.private_words(), "the city, postal code and description are left out")
        self.assertEqual(len(list(app.paths.root.rglob("*.pdf"))), 1)


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "portlandgeneral_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
