"""The bill history API and the PDF address, with invented values only.
No browser, no network."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import verizonmobile_site as site  # noqa: E402

FAKE_ACCOUNT = "9876543210-00001"
OTHER_ACCOUNT = "1234567890-00001"
TAG = "3210-00001"
PDF = b"%PDF-1.4 " + b"x" * 3000


def cycle(end):
    return {"billCycleYearRange": end[-4:], "billAmount": "$10.00", "billCycleDateRange": "Sep 12 - Oct 11",
            "billEndDate": end, "billCycleRange": "09/12/2026 - " + end,
            "cta": [{"type": "primary", "label": "Review bill", "link": site.BASE + "/x"},
                    {"type": "secondary", "label": "Review bill PDF", "link": ""}]}


def answer(ends, account=FAKE_ACCOUNT):
    address = {"accountName": "Zyxwvut Qponml", "addressline1": "100 Main Ln",
               "city": "Abcdefgh", "state": "OR", "zipCode": "00000-0000"}
    if account is not None:
        address["accountNumber"] = account
    return {"responseInfo": {"responseCode": "00", "sectionErrors": []},
            "body": {"billingHistory": {"billCycle": [cycle(e) for e in ends],
                                        "address": address}}}


ENDS = ["10/11/2026", "09/11/2026", "08/11/2026"]


class Req:
    method = "GET"

    def __init__(self, channel="abc-def123"):
        self.channel = channel

    def all_headers(self):
        return {"channelid": self.channel, "cookie": "never-taken"} if self.channel is not None else {}


class Resp:
    def __init__(self, data, status=200, channel="abc-def123"):
        self.url = site.BASE + site.HISTORY_API_PATH
        self.status, self._data = status, data
        self.request = Req(channel)
        self.headers = {}

    def body(self):
        import json
        return json.dumps(self._data).encode()


class Locator:
    def __init__(self, n=0):
        self.n = n

    def count(self):
        return self.n


class Page:
    """A signed-in tab on Bill & payment history. Each load answers with the
    next of `loads` while there are any, as (data, status, signed_out), and
    with `data` and `status` after them."""

    def __init__(self, data=None, status=200, channel="abc-def123", pdf=PDF, pdf_status=200,
                 asks=True, loads=None):
        self.data = answer(ENDS) if data is None else data
        self.status, self.channel, self.pdf, self.pdf_status, self.asks = status, channel, pdf, pdf_status, asks
        self.loads = list(loads or [])
        self.url = "about:blank"
        self.signed_out = False
        self.handlers, self.asked, self.gotos = [], [], 0

    def on(self, event, h):
        self.handlers.append(h)

    def remove_listener(self, event, h):
        self.handlers.remove(h)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.gotos += 1
        data, status, self.signed_out = (self.loads.pop(0) if self.loads
                                         else (self.data, self.status, False))
        self.url = "https://secure.verizon.com/signin" if self.signed_out else site.HISTORY_URL
        if self.asks and not self.signed_out:
            for h in list(self.handlers):
                h(Resp(data, status, self.channel))

    def locator(self, sel):
        return Locator(1 if self.signed_out and "password" in sel else 0)

    def evaluate(self, js, arg=None):
        self.asked.append(arg[0])
        if self.pdf_status in ("redirect",):
            return {"status": 0, "redirected": True}
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "text/html"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}


def stop_of(page):
    try:
        site.collect_download_docs(page)
    except (site.ListStopped, site.SessionExpired) as stop:
        return stop
    raise AssertionError("the list was taken whole")


class History(unittest.TestCase):
    def setUp(self):
        site.set_private_words([])

    def test_every_cycle_is_a_bill_known_by_its_account_and_end(self):
        got = site.collect_download_docs(Page())
        self.assertEqual([d.date_text for d in got], ["2026-10-11", "2026-09-11", "2026-08-11"])
        self.assertEqual([d.document_id for d in got],
                         [f"bill-{TAG}-2026-10-11", f"bill-{TAG}-2026-09-11", f"bill-{TAG}-2026-08-11"])
        self.assertEqual({d.href for d in got}, {site.PDF_PATH})

    def test_two_accounts_bills_of_one_day_are_two_bills(self):
        mine = site.bills_of(answer(ENDS))
        theirs = site.bills_of(answer(ENDS, account=OTHER_ACCOUNT))
        self.assertFalse({d.document_id for d in mine} & {d.document_id for d in theirs})
        self.assertEqual(theirs[0].document_id, "bill-7890-00001-2026-10-11")

    def test_the_account_is_read_in_the_shapes_it_takes(self):
        self.assertEqual(site.account_of(answer([], account="987654321-00002")), "4321-00002")
        self.assertEqual(site.account_of(answer([], account=" 9876543210 ")), "3210")
        for bad in (None, "", "12345", "98765432a0-00001", "9876543210-", 9876543210):
            with self.assertRaises(site.ListStopped):
                site.account_of(answer([], account=bad))

    def test_the_account_number_and_name_are_private_and_the_street_is_not(self):
        site.collect_download_docs(Page())
        words = site._private_words()
        for word in ("9876543210", "00001", "Zyxwvut", "Qponml"):
            self.assertIn(word, words)
        # A street word such as Main would turn "Maintenance" into
        # "[name]tenance" in a diagnostic, and ZIP+4 digits mask others.
        for word in ("Main", "Abcdefgh", "0000", "100"):
            self.assertNotIn(word, words)
        self.assertEqual(site.redact("Maintenance"), "Maintenance")

    def test_an_unreadable_history_stops_the_list(self):
        """Never a list of what was read taken for the whole of it. A page
        that never asks, a refusal, an answer that is no history, an
        account the bills cannot be told by, a cycle that is not a calendar
        date or two of one end date all stop it."""
        for page in (Page(asks=False), Page(status=500), Page(channel=""),
                     Page(data={"responseInfo": {"responseCode": "99"}}),
                     Page(data={"responseInfo": {"responseCode": "00"}, "body": {}}),
                     Page(data=answer([])), Page(data=answer(ENDS, account=None)),
                     Page(data=answer(ENDS + ["02/30/2026"])),
                     Page(data=answer(ENDS + ["10/11/2026"]))):
            self.assertIsInstance(stop_of(page), site.ListStopped)

    def test_a_stop_carries_the_bills_read_before_it(self):
        stop = stop_of(Page(data=answer(ENDS + ["02/30/2026", "07/11/2026"])))
        self.assertEqual([d.date_text for d in stop.docs], ["2026-10-11", "2026-09-11", "2026-08-11"])

    def test_a_signed_out_history_is_a_sign_out(self):
        for page in (Page(status=401), Page(status=403), Page(loads=[(None, 200, True)])):
            self.assertIsInstance(stop_of(page), site.SessionExpired)

    def test_login_says_the_list_opens_only_when_it_reads_whole(self):
        self.assertTrue(site.bill_list_opens(Page()))
        for page in (Page(asks=False), Page(data=answer([])), Page(status=401)):
            self.assertFalse(site.bill_list_opens(page))


class PdfAddress(unittest.TestCase):
    def test_the_address_has_exactly_its_two_parameters(self):
        url = site.pdf_url("10/11/2026", "abc-def123")
        self.assertTrue(site.is_pdf_url(url))
        self.assertIn("startMonthDate=10%2F11%2F2026", url)
        for end, chan in (("2026-10-11", "abc"), ("10/11/2026", "a b"), ("10/11/2026", "")):
            self.assertEqual(site.pdf_url(end, chan), "")
        self.assertFalse(site.is_pdf_url(url + "&x=1"))
        self.assertFalse(site.is_pdf_url(url.replace("www.verizon.com", "evil.example")))


BILL = f"bill-{TAG}-2026-09-11"


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def fetch(self, page, day="2026-09-11", document_id=BILL):
        return site.download_bill(page, None, day, self.out, document_id=document_id)

    def test_the_bill_of_that_account_and_day_is_asked_for_and_saved(self):
        page = Page()
        self.assertTrue(self.fetch(page))
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual(page.asked, [site.pdf_url("09/11/2026", "abc-def123")])
        self.assertEqual(page.gotos, 1, "the history is read once for a bill")

    def test_another_account_shown_is_never_asked_for_its_bill(self):
        """The PDF address names no account, so with another account shown
        it would give that account's bill of the same day."""
        page = Page(data=answer(ENDS, account=OTHER_ACCOUNT))
        with self.assertRaises(site.OtherAccountShown) as shown:
            self.fetch(page)
        self.assertEqual((shown.exception.wanted, shown.exception.shown), (TAG, "7890-00001"))
        self.assertEqual(page.asked, [])
        self.assertFalse(self.out.exists())

    def test_a_history_that_cannot_be_read_again_stops_the_run(self):
        for page in (Page(asks=False), Page(data=answer([])), Page(status=500),
                     Page(data=answer(ENDS + ["13/45/2026"]))):
            with self.assertRaises(site.ListStopped):
                self.fetch(page)
            self.assertEqual(page.asked, [])
        for page in (Page(status=401), Page(loads=[(None, 200, True)])):
            with self.assertRaises(site.SessionExpired):
                self.fetch(page)
            self.assertEqual(page.asked, [])
        self.assertFalse(self.out.exists())

    def test_a_refused_bill_after_a_sign_out_stops_the_run(self):
        """The history is read again after a refusal, and the sign-in it
        then shows stops the run rather than send every bill to review."""
        for status in (401, 403, "redirect"):
            page = Page(pdf_status=status, loads=[(answer(ENDS), 200, False), (None, 200, True)])
            with self.assertRaises(site.SessionExpired):
                self.fetch(page)
            self.assertEqual(page.gotos, 2)
        page = Page(pdf=b"<html>sign in</html>",
                    loads=[(answer(ENDS), 200, False), (answer(ENDS), 401, False)])
        with self.assertRaises(site.SessionExpired):
            self.fetch(page)
        self.assertFalse(self.out.exists())

    def test_a_refused_bill_while_the_history_still_reads_is_that_bills_alone(self):
        """So one bill Verizon will not give never stops every later run at
        that same bill."""
        for page in (Page(pdf_status=403), Page(pdf_status="redirect"),
                     Page(pdf=b"<html>not available</html>"), Page(pdf=b'{"error": "none"}')):
            self.assertFalse(self.fetch(page))
            self.assertEqual(page.gotos, 2, "read again once to tell a sign-out apart")
            self.assertFalse(self.out.exists())

    def test_no_single_match_or_a_non_pdf_saves_nothing(self):
        for page, day, doc_id in ((Page(), "2026-01-11", f"bill-{TAG}-2026-01-11"),
                                  (Page(), "2026-09-11", ""), (Page(), "2026-09-11", "bill-2026-09-11"),
                                  (Page(), "2026-08-11", BILL),
                                  (Page(pdf=b"GIF89a"), "2026-09-11", BILL),
                                  (Page(pdf_status=500), "2026-09-11", BILL)):
            self.assertFalse(self.fetch(page, day, doc_id))
            self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
