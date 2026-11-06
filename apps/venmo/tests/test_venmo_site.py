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
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import venmo_site as site  # noqa: E402
import venmo_docs as docs  # noqa: E402

HOST = "account.venmo.com"
TODAY = date(2026, 10, 13)
# Invented profile details, which must never leave through a log, the
# console, a diagnostic, a record or a file name.
FAKE_PROFILE_ID = "4455667788990011"
FAKE_HANDLE = "@Qzxv-Wplk-42"
FAKE_NAME = "Zyxwvut Qponmlk"
FAKE_EMAIL = "zyx.qpo@example.invalid"
FAKE_PHONE = "(555) 010-4477"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]


def statement_url(month=10, year=2026, account="personal", profile=FAKE_PROFILE_ID):
    return (f"https://{HOST}/statement?accountType={account}&month={month}"
            f"&profileId={profile}&year={year}")


class Request:
    def __init__(self, url, body="", navigation=False):
        self.url, self.post_data, self.navigation = url, body, navigation

    def is_navigation_request(self):
        return self.navigation


GRAPHQL = "https://api.venmo.com/graphql"
WHOLE = {"data": {"transactionsHistory": {"items": [{"amount": "-1.00", "note": FAKE_NAME}],
                                          "pageInfo": {"hasNextPage": False, "endCursor": "abc"}}}}


class Response:
    def __init__(self, url, status, op, body=None, request=None):
        self.url, self.status, self._body = url, status, WHOLE if body is None else body
        self.request = request or Request(url, json.dumps(
            {"operationName": op, "variables": {"input": {"x": FAKE_PROFILE_ID}}}))

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Locator:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n

    def inner_text(self, **kw):
        return ""

    def all_inner_texts(self):
        return ["Account Statement"]


class Page:
    """The Statements page as the survey saw it, with nothing pressed. A
    visit to /statement settles on the current month's address; a month's
    own address shows that month and the page's TransactionsHistory answer
    is heard, unless told otherwise."""

    def __init__(self, settle=None, password=False, status=200, heard=True, heading=True,
                 picker=None, labels=("Download CSV", "Send to email"), plain_settles=None,
                 refuse_before=None, start=f"https://{HOST}/", survey=None, extra_answers=(),
                 body=None, stale=None, rows=3, empty=False, loading=0, kids=None, lists=None,
                 states=None, total=None, pager_label="Show more", grow=10, pagers=1):
        self.settle, self.password, self.status, self.heard = settle, password, status, heard
        self.heading, self.picker, self.labels = heading, picker, list(labels)
        self.plain_settles = plain_settles or statement_url()
        self.refuse_before, self.url, self.gotos = refuse_before, start, []
        self.survey_answer, self.extra_answers = survey or {}, list(extra_answers)
        self.body, self.stale = body, stale
        self.rows, self.empty, self.loading = rows, empty, loading
        self.kids, self.lists = kids, lists
        # A busy month: `total` rows, drawn `rows` at first and `grow` more
        # each time its own "Show more" is pressed.
        self.total, self.pager_label, self.grow, self.pagers = total, pager_label, grow, pagers
        self.pressed = 0
        # Called after each Show more press, to have the page do something
        # more: answer as signed out, or move to another address.
        self.after_press = None
        # Page states to show in turn before the settled one, as a page
        # still drawing does.
        self.states = list(states or [])
        self.listeners, self.requests, self.evaluated, self.waited = [], [], [], []
        page = self

        class Ctx:
            pages = [page]
        self.context = Ctx()

    def on(self, event, fn):
        assert event in ("request", "response"), event
        (self.requests if event == "request" else self.listeners).append(fn)

    def remove_listener(self, event, fn):
        (self.requests if event == "request" else self.listeners).remove(fn)

    def _fire(self, event, obj):
        for fn in list(self.requests if event == "request" else self.listeners):
            fn(obj)

    def _month_shown(self):
        q = parse_qs(urlsplit(self.url).query)
        if "month" not in q:
            return None
        y, m = int(q["year"][0]), int(q["month"][0])
        if self.refuse_before and (y, m) < self.refuse_before:
            # A month the page will not show: it shows the earliest it has.
            y, m = self.refuse_before
        return f"{MONTH_NAMES[m - 1]} {y}"

    def goto(self, url, **kw):
        self.gotos.append(url)
        if self.settle:
            self.url = self.settle
        elif url == site.DOCUMENTS_URL:
            self.url = self.plain_settles
        else:
            self.url = url
        # An answer the page before asked for, arriving after this
        # navigation began.
        if self.stale is not None:
            self._fire("response", self.stale)
        self._fire("request", Request(self.url, navigation=True))
        for r in self.extra_answers:
            self._fire("request", r.request)
            self._fire("response", r)
        if self.heard:
            r = Response(GRAPHQL, self.status, "TransactionsHistory", body=self.body)
            self._fire("request", r.request)
            self._fire("response", r)

    def wait_for_timeout(self, ms):
        self.waited.append(ms)

    def _pager(self):
        return 1 if (self.total is not None and self.rows < self.total and not self.empty) else 0

    def locator(self, sel):
        if sel == site.SHOW_MORE_CSS:
            return ShowMore(self)
        return Locator(1 if ("password" in sel and self.password) else 0)

    def press_show_more(self):
        self.pressed += 1
        self.rows = min(self.total, self.rows + self.grow)
        if self.after_press:
            self.after_press(self)

    def title(self):
        return "Venmo | Account Statement"

    def evaluate(self, js, arg=None):
        self.evaluated.append(js)
        if "matchAll" in js:
            return [FAKE_NAME, f"/u/{FAKE_HANDLE[1:]}", FAKE_HANDLE, FAKE_EMAIL, FAKE_PHONE,
                    "Venmo", "Statement", "https://account.venmo.com/u/x"]
        if "heading" in js:
            shown = self.picker if self.picker is not None else (
                [self._month_shown()] if self._month_shown() else [])
            if self.states:
                return self.states.pop(0)
            lists = self.lists if self.lists is not None else (0 if self.empty else 1)
            pager = self._pager()
            labels = list(self.labels) + ([self.pager_label] if pager else [])
            return {"months": shown, "heading": self.heading, "labels": labels,
                    "lists": lists, "rows": 0 if self.empty else self.rows, "pager": pager,
                    "kids": self.kids if self.kids is not None else (0 if self.empty else self.rows + pager),
                    "empty": self.empty, "loading": self.loading}
        if "inputs" in js:
            return self.survey_answer
        return None


class ShowMore:
    """The list's own pager as Playwright would find it."""

    def __init__(self, page):
        self.page = page

    def count(self):
        return self.page.pagers if self.page._pager() else 0

    @property
    def first(self):
        return self

    def inner_text(self, **kw):
        return self.page.pager_label


class Presser:
    """Stands in for pressing.click: records the press and has the page
    draw the next rows."""

    def __init__(self):
        self.presses = []

    def __call__(self, page, locator, **kw):
        self.presses.append(kw)
        page.press_show_more()


class Printer:
    """Stands in for receipt_pdf.print_page_to_pdf, which needs a real
    browser: it writes a small PDF and remembers which month was showing."""

    def __init__(self, body=b"%PDF-1.4 " + b"x" * 3000, fail=False):
        self.body, self.fail, self.printed = body, fail, []

    def __call__(self, page, out_path):
        if self.fail:
            raise RuntimeError("printToPDF returned non-PDF data")
        self.printed.append(page.url)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(self.body)


class WithPrinter(unittest.TestCase):
    def setUp(self):
        self.printer = Printer()
        self.presser = Presser()
        self._real = site.receipt_pdf.print_page_to_pdf
        self._click = site.pressing.click
        site.receipt_pdf.print_page_to_pdf = self.printer
        site.pressing.click = self.presser

    def tearDown(self):
        site.receipt_pdf.print_page_to_pdf = self._real
        site.pressing.click = self._click


class Dead:
    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")


