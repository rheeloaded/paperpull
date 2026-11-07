"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import io
import itertools
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
import sdge_site as site  # noqa: E402
import sdge_docs as docs  # noqa: E402

HOST = "myenergycenter.com"
ID1, ID2, ID3 = "ISU000000000101", "ISU000000000102", "ISU000000000103"
PDF_URL = f"https://{HOST}/portal/BillingHistory/DownloadBillPdf?invoiceId={ID1}"


def laid_out(*texts):
    """Cells as the page reader returns them, one column and one row each,
    in order."""
    return [{"text": t, "at": n, "wide": 1, "tall": 1} for n, t in enumerate(texts)]


# The header the bill table draws, a control column first, and each row
# under it with its Due Date beside the Statement Date.
HEADS = laid_out("", "Statement Date", "Due Date", "Amount Due", "Status")


def row(inv, statement, due="Oct 14, 2026"):
    return {"id": inv, "cells": laid_out("", statement, due, "$1.00", "Billed")}


ROWS = [row(ID1, "Sep 12, 2026"), row(ID2, "Aug 13, 2026"), row(ID3, "Jul 14, 2026")]


# These pages stand still, so the wait for rows to settle need not be long.
# It cannot go under ready.POLL_MS.
SHORT_WAIT = mock.patch.object(site, "ROWS_QUIET_MS", 1)


def setUpModule():
    SHORT_WAIT.start()


def tearDownModule():
    SHORT_WAIT.stop()


# The live table's header, and a bill row led by its hidden number.
LIVE_HEADS = laid_out("Statement Date", "Due Date", "Days in Billing Cycle", "Current Charges",
                      "Amount Due", "Status", "Details")


def numbered(inv, number, statement):
    return {"id": inv, "number": number,
            "cells": laid_out(number, statement, "Oct 14, 2031", "30", "$1.00", "$1.00", "Billed",
                              "")}


LIVE_ROWS = [numbered(ID1, "1", "Sep 12, 2031"), numbered(ID2, "2", "Aug 13, 2031"),
             numbered(ID3, "3", "Jul 14, 2031")]
LIVE_DATES = ["2031-09-12", "2031-08-13", "2031-07-14"]


def near(said="", press=False, pager=False):
    """One thing drawn near the table, as the page reader returns it."""
    return {"said": said, "press": press, "pager": pager}
# Invented account details, which must never leave through a log, the
# console or a diagnostic.
FAKE_ACCOUNT = "987650001234"
FAKE_CONTRACT = "876540009876"
FAKE_STREET = "Zyxwvut"


class Resp:
    def __init__(self, status=200, ctype="application/pdf", body=b"%PDF-1.4 x", location="", extra=None):
        self.status, self.ok = status, status == 200
        self.headers = {"content-type": ctype, **({"location": location} if location else {}), **(extra or {})}
        self._body, self.url, self.disposed = body, "", False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


class Req:
    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_redirects")))
        r = self.answers.pop(0)
        r.url = url
        return r


class Locator:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n

    def inner_text(self, **kw):
        return ""


class Page:
    """Billing History as the portal draws it, with nothing pressed."""

    def __init__(self, rows=ROWS, empty="", ready=True, settled=None, password=False,
                 answers=(), accounts=1, start=f"https://{HOST}/portal/Dashboard/index",
                 api=None, info="", heads=HEADS, around=None):
        self.rows, self.empty, self.ready, self.settled = list(rows), empty, ready, settled
        self.api, self.info, self.heads, self.around = api, info, heads, around
        self.password, self.accounts, self.url, self.gotos = password, accounts, start, []
        page = self

        class Ctx:
            request = Req(answers)
            pages = [page]
        self.context = Ctx()

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = self.settled or url

    def wait_for_selector(self, sel, **kw):
        if self.rows and self.ready:
            return
        if "dataTables_empty" in sel and self.empty and self.ready:
            return
        raise TimeoutError("waited")

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        return Locator(1 if ("password" in sel and self.password) else 0)

    def title(self):
        return "My Energy Center"

    def evaluate(self, js, selector=None):
        if selector == site.BILL_ROW:
            return len(self.rows)
        if "accountList" in js:
            words = []
            for i in range(self.accounts):
                words += [f"{FAKE_ACCOUNT}{i}", f"{FAKE_ACCOUNT}{i}", f"{FAKE_CONTRACT}{i}",
                          f"100 {FAKE_STREET} Ave San Diego CA", f"{FAKE_ACCOUNT}{i} - 100 {FAKE_STREET} Ave"]
            return {"count": self.accounts, "words": words + [FAKE_CONTRACT]}
        return {"rows": [dict(r) for r in self.rows], "heads": self.heads, "empty": self.empty,
                "api": self.api, "info": self.info, "around": self.around}

    def is_closed(self):
        return False


