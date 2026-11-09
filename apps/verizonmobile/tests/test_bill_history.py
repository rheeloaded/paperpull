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
PDF = b"%PDF-1.4 " + b"x" * 3000


def cycle(end):
    return {"billCycleYearRange": end[-4:], "billAmount": "$10.00", "billCycleDateRange": "Sep 12 - Oct 11",
            "billEndDate": end, "billCycleRange": "09/12/2026 - " + end,
            "cta": [{"type": "primary", "label": "Review bill", "link": site.BASE + "/x"},
                    {"type": "secondary", "label": "Review bill PDF", "link": ""}]}


def answer(ends):
    return {"responseInfo": {"responseCode": "00", "sectionErrors": []},
            "body": {"billingHistory": {"billCycle": [cycle(e) for e in ends],
                                        "address": {"accountName": "Zyxwvut Qponml", "addressline1": "100 Wvutsr Ln",
                                                    "city": "Abcdefgh", "state": "OR", "zipCode": "00000-0000",
                                                    "accountNumber": FAKE_ACCOUNT}}}}


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
    def count(self):
        return 0


class Page:
    def __init__(self, data=None, status=200, channel="abc-def123", pdf=PDF, pdf_status=200, asks=True):
        self.data = answer(ENDS) if data is None else data
        self.status, self.channel, self.pdf, self.pdf_status, self.asks = status, channel, pdf, pdf_status, asks
        self.url = "about:blank"
        self.handlers, self.asked = [], []

    def on(self, event, h):
        self.handlers.append(h)

    def remove_listener(self, event, h):
        self.handlers.remove(h)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.url = site.HISTORY_URL
        if self.asks:
            for h in list(self.handlers):
                h(Resp(self.data, self.status, self.channel))

    def locator(self, sel):
        return Locator()

    def evaluate(self, js, arg=None):
        self.asked.append(arg[0])
        if self.pdf_status != 200:
            return {"status": self.pdf_status, "type": "text/html"}
        return {"status": 200, "type": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}


class History(unittest.TestCase):
    def test_every_cycle_is_a_bill_dated_by_its_end(self):
        got = site.collect_download_docs(Page())
        self.assertEqual([d.date_text for d in got], ["2026-10-11", "2026-09-11", "2026-08-11"])
        self.assertEqual([d.document_id for d in got], ["bill-2026-10-11", "bill-2026-09-11", "bill-2026-08-11"])
        self.assertIn(FAKE_ACCOUNT.split("-")[0], site._private_words())
        self.assertNotIn("100", site._private_words(), "a house number is too short to be a word")

    def test_an_unreadable_history_gives_no_list(self):
        for page in (Page(asks=False), Page(status=500), Page(channel=""),
                     Page(data=answer(ENDS + ["02/30/2026"])), Page(data=answer(ENDS + ["10/11/2026"])),
                     Page(data={"responseInfo": {"responseCode": "99"}})):
            self.assertEqual(site.collect_download_docs(page), [])


class PdfAddress(unittest.TestCase):
    def test_the_address_has_exactly_its_two_parameters(self):
        url = site.pdf_url("10/11/2026", "abc-def123")
        self.assertTrue(site.is_pdf_url(url))
        self.assertIn("startMonthDate=10%2F11%2F2026", url)
        for end, chan in (("2026-10-11", "abc"), ("10/11/2026", "a b"), ("10/11/2026", "")):
            self.assertEqual(site.pdf_url(end, chan), "")
        self.assertFalse(site.is_pdf_url(url + "&x=1"))
        self.assertFalse(site.is_pdf_url(url.replace("www.verizon.com", "evil.example")))


class Download(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "Statements" / "bill.pdf"

    def test_the_bill_of_that_day_is_asked_for_and_saved(self):
        page = Page()
        self.assertTrue(site.download_bill(page, None, "2026-09-11", self.out))
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual(page.asked, [site.pdf_url("09/11/2026", "abc-def123")])

    def test_no_single_match_or_a_refusal_saves_nothing(self):
        for page, day in ((Page(), "2026-01-11"), (Page(pdf_status=401), "2026-09-11"),
                          (Page(pdf=b"<html>sign in</html>"), "2026-09-11"), (Page(pdf=b"GIF89a"), "2026-09-11")):
            self.assertFalse(site.download_bill(page, None, day, self.out))
            self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