class Hosts(unittest.TestCase):
    def test_only_the_account_host_over_https(self):
        for u in [f"https://{HOST}/", f"https://{HOST}/statement", statement_url()]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["https://venmo.com/account/statement", "https://id.venmo.com/signin",
                  "https://api.venmo.com/graphql", f"http://{HOST}/statement",
                  f"https://user@{HOST}/statement", f"https://{HOST}@evil.test/statement", f"https://x.{HOST}/",
                  f"https://{HOST}.evil.test/", f"https://{HOST}:8443/statement", f"blob:https://{HOST}/0b1c",
                  "https://www.paypal.com/myaccount/statements", "javascript:alert(1)", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_a_statement_address_is_one_shape_only(self):
        self.assertEqual(site.statement_query(statement_url(9, 2026)),
                         {"accountType": "personal", "month": "9", "year": "2026", "profileId": FAKE_PROFILE_ID})
        self.assertIsNotNone(site.statement_query(statement_url("09", 2026)))
        base = statement_url()
        for u in [f"https://{HOST}/statement", f"https://{HOST}/statement?month=9&year=2026",
                  base + "&csv=true", base + "&month=8", base + "#x", base.replace("month=10", "month=13"),
                  base.replace("month=10", "month=0"), base.replace("year=2026", "year=26"),
                  base.replace(FAKE_PROFILE_ID, "a b"), base.replace(FAKE_PROFILE_ID, ""),
                  base.replace("personal", "per-sonal"), base.replace("/statement", "/statements"),
                  base.replace(HOST, "venmo.com"), base.replace("https:", "http:"),
                  f"https://{HOST}/api/statement/download-v2?startDate=2026-09-01&endDate=2026-09-30&csv=true",
                  f"https://{HOST}/account/logout", "", None]:
            self.assertIsNone(site.statement_query(u), u)

    def test_a_month_address_keeps_the_profile_and_names_the_month(self):
        where = site.Where("personal", FAKE_PROFILE_ID)
        url = site.month_url(where, "2025-02")
        self.assertEqual(site.statement_query(url)["month"], "2")
        self.assertEqual(site.statement_query(url)["year"], "2025")
        self.assertEqual(site.statement_query(url)["profileId"], FAKE_PROFILE_ID)
        for bad in ("", None, "2025-13", "2025-2", "2025-02-28", "February 2025"):
            self.assertEqual(site.month_url(where, bad), "", repr(bad))
        self.assertEqual(site.month_url(site.Where("personal", ""), "2025-02"), "")


class Tabs(unittest.TestCase):
    """A statement in Wallet and Balance tabs, what can be said of it with no
    browser. tests/test_a_statement_in_two_tabs.py drives the page."""

    WHERE = site.Where("personal", FAKE_PROFILE_ID)
    BALANCE = site.Where("personal", FAKE_PROFILE_ID, tab=site.BALANCE_TAB)
    # A month of rows, on each tab, as _STATE_JS reads it.
    WALLET_PAGE = {"months": ["September 2026"], "heading": True, "lists": 1, "rows": 2, "kids": 2,
                   "empty": False, "loading": 0, "tabbed": 1, "wallet": 1, "balance": 0,
                   "asked": site.WALLET_TAB}
    BALANCE_PAGE = dict(WALLET_PAGE, wallet=0, balance=1, asked=site.BALANCE_TAB)

    def test_the_address_may_name_either_tab_and_nothing_else(self):
        base = statement_url()
        self.assertNotIn(site.TAB_KEY, site.statement_query(base))
        for tab in (site.WALLET_TAB, site.BALANCE_TAB):
            self.assertEqual(site.statement_query(f"{base}&accountTab={tab}")[site.TAB_KEY], tab)
        for bad in ("&accountTab=", "&accountTab=venmo", "&accountTab=VENMO-BALANCE", "&accounttab=venmo-balance",
                    "&accountTab=venmo-balance&accountTab=venmo-account", "&accountTab=venmo-account&csv=true"):
            self.assertIsNone(site.statement_query(base + bad), bad)

    def test_a_month_address_names_the_tab_it_is_for(self):
        self.assertNotIn(site.TAB_KEY, site.statement_query(site.month_url(self.WHERE, "2026-09")))
        got = site.statement_query(site.month_url(self.BALANCE, "2026-09"))
        self.assertEqual((got["month"], got[site.TAB_KEY]), ("9", site.BALANCE_TAB))

    def test_a_statement_s_id_says_its_month_and_its_tab(self):
        self.assertEqual(site.month_and_tab("2026-09"), ("2026-09", ""))
        self.assertEqual(site.month_and_tab("2026-09-balance"), ("2026-09", site.BALANCE_TAB))
        for odd in ("", None):
            self.assertEqual(site.month_and_tab(odd), ("", ""))
        for tab in ("", site.BALANCE_TAB):
            made = site._rawdoc("2026-09", 0, self.WHERE, tab)
            self.assertEqual(site.month_and_tab(made.document_id), ("2026-09", tab))
            self.assertEqual(made.date_text, "2026-09-30")

    def test_a_balance_statement_goes_by_a_name_of_its_own(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        said = [doc_types.classify_document(site._rawdoc("2026-09", 0, self.WHERE, tab).title, rules)[1]
                for tab in ("", site.BALANCE_TAB)]
        self.assertEqual(said, ["Statement", "Balance Statement"])

    def test_a_tab_counts_only_when_it_is_the_one_the_address_names_drawn_alone(self):
        self.assertEqual(site.settled(self.WALLET_PAGE, "2026-09"), "")
        self.assertEqual(site.settled(self.BALANCE_PAGE, "2026-09"), "")
        words = dict(lists=0, rows=0, kids=0, empty=True)
        self.assertEqual(site.settled(dict(self.WALLET_PAGE, **words), "2026-09"), "")
        self.assertEqual(site.settled(dict(self.BALANCE_PAGE, **words), "2026-09"), "")
        not_named = dict(self.WALLET_PAGE, asked="")
        not_drawn = dict(self.WALLET_PAGE, tabbed=0, wallet=0)
        reasons = {site.settled(state, "2026-09") for state in (
            not_named, not_drawn,
            dict(self.WALLET_PAGE, asked=site.BALANCE_TAB),
            dict(self.BALANCE_PAGE, asked=site.WALLET_TAB),
            dict(self.WALLET_PAGE, balance=1),
            dict(self.BALANCE_PAGE, wallet=0, balance=0))}
        self.assertEqual(len(reasons), 3, reasons)
        self.assertNotIn("", reasons)

    def test_a_page_with_no_tabs_reads_as_it_always_has(self):
        plain = {k: v for k, v in self.WALLET_PAGE.items() if k not in ("tabbed", "wallet", "balance", "asked")}
        self.assertEqual(site.settled(plain, "2026-09"), "")
        self.assertEqual(site.settled(dict(plain, tabbed=0, wallet=0, balance=0, asked=""), "2026-09"), "")
        self.assertEqual(site._unproved_empty(dict(plain, lists=0, rows=0, kids=0, empty=True), site.Heard()), "")

    def test_only_a_whole_answer_with_nothing_in_it_proves_the_wallet_s_words(self):
        empty = dict(self.WALLET_PAGE, lists=0, rows=0, kids=0, empty=True)
        heard = site.Heard()
        self.assertNotEqual(site._unproved_empty(empty, heard), "", "no answer read")
        heard.said = {"errors": False, "completed": 0, "pending": 0}
        self.assertEqual(site._unproved_empty(empty, heard), "")
        for said in ({"errors": True, "completed": 0, "pending": 0}, {"errors": True, "completed": None, "pending": None},
                     {"errors": False, "completed": None, "pending": 0}, {"errors": False, "completed": 0, "pending": None},
                     {"errors": False, "completed": 1, "pending": 0}, {"errors": False, "completed": 0, "pending": 1}):
            heard.said = said
            self.assertNotEqual(site._unproved_empty(empty, heard), "", repr(said))
        # A tab of rows needs no answer, and the Balance tab's words stand.
        heard.said = None
        self.assertEqual(site._unproved_empty(self.WALLET_PAGE, heard), "")
        self.assertEqual(site._unproved_empty(dict(empty, wallet=0, balance=1), heard), "")

    def test_a_tab_stays_the_one_it_was_opened_on(self):
        heard = site.Heard()
        base = statement_url(9)

        def page(url):
            return Page(start=url)
        for where, url in ((self.WHERE, base), (self.WHERE, f"{base}&accountTab={site.WALLET_TAB}"),
                           (self.BALANCE, f"{base}&accountTab={site.BALANCE_TAB}")):
            site._still_here(page(url), where, "2026-09", heard)
        for where, url in ((self.WHERE, f"{base}&accountTab={site.BALANCE_TAB}"), (self.BALANCE, base),
                           (self.BALANCE, f"{base}&accountTab={site.WALLET_TAB}")):
            with self.assertRaises(site.ListStopped):
                site._still_here(page(url), where, "2026-09", heard)

    def test_only_a_page_the_server_said_nothing_about_is_waited_on(self):
        with_tabs = Page(start=f"{statement_url(9)}&accountTab={site.WALLET_TAB}")
        self.assertTrue(site._draws_tabs(with_tabs))
        self.assertEqual(with_tabs.waited, [])
        for told, waited in ((None, site.LAYOUT_HOLD_MS), (False, 0)):
            page = Page(start=statement_url(9))
            with mock.patch.object(site, "_state", return_value={"told": told}):
                self.assertFalse(site._draws_tabs(page))
            self.assertEqual(sum(page.waited), waited, repr(told))

    def test_a_server_that_says_tabs_is_not_answered_by_a_page_with_none(self):
        rows = {k: v for k, v in self.WALLET_PAGE.items() if k not in ("tabbed", "wallet", "balance", "asked")}
        self.assertEqual(site.settled(dict(rows, told=None), "2026-09"), "")
        self.assertEqual(site.settled(dict(rows, told=False), "2026-09"), "")
        self.assertNotEqual(site.settled(dict(rows, told=True), "2026-09"), "")
        self.assertEqual(site.settled(dict(self.WALLET_PAGE, told=True), "2026-09"), "")

    def test_what_a_balance_answer_held_is_counted_from_its_own_field(self):
        body = {"data": {site.BALANCE_FIELD: {"completedTransaction": {"edges": [{}, {}]},
                                              "pendingTransaction": {"edges": []}}}}
        self.assertEqual(site.answer_counts(body, site.BALANCE_FIELD), {"errors": False, "completed": 2, "pending": 0})
        self.assertEqual(site.answer_counts(body), {"errors": False, "completed": None, "pending": None})

    def test_only_a_clean_null_says_there_is_no_balance_account(self):
        null = {"data": {site.BALANCE_FIELD: None}}
        self.assertTrue(site.no_balance_account(null))
        self.assertTrue(site.no_balance_account([null]))
        for not_that in ({"errors": [{"message": FAKE_NAME}], "data": None},
                         {"errors": [{"message": FAKE_NAME}], "data": {site.BALANCE_FIELD: None}},
                         {"data": None}, {"data": {}}, {"data": {"other": None}}, {"data": {site.BALANCE_FIELD: {}}},
                         {}, [], "text", None, 3, [null, {"data": {site.BALANCE_FIELD: {}}}]):
            self.assertFalse(site.no_balance_account(not_that), repr(not_that))

    def test_each_tab_hears_its_own_answer_and_no_other(self):
        more = {"pageInfo": {"hasNextPage": True}}
        wallet = {"data": {"transactionsHistory": {"completedTransaction": dict(more, edges=[{}])}}}
        null = {"data": {site.BALANCE_FIELD: None}}

        def hears(heard):
            heard.on_request(Request(statement_url(9), navigation=True))
            for r in (Response(GRAPHQL, 200, "TransactionsHistory", body=wallet),
                      Response(GRAPHQL, 200, site.BALANCE_OP, body=null)):
                heard.on_request(r.request)
                heard.on_response(r)
            heard.statement()
            return heard
        on_balance = hears(site._month_heard("2026-09", site.BALANCE_TAB))
        self.assertEqual((on_balance.no_balance, on_balance.partial), (True, False))
        on_wallet = hears(site._month_heard("2026-09"))
        self.assertEqual((on_wallet.no_balance, on_wallet.partial), (False, True))
        self.assertEqual(on_wallet.said["completed"], 1)
        on_balance.on_request(Request(statement_url(8), navigation=True))
        self.assertTrue(on_balance.no_balance, "another month's address is not this one's")
        on_balance.on_request(Request(statement_url(9), navigation=True))
        self.assertFalse(on_balance.no_balance, "a new visit starts clean")

    def test_a_batch_is_read_for_the_answer_asked_about(self):
        batch = json.dumps([{"operationName": "TransactionsHistory"}, {"operationName": site.BALANCE_OP}])
        self.assertEqual(site._operation(batch), site.STATEMENT_OP)
        self.assertEqual(site._operation(batch, site.BALANCE_OP), site.BALANCE_OP)
        self.assertEqual(site._operation(json.dumps([{"operationName": "Other"}]), site.BALANCE_OP), "")

    def test_a_signed_out_answer_to_either_request_is_signed_out(self):
        for op in ("TransactionsHistory", site.BALANCE_OP):
            heard = site._month_heard("2026-09", site.BALANCE_TAB)
            heard.on_request(Request(statement_url(9), navigation=True))
            r = Response(GRAPHQL, 401, op)
            heard.on_request(r.request)
            heard.on_response(r)
            self.assertTrue(heard.signed_out(), op)


class Controls(unittest.TestCase):
    def test_document_words_alone_are_accepted(self):
        for label in ["Download PDF", "Download Statement", "View Statement", "View PDF", "Download",
                      "Download Balance Statement", "View Balance Statement"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_balance_is_a_kind_of_statement_and_nothing_more(self):
        for label in ["Transfer balance", "Download balance", "View balance", "Balance", "Transfer Balance Statement"]:
            self.assertFalse(site.is_safe_control(label), label)

    def test_everything_venmo_shows_is_refused(self):
        # Every control the survey found on the start page and Statements.
        for label in ["Download CSV", "Send to email", "Transfer balance", "Pay or Request",
                      "Create a business profile", "Learn more", "Search", "Notifications", "Incomplete",
                      "Statements", "Profile", "Payment Methods", "Addresses", "Friends & Social", "Security",
                      "Tax Documents", "Privacy", "Connected Businesses", "Backup Payment", "Help Center",
                      "Log out", "Contact Us", "Manage Cookies", "Settings", "like", "comment",
                      "Load More", "Go paperless", "Crypto", "USD", "Open menu",
                      "Cash Out", "Add money", "Add a bank or card", "Buy Crypto", "Sell", "Split",
                      "Download PDF | Pay", "Send | Download PDF", "Download PDF and pay",
                      "Download statement for business", "", "   ", None]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Months(unittest.TestCase):
    def test_the_walk_is_finished_months_newest_first(self):
        self.assertEqual(site.months_to_walk(TODAY, limit=3), ["2026-09", "2026-08", "2026-07"])
        self.assertEqual(site.months_to_walk(date(2026, 1, 31), limit=2), ["2025-12", "2025-11"])
        self.assertEqual(len(site.months_to_walk(TODAY)), site.MAX_MONTHS)
        self.assertEqual(site.months_to_walk(TODAY, limit=0), [])

    def test_the_month_just_ended_waits_a_day(self):
        """On the 1st the month that ended last night is not walked yet,
        since the computer's date can be a day ahead of Venmo's own."""
        self.assertEqual(site.months_to_walk(date(2026, 10, 1), limit=2), ["2026-08", "2026-07"])
        self.assertEqual(site.months_to_walk(date(2026, 10, 2), limit=2), ["2026-09", "2026-08"])

    def test_the_walk_stops_at_the_start_date(self):
        self.assertEqual(site.months_to_walk(TODAY, floor="2026-07-31"), ["2026-09", "2026-08", "2026-07"])
        self.assertEqual(site.months_to_walk(TODAY, floor="2026-08-01"), ["2026-09", "2026-08"])
        self.assertEqual(site.months_to_walk(TODAY, floor="2026-10-01"), [])

    def test_a_start_date_past_two_years_is_walked_back_to(self):
        walk = site.months_to_walk(TODAY, floor="2023-10-01")
        self.assertEqual((len(walk), walk[0], walk[-1]), (36, "2026-09", "2023-10"))
        # Never past the first month a statement address can name.
        self.assertEqual(site.months_to_walk(TODAY, floor="1990-01-01")[-1], "2000-01")
        # A limit given still ends the walk when it comes first.
        self.assertEqual(site.months_to_walk(TODAY, floor="2020-01-01", limit=2), ["2026-09", "2026-08"])

    def test_month_of_and_month_end(self):
        self.assertEqual(site.month_of(" October   2026 "), "2026-10")
        for bad in ("october 2026", "Oct 2026", "October 26", "October 2026 PDF", "", None, "October 1999"):
            self.assertIsNone(site.month_of(bad), repr(bad))
        self.assertEqual(site.month_end("2024-02"), "2024-02-29")
        self.assertEqual(site.month_end("2025-02"), "2025-02-28")
        for bad in ("2025-13", "2025-1", "", None, "2025-01-31"):
            self.assertEqual(site.month_end(bad), "", repr(bad))

    def test_rules_name_the_file_as_the_month_end_venmo_statement(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        self.assertEqual(doc_types.classify_document("Venmo Statement 2026-09", rules)[:2],
                         ("Statement", "Statement"))
        self.assertTrue(doc_types.should_skip("Download CSV", rules))
        make_app(tempfile.mkdtemp(), "--discover")
        from storage import build_pdf_filename
        self.assertEqual(build_pdf_filename("2026-09-30", "Statement", ""), "2026-09-30 Venmo Statement.pdf")


class Listing(unittest.TestCase):
    def test_each_month_is_opened_by_its_address_and_listed_when_shown(self):
        page = Page()
        got = site.collect_download_docs(page, today=TODAY, limit=3)
        self.assertEqual([(d.document_id, d.date_text, d.title, d.href) for d in got],
                         [("2026-09", "2026-09-30", "Venmo Statement 2026-09", "/statement"),
                          ("2026-08", "2026-08-31", "Venmo Statement 2026-08", "/statement"),
                          ("2026-07", "2026-07-31", "Venmo Statement 2026-07", "/statement")])
        self.assertEqual(page.gotos[0], site.DOCUMENTS_URL)
        self.assertEqual([site.statement_query(u)["month"] for u in page.gotos[1:]], ["9", "8", "7"])
        self.assertEqual(page.listeners + page.requests, [], "every listener is taken off again")

    def test_a_month_the_page_will_not_show_stops_with_what_was_read(self):
        page = Page(refuse_before=(2026, 8))
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page, today=TODAY, limit=5)
        self.assertEqual([d.document_id for d in stop.exception.docs], ["2026-09", "2026-08"])

    def test_a_month_bound_by_page_state_needs_no_answer_heard(self):
        # Venmo's client cache answers some months without asking; the
        # page's own state is what binds the month.
        page = Page(heard=False)
        self.assertEqual([d.document_id for d in site.collect_download_docs(page, today=TODAY, limit=2)],
                         ["2026-09", "2026-08"])
        # Nor does an answer whose body cannot be read stop anything.
        self.assertEqual(len(site.collect_download_docs(Page(body=ValueError("gone")), today=TODAY, limit=1)), 1)
        self.assertEqual(len(site.collect_download_docs(Page(body="text"), today=TODAY, limit=1)), 1)

    def test_an_empty_month_is_skipped_and_the_walk_goes_on(self):
        self.assertEqual(site.collect_download_docs(Page(empty=True), today=TODAY, limit=3), [])
        page = Page(empty=True)
        real = page._month_shown

        def shown():
            # Only August 2026 has transactions.
            page.empty = "month=8&" not in page.url
            return real()
        page._month_shown = shown
        got = site.collect_download_docs(page, today=TODAY, limit=3)
        self.assertEqual([d.document_id for d in got], ["2026-08"])

    def test_two_years_whose_oldest_month_has_rows_are_not_the_whole_list(self):
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(Page(), today=TODAY)
        self.assertIsInstance(stop.exception, site.CapReached)
        got = [d.document_id for d in stop.exception.docs]
        self.assertEqual((len(got), got[0], got[-1]), (site.MAX_MONTHS, "2026-09", "2024-10"))

    def test_two_years_whose_oldest_month_is_empty_end_the_list(self):
        page = Page()
        real = page._month_shown

        def shown():
            # Only October 2024, the oldest of the two years, has none.
            page.empty = "month=10&" in page.url and "year=2024" in page.url
            return real()
        page._month_shown = shown
        got = site.collect_download_docs(page, today=TODAY)
        self.assertEqual((len(got), got[-1].document_id), (site.MAX_MONTHS - 1, "2024-11"))

    def test_a_start_date_past_two_years_is_listed_back_to(self):
        got = site.collect_download_docs(Page(), today=TODAY, floor="2023-10-01")
        self.assertEqual((len(got), got[-1].document_id), (36, "2023-10"))

    def test_a_month_that_says_it_is_empty_for_a_moment_is_waited_for(self):
        # "No transactions yet" for most of two seconds, then the rows.
        empty = {"months": ["September 2026"], "heading": True, "labels": [], "lists": 0, "rows": 0,
                 "kids": 0, "empty": True, "loading": 0}
        page = Page(states=[dict(empty) for _ in range(8)])
        self.assertEqual([d.document_id for d in site.collect_download_docs(page, today=TODAY, limit=1)],
                         ["2026-09"])

    def test_a_month_is_skipped_as_empty_only_once_that_has_held_two_seconds(self):
        page = Page(empty=True)
        self.assertEqual(site.collect_download_docs(page, today=TODAY, limit=1), [])
        self.assertGreaterEqual(sum(page.waited), 2000)

    def test_a_paged_month_is_listed_without_a_press(self):
        page = Page(rows=10, total=23)
        self.assertEqual(len(site.collect_download_docs(page, today=TODAY, limit=2)), 2)
        self.assertEqual(page.pressed, 0, "discovery presses nothing")

    def test_a_page_still_drawing_is_waited_for(self):
        drawing = {"months": ["September 2026"], "heading": True, "labels": [], "lists": 0, "rows": 0,
                   "kids": 0, "empty": False, "loading": 8}
        page = Page(states=[dict(drawing), dict(drawing)])
        self.assertEqual(len(site.collect_download_docs(page, today=TODAY, limit=1)), 1)

    def test_settled(self):
        ok = {"months": ["September 2026"], "heading": True, "lists": 1, "rows": 2, "kids": 2,
              "empty": False, "loading": 0}
        self.assertEqual(site.settled(ok, "2026-09"), "")
        self.assertEqual(site.settled(dict(ok, lists=0, rows=0, kids=0, empty=True), "2026-09"), "")
        for bad in (dict(ok, heading=False), dict(ok, months=[]), dict(ok, months=["August 2026"]),
                    dict(ok, months=["September 2026"] * 2), dict(ok, loading=2),
                    dict(ok, rows=0, kids=0), dict(ok, kids=3), dict(ok, lists=2),
                    dict(ok, lists=0, rows=0, kids=0), dict(ok, empty=True), {}):
            self.assertNotEqual(site.settled(bad, "2026-09"), "", repr(bad))

    def test_pending_transactions_are_never_an_empty_month(self):
        # Beside completed rows they change nothing. With none, the month
        # is neither read nor empty, whatever the page says.
        ok = {"months": ["September 2026"], "heading": True, "lists": 1, "rows": 2, "kids": 2,
              "empty": False, "loading": 0}
        self.assertEqual(site.settled(dict(ok, pending=1), "2026-09"), "")
        for bad in (dict(ok, lists=0, rows=0, kids=0, pending=1),
                    dict(ok, lists=0, rows=0, kids=0, pending=1, empty=True)):
            self.assertNotEqual(site.settled(bad, "2026-09"), "", repr(bad))

    def test_each_page_that_is_not_a_month_has_its_own_reason(self):
        # What a tester sends back says which page it was (#136).
        ok = {"months": ["September 2026"], "heading": True, "lists": 1, "rows": 2, "kids": 2,
              "empty": False, "loading": 0}
        none = dict(ok, lists=0, rows=0, kids=0)
        reasons = {site.settled(state, "2026-09") for state in (
            none, dict(none, pending=1), dict(ok, empty=True), dict(ok, kids=3))}
        self.assertEqual(len(reasons), 4, reasons)

    def test_only_venmo_s_two_sentences_are_an_empty_month(self):
        for said in ("No transactions yet for this month, but as soon as they start rolling in, "
                     "we\u2019ll list them here.",
                     "There are no transactions for these dates.\nTo view past transactions, "
                     "select new dates."):
            self.assertTrue(site.EMPTY_MONTH_RE.search(said), said)
        for said in ("Completed transactions", "Pending transactions", "No transactions", "no transactions",
                     "Your transaction history on this page hasn't loaded yet. Check back in a couple "
                     "of minutes.", "Error loading data", "We couldn't get the information for the "
                     "selected period. Please try again.", "To view past transactions, select new dates.",
                     "There are no statements for these dates."):
            self.assertIsNone(site.EMPTY_MONTH_RE.search(said), said)

    def test_a_stopped_month_keeps_what_its_page_held(self):
        page = Page(rows=0, kids=0, body={"data": {"transactionsHistory": {
            "completedTransaction": {"edges": []}, "pendingTransaction": {"edges": [{"node": {"note": FAKE_NAME}}]}}}})
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page, today=TODAY, limit=1)
        self.assertEqual(stop.exception.month, "2026-09")
        seen = stop.exception.seen
        self.assertEqual((seen["lists"], seen["rows"], seen["children"], seen["status"]), (1, 0, 0, 200))
        self.assertEqual(seen["answer"], {"errors": False, "completed": 0, "pending": 1})
        self.assertNotIn("Zyxwvut", repr(seen))

    def test_what_an_answer_held_is_counted_and_nothing_else(self):
        two = {"edges": [{"node": {"note": FAKE_NAME}}, {"node": None}]}
        self.assertEqual(site.answer_counts({"data": {"transactionsHistory": {
            "completedTransaction": two, "pendingTransaction": {"edges": []}}}}),
            {"errors": False, "completed": 2, "pending": 0})
        # A failed month, and an answer that holds no list for a part.
        failed = {"errors": [{"message": FAKE_NAME}], "data": None}
        self.assertEqual(site.answer_counts(failed), {"errors": True, "completed": None, "pending": None})
        self.assertEqual(site.answer_counts([failed]), {"errors": True, "completed": None, "pending": None})
        self.assertEqual(site.answer_counts({"data": {"transactionsHistory": {"completedTransaction": None}}}),
                         {"errors": False, "completed": None, "pending": None})
        for odd in ("text", 3, None, [], [1], {"data": "x"}, {"data": {"transactionsHistory": []}}):
            self.assertEqual(site.answer_counts(odd), {"errors": False, "completed": None, "pending": None},
                             repr(odd))

    def test_the_newest_answer_read_is_the_one_counted_and_a_new_month_starts_clean(self):
        def said(*bodies):
            heard = site.Heard()
            heard.on_request(Request(statement_url(9), navigation=True))
            for body in bodies:
                r = Response(GRAPHQL, 200, "TransactionsHistory", body=body)
                heard.on_request(r.request)
                heard.on_response(r)
            heard.statement()
            return heard
        one = {"data": {"transactionsHistory": {"completedTransaction": {"edges": [{}]}}}}
        none = {"data": {"transactionsHistory": {"completedTransaction": {"edges": []}}}}
        self.assertEqual(said(one, none).said["completed"], 0)
        self.assertEqual(said(none, ValueError("gone")).said["completed"], 0, "an answer not read counts nothing")
        heard = said(one)
        heard.on_request(Request(statement_url(8), navigation=True))
        self.assertIsNone(heard.said)

    def test_a_month_not_drawn_whole_stops(self):
        for page in (Page(heading=False), Page(picker=[]), Page(rows=0, kids=0),
                     Page(picker=["September 2026", "August 2026"]), Page(loading=8),
                     Page(kids=4), Page(lists=2), Page(empty=True, lists=1),
                     Page(rows=10, total=23, pagers=1, labels=["Load more"]),
                     Page(labels=["Download CSV", "Load More"]), Page(labels=["Show more"])):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page, today=TODAY, limit=1)
            self.assertEqual(page.listeners + page.requests, [])

    def test_a_late_answer_from_the_page_before_is_never_taken(self):
        stale = Response(GRAPHQL, 401, "TransactionsHistory")
        self.assertEqual(len(site.collect_download_docs(Page(heard=False, stale=stale), today=TODAY, limit=1)), 1,
                         "a late 401 for another page is not this month's")
        stale = Response(GRAPHQL, 200, "TransactionsHistory", body={"pageInfo": {"hasNextPage": True}})
        self.assertEqual(len(site.collect_download_docs(Page(heard=False, stale=stale), today=TODAY, limit=1)), 1)
        # Nor one whose request was made before this navigation began.
        early = Response(GRAPHQL, 200, "TransactionsHistory")
        heard = site.Heard()
        heard.on_request(early.request)
        heard.on_request(Request(statement_url(9), navigation=True))
        heard.on_response(early)
        self.assertIsNone(heard.statement())

    def test_an_answer_that_says_more_is_coming_stops(self):
        for body in ({"data": {"t": {"pageInfo": {"hasNextPage": True, "endCursor": "x"}}}},
                     {"data": {"t": {"items": [], "nextId": "123"}}},
                     {"data": {"t": [{"hasMore": True}]}}):
            with self.assertRaises(site.ListStopped, msg=repr(body)):
                site.collect_download_docs(Page(body=body), today=TODAY, limit=1)
        for body in (WHOLE, {"data": {"t": {"items": [], "nextId": None}}}, {"data": {}}):
            self.assertEqual(len(site.collect_download_docs(Page(body=body), today=TODAY, limit=1)), 1)

    def test_the_newest_answer_read_says_whether_more_is_to_come(self):
        more = {"data": {"t": {"pageInfo": {"hasNextPage": True, "endCursor": "x"}}}}

        def heard_after(*bodies):
            heard = site.Heard()
            heard.on_request(Request(statement_url(9), navigation=True))
            for body in bodies:
                r = Response(GRAPHQL, 200, "TransactionsHistory", body=body)
                heard.on_request(r.request)
                heard.on_response(r)
            heard.statement()
            return heard.partial
        self.assertFalse(heard_after(more, WHOLE), "the answer with the last rows clears the first")
        self.assertTrue(heard_after(WHOLE, more))
        self.assertTrue(heard_after(more, ValueError("gone")), "an answer not read clears nothing")

    def test_more_to_come(self):
        self.assertFalse(site.more_to_come({"pageInfo": {"hasNextPage": False, "endCursor": "abc"}}))
        self.assertTrue(site.more_to_come({"pageInfo": {"hasNextPage": True}}))
        self.assertTrue(site.more_to_come({"next": "abc"}))
        self.assertFalse(site.more_to_come({"next": ""}))
        self.assertFalse(site.more_to_come([]))
        self.assertFalse(site.more_to_come(None))

    def test_an_answer_from_another_host_or_operation_is_not_heard(self):
        others = [Response("https://evil.test/graphql", 200, "TransactionsHistory"),
                  Response("https://api.venmo.com/graphql/x", 200, "TransactionsHistory"),
                  Response("https://api.venmo.com/graphql", 200, "Identity")]
        heard = site.Heard()
        heard.on_request(Request(statement_url(9), navigation=True))
        for r in others:
            heard.on_request(r.request)
            heard.on_response(r)
        self.assertIsNone(heard.statement())

    def test_a_page_that_settles_off_the_month_or_profile_stops(self):
        for settle in (f"https://{HOST}/", statement_url(8, 2026), statement_url(account="business"),
                       f"https://{HOST}/statement", "https://www.paypal.com/myaccount/statements"):
            with self.assertRaises(site.ListStopped, msg=settle):
                site.collect_download_docs(Page(settle=settle), today=TODAY, limit=1)
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(plain_settles=statement_url(account="business")), today=TODAY)

    def test_a_signed_out_page_or_answer_is_session_expired(self):
        for page in (Page(settle="https://id.venmo.com/signin?return=statement"),
                     Page(settle=f"https://{HOST}/account/logout"),
                     Page(password=True), Page(status=401), Page(status=403)):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page, today=TODAY, limit=1)

    def test_login_check(self):
        self.assertTrue(site.bill_list_opens(Page()))
        self.assertFalse(site.bill_list_opens(Page(heading=False)))
        self.assertFalse(site.bill_list_opens(Page(settle="https://id.venmo.com/signin")))
        self.assertTrue(site.goto_documents(Page()))
        self.assertFalse(site.goto_documents(Page(settle=f"https://{HOST}/")))