class Dead:
    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")


class Hosts(unittest.TestCase):
    def test_only_the_portal_host_over_https(self):
        for u in [f"https://{HOST}/portal/", f"https://{HOST}/portal/BillingHistory/index", PDF_URL]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["https://www.sdge.com/my-energy-center", f"http://{HOST}/portal/", f"https://user@{HOST}/portal/",
                  f"https://{HOST}@evil.test/portal/", f"https://ent.{HOST}/portal/", f"https://{HOST}.evil.test/",
                  f"https://{HOST}:8443/portal/", f"blob:https://{HOST}/0b1c", "https://sdge-ortsvc.smartcmobile.net/APIService/x",
                  "https://ipn4.paymentus.com/rotp/sdg", "javascript:alert(1)", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_a_bill_address_is_one_shape_only(self):
        self.assertTrue(site.is_download_url(PDF_URL))
        self.assertEqual(site.download_url(ID1), PDF_URL)
        base = f"https://{HOST}/portal/BillingHistory/DownloadBillPdf"
        for u in [base, f"{base}?invoiceId=", f"{base}?invoiceId=ISU12345", f"{base}?invoiceId=isu000000000101",
                  f"{base}?invoiceId=ISU0000000001011", f"{base}?invoiceId={ID1}&invoiceId={ID2}",
                  f"{base}?invoiceId={ID1}&type=Bill", f"{base}?invoiceId=%49SU000000000101", f"{base}?invoiceId={ID1}#x",
                  f"{base}/?invoiceId={ID1}", f"https://{HOST}/portal/BillingHistory/GetHistoryDownload?type=Bill",
                  PDF_URL.replace("https:", "http:"), PDF_URL.replace(HOST, "www.sdge.com"),
                  f"https://{HOST}/portal/PreLogin/Validate", f"blob:{PDF_URL}", ""]:
            self.assertFalse(site.is_download_url(u), u)
        for bad in ("", None, "ISU1", "ISU00000000010\n", "XSU000000000101"):
            self.assertEqual(site.download_url(bad), "", repr(bad))


class Controls(unittest.TestCase):
    def test_own_documents_under_view_and_download(self):
        for label in ["View Your Detailed Bill PDF", "Download Your Solar Bill", "View Bill", "Download Bill",
                      "View Utility Bill", "Download Utility Bill", "view your bill"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_everything_else_is_refused(self):
        for label in ["Make a Payment", "Auto Pay", "AutoPay", "Text to Pay", "Bank Accounts", "Payment Arrangements",
                      "Pricing Plans", "Level Pay", "Start Service", "Transfer Service", "Stop Service",
                      "Notifications Settings", "Sign Out", "Guest Pay", "Register", "Go Paperless",
                      "Download billing history (Excel)", "Export", "View Bill History", "Billing History",
                      "View Additional Solar Bill Details", "Letter of Residency", "View Bill | Make a Payment",
                      "Make a Payment | View Bill", "Download Bill and Pay", "View Bill and enroll in paperless",
                      "Pay Bill", "View Bill Now", "Details", "", "   ", None]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Rows(unittest.TestCase):
    def test_the_statement_date_is_read_from_its_own_column(self):
        docs = site.bills_of([row(ID1, "Sep 25, 2026", due="Oct 14, 2026")], HEADS)
        self.assertEqual([d.date_text for d in docs], ["2026-09-25"])
        # Found by its header, wherever the table puts it.
        heads = laid_out("", "Due Date", "Statement Date", "Amount Due")
        moved = {"id": ID1, "cells": laid_out("", "Oct 14, 2026", "Sep 25, 2026", "$1.00")}
        self.assertEqual([d.date_text for d in site.bills_of([moved], heads)], ["2026-09-25"])
        # The header holds both words, whatever else it holds, since its
        # whole text on the live page has never been seen.
        for named in (" statement   DATE ", "Statement Date *", "Statement Date (i) more info",
                      "Bill Statement Date"):
            self.assertEqual(site.header_layout(laid_out("", named, "Due Date")), (1, 3), named)

    def test_a_blank_statement_date_is_never_taken_from_the_due_date(self):
        # The Due Date beside a blank Statement Date used to date the bill.
        for blank in ("", "   "):
            with self.assertRaises(site.ListStopped) as stop:
                site.bills_of(ROWS[:2] + [row(ID3, blank, due="Oct 14, 2026")], HEADS)
            self.assertIn("Statement Date cell is blank", str(stop.exception))
            self.assertEqual([d.date_text for d in stop.exception.docs], ["2026-09-12", "2026-08-13"])
        with self.assertRaises(site.ListStopped):
            site.bills_of([{"id": ID1, "cells": laid_out("", "Billed", "Oct 14, 2026")}], HEADS)

    def test_a_table_without_one_statement_date_column_stops(self):
        # Each header is as wide as the rows, so only its Statement Date
        # column is in question.
        spanning = laid_out("", "Statement Date", "Amount Due", "Status")
        spanning[1]["wide"] = 2
        spanning[2]["at"], spanning[3]["at"] = 3, 4
        no_height = laid_out("", "Statement Date", "Due Date", "Amount Due", "Status")
        no_height[0]["tall"] = 0
        unread = laid_out("", "Statement Date", "Due Date", "Amount Due", "Status")
        unread[1]["at"] = "1"
        for heads in (None, [], laid_out("", "Bill Date", "Due Date", "Amount Due", "Status"),
                      laid_out("", "Statement Date", "Statement Date", "Amount Due", "Status"),
                      laid_out("", "Statement Date", "Statement Due Date", "Amount Due", "Status"),
                      laid_out("", "Statements", "Due Date", "Amount Due", "Status"),
                      laid_out("", "Statement", "Date", "Amount Due", "Status"),
                      spanning, no_height, unread):
            with self.assertRaises(site.ListStopped, msg=repr(heads)) as stop:
                site.bills_of(ROWS, heads)
            self.assertEqual(stop.exception.docs, [], repr(heads))

    def test_a_row_that_does_not_line_up_with_the_header_stops(self):
        short = {"id": ID3, "cells": laid_out("")}
        across = {"id": ID3, "cells": laid_out("", "Jul 14, 2026", "$1.00", "Billed")}
        across["cells"][1]["wide"] = 2
        across["cells"][2]["at"], across["cells"][3]["at"] = 3, 4
        # A cell taller than its row moves the next row's cells left, so the
        # Due Date would sit under Statement Date there.
        tall = row(ID3, "Jul 14, 2026")
        tall["cells"][0]["tall"] = 2
        moved_left = {"id": ID3, "cells": laid_out("Jul 14, 2026", "Oct 14, 2026", "$1.00", "Billed")}
        longer = {"id": ID3, "cells": laid_out("", "Jul 14, 2026", "Oct 14, 2026", "$1.00", "Billed", "x")}
        odd = {"id": ID3, "cells": laid_out("", "Jul 14, 2026", "Oct 14, 2026", "$1.00", "Billed")}
        del odd["cells"][0]["tall"]
        gap = {"id": ID3, "cells": laid_out("", "Jul 14, 2026", "Oct 14, 2026", "$1.00", "Billed")}
        gap["cells"][2]["at"] = 3
        for bad in (short, across, tall, moved_left, longer, odd, gap, {"id": ID3},
                    {"id": ID3, "cells": None}):
            with self.assertRaises(site.ListStopped, msg=repr(bad)) as stop:
                site.bills_of(ROWS[:2] + [bad], HEADS)
            self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2], repr(bad))

    def test_good_rows(self):
        got = site.bills_of(ROWS, HEADS)
        self.assertEqual([(d.title, d.date_text, d.document_id, d.kind) for d in got],
                         [("SDG&E Bill 2026-09-12", "2026-09-12", ID1, "statement"),
                          ("SDG&E Bill 2026-08-13", "2026-08-13", ID2, "statement"),
                          ("SDG&E Bill 2026-07-14", "2026-07-14", ID3, "statement")])
        for d in got:
            self.assertEqual(d.href, site.DOWNLOAD_PATH)
            self.assertEqual(d.account, "")

    def test_the_live_rows_are_read_past_their_hidden_number(self):
        got = site.bills_of(LIVE_ROWS, LIVE_HEADS)
        self.assertEqual([d.date_text for d in got], LIVE_DATES)

    def test_the_hidden_number_is_passed_over_only_in_the_live_shape(self):
        live = numbered(ID1, "1", "Sep 12, 2031")
        layout = site.header_layout(LIVE_HEADS)
        self.assertEqual([c["text"] for c in site.past_row_number(live, layout)[:2]],
                         ["Sep 12, 2031", "Oct 14, 2031"])
        self.assertEqual([c["at"] for c in site.past_row_number(live, layout)], list(range(7)))
        # No number, the first header not Statement Date, or a row not
        # exactly one wider than the header.
        plain = dict(live, number="")
        self.assertEqual(site.past_row_number(plain, layout), live["cells"])
        self.assertEqual(site.past_row_number(live, (1, 7)), live["cells"])
        for width in (6, 8, 9):
            self.assertEqual(site.past_row_number(live, (0, width)), live["cells"], width)

    def test_a_numbered_row_with_a_cell_it_cannot_lay_out_stops(self):
        odd = numbered(ID1, "1", "Sep 12, 2031")
        del odd["cells"][3]["wide"]
        with self.assertRaises(site.ListStopped) as stop:
            site.bills_of([odd], LIVE_HEADS)
        self.assertIn("does not line up", str(stop.exception))

    def test_a_real_number_column_with_a_headerless_cell_stops(self):
        # The header has its own first column, so the row's first cell is
        # that column's, and a row one wider has a cell with no header.
        heads = laid_out("#", "Statement Date", "Due Date", "Days in Billing Cycle",
                         "Current Charges", "Amount Due", "Status")
        with self.assertRaises(site.ListStopped) as stop:
            site.bills_of(LIVE_ROWS, heads)
        self.assertIn("does not line up", str(stop.exception))
        self.assertEqual(stop.exception.docs, [])

    def test_unreadable_rows_stop_the_list_with_what_was_read(self):
        for bad, why in [(row("ISU123", "Jun 1, 2026"), "bad id"),
                         (row("", "Jun 1, 2026"), "no id"),
                         (row(ID3, "Feb 30, 2026"), "no such day"),
                         (row(ID3, "2026-06-01"), "another shape"),
                         (row(ID3, "Due Jun 1, 2026"), "a date inside other text"),
                         (row(ID1, "Jun 1, 2026"), "duplicate id"),
                         (row(ID3, "Sep 12, 2026"), "two bills one date")]:
            with self.assertRaises(site.ListStopped, msg=why) as stop:
                site.bills_of(ROWS[:2] + [bad], HEADS)
            self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2], why)
            self.assertNotIn("ISU", str(stop.exception), why)

    def test_statement_dates(self):
        self.assertEqual(site.statement_date("Feb 28, 2026"), "2026-02-28")
        self.assertEqual(site.statement_date(" Sep  2,  2026 "), "2026-09-02")
        for bad in ("Feb 29, 2026", "Sept 2, 2026", "2026-09-02", "09/02/2026", "", None):
            self.assertIsNone(site.statement_date(bad), repr(bad))

    def test_rules_classify(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        self.assertEqual(doc_types.classify_document("SDG&E Bill 2026-09-12", rules)[:2], ("Statement", "Utility Bill"))


class ListReady(unittest.TestCase):
    def test_rows_are_read_from_the_page(self):
        page = Page()
        self.assertEqual([d.document_id for d in site.collect_download_docs(page)], [ID1, ID2, ID3])
        self.assertEqual(page.gotos, [site.DOCUMENTS_URL])
        self.assertEqual(page.context.request.asked, [], "the list asks nothing of its own")

    def test_the_empty_table_is_not_yet_read_as_no_bills(self):
        # Never seen live, so it stops the list rather than calling it whole.
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(rows=[], empty="No data available in table"))

    def test_a_sign_out_during_the_wait_for_rows_is_session_expired(self):
        page = Page(rows=[], empty="Loading...")
        real = page.wait_for_selector

        def wait(sel, **kw):
            page.url = f"https://{HOST}/portal/PreLogin/Validate"
            return real(sel, **kw)
        page.wait_for_selector = wait
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(page)

    def test_a_table_that_counts_only_the_rows_read_is_whole(self):
        n = len(ROWS)
        for page in (Page(api={"total": n, "shown": n, "search": ""}),
                     Page(info=f"Showing 1 to {n} of {n} entries"),
                     Page(api={"total": n, "shown": n, "search": ""}, info=f"Showing 1 to {n} of {n} entries")):
            self.assertEqual([d.document_id for d in site.collect_download_docs(page)], [ID1, ID2, ID3])

    def test_one_page_of_a_longer_table_stops_with_what_was_read(self):
        n = len(ROWS)
        for page in (Page(api={"total": 24, "shown": 24, "search": ""}),
                     Page(info=f"Showing 1 to {n} of 24 entries"),
                     Page(info=f"Showing 1 to {n} of 1,024 entries"),
                     Page(api={"total": n, "shown": n, "search": ""}, info=f"Showing 1 to {n} of 24 entries")):
            with self.assertRaises(site.ListStopped) as stop:
                site.collect_download_docs(page)
            self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2, ID3])
            self.assertFalse(site.bill_list_opens(page))

    def test_a_filtered_or_unreadable_count_stops(self):
        n = len(ROWS)
        for page in (Page(api={"total": 24, "shown": n, "search": ""}),
                     Page(api={"total": n, "shown": n, "search": "2026"}),
                     Page(api={"unreadable": True}),
                     Page(info=f"Showing 1 to {n} of {n} entries (filtered from 24 total entries)"),
                     Page(info="Page one")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)

    def test_the_live_table_counts_by_its_hidden_numbers(self):
        page = Page(rows=LIVE_ROWS, heads=LIVE_HEADS)
        self.assertEqual([d.date_text for d in site.collect_download_docs(page)], LIVE_DATES)

    def test_hidden_numbers_run_from_1_in_the_rows_read(self):
        def rows(*numbers):
            return [{"number": n} for n in numbers]
        for good in (rows("1", "2", "3"), rows("01", "02", "03"), rows("001"), rows(), None,
                     rows("", "", ""), rows("1", "", "3"), rows("", "2"),
                     rows("3", "2", "1"), rows("03", "02", "01")):
            self.assertTrue(site.numbers_in_place(good), good)
        for bad in (rows("0", "1", "2"), rows("2", "3"), rows("11", "12"), rows("1", "2", "4"),
                    rows("1", "1", "2"), rows("1", "", "2"), rows("10"),
                    rows("12", "11"), rows("4", "2", "1"), rows("2", "1", "3")):
            self.assertFalse(site.numbers_in_place(bad), bad)

    def test_numbers_that_do_not_run_from_1_stop_with_what_was_read(self):
        second_page = [numbered(ID1, "11", "Sep 12, 2031"), numbered(ID2, "12", "Aug 13, 2031")]
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(Page(rows=second_page, heads=LIVE_HEADS))
        self.assertIn("hidden row numbers do not run from 1 to 2", str(stop.exception))
        self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2])

    def test_rows_with_no_hidden_number_are_not_asked_about_it(self):
        # The older shape, and a table carrying numbers on only some rows
        # where the ones it carries are in their place.
        self.assertEqual(len(site.collect_download_docs(Page())), 3)
        some = [LIVE_ROWS[0], {"id": ID2, "cells": laid_out(
            "Aug 13, 2031", "Oct 14, 2031", "30", "$1.00", "$1.00", "Billed", "")}, LIVE_ROWS[2]]
        self.assertEqual([d.date_text for d in site.collect_download_docs(
            Page(rows=some, heads=LIVE_HEADS))], LIVE_DATES)

    def test_what_looks_like_a_pager_or_show_more_is_known(self):
        steps = ["Next", "next", "Next page", "Next 10", "Next \u203a", "\u2039 Prev", "Previous",
                 "Older", "Newer", "First", "Last", "Last page", "More", "Page 2", "Go to page 2"]
        arrows = [">", ">>", "\u00bb", "\u203a", "<", "\u00ab", "\u2039"]
        for said in steps + arrows:
            self.assertTrue(site.shows_more([near(said, press=True)]), said)
        for said in ("Show more", "SHOW MORE", "show   more", "Show more \u00bb", "Load more",
                     "View more", "See more", "See all", "View all", "Show all", "Get more",
                     "Display more", "Show 10 more", "Show older", "Load previous bills",
                     "View older bills", "See all statements", "View additional bills",
                     "View more entries", "Show more rows", "Show more results",
                     "Show more records", "Show more items", "Show more invoices", "Show earlier",
                     "View all history", "More bills", "Older bills", "Previous statements",
                     "Earlier bills", "Showing 1 to 10 of 24 entries", "Bills 1-10 of 24",
                     "1\u201310 of 24", "Page 1 of 3", "page 2 of 2"):
            self.assertTrue(site.shows_more([near(said)]), said)
        self.assertTrue(site.shows_more([near(pager=True)]))
        self.assertTrue(site.shows_more([near("1", press=True), near("2", press=True)]))
        self.assertTrue(site.shows_more([near("Billed"), near("Show more")]), "wherever it comes")

    def test_a_steps_words_alone_on_something_not_pressed_are_no_pager(self):
        # A detail row can head a column Previous, and a tile can hold a number.
        for said in ("Next", "Previous", "First", "Last", "More", "Page 2", ">", "\u00bb", "2"):
            self.assertFalse(site.shows_more([near(said)]), said)
        self.assertFalse(site.shows_more([near("12"), near("30")]))

    def test_one_page_number_says_there_are_no_others(self):
        for around in ([near("1", press=True)], [near("1", press=True), near("1", press=True)],
                       [near("1", press=True), near("2")],
                       [near("2031", press=True), near("2030", press=True)]):
            self.assertFalse(site.shows_more(around), around)

    def test_the_pages_own_words_are_no_pager(self):
        # The labels this page is known by, and others like them.
        for said in ("View Your Detailed Bill PDF", "Download Your Solar Bill",
                     "View Additional Solar Bill Details", "Download billing history (Excel)",
                     "View Bill", "View Bill History", "Billing History", "Details", "+",
                     "Make a Payment", "Statement Date", "Days in Billing Cycle", "Billed", "All",
                     "Show", "Next Bill Date", "Previous Balance", "Last Payment", "Show details",
                     "$12.34", "Sep 12, 2031", "", None):
            for press in (True, False):
                self.assertFalse(site.shows_more([near(said, press=press)]), said)
        for around in (None, []):
            self.assertFalse(site.shows_more(around))

    def test_something_near_the_table_stops_with_what_was_read(self):
        for around in ([near("Show more", press=True)], [near(pager=True)]):
            with self.assertRaises(site.ListStopped) as stop:
                site.collect_download_docs(Page(around=around))
            self.assertIn("pager or a show-more control", str(stop.exception))
            self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2, ID3])

    def test_rows_that_keep_arriving_stop_with_what_was_read(self):
        page = Page()
        real, asked = page.evaluate, itertools.count()

        def evaluate(js, selector=None):
            return next(asked) if selector == site.BILL_ROW else real(js)
        page.evaluate = evaluate
        with mock.patch.object(site, "ROWS_BUDGET_MS", 300):
            with self.assertRaises(site.ListStopped) as stop:
                site.collect_download_docs(page)
        self.assertIn("still being drawn", str(stop.exception))
        self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2, ID3])

    def test_a_count_that_cannot_be_asked_is_not_a_settled_one(self):
        page = Page()
        real = page.evaluate

        def evaluate(js, selector=None):
            if selector == site.BILL_ROW:
                raise RuntimeError("Target page, context or browser has been closed")
            return real(js)
        page.evaluate = evaluate
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page)
        self.assertIn("still being drawn", str(stop.exception))

    def test_the_wait_for_rows_reaches_the_journal(self):
        class Journal:
            said = []

            def waited(self, name, result):
                self.said.append((name, [a.outcome for a in result.attempts]))
        site.set_journal(Journal())
        self.addCleanup(site.set_journal, None)
        site.collect_download_docs(Page())
        self.assertEqual(Journal.said, [("a further bill row", ["not_satisfied"])])

    def test_a_sign_out_while_the_rows_settle_is_session_expired(self):
        page = Page()
        real = page.evaluate

        def evaluate(js, selector=None):
            if selector == site.BILL_ROW:
                page.url = f"https://{HOST}/portal/PreLogin/Validate"
            return real(js, selector)
        page.evaluate = evaluate
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(page)

    def test_the_rows_are_read_after_they_settle(self):
        # The first look has one row, and the wait ends on all three.
        page = Page(rows=ROWS[:1])
        real = page.evaluate

        def evaluate(js, selector=None):
            if selector == site.BILL_ROW:
                page.rows = ROWS
            return real(js, selector)
        page.evaluate = evaluate
        self.assertEqual([d.document_id for d in site.collect_download_docs(page)], [ID1, ID2, ID3])

    def test_a_list_that_never_draws_stops(self):
        for page in (Page(ready=False), Page(rows=[], empty="Loading..."), Page(rows=[], empty="")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)
            self.assertFalse(site.bill_list_opens(page))
        self.assertFalse(site.goto_documents(Page(ready=False)))
        self.assertTrue(site.bill_list_opens(Page()))

    def test_a_signed_out_portal_is_session_expired(self):
        for page in (Page(settled=f"https://{HOST}/portal/PreLogin/Validate"),
                     Page(ready=False, password=True)):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)

    def test_a_page_that_settles_elsewhere_is_not_read(self):
        for where in ("https://www.sdge.com/", f"https://{HOST}/portal/Dashboard/index"):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(Page(settled=where))