class SignedOut(unittest.TestCase):
    def test_sign_in_shapes(self):
        self.assertTrue(site.looks_signed_out(Page(start="https://id.venmo.com/signin")))
        self.assertTrue(site.looks_signed_out(Page(start=f"https://{HOST}/account/logout")))
        self.assertTrue(site.looks_signed_out(Page(start=site.DOCUMENTS_URL, password=True)))
        self.assertFalse(site.looks_signed_out(Page(start=statement_url())))

    def test_a_dead_page_raises(self):
        with self.assertRaises(RuntimeError):
            site.looks_signed_out(Dead())


class Download(WithPrinter):
    def save(self, page, month="2026-09", date_="2026-09-30", href="/statement", today=TODAY,
             profile=None):
        out = Path(tempfile.mkdtemp()) / "o.pdf"
        ok = site.download_bill(page, None, date_, out, trace=[], href=href, document_id=month, today=today,
                                profile=site.profile_tag(FAKE_PROFILE_ID) if profile is None else profile)
        return ok, out

    def test_the_month_just_ended_is_not_printed_on_the_first(self):
        ok, out = self.save(Page(), today=date(2026, 10, 1))
        self.assertFalse(ok)
        self.assertFalse(out.exists())
        ok, out = self.save(Page(), today=date(2026, 10, 2))
        self.assertTrue(ok)

    def test_a_paged_month_is_drawn_whole_before_it_is_printed(self):
        page = Page(rows=10, total=23)
        drawn = {}
        out = Path(tempfile.mkdtemp()) / "o.pdf"
        self.assertTrue(site.download_bill(page, None, "2026-09-30", out, trace=[], href="/statement",
                                           document_id="2026-09", today=TODAY,
                                           profile=site.profile_tag(FAKE_PROFILE_ID), drawn=drawn))
        self.assertEqual(page.pressed, 2)
        self.assertEqual(drawn, {"rows": 23})
        self.assertEqual([p["step"] for p in self.presser.presses], ["show more of the month"] * 2)
        self.assertEqual({p["css"] for p in self.presser.presses}, {site.SHOW_MORE_CSS})
        self.assertEqual(len(self.printer.printed), 1)

    def test_a_sign_out_answered_to_a_show_more_press_stops_the_run(self):
        page = Page(rows=10, total=23)

        def answer_401(p):
            r = Response(GRAPHQL, 401, "TransactionsHistory")
            p._fire("request", r.request)
            p._fire("response", r)
        page.after_press = answer_401
        with self.assertRaises(site.SessionExpired):
            self.save(page)
        self.assertEqual(page.pressed, 1)
        self.assertEqual(self.printer.printed, [])
        self.assertEqual(page.listeners + page.requests, [], "the listener is taken off")

    def test_a_show_more_press_that_moves_the_page_prints_nothing(self):
        for where in (statement_url(8), statement_url(9, profile="9988776655443322"),
                      statement_url(9, account="business"), f"https://{HOST}/"):
            page = Page(rows=10, total=23)

            def move(p, where=where):
                p.url = where
            page.after_press = move
            ok, out = self.save(page)
            self.assertFalse(ok, where)
            self.assertFalse(out.exists())
        self.assertEqual(self.printer.printed, [])

    def test_the_last_check_before_printing(self):
        where = site.Where("personal", FAKE_PROFILE_ID)
        heard = site.Heard()
        page = Page(start=statement_url(9))
        site.ready_to_print(page, where, "2026-09", heard)
        for bad in (Page(start=statement_url(9), labels=["Load more"]),
                    Page(start=statement_url(9), rows=10, total=23),
                    Page(start=statement_url(9), empty=True),
                    Page(start=statement_url(8)), Page(start=statement_url(9), loading=3)):
            with self.assertRaises(site.ListStopped):
                site.ready_to_print(bad, where, "2026-09", heard)
        with self.assertRaises(site.SessionExpired):
            site.ready_to_print(Page(start=statement_url(9), password=True), where, "2026-09", heard)

    def test_a_show_more_that_draws_nothing_or_never_ends_prints_nothing(self):
        for page in (Page(rows=10, total=23, grow=0), Page(rows=1, total=10_000, grow=1),
                     Page(rows=10, total=23, pager_label="Show more and pay"),
                     Page(rows=10, total=23, pagers=2)):
            ok, out = self.save(page)
            self.assertFalse(ok)
            self.assertFalse(out.exists())
            self.assertLessEqual(page.pressed, site.SHOW_MORE_PRESSES)
        self.assertEqual(self.printer.printed, [])

    def test_a_turned_off_show_more_leaves_the_month_and_the_run_goes_on(self):
        def turned_off(page, locator, **kw):
            raise site.pressing.TurnedOff(kw["step"], "the control is turned off",
                                          ["The Show more control is turned off on the page."])
        site.pressing.click = turned_off
        page = Page(rows=10, total=23)
        ok, out = self.save(page)
        self.assertFalse(ok)
        self.assertFalse(out.exists())
        self.assertEqual(self.printer.printed, [])
        self.assertEqual(page.listeners + page.requests, [], "the listener is taken off")

    def test_nothing_is_printed_while_the_newest_answer_says_more_is_to_come(self):
        more = {"data": {"t": {"pageInfo": {"hasNextPage": True, "endCursor": "x"}}}}

        def answer(p, body):
            r = Response(GRAPHQL, 200, "TransactionsHistory", body=body)
            p._fire("request", r.request)
            p._fire("response", r)
        # Every press's answer says more is to come, while the page draws
        # every row and no Show more.
        page = Page(rows=10, total=23, body=more)
        page.after_press = lambda p: answer(p, more)
        ok, out = self.save(page)
        self.assertFalse(ok)
        self.assertFalse(out.exists())
        self.assertEqual(self.printer.printed, [])
        # The answer to the press that drew the last rows says the list is whole.
        page = Page(rows=10, total=23, body=more)
        page.after_press = lambda p: answer(p, more if p.rows < p.total else WHOLE)
        ok, out = self.save(page)
        self.assertTrue(ok)
        self.assertEqual(len(self.printer.printed), 1)

    def test_the_only_label_pressed_is_show_more(self):
        for label in ("Show more", "show  more", " Show More "):
            self.assertTrue(site.is_show_more(label), label)
        for label in ("Show more details", "Show", "Load more", "Show more | Pay", "Send", "", None):
            self.assertFalse(site.is_show_more(label), repr(label))

    def test_another_profile_stops_the_run_and_prints_nothing(self):
        page = Page(plain_settles=statement_url(profile="9988776655443322"))
        with self.assertRaises(site.ProfileChanged):
            self.save(page)
        self.assertEqual(self.printer.printed, [])
        self.assertEqual(len(page.gotos), 1, "no month is opened")

    def test_the_month_is_printed_once_it_is_shown(self):
        page = Page()
        ok, out = self.save(page)
        self.assertTrue(ok)
        self.assertTrue(out.read_bytes().startswith(b"%PDF-"))
        self.assertEqual(len(self.printer.printed), 1)
        self.assertEqual(site.statement_query(self.printer.printed[0])["month"], "9")

    def test_nothing_is_printed_for_a_wrong_record(self):
        for kw in (dict(date_="2026-09-29"), dict(month="", date_=""), dict(href=statement_url()),
                   dict(month="2026-10", date_="2026-10-31"), dict(month="2026-13", date_=""),
                   dict(profile="")):
            page = Page()
            ok, out = self.save(page, **kw)
            self.assertFalse(ok, kw)
            self.assertEqual(page.gotos, [], kw)
            self.assertFalse(out.exists())
        self.assertEqual(self.printer.printed, [])

    def test_nothing_is_printed_when_the_month_is_not_shown_whole(self):
        for page in (Page(rows=0, kids=0), Page(picker=["October 2026"]), Page(settle=statement_url(8)),
                     Page(labels=["Load More"]), Page(loading=8), Page(heading=False),
                     Page(body={"pageInfo": {"hasNextPage": True}})):
            ok, out = self.save(page)
            self.assertFalse(ok)
            self.assertFalse(out.exists())
        self.assertEqual(self.printer.printed, [])

    def test_signed_out_raises_and_prints_nothing(self):
        for page in (Page(settle="https://id.venmo.com/signin"), Page(status=401), Page(password=True)):
            with self.assertRaises(site.SessionExpired):
                self.save(page)
        self.assertEqual(self.printer.printed, [])

    def test_a_failed_or_non_pdf_print_keeps_nothing(self):
        site.receipt_pdf.print_page_to_pdf = Printer(fail=True)
        ok, out = self.save(Page())
        self.assertFalse(ok)
        self.assertFalse(out.exists())
        site.receipt_pdf.print_page_to_pdf = Printer(body=b"<html>")
        ok, out = self.save(Page())
        self.assertFalse(ok)
        self.assertFalse(out.exists())


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class HeldDay(date):
    """The app's own clock, held at TODAY for the runs these tests start. A
    run walks back from the day the app reads, so on the real clock its
    newest month moves every month, and on the 1st it holds back one month
    more (SETTLE_DAYS)."""

    @classmethod
    def today(cls):
        return TODAY


class Orchestrator(WithPrinter):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self._date, site._date = site._date, HeldDay

    def tearDown(self):
        site._date = self._date
        super().tearDown()

    def test_config_example_is_unique_and_holds_no_one(self):
        config = json.loads((HERE / "config.example.json").read_text())
        self.assertEqual(config["cdp_url"], "http://127.0.0.1:9295")
        self.assertEqual(config["pilot_count"], 1)
        self.assertEqual(config["owner"], "")
        self.assertEqual(config["output_dir"], ".")

    def test_persisted_record_has_no_query_and_is_keyed_by_the_month(self):
        app = make_app(self.tmp, "--discover")
        for r in site.collect_download_docs(Page(), today=TODAY, limit=2):
            app._record_rawdoc(r, statement_url())
        app.discovery.save()
        text = app.paths.discovery_json.read_text()
        self.assertNotIn("?", text)
        self.assertNotIn(FAKE_PROFILE_ID, text)
        tag = site.profile_tag(FAKE_PROFILE_ID)
        rec = app.discovery.get(f"id:{tag}:2026-09")
        self.assertEqual((rec["href"], rec["document_id"], rec["account"], rec["summary"], rec["date"]),
                         ("/statement", "2026-09", tag, "Statement", "2026-09-30"))
        self.assertEqual(docs.told_apart_by(rec), "2026-09", "only a taken name gets the month")

    def test_an_expired_session_stops_the_run_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.collect_download_docs(Page(), today=TODAY, limit=2):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page(status=401)
        app._delay = lambda *a, **k: None
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.process(app._select())
        self.assertIn("signed out", said.getvalue())
        self.assertEqual(app.progress.data, {})
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)

    def test_an_expired_session_during_discovery_stops_the_run(self):
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(settle="https://id.venmo.com/signin", start=statement_url())
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(app.discovery.data, {})
        self.assertIn("signed out", out.getvalue())
        self.assertNotIn("Press Enter", out.getvalue())

    def test_a_list_that_stops_keeps_what_was_read_and_is_not_whole(self):
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(refuse_before=(2026, 8), start=statement_url())
        from paperpull_core import listing
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertTrue({f"id:{site.profile_tag(FAKE_PROFILE_ID)}:2026-08"} <= set(app.discovery.data))
        self.assertIn("stopped partway", said.getvalue())
        self.assertTrue(hasattr(listing, "read_whole"))

    def test_a_list_that_stops_says_what_the_page_held_in_the_failure_file(self):
        app = make_app(self.tmp, "--discover")
        page = Page(rows=0, kids=0, start=statement_url(), body={"errors": [{"message": FAKE_NAME}], "data": None})
        app.page = lambda: page
        app.check_session = lambda p: None
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertIn("It stopped on 2026-09.", said.getvalue())
        text = next(app.paths.diagnostics.glob("failure-*.json")).read_text(encoding="utf-8")
        for word in (FAKE_PROFILE_ID, "Zyxwvut", "Qponmlk"):
            self.assertNotIn(word, text, word)
        seen = json.loads(text)["extra"]["month_page"]
        self.assertEqual((seen["lists"], seen["rows"], seen["children"], seen["pending"], seen["status"]),
                         (1, 0, 0, 0, 200))
        self.assertEqual(seen["answer"], {"errors": True, "completed": None, "pending": None})

    def test_a_resume_on_another_profile_stops_and_records_nothing(self):
        app = make_app(self.tmp, "--resume")
        for r in site.collect_download_docs(Page(), today=TODAY, limit=2):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page(plain_settles=statement_url(profile="9988776655443322"))
        app._delay = lambda *a, **k: None
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.process(app._select())
        self.assertIn("another Venmo profile", said.getvalue())
        self.assertEqual(app.progress.data, {})
        self.assertEqual(self.printer.printed, [])
        self.assertNotIn("9988776655443322", said.getvalue())

    def test_an_error_s_own_text_reaches_no_log_record_or_diagnostic(self):
        app = make_app(self.tmp, "--all")
        for r in site.collect_download_docs(Page(), today=TODAY, limit=1):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def boom(*a, **k):
            raise RuntimeError("Target crashed at " + statement_url(9) + " for " + FAKE_NAME)
        original = site.download_bill
        site.download_bill = boom
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(seen):
                app.process(app._select())
        finally:
            site.download_bill = original
            root.removeHandler(handler)
            root.setLevel(old)
        self.assertEqual(app.stats["failed"], 1)
        files = "".join(p.read_text(errors="ignore") for p in Path(self.tmp).rglob("*")
                        if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"))
        for word in (FAKE_PROFILE_ID, "Zyxwvut", "Target crashed"):
            self.assertNotIn(word, seen.getvalue(), word)
            self.assertNotIn(word, files, word)
        self.assertIn("RuntimeError", json.dumps(app.progress.data))

    def test_discovery_honors_the_start_date(self):
        app = make_app(self.tmp, "--discover", "--start-date", "2026-06-01")
        page = Page(start=statement_url())
        app.page = lambda: page
        app.check_session = lambda p: None
        with redirect_stdout(io.StringIO()):
            app.cmd_discover()
        months = sorted(r["document_id"] for r in app.discovery.data.values())
        self.assertEqual(months[0], "2026-06")
        self.assertNotIn(f"{TODAY:%Y-%m}", months, "the month under way is never listed")

    def capped_app(self, *args):
        """An app whose Venmo has transactions in every month, so a walk
        with no start date stops at two years (CapReached). Each month is
        printed as a PDF that passes the run's own check."""
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_metadata({"/Subject": "x" * 3000})
        body = io.BytesIO()
        writer.write(body)
        self.printer.body = body.getvalue()
        app = make_app(self.tmp, *args)
        page = Page(start=statement_url())
        app.page = lambda: page
        app.check_session = lambda p: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None
        return app

    def test_discover_alone_lists_two_years_and_ends_as_a_run_that_stopped(self):
        from unittest import mock
        from paperpull_core import listing
        make_app(self.tmp, "--discover")
        page = Page(start=statement_url())
        with mock.patch.object(docs.App, "page", lambda app: page), \
                mock.patch.object(docs.App, "check_session", lambda app, p: None), \
                redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit) as stop:
            docs.main(["--discover", "--config", str(Path(self.tmp) / "config.json")])
        self.assertEqual(stop.exception.code, 1)
        said = said.getvalue()
        self.assertIn("Documents known: %d" % site.MAX_MONTHS, said, "the months read are listed")
        self.assertIn("Months older than the two years read were not listed", said)
        self.assertIn("default_start_date", said)
        app = make_app(self.tmp, "--discover")
        self.assertEqual(len(app.discovery.data), site.MAX_MONTHS, "what was read is kept")
        self.assertEqual(listing.last(app), listing.STOPPED)
        self.assertEqual(list(app.paths.diagnostics.glob("failure-*.json")), [], "nothing went wrong")

    def test_a_run_stopped_at_two_years_takes_what_it_read_and_then_stops(self):
        app = self.capped_app("--all", "--yes")
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit) as stop:
            app.cmd_run("all")
        self.assertEqual(stop.exception.code, 1)
        self.assertEqual(len(self.printer.printed), site.MAX_MONTHS, "every month read is saved")
        self.assertEqual(app.stats["statements"], site.MAX_MONTHS)
        self.assertIn("Months older than the two years read were not listed", said.getvalue())

    def test_a_pilot_stopped_at_two_years_takes_its_statement_and_then_stops(self):
        app = self.capped_app("--pilot")
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit) as stop:
            app.cmd_pilot()
        self.assertEqual(stop.exception.code, 1)
        self.assertEqual(len(self.printer.printed), 1)
        self.assertIn("No problems detected in the pilot", said.getvalue())
        self.assertIn("Months older than the two years read were not listed", said.getvalue())

    def test_a_resume_after_a_run_stopped_at_two_years_is_not_finished(self):
        app = self.capped_app("--all", "--yes")
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            app.cmd_run("all")
        self.assertEqual(len(self.printer.printed), site.MAX_MONTHS)
        app = self.capped_app("--resume")
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.cmd_resume()
        self.assertNotIn("everything in scope is complete", said.getvalue())
        self.assertIn("not read to its end", said.getvalue())
        self.assertEqual(len(self.printer.printed), site.MAX_MONTHS, "nothing is taken twice")

    def test_discovery_of_one_year_goes_back_to_its_first_month(self):
        year = TODAY.year - 1
        app = make_app(self.tmp, "--discover", "--year", str(year))
        page = Page(start=statement_url())
        app.page = lambda: page
        app.check_session = lambda p: None
        with redirect_stdout(io.StringIO()):
            app.cmd_discover()
        months = sorted(r["document_id"] for r in app.discovery.data.values())
        self.assertEqual(months[0], "%d-01" % year)
        self.assertIn("%d-12" % year, months)

    def test_discovery_goes_back_to_a_start_date_past_two_years(self):
        app = make_app(self.tmp, "--discover", "--start-date", "2023-10-01")
        page = Page(start=statement_url())
        app.page = lambda: page
        app.check_session = lambda p: None
        with redirect_stdout(io.StringIO()):
            app.cmd_discover()
        months = sorted(r["document_id"] for r in app.discovery.data.values())
        self.assertEqual((len(months), months[0], months[-1]), (36, "2023-10", "2026-09"))

    def test_the_statements_tab_is_preferred_and_a_dead_tab_passed_over(self):
        class Tab:
            def __init__(self, url, closed=False, dead=False):
                self._url, self.closed, self.dead = url, closed, dead

            def is_closed(self):
                return self.closed

            @property
            def url(self):
                if self.dead:
                    raise RuntimeError("Target page, context or browser has been closed")
                return self._url

        class Ctx:
            pass
        mail, home = Tab("https://mail.example/"), Tab(f"https://{HOST}/")
        statements = Tab(statement_url())
        ctx = Ctx()
        ctx.pages = [mail, Tab(f"https://{HOST}/x", dead=True), home, Tab(statement_url(), closed=True), statements]
        self.assertIs(docs.App._venmo_tab(ctx), statements)
        ctx.pages = [mail, home]
        self.assertIs(docs.App._venmo_tab(ctx), home)
        ctx.pages = [mail, Tab("https://account.venmo.com.evil.test/statement")]
        self.assertIsNone(docs.App._venmo_tab(ctx))

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