class SignedOut(unittest.TestCase):
    def test_sign_in_shapes(self):
        self.assertTrue(site.looks_signed_out(Page(start=f"https://{HOST}/portal/PreLogin/Validate")))
        self.assertTrue(site.looks_signed_out(Page(start=f"https://{HOST}/portal/Accounts/Logout")))
        self.assertTrue(site.looks_signed_out(Page(start=site.DOCUMENTS_URL, password=True)))
        self.assertFalse(site.looks_signed_out(Page(start=site.DOCUMENTS_URL)))

    def test_a_dead_page_raises(self):
        with self.assertRaises(RuntimeError):
            site.looks_signed_out(Dead())


class Download(unittest.TestCase):
    def fetch(self, page, date="2026-09-12", inv=ID1, href=None):
        td = tempfile.mkdtemp()
        out = Path(td) / "o.pdf"
        ok = site.download_bill(page, None, date, out, title="SDG&E Bill " + date, trace=[],
                                href=site.DOWNLOAD_PATH if href is None else href, document_id=inv)
        return ok, out

    def test_one_request_with_the_exact_id_and_no_redirect(self):
        page = Page(answers=[Resp(ctype="Application/PDF; charset=binary",
                                  extra={"content-disposition": "attachment; filename=x.pdf"})])
        ok, out = self.fetch(page)
        self.assertTrue(ok)
        self.assertEqual(page.context.request.asked, [(PDF_URL, 0)])
        self.assertTrue(out.read_bytes().startswith(b"%PDF-"))

    def test_a_live_row_fetches_its_bill(self):
        page = Page(rows=LIVE_ROWS, heads=LIVE_HEADS, answers=[Resp()])
        ok, out = self.fetch(page, date="2031-09-12")
        self.assertTrue(ok)
        self.assertEqual(page.context.request.asked, [(PDF_URL, 0)])
        self.assertTrue(out.read_bytes().startswith(b"%PDF-"))

    def test_no_single_matching_row_means_no_request(self):
        for page, kw in [(Page(answers=[Resp()]), dict(date="2026-09-11")),
                         (Page(answers=[Resp()]), dict(inv="ISU000000000999")),
                         (Page(answers=[Resp()]), dict(inv="")),
                         (Page(answers=[Resp()]), dict(href="/portal/BillingHistory/DownloadBillPdf?invoiceId=" + ID1))]:
            ok, out = self.fetch(page, **kw)
            self.assertFalse(ok, kw)
            self.assertEqual(page.context.request.asked, [], kw)
            self.assertFalse(out.exists())

    def test_a_list_that_cannot_be_read_again_stops(self):
        """Billing History read again for a bill is the list every bill
        after it reads too, so a list that stops is raised to the run, never
        this bill's False (#126's review)."""
        for page in [Page(rows=ROWS + [dict(ROWS[0])], answers=[Resp()]),
                     Page(rows=[], empty="No data available in table", answers=[Resp()]),
                     Page(ready=False, answers=[Resp()]),
                     Page(around=[near("Show more")], answers=[Resp()]),
                     Page(rows=LIVE_ROWS[1:], heads=LIVE_HEADS, answers=[Resp()])]:
            with self.assertRaises(site.ListStopped):
                self.fetch(page)
            self.assertEqual(page.context.request.asked, [])

    def test_signed_out_answers_raise_and_save_nothing(self):
        for answer in [Resp(302, ctype="text/html", body=b"", location="/portal/PreLogin/Validate"),
                       Resp(302, ctype="text/html", body=b"", location=PDF_URL.replace(ID1, ID2)),
                       Resp(401, ctype="application/json", body=b'{"StatusCode":401}'),
                       Resp(200, ctype="application/json", body=b'{"StatusCode":401}'),
                       Resp(200, ctype="text/html; charset=utf-8", body=b"<html>Log into My Energy Center</html>"),
                       Resp(403, ctype="text/plain", body=b"no")]:
            page = Page(answers=[answer])
            with self.assertRaises(site.SessionExpired):
                self.fetch(page)
            self.assertEqual(len(page.context.request.asked), 1, "a redirect is never followed")
            self.assertEqual(page.context.request.asked[0][1], 0)

    def test_a_list_showing_the_sign_in_page_raises(self):
        with self.assertRaises(site.SessionExpired):
            self.fetch(Page(settled=f"https://{HOST}/portal/PreLogin/Validate", answers=[Resp()]))

    def test_sign_in_bodies_labelled_as_pdf_are_session_expired(self):
        for answer in [Resp(body=b"<!doctype html><html>Log in</html>"),
                       Resp(body=b'  {"StatusCode":401}'),
                       Resp(ctype="application/problem+json", body=b'{"status":401}')]:
            with self.assertRaises(site.SessionExpired):
                self.fetch(Page(answers=[answer]))

    def test_other_non_pdfs_are_refused_without_a_file(self):
        for answer in [Resp(500, ctype="text/plain"), Resp(ctype="application/octet-stream"),
                       Resp(body=b"not a pdf")]:
            ok, out = self.fetch(Page(answers=[answer]))
            self.assertFalse(ok)
            self.assertFalse(out.exists())


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_persisted_record_has_no_query_and_is_keyed_by_the_id(self):
        app = make_app(self.tmp, "--discover")
        for r in site.bills_of(ROWS, HEADS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        text = app.paths.discovery_json.read_text()
        self.assertNotIn("?", text)
        self.assertNotIn("invoiceId", text)
        rec = app.discovery.get("id:" + ID1)
        self.assertEqual((rec["href"], rec["document_id"], rec["account"], rec["summary"]),
                         (site.DOWNLOAD_PATH, ID1, "", "Utility Bill"))
        self.assertEqual(docs.told_apart_by(rec), ID1[-6:], "only a taken name gets the id's end")

    def test_an_expired_session_stops_the_run_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(ROWS, HEADS):
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

    def test_a_list_that_stops_on_resume_stops_the_run_once(self):
        """A Resume reads no list of its own. After a listing read whole,
        Billing History that now stops (here it draws no bill) is read once,
        for the first bill, and the run stops there as one whose list did
        not end whole, with nothing recorded against any bill. Each bill
        used to read the whole list and go to review, and the run ended
        clean."""
        from paperpull_core import listing
        app = make_app(self.tmp, "--resume")
        listing.started(app)
        for r in site.bills_of(ROWS, HEADS):
            app._record_rawdoc(r, site.BILLING_URL)
        listing.read_whole(app)
        app.check_session = lambda page: None
        app._delay = lambda *a, **k: None
        app.write_failure = lambda *a, **k: None
        pages = []

        def later():
            pages.append(Page(rows=[], empty="No data available in table", answers=[Resp()]))
            return pages[-1]
        app._on_its_site = later
        bills = app._select()
        self.assertGreater(len(bills), 1)
        # A stop only a run that lists carries on from, so the panel offers
        # that, not Continue, which would read the same list and stop again.
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(listing.ListNotRead):
            app.process(bills)
        self.assertEqual(len(pages), 1, "one list read, for the first bill only")
        self.assertEqual(pages[0].context.request.asked, [])
        self.assertIn("could not be read again", said.getvalue())
        self.assertEqual(app.progress.data, {})
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)
        self.assertEqual(listing.last(app), listing.STOPPED)

    def test_a_pager_that_comes_while_bills_download_stops_the_run_once(self):
        """A pager on the list a bill reads again, after a listing read
        whole, is the list every bill after it reads. The run stops on the
        first bill, as one whose list did not end whole."""
        from paperpull_core import listing
        app = make_app(self.tmp, "--resume")
        listing.started(app)
        for r in site.bills_of(ROWS, HEADS):
            app._record_rawdoc(r, site.BILLING_URL)
        listing.read_whole(app)
        app.check_session = lambda page: None
        app._delay = lambda *a, **k: None
        app.write_failure = lambda *a, **k: None
        pages = []

        def later():
            pages.append(Page(around=[near("Next", press=True)], answers=[Resp()]))
            return pages[-1]
        app._on_its_site = later
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(listing.ListNotRead):
            app.process(app._select())
        self.assertEqual(len(pages), 1, "one list read, for the first bill only")
        self.assertEqual(pages[0].context.request.asked, [])
        self.assertIn("could not be read again", said.getvalue())
        self.assertEqual(app.progress.data, {})
        self.assertEqual(listing.last(app), listing.STOPPED)

    def test_an_expired_session_during_discovery_stops_the_run(self):
        # check_session is not stubbed: the list opens and signs out in one
        # step, so no prompt to sign in again is ever reached.
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(settled=f"https://{HOST}/portal/PreLogin/Validate")
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(app.discovery.data, {})
        self.assertIn("signed out", out.getvalue())
        self.assertNotIn("Press Enter", out.getvalue())
        self.assertFalse(list((Path(self.tmp) / "out").rglob("*.json")) and
                         any("failure" in p.name.lower() for p in (Path(self.tmp) / "out").rglob("*")))

    def test_a_tab_that_left_the_site_still_stops_the_run_unread(self):
        """The tab the run works in, moved to another site after it was on
        My Energy Center, is never read, loaded or prompted about. Discover
        and the session check stop the run and say so, with nothing
        listed."""
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
            self.assertIn("left My Energy Center", said.getvalue())
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
        self.assertTrue(docs.pilot_failed({"a": {"state": "Needs Manual Review"}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({}, [D("a")]))
        self.assertTrue(docs.pilot_failed(done, []))


class Privacy(unittest.TestCase):
    """Nothing that names the account reaches a log line or the console,
    and all of it is registered as private words."""

    def test_account_details_stay_out_of_logs_and_stdout(self):
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
                page = Page(accounts=2, answers=[Resp()])
                for r in site.collect_download_docs(page):
                    app._record_rawdoc(r, site.BILLING_URL)
                app.discovery.save()
                app.check_session = lambda p: None
                app._delay = lambda *a, **k: None
                app._on_its_site = lambda: Page(accounts=2, answers=[Resp(body=b"%PDF-1.4 " + b"x" * 3000)])
                app.process(app._select(limit=1))
                bad = Page(accounts=2, rows=ROWS + [row(ID3, "Sep 12, 2026")])
                with self.assertRaises(site.ListStopped):
                    site.collect_download_docs(bad)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        out = seen.getvalue() + app.paths.discovery_json.read_text() + app.paths.progress_json.read_text()
        self.assertIn("accounts", seen.getvalue(), "the one-account notice was said")
        for word in (FAKE_ACCOUNT, FAKE_CONTRACT, FAKE_STREET):
            self.assertNotIn(word, out)
        for word in (FAKE_ACCOUNT + "0", FAKE_CONTRACT, FAKE_STREET):
            self.assertIn(word, site.private_words())
        self.assertIn("Tester", site.private_words(), "the owner's name is kept beside them")
        self.assertNotIn(FAKE_CONTRACT, site.redact("contract " + FAKE_CONTRACT))
        self.assertIn("CAPTCHA", site.redact("CAPTCHA Statement"), "a short address part is not a word")
        self.assertEqual(len(site.private_words()), len(set(site.private_words())), "nothing twice")
        names = [p.name for p in app.paths.root.rglob("*.pdf")]
        self.assertEqual(len(names), 1)
        self.assertNotIn("ISU", names[0])


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "sdge_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