class Privacy(WithPrinter):
    """Nothing that names the account holder reaches a log line, the
    console, a record or a file name, and all of it is registered as
    private words before anything is printed."""

    def test_profile_details_stay_out_of_logs_stdout_and_files(self):
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
                for r in site.collect_download_docs(Page(), limit=2):
                    app._record_rawdoc(r, statement_url())
                app.discovery.save()
                app.check_session = lambda p: None
                app._delay = lambda *a, **k: None
                app._on_its_site = lambda: Page()
                app.process(app._select(limit=1))
                with self.assertRaises(site.ListStopped):
                    site.collect_download_docs(Page(settle=statement_url(account="business")), limit=1)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        out = seen.getvalue() + app.paths.discovery_json.read_text() + app.paths.progress_json.read_text()
        for word in (FAKE_PROFILE_ID, FAKE_HANDLE, FAKE_HANDLE[1:], "Zyxwvut", "Qponmlk", FAKE_EMAIL, "010-4477"):
            self.assertNotIn(word, out, word)
        for word in (FAKE_PROFILE_ID, FAKE_HANDLE, FAKE_HANDLE[1:], "Zyxwvut", "Qponmlk", FAKE_EMAIL):
            self.assertIn(word, site.private_words(), word)
        self.assertNotIn(FAKE_PROFILE_ID, site.redact("profile " + FAKE_PROFILE_ID))
        self.assertIn("Statement", site.redact("CAPTCHA Statement Venmo"), "Venmo's own words are not private")
        self.assertIn("Tester", site.private_words(), "the owner's name is kept beside them")
        self.assertEqual(len(site.private_words()), len(set(site.private_words())), "nothing twice")
        names = [p.name for p in app.paths.root.rglob("*.pdf")]
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r"^\d{4}-\d{2}-\d{2} Venmo Statement\.pdf$")

    def test_the_profile_id_is_registered_before_anything_is_printed(self):
        site.set_private_words(["Tester Example"])
        when = []
        printer = self.printer

        def spy(page, out_path):
            when.append(FAKE_PROFILE_ID in site.private_words())
            printer(page, out_path)
        site.receipt_pdf.print_page_to_pdf = spy
        out = Path(tempfile.mkdtemp()) / "o.pdf"
        self.assertTrue(site.download_bill(Page(), None, "2026-09-30", out, href="/statement",
                                           document_id="2026-09", today=TODAY,
                                           profile=site.profile_tag(FAKE_PROFILE_ID)))
        self.assertEqual(when, [True])

    def test_only_the_operation_name_of_a_graphql_body_is_read(self):
        heard = site.Heard()
        answer = Response("https://api.venmo.com/graphql", 200, "TransactionsHistory")
        heard.on_request(Request(statement_url(9), navigation=True))
        heard.on_request(answer.request)
        heard.on_response(answer)
        self.assertEqual(heard.answers, [("TransactionsHistory", 200)])
        self.assertNotIn(FAKE_PROFILE_ID, repr(heard.answers))
        self.assertEqual(site._operation("not json"), "")
        self.assertEqual(site._operation('[{"operationName":"TransactionsHistory"},{"operationName":"Identity"}]'),
                         "TransactionsHistory")

    def test_private_parts(self):
        got = site.private_parts([FAKE_HANDLE, "Al Bo", "Venmo", "statement", "https://account.venmo.com/u/x",
                                  "", None, FAKE_PHONE])
        self.assertTrue({FAKE_HANDLE, FAKE_HANDLE[1:], "555", "010-4477"} <= got)
        self.assertNotIn("Al", got, "a short part is not a word")
        self.assertNotIn("Venmo", got)
        self.assertFalse(any(" " in p for p in got))
        self.assertFalse(any(p.startswith("http") for p in got))
        self.assertEqual(site.private_parts(None), set())

    def test_the_survey_writes_paths_and_field_names_never_values(self):
        site.set_private_words(["Tester Example"])
        answer = {"inputs": [{"type": "text", "role": "", "value": "October 2026"},
                             {"type": "text", "role": "", "value": FAKE_NAME}],
                  "controls": [{"tag": "button", "text": "Download CSV", "href": "", "download": False},
                               {"tag": "a", "text": FAKE_NAME, "href": f"/u/{FAKE_HANDLE[1:]}", "download": False},
                               {"tag": "a", "text": "Log out", "href": "/account/logout", "download": False}]}
        page = Page(survey=answer)
        report = site.survey(page, dwell_ms=0)
        text = json.dumps(report)
        for word in (FAKE_PROFILE_ID, "Zyxwvut", "Qzxv"):
            self.assertNotIn(word, text, word)
        p = report["pages"][0]
        self.assertEqual(p["query_fields"], ["accountType", "month", "profileId", "year"])
        self.assertTrue(p["statement_address"])
        self.assertEqual(p["inputs"][0]["month"], "2026-10")
        self.assertEqual([c["safe"] for c in p["controls"]], [False, False, False])
        self.assertEqual(p["graphql_heard"], [{"operation": "TransactionsHistory", "status": 200}])
        self.assertEqual(page.gotos, [site.DOCUMENTS_URL], "the survey opens only Statements")
        self.assertEqual(page.listeners + page.requests, [])


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_takes_a_download(self):
        tree = ast.parse((HERE / "venmo_site.py").read_text(encoding="utf-8"))
        clicks = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "click"]
        # The one press: pressing.click, in show_all, on the list's own pager.
        self.assertEqual(len(clicks), 1)
        self.assertEqual(ast.unparse(clicks[0].func), "pressing.click")
        self.assertIn("css=SHOW_MORE_CSS", ast.unparse(clicks[0]))
        owner = [f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                 and any(n is clicks[0] for n in ast.walk(f))]
        self.assertEqual(owner, ["show_all"])
        guarded = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "show_all"][0]
        self.assertIn("is_show_more(label)", ast.unparse(guarded))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)} - {"click"}
        for verb in ("dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially", "expect_download",
                     "save_as", "fetch", "new_page"):
            self.assertNotIn(verb, called, verb)
        listened = [n.args[0].value for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("on", "once") and n.args and isinstance(n.args[0], ast.Constant)]
        self.assertEqual(set(listened), {"request", "response"}, "only the page's own traffic is heard")


if __name__ == "__main__":
    unittest.main()
