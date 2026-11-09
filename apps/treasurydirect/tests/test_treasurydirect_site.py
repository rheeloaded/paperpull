"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only. The pages below are made up
in the shape the 2026-10-13 survey saw (every signed-in page is
/RS/RSGatewayRW?UIHandler=...&processID=..., with the same top tabs); the
taxable year and 1099 pages are the UNCONFIRMED shape the site layer
assumes."""
import ast
import io
import json
import logging
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import treasurydirect_site as site  # noqa: E402
import treasurydirect_docs as docs  # noqa: E402
from paperpull_core import receipt_pdf  # noqa: E402

HOST = "www.treasurydirect.gov"
GATEWAY = f"https://{HOST}/RS/RSGatewayRW"
TODAY = date.today().isoformat()
# Invented account details, which must never leave through a log, the
# console, a record or a diagnostic.
FAKE_NAME = "Zyxwvut"
FAKE_ACCOUNT = "Q-987-654-321"
FAKE_PROCESS = "7777123456"
FAKE_CONFIRM = "QXZ4455667"
FAKE_TIN = "XXX-XX-6789"
# What the account is known by, a digest of its number.
MINE = site.account_digest(FAKE_ACCOUNT)


def href(handler, extra=""):
    return f"/RS/RSGatewayRW?uiFrom=misc.DisplayWelcome&amp;primary=true&amp;processID={FAKE_PROCESS}" \
           f"&amp;fromTabLink=true&amp;UIHandler={handler}{extra}"


TABS = [("My Account", "misc.DisplayWelcome"), ("BuyDirect®", "bd.DisplayBuyDirectIntro"),
        ("Current Holdings", "ch.DisplayCurrentHoldings"), ("ManageDirect®", "md.DisplayManageDirect"),
        ("Account Info", "ai.DisplayAccountInfo"), ("History", "hist.DisplayHistory"),
        ("Investor InBox", "misc.DisplayInvestorInbox"), ("Gift Box", "gb.DisplayGiftBox")]


def frame(h1, body, tabs=True):
    bar = "".join(f'<li><a href="{href(h)}">{t}</a></li>' for t, h in TABS) if tabs else ""
    return f"""<html><head><title>{h1}</title><script>window.x=1</script></head><body>
<a href="{href('misc.MultiAccountSelection')}">Return To Account Listing</a>
<a href="{href('misc.DisplayExit')}">Logoff</a><ul>{bar}</ul>
<p><strong>{FAKE_NAME}'s account:</strong> {FAKE_ACCOUNT}</p><h1>{h1}</h1>{body}
<form action="RSGatewayRW" method="post"><input type="hidden" name="processID" value="{FAKE_PROCESS}"></form>
</body></html>"""


TAXES_NONE = "".join(f"<li>Year {y} (No taxable transactions)</li>" for y in (2026, 2025, 2024))


def managedirect(taxes=TAXES_NONE):
    return frame("ManageDirect", f"""<h4>Manage My Account</h4><ul>
<li><a href="{href('al.DisplayUserChangeSecurityQuestions')}">View/Change my security questions</a></li>
<li><a href="{href('bank.DisplayBankInfo')}">Update my Bank Information</a></li></ul>
<h4>Manage My Securities</h4><ul><li><a href="{href('rd.DisplayRedeem')}">Redeem securities</a></li></ul>
<h4>Manage My Taxes</h4><ul>{taxes}</ul>
<h4>Manage My Linked Accounts</h4><ul><li><a href="{href('la.DisplayLinkedAccountSummary')}">Access my Linked Accounts</a></li></ul>""")


TAXABLE_2025 = (f'<li><a href="{href("tax.DisplayTaxSummary", "&amp;year=2025")}">Year 2025</a></li>'
                "<li>Year 2024 (No taxable transactions)</li>")

PAGES = {
    "misc.DisplayWelcome": lambda: frame("Welcome to Your Account Summary, " + FAKE_NAME + "'s account",
                                         f'<a href="{href("trfrmyt.DisplaySecurityTransfers")}">here</a>'),
    "ch.DisplayCurrentHoldings": lambda: frame("Current Holdings", "<table class='border'><tr><td>Series I Savings Bond</td>"
                                               "<td>$1.00</td></tr></table><form><input type='radio' name='seriesCode'>"
                                               "<input type='submit' value='Submit'></form>"),
    "md.DisplayManageDirect": managedirect,
    "hist.DisplayHistory": lambda: frame("History", f'<a href="{href("sechist.DisplaySecurityHistory")}">Security History</a>'
                                         f'<a href="{href("payhist.DisplayPaymentHistorySummary")}">Payment History</a>'
                                         f'<a href="{href("hist.DisplayAccountHistory")}">Account History</a>'),
    "sechist.DisplaySecurityHistory": lambda: frame("History » Security History",
                                                    f"<table><tr><td>{FAKE_CONFIRM}</td><td>08-08-2026</td></tr></table>"),
    "payhist.DisplayPaymentHistorySummary": lambda: frame("History » Payment History", "<table><tr><td>Confirm #</td></tr></table>"),
    "tax.DisplayTaxSummary": lambda: frame("Taxable Transaction Summary", "<p>Tax year 2025</p>"
                                           f'<a href="{href("tax.Display1099")}">View your 1099 for tax year 2025</a>'),
    "tax.Display1099": lambda: frame("Form 1099-INT", f"<p>For tax year 2025</p><p>Recipient TIN: {FAKE_TIN}</p>"
                                     f'<a href="{href("tax.DisplayTaxSummary")}">Return</a>', tabs=False),
}
UNAVAILABLE = "<html><head><title>TreasuryDirect is unavailable.</title></head><body><h1>TreasuryDirect is unavailable.</h1></body></html>"
OTP = '<html><body><h1>One-time passcode</h1><p>Enter the code we sent</p><input type="text" name="otp"></body></html>'


def handler_of(url):
    return (parse_qs(urlsplit(url).query).get("UIHandler") or [""])[0]


class Loc:
    def __init__(self, page, handler, rx):
        self.page, self.handler, self.rx = page, handler, rx

    def filter(self, has_text):
        return Loc(self.page, self.handler, has_text)

    def _hits(self):
        return [lk for lk in site.read_page(self.page.content()).links
                if lk.handler == self.handler and (self.rx is None or self.rx.search(lk.text))]

    def count(self):
        return len(self._hits())

    @property
    def first(self):
        hits = self._hits()
        return {"page": self.page, "href": hits[0].href if hits else ""}


class Page:
    """The person's tab on the made-up site. Opening an address fails the
    test; a press (the fake pressing.click below) follows the link."""

    def __init__(self, at="misc.DisplayWelcome", pages=None, html=None, url=None):
        self.pages = dict(PAGES, **(pages or {}))
        self.pressed = []
        self._html = html
        self.url = url or f"{GATEWAY}?uiFrom=x&primary=true&processID={FAKE_PROCESS}&UIHandler={at}"
        page = self

        class Ctx:
            pages = [page]
        self.context = Ctx()

    def content(self):
        if self._html is not None:
            return self._html
        return self.pages[handler_of(self.url)]()

    def follow(self, link_href):
        self._html = None
        h = handler_of(link_href.replace("&amp;", "&"))
        target = self.pages.get(h)
        if isinstance(target, str):
            self._html = target
        self.url = f"{GATEWAY}?uiFrom=y{len(self.pressed)}&processID={FAKE_PROCESS}&UIHandler={h}"

    def locator(self, css):
        m = re.search(r'UIHandler=([\w.]+)', css)
        return Loc(self, m.group(1) if m else "", None)

    def wait_for_url(self, pred, timeout=0):
        if not pred(self.url):
            raise TimeoutError("waited")

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def title(self):
        return "TreasuryDirect"

    def is_closed(self):
        return False

    def goto(self, *a, **k):
        raise AssertionError("an address must never be opened")


def fake_click(page, el, *, css, what, words, step="", **kw):
    page.pressed.append(what)
    page.follow(el["href"])


class Pressing(unittest.TestCase):
    def setUp(self):
        self.original = site.pressing.click
        site.pressing.click = fake_click

    def tearDown(self):
        site.pressing.click = self.original


class Hosts(unittest.TestCase):
    def test_only_treasurydirect_hosts_over_https(self):
        self.assertTrue(site.is_safe_url(GATEWAY))
        for u in ("http://www.treasurydirect.gov/RS/RSGatewayRW", "https://caia.treasury.gov/as/authorization.oauth2",
                  "https://www.treasurydirect.gov.evil.test/RS/", "https://maint.treasurydirect.gov/", "", None):
            self.assertFalse(site.is_safe_url(u), u)

    def test_only_the_gateway_on_www_is_a_signed_in_page(self):
        self.assertTrue(site.is_signed_in_url(GATEWAY + "?UIHandler=misc.DisplayWelcome"))
        self.assertFalse(site.is_signed_in_url("https://treasurydirect.gov/RS/RSGatewayRW?UIHandler=misc.DisplayWelcome"))
        self.assertFalse(site.is_signed_in_url(f"https://{HOST}/indiv/help/TDHelp/default.htm"))

    def test_the_handler_is_read_from_the_address(self):
        self.assertEqual(site.handler_of(GATEWAY + "?a=1&UIHandler=ch.DisplayCurrentHoldings"), "ch.DisplayCurrentHoldings")
        for u in ("", None, GATEWAY, GATEWAY + "?UIHandler=a&UIHandler=b", GATEWAY + "?UIHandler=x;y"):
            self.assertEqual(site.handler_of(u), "", u)


class Controls(unittest.TestCase):
    def test_only_the_named_links_are_pressed(self):
        for ok in ("My Account", "Current Holdings", "ManageDirect®", "History", "Security History",
                   "Payment History"):
            self.assertTrue(site.is_safe_control(ok), ok)

    def test_everything_else_is_refused(self):
        for bad in ("", None, "BuyDirect®", "Gift Box", "Logoff", "Return To Account Listing", "here",
                    "Redeem securities", "Transfer securities", "Update my Bank Information",
                    "View/Change my security questions", "Change my password", "Update my Registration List",
                    "Schedule reinvestments", "Assign View or Transact rights", "Access my Linked Accounts",
                    "Establish a Minor Linked Account", "De-Link a Linked Account", "Investor InBox",
                    "Account Info", "Account History", "Submit", "Cancel", "Delete", "View my Funding Options",
                    "View/Delete a pending redemption", "Year 2025 (No taxable transactions)", "Approve",
                    "Year 2025", "View your 1099 for tax year 2025", "Return"):
            self.assertFalse(site.is_safe_control(bad), bad)

    def test_only_the_named_handlers_are_pressed(self):
        for ok in ("misc.DisplayWelcome", "ch.DisplayCurrentHoldings", "md.DisplayManageDirect", "hist.DisplayHistory",
                   "sechist.DisplaySecurityHistory", "payhist.DisplayPaymentHistorySummary"):
            self.assertTrue(site.is_safe_handler(ok), ok)
        for bad in ("", "tax.DisplayTaxSummary", "tax.Display1099", "bd.DisplayBuyDirectIntro", "gb.DisplayGiftBox", "misc.DisplayExit", "misc.MultiAccountSelection",
                    "bank.DisplayBankInfo", "al.DisplayUserChangeSecurityQuestions", "trfrmyt.DisplaySecurityTransfers",
                    "misc.DisplayInvestorInbox", "ai.DisplayAccountInfo", "hist.DisplayRightsHistory",
                    "tax.DisplayTaxEdit", "la.DisplayLinkedAccountSummary", "rd.DisplayRedeem",
                    "tax.DisplayTaxCancel", "tax.DisplayTaxSubmit", "tax.DisplayTaxConfirm", "tax.DisplayApproveTax",
                    "tax.Display1099Request", "tax.DisplayTaxUpdate"):
            self.assertFalse(site.is_safe_handler(bad), bad)


class Session(unittest.TestCase):
    def test_a_signed_in_page_has_the_top_tabs(self):
        site.check_signed_in(PAGES["misc.DisplayWelcome"](), GATEWAY + "?UIHandler=misc.DisplayWelcome")
        with self.assertRaises(site.NotLive):
            site.check_signed_in(PAGES["tax.Display1099"](), GATEWAY + "?UIHandler=tax.Display1099")
        with self.assertRaises(site.NotLive):
            site.check_signed_in(PAGES["misc.DisplayWelcome"](), "https://example.test/RS/RSGatewayRW")

    def test_ended_sessions_are_session_expired(self):
        for html, url in ((UNAVAILABLE, GATEWAY), ("<p>x</p>", "https://caia.treasury.gov/as/authorization.oauth2?x=1"),
                          ('<input type="password">', GATEWAY), ("<p>x</p>", f"https://{HOST}/RS/UN-Display.do")):
            with self.assertRaises(site.SessionExpired, msg=url):
                site.check_signed_in(html, url)

    def test_a_passcode_page_is_otp_required_and_a_link_about_questions_is_not(self):
        with self.assertRaises(site.OtpRequired):
            site.check_signed_in(OTP, GATEWAY)
        self.assertFalse(site.html_asks_for_code(managedirect()))
        welcome = frame("Welcome", '<input type="text" name="iesinglesubmithack"><p>The Traditional login method '
                                   'and security questions will be retired. Enter the code</p>')
        self.assertFalse(site.html_asks_for_code(welcome), "the welcome page's notice is not a passcode page")
        self.assertFalse(site.html_asks_for_code(None))

    def test_a_dead_tab_is_never_called_signed_in(self):
        class Dead:
            @property
            def url(self):
                raise RuntimeError("closed")

            def content(self):
                raise RuntimeError("closed")
        self.assertFalse(site.goto_documents(Dead()))


class TaxYears(unittest.TestCase):
    def test_years_without_taxable_transactions_offer_nothing(self):
        self.assertEqual(site.tax_years_of(site.read_page(managedirect())), [])

    def test_a_taxable_year_link(self):
        self.assertEqual(site.tax_years_of(site.read_page(managedirect(TAXABLE_2025))), ["2025"])

    def test_lists_that_cannot_be_read_stop(self):
        cases = {
            "no section": managedirect().replace("Manage My Taxes", "Something Else"),
            "no items": managedirect(""),
            "an item of another shape": managedirect("<li>Tax summary 2025</li>"),
            "a year link to no handler": managedirect('<li><a href="/RS/RSGatewayRW">Year 2025</a></li>'),
            "a year link to a refused handler": managedirect(f'<li><a href="{href("tax.DisplayTaxEdit")}">Year 2025</a></li>'),
            "a year twice": managedirect(TAXABLE_2025 + f'<li><a href="{href("tax.DisplayTaxSummary")}">Year 2025</a></li>'),
        }
        for name, html in cases.items():
            with self.assertRaises(site.ListStopped, msg=name):
                site.tax_years_of(site.read_page(html))


class Listing(Pressing):
    def test_snapshots_and_taxable_years_with_only_the_managedirect_tab_pressed(self):
        page = Page(pages={"md.DisplayManageDirect": lambda: managedirect(TAXABLE_2025)})
        got = [(d.document_id, d.date_text) for d in site.collect_download_docs(page, today="2026-10-13")]
        self.assertEqual(got, [("holdings-2026-10-13", "2026-10-13"), ("security-history-2026-10-13", "2026-10-13"),
                               ("payment-history-2026-10-13", "2026-10-13"), ("2025-1099", "2025-12-31")])
        self.assertEqual(page.pressed, ["the ManageDirect tab"])

    def test_a_list_that_cannot_be_read_stops_with_the_snapshots(self):
        page = Page(pages={"md.DisplayManageDirect": lambda: managedirect("<li>odd</li>")})
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page)
        self.assertEqual(len(stop.exception.docs), 3)

    def test_session_boundaries_propagate(self):
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(Page(pages={"md.DisplayManageDirect": UNAVAILABLE}))
        with self.assertRaises(site.NotLive):
            site.collect_download_docs(Page(html="<h1>Help</h1>", url=f"https://{HOST}/indiv/help/"))

    def test_a_press_that_lands_elsewhere_stops(self):
        page = Page(pages={"md.DisplayManageDirect": lambda: frame("Something Else", "")})
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(page)


class Download(Pressing):
    def setUp(self):
        super().setUp()
        self.rendered = []
        self.original_render = site.render
        site.render = lambda page, html, out: (self.rendered.append(html), Path(out).write_bytes(b"%PDF-1.4 x"))
        self.out = Path(tempfile.mkdtemp())

    def tearDown(self):
        site.render = self.original_render
        super().tearDown()

    def test_each_snapshot_is_reached_by_its_own_links(self):
        for doc_id, pressed, h1 in (
                (f"holdings-{TODAY}", ["the Current Holdings tab"], "Current Holdings"),
                (f"security-history-{TODAY}", ["the History tab", "the Security History link"], "Security History"),
                (f"payment-history-{TODAY}", ["the History tab", "the Payment History link"], "Payment History")):
            page = Page()
            self.assertTrue(site.download_document(page, doc_id, TODAY, self.out / "a.pdf", account=MINE), doc_id)
            self.assertEqual(page.pressed, pressed)
            self.assertIn(h1, self.rendered[-1])

    def test_a_taxable_year_link_is_never_pressed(self):
        page = Page(pages={"md.DisplayManageDirect": lambda: managedirect(TAXABLE_2025)})
        self.assertFalse(site.download_document(page, "2025-1099", "2025-12-31", self.out / "b.pdf"))
        self.assertEqual(page.pressed, [])
        self.assertEqual(self.rendered, [])
        self.assertFalse(site.TAX_PAGES_SURVEYED)

    def test_a_record_that_is_not_one_presses_nothing(self):
        page = Page()
        for doc_id, day in (("", TODAY), (f"holdings-{TODAY}", "2020-01-01"), ("2025-holdings", TODAY),
                            (None, None), ("2025-1099", "2024-12-31"), ("holdings-2020-01-01", "2020-01-01"),
                            ("inbox-2026-01-01", "2026-01-01")):
            self.assertFalse(site.download_document(page, doc_id, day, self.out / "x.pdf"), doc_id)
        self.assertEqual(page.pressed, [])
        self.assertTrue(site.is_stale("holdings-2020-01-01"))
        self.assertFalse(site.is_stale("2020-1099"))
        self.assertFalse(site.is_stale(None))

    def test_what_no_longer_reads_as_the_document_is_not_saved(self):
        self.assertFalse(site.download_document(Page(), "2025-1099", "2025-12-31", self.out / "x.pdf"))
        wrong = {"md.DisplayManageDirect": lambda: managedirect(TAXABLE_2025),
                 "tax.Display1099": lambda: frame("Form 1099-INT", "<p>For tax year 2019</p>"
                                                  f'<a href="{href("tax.DisplayTaxSummary")}">Return</a>', tabs=False)}
        self.assertFalse(site.download_document(Page(pages=wrong), "2025-1099", "2025-12-31", self.out / "x.pdf"))
        self.assertEqual(self.rendered, [])
        self.assertFalse((self.out / "x.pdf").exists())

    def test_a_sign_out_or_passcode_while_saving_propagates(self):
        with self.assertRaises(site.SessionExpired):
            site.download_document(Page(pages={"ch.DisplayCurrentHoldings": UNAVAILABLE}),
                                   f"holdings-{TODAY}", TODAY, self.out / "x.pdf", account=MINE)
        with self.assertRaises(site.OtpRequired):
            site.download_document(Page(pages={"hist.DisplayHistory": OTP}),
                                   f"security-history-{TODAY}", TODAY, self.out / "x.pdf", account=MINE)

    def test_the_tab_already_on_its_page_is_not_pressed_again(self):
        page = Page(at="ch.DisplayCurrentHoldings")
        self.assertTrue(site.download_document(page, f"holdings-{TODAY}", TODAY, self.out / "c.pdf",
                                               account=MINE))
        self.assertEqual(page.pressed, [])

    def test_a_link_off_the_signed_in_pages_is_never_pressed(self):
        page = Page()
        for h in ("https://evil.test/RS/RSGatewayRW?UIHandler=hist.DisplayHistory",
                  f"https://{HOST}/indiv/help/x.htm?UIHandler=hist.DisplayHistory",
                  "http://www.treasurydirect.gov/RS/RSGatewayRW?UIHandler=hist.DisplayHistory",
                  "https://treasurydirect.gov/RS/RSGatewayRW?UIHandler=hist.DisplayHistory",
                  "javascript:go('UIHandler=hist.DisplayHistory')", "#UIHandler=hist.DisplayHistory"):
            with self.assertRaises(site.ListStopped, msg=h):
                site._press_link(page, site.Link("History", h), "x", "x", lambda hh, p: True)
        self.assertEqual(page.pressed, [])

    def test_a_same_year_summary_is_never_taken_for_the_1099(self):
        summary = PAGES["tax.DisplayTaxSummary"]().replace("<p>Tax year 2025</p>", "<p>Form 1099 for tax year 2025</p>")
        self.assertFalse(site.is_1099_page(summary, "2025"))
        self.assertTrue(site.is_1099_page(PAGES["tax.Display1099"](), "2025"))
        self.assertFalse(site.is_1099_page(PAGES["tax.Display1099"](), "2024"))
        self.assertFalse(site.is_1099_page(None, "2025"))

    def test_a_refused_label_is_never_pressed_even_when_asked(self):
        page = Page()
        with self.assertRaises(site.ListStopped):
            site._press_link(page, site.Link("Logoff", href("misc.DisplayExit")), "x", "x", lambda h, p: True)
        with self.assertRaises(site.ListStopped):
            site._press_link(page, site.Link("History", href("bd.DisplayBuyDirectIntro")), "x", "x", lambda h, p: True)
        self.assertEqual(page.pressed, [])


class Inert(unittest.TestCase):
    def test_the_page_is_rendered_without_scripts_forms_cookies_or_network(self):
        drawn = {}

        class Tmp:
            def set_content(self, html, **kw):
                drawn["html"] = html

            def wait_for_timeout(self, ms):
                pass

        class Ctx:
            def route(self, pattern, handler):
                drawn["route"] = pattern

            def new_page(self):
                return Tmp()

            def close(self):
                drawn["closed"] = True

        class Browser:
            def new_context(self, **kw):
                drawn["context"] = kw
                return Ctx()

        class Signed:
            class context:
                browser = Browser()

        original = receipt_pdf.print_page_to_pdf
        receipt_pdf.print_page_to_pdf = lambda page, out: Path(out).write_bytes(b"%PDF-1.4 x")
        try:
            site.render(Signed(), PAGES["ch.DisplayCurrentHoldings"](), Path(tempfile.mkdtemp()) / "x.pdf")
        finally:
            receipt_pdf.print_page_to_pdf = original
        self.assertFalse(drawn["context"]["java_script_enabled"])
        self.assertEqual(drawn["route"], "**/*")
        self.assertTrue(drawn["closed"])
        for active in ("<script", "<form", "<input", "Submit"):
            self.assertNotIn(active, drawn["html"])
        self.assertIn("Current Holdings", drawn["html"])
        self.assertIn("Series I Savings Bond", drawn["html"])

    @staticmethod
    def _drawn(html):
        """The HTML render hands the fresh page, with a stand-in browser."""
        drawn = {}

        class Tmp:
            def set_content(self, html, **kw):
                drawn["html"] = html

            def wait_for_timeout(self, ms):
                pass

        class Ctx:
            def route(self, pattern, handler):
                pass

            def new_page(self):
                return Tmp()

            def close(self):
                pass

        class Signed:
            class context:
                class browser:
                    @staticmethod
                    def new_context(**kw):
                        return Ctx()

        original = receipt_pdf.print_page_to_pdf
        receipt_pdf.print_page_to_pdf = lambda page, out: Path(out).write_bytes(b"%PDF-1.4 x")
        try:
            site.render(Signed(), html, Path(tempfile.mkdtemp()) / "x.pdf")
        finally:
            receipt_pdf.print_page_to_pdf = original
        return drawn["html"]

    def test_no_link_carries_the_session_id_into_the_pdf(self):
        out = self._drawn(PAGES["hist.DisplayHistory"]())
        for gone in (FAKE_PROCESS, "processID", "UIHandler"):
            self.assertNotIn(gone, out)
        for kept in ("Security History", "Payment History", "History"):
            self.assertIn(kept, out)
        tricky = ("<p><a title=\"a > b\" href='/RS/RSGatewayRW?processID=111'>One</a>"
                  "<A HREF=/RS/RSGatewayRW?processID=222>Two</A>"
                  "<a\nhref = \"/x?processID=333\">Three</a>"
                  "<svg><a xlink:href=\"/x?processID=444\">Four</a></svg>"
                  "<area href=\"/x?processID=555\"><p>href=words stay</p>")
        cut = site.drop_links(tricky)
        for gone in ("111", "222", "333", "444", "555", "processID"):
            self.assertNotIn(gone, cut)
        for kept in ("One", "Two", "Three", "Four", "href=words stay", 'title="a > b"'):
            self.assertIn(kept, cut)
        self.assertEqual(site.drop_links(None), "")

    def test_a_page_wrapped_whole_in_a_form_keeps_its_words(self):
        html = ('<html><body><form method="post" action="RSGatewayRW"><h1>History » Security History</h1>'
                '<table><tr><td>Gift Received</td></tr></table><input type="radio" name="p">'
                '<input type="submit" value="Submit"><button>Delete</button><select name="s"><option>x</option>'
                '</select></form></body></html>')
        out = receipt_pdf.inert_html(site.unwrap_forms(html), site.BASE + "/")
        self.assertIn("Gift Received", out)
        self.assertIn("Security History", out)
        for gone in ("<form", "<input", "<button", "<select", "Delete", "Submit"):
            self.assertNotIn(gone, out)
        self.assertEqual(site.unwrap_forms(None), "")


def real_pdf(text: str = "") -> bytes:
    """A small one-page PDF pypdf opens, with `text` on it (none for a blank
    page), padded past the app's minimum size."""
    safe = re.sub(r"[()\\]", "", text)
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode() if safe else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n%" + b"x" * 3000 + b"\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def h1_pdf(page, html, out, base=None):
    """The fake inert render: a PDF whose text is the page's h1."""
    heads = site.read_page(html).h1
    Path(out).write_bytes(real_pdf(heads[0] if heads else ""))


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(Pressing):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()

    def test_records_are_keyed_by_kind_and_day_and_carry_no_query(self):
        app = make_app(self.tmp, "--discover")
        page = Page(pages={"md.DisplayManageDirect": lambda: managedirect(TAXABLE_2025)})
        for r in site.collect_download_docs(page, today="2026-10-13"):
            app._record_rawdoc(r, page.url)
        app.discovery.save()
        text = app.paths.discovery_json.read_text()
        self.assertNotIn("?", text)
        self.assertNotIn(FAKE_PROCESS, text)
        rec = app.discovery.get(f"id:{MINE}:2025-1099")
        self.assertEqual((rec["category"], rec["summary"], rec["date"], rec["period"], rec["account"]),
                         ("Tax Document", "1099 Tax Form", "2025-12-31", "Tax Year 2025", MINE))
        hold = app.discovery.get(f"id:{MINE}:holdings-2026-10-13")
        self.assertEqual((hold["category"], hold["summary"], hold["period"]), ("Statement", "Current Holdings", ""))
        self.assertEqual(docs.told_apart_by(rec), MINE[:6])
        self.assertEqual(docs.told_apart_by({"document_id": "2025-1099"}), "2025-1099")
        self.assertEqual(docs.told_apart_by({}), "")
        for r, name in ((rec, "2025-12-31 TreasuryDirect 1099 Tax Form.pdf"),
                        (hold, "2026-10-13 TreasuryDirect Current Holdings.pdf")):
            self.assertEqual(docs.build_pdf_filename(r["date"], r["summary"], "", record=docs.Document.from_dict(r)), name)

    def test_a_stale_snapshot_is_skipped_without_a_press(self):
        app = make_app(self.tmp, "--all")
        app._record_rawdoc(site._snapshot(site.HOLDINGS, "2020-01-01"), GATEWAY)
        app._on_its_site = lambda: (_ for _ in ()).throw(AssertionError("no tab is wanted"))
        app._delay = lambda *a, **k: None
        self.assertEqual(app._select(), [])
        # Handed to the run all the same, it is still not taken.
        with redirect_stdout(io.StringIO()) as out:
            app.process([docs.Document.from_dict(v) for v in app.discovery.data.values()])
        self.assertIn("earlier day", out.getvalue())
        self.assertEqual(app.progress.data, {})

    def _stops(self, raised, said):
        app = make_app(self.tmp, "--all")
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, GATEWAY)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def boom(*a, **k):
            raise raised
        original = site.download_document
        site.download_document = boom
        try:
            with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
                app.process(app._select())
        finally:
            site.download_document = original
        self.assertIn(said, out.getvalue())
        self.assertEqual(app.progress.data, {})
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)

    def test_a_press_the_core_refuses_stops_the_run_before_any_later_document(self):
        from paperpull_core import pressing
        app = make_app(self.tmp, "--all")
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, GATEWAY)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None
        asked = []

        def covered(*a, **k):
            asked.append(a[1])
            raise pressing.Covered("press a control", "covered", ["something covered the link"])
        original = site.download_document
        site.download_document = covered
        try:
            with redirect_stdout(io.StringIO()), self.assertRaises(pressing.Stop):
                app.process(app._select())
        finally:
            site.download_document = original
        self.assertEqual(len(asked), 1, "no later document is touched")
        self.assertEqual(app.progress.data, {})

    def test_an_error_keeps_only_its_kind(self):
        app = make_app(self.tmp, "--all")
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, GATEWAY)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None
        leak = f"{GATEWAY}?processID={FAKE_PROCESS} {FAKE_NAME}'s account {FAKE_ACCOUNT}"

        def boom(*a, **k):
            raise RuntimeError(leak)
        original = site.download_document
        site.download_document = boom
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        logging.getLogger().addHandler(handler)
        try:
            with redirect_stdout(seen):
                app.process(app._select(limit=1))
        finally:
            site.download_document = original
            logging.getLogger().removeHandler(handler)
        out = seen.getvalue() + app.paths.progress_json.read_text()
        for word in (FAKE_PROCESS, FAKE_NAME, FAKE_ACCOUNT):
            self.assertNotIn(word, out)
        self.assertIn("RuntimeError", out)

    def test_a_sign_out_stops_the_run_and_records_nothing(self):
        self._stops(site.SessionExpired("x"), "signed out")

    def test_a_passcode_stops_the_run_and_records_nothing(self):
        self._stops(site.OtpRequired("x"), "never answers one")

    def test_a_tab_off_the_account_stops_the_run_and_records_nothing(self):
        self._stops(site.NotLive("x"), "not on a page of your account")

    def test_discovery_on_a_signed_out_or_wrong_tab_stops_without_a_prompt(self):
        for html, url, said in ((UNAVAILABLE, GATEWAY, "signed out"),
                                ("<p>x</p>", "https://caia.treasury.gov/as/authorization.oauth2", "signed out"),
                                (OTP, GATEWAY, "never answers one"),
                                ("<h1>Help</h1>", f"https://{HOST}/indiv/help/", "not on a page of your account"),
                                (PAGES["misc.DisplayWelcome"](), "https://example.test/", "not on TreasuryDirect")):
            app = make_app(tempfile.mkdtemp(), "--discover")
            app.page = lambda: Page(html=html, url=url)
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit):
                app.cmd_discover()
            self.assertEqual(app.discovery.data, {})
            self.assertIn(said, out.getvalue())
            self.assertNotIn("Press Enter", out.getvalue())

    def test_a_list_that_stops_keeps_what_was_read_and_is_not_whole(self):
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(pages={"md.DisplayManageDirect": lambda: managedirect("<li>odd</li>")})
        app.write_failure = lambda *a, **k: None
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            app.cmd_discover()
        self.assertEqual(stop.exception.code, 1)
        self.assertEqual(len(app.discovery.data), 3)

    def test_the_failure_file_of_a_list_that_stops_names_nobody(self):
        app = make_app(self.tmp, "--discover")
        tab = Page(pages={"md.DisplayManageDirect": lambda: managedirect("<li>odd</li>")})
        app.page = lambda: tab
        app._work_page = tab
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            app.cmd_discover()
        written = list(app.paths.diagnostics.rglob("*.json"))
        self.assertTrue(written, "a failure file was written")
        out = "".join(p.read_text(errors="ignore") for p in written)
        for word in (FAKE_PROCESS, FAKE_NAME, FAKE_ACCOUNT, FAKE_CONFIRM):
            self.assertNotIn(word, out, word)

    def _saved(self, pdf_text):
        app = make_app(tempfile.mkdtemp(), "--all")
        app._record_rawdoc(site._snapshot(site.HOLDINGS, TODAY, MINE), GATEWAY)
        app._delay = lambda *a, **k: None
        app._on_its_site = lambda: Page()
        app.write_failure = lambda *a, **k: None
        original = receipt_pdf.print_html_inert_to_pdf
        receipt_pdf.print_html_inert_to_pdf = lambda page, html, out, base=None: Path(out).write_bytes(real_pdf(pdf_text))
        try:
            with redirect_stdout(io.StringIO()):
                app.process(app._select())
        finally:
            receipt_pdf.print_html_inert_to_pdf = original
        return app.progress.get(f"id:{MINE}:holdings-{TODAY}")["state"]

    def test_a_pdf_whose_text_names_its_page_is_saved(self):
        self.assertEqual(self._saved("History Current Holdings"), "Completed")

    def test_a_blank_or_wrong_pdf_is_never_marked_saved(self):
        self.assertEqual(self._saved(""), "Needs Manual Review")
        self.assertEqual(self._saved("Payment History"), "Needs Manual Review")

    def test_pdf_names_document(self):
        self.assertTrue(site.pdf_names_document(f"security-history-{TODAY}", "History » Security History"))
        self.assertTrue(site.pdf_names_document("2025-1099", "Form 1099-INT For tax year 2025"))
        self.assertFalse(site.pdf_names_document("2025-1099", "Form 1099-INT For tax year 2024"))
        for doc_id, text in (("", "Current Holdings"), (None, None), (f"holdings-{TODAY}", "  "),
                             (f"holdings-{TODAY}", "Security History")):
            self.assertFalse(site.pdf_names_document(doc_id, text))

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


# A second made-up account, as the same sign-in might hold.
OTHER_NAME = "Qwertyu"
OTHER_ACCOUNT = "Z-111-222-333"
NUMBER_LINE = f"<p><strong>{FAKE_NAME}'s account:</strong> {FAKE_ACCOUNT}</p>"
LISTING_LINK = f'<a href="{href("misc.MultiAccountSelection")}">Return To Account Listing</a>'


def pages_of(name, account):
    """The made-up site as another account of the sign-in draws it."""
    def swap(make):
        return lambda: make().replace(FAKE_NAME, name).replace(FAKE_ACCOUNT, account)
    return {h: swap(make) for h, make in PAGES.items()}


def pages_without_number(listing=True):
    """The made-up site with no account number drawn, and with or without
    the link back to a list of the sign-in's accounts."""
    def cut(make):
        def page():
            html = make().replace(NUMBER_LINE, "")
            return html if listing else html.replace(LISTING_LINK, "")
        return page
    return {h: cut(make) for h, make in PAGES.items()}


class Accounts(Pressing):
    """One sign-in can hold several accounts (Return To Account Listing), so
    each record is bound to the account it was listed on, by a digest of
    its number, and saved only while the tab is on that account."""

    def setUp(self):
        super().setUp()
        self.original_render = receipt_pdf.print_html_inert_to_pdf
        receipt_pdf.print_html_inert_to_pdf = h1_pdf

    def tearDown(self):
        receipt_pdf.print_html_inert_to_pdf = self.original_render
        super().tearDown()

    @staticmethod
    def _run(app, tab, discover=True):
        app.page = lambda: tab
        app._on_its_site = lambda: tab
        app._delay = lambda *a, **k: None
        app.write_failure = lambda *a, **k: None
        with redirect_stdout(io.StringIO()) as out:
            if discover:
                app.cmd_discover(quiet=True)
            app.process(app._select())
        return out.getvalue()

    def test_a_second_account_on_the_same_day_is_saved_under_its_own_key(self):
        tmp = tempfile.mkdtemp()
        self._run(make_app(tmp, "--all"), Page(pages=pages_of(OTHER_NAME, OTHER_ACCOUNT)))
        app = make_app(tmp, "--all")
        out = self._run(app, Page())
        self.assertEqual(out.count("Saved:"), 3, "the second account's are taken, not skipped")
        saved = [r for r in app.progress.data.values() if r.get("state") == "Completed"]
        self.assertEqual(len(saved), 6)
        self.assertEqual(len({r["account"] for r in saved}), 2)
        names = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
        self.assertEqual(len(names), 6)
        written = names + list(app.progress.data) + [app.paths.progress_json.read_text(),
                                                     app.paths.discovery_json.read_text()]
        for text in written:
            for word in (FAKE_ACCOUNT, OTHER_ACCOUNT, "987654321", "111222333", "987-654", "111-222"):
                self.assertNotIn(word, text)

    def test_a_tab_on_another_account_sends_the_document_to_review_unsaved(self):
        app = make_app(tempfile.mkdtemp(), "--all")
        app.page = lambda: Page()
        with redirect_stdout(io.StringIO()):
            app.cmd_discover(quiet=True)
        other = Page(pages=pages_of(OTHER_NAME, OTHER_ACCOUNT))
        out = self._run(app, other, discover=False)
        self.assertEqual({r["state"] for r in app.progress.data.values()}, {"Needs Manual Review"})
        self.assertEqual(list(app.paths.root.rglob("*.pdf")), [])
        self.assertEqual(other.pressed, [])
        self.assertIn("another TreasuryDirect account", out)

    def test_the_page_reached_must_be_the_recorded_account(self):
        mine = site.account_digest(FAKE_ACCOUNT)
        out = Path(tempfile.mkdtemp()) / "x.pdf"
        rendered = []
        original = site.render
        site.render = lambda page, html, path: rendered.append(html)
        try:
            other = Page(pages=pages_of(OTHER_NAME, OTHER_ACCOUNT))
            with self.assertRaises(site.OtherAccount):
                site.download_document(other, f"holdings-{TODAY}", TODAY, out, account=mine)
            self.assertEqual(other.pressed, [])
            moved = Page(pages={"ch.DisplayCurrentHoldings":
                                pages_of(OTHER_NAME, OTHER_ACCOUNT)["ch.DisplayCurrentHoldings"]})
            with self.assertRaises(site.OtherAccount):
                site.download_document(moved, f"holdings-{TODAY}", TODAY, out, account=mine)
        finally:
            site.render = original
        self.assertEqual(rendered, [])

    def test_several_accounts_and_no_number_stop_the_list(self):
        page = Page(pages=pages_without_number(listing=True))
        with self.assertRaises(site.ListStopped) as stop:
            site.collect_download_docs(page)
        self.assertEqual(stop.exception.docs, [])
        self.assertEqual(page.pressed, [])

    def test_one_account_and_no_number_is_listed_as_before(self):
        page = Page(pages=pages_without_number(listing=False))
        got = site.collect_download_docs(page, today="2026-10-13")
        self.assertEqual([(d.document_id, d.account) for d in got],
                         [("holdings-2026-10-13", ""), ("security-history-2026-10-13", ""),
                          ("payment-history-2026-10-13", "")])

    def test_the_account_number_is_private_and_only_its_digest_is_kept(self):
        site.set_private_words([])
        got = site.collect_download_docs(Page(), today="2026-10-13")
        digest = site.account_digest(FAKE_ACCOUNT)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{12}", digest), digest)
        self.assertEqual({d.account for d in got}, {digest})
        self.assertEqual(site.account_digest("q987654321"), digest)
        self.assertNotEqual(site.account_digest(OTHER_ACCOUNT), digest)
        self.assertEqual(site.account_digest(""), "")
        for word in (FAKE_ACCOUNT, "Q987654321"):
            self.assertIn(word, site.private_words())
        keys ={docs.Document(**{"title": d.title, "account": d.account, "document_id": d.document_id}).key
                for d in got}
        self.assertEqual(keys, {f"id:{digest}:{d.document_id}" for d in got})


class Repeats(Pressing):
    """What a run has told once is not told again on every later run."""

    def test_a_taxable_year_set_aside_is_recorded_once(self):
        tmp = tempfile.mkdtemp()
        tab = Page(pages={"md.DisplayManageDirect": lambda: managedirect(TAXABLE_2025)})
        counts, said = [], []
        for _ in range(3):
            app = make_app(tmp, "--all")
            app.page = lambda: tab
            app._on_its_site = lambda: tab
            app._delay = lambda *a, **k: None
            with redirect_stdout(io.StringIO()) as out:
                app.cmd_discover(quiet=True)
                app.process([d for d in app._select() if d.document_id.endswith("-1099")])
            app.progress.save()
            rows = [r for r in app.index_csv.read_all() if "1099" in r.get("Document Title", "")]
            counts.append((app.stats["manual_review"], len(rows)))
            said.append(out.getvalue())
        self.assertEqual(counts, [(1, 1), (0, 1), (0, 1)])
        self.assertIn("save by hand", said[-1])
        self.assertFalse(any("Year" in p or "1099" in p for p in tab.pressed))
        app = make_app(tmp, "--resume")
        left = [d for d in app._select() if not app._already_done(d)]
        self.assertFalse([d for d in left if d.document_id.endswith("-1099")])

    def test_snapshots_of_earlier_days_are_not_selected_or_resumed(self):
        app = make_app(tempfile.mkdtemp(), "--resume")
        days = [(date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]
        for day in days:
            for r in site.collect_download_docs(Page(), today=day):
                app._record_rawdoc(r, GATEWAY)
        app.discovery.save()
        today = sorted(f"{k}-{TODAY}" for k in ("holdings", "security-history", "payment-history"))
        self.assertEqual(sorted(d.document_id for d in app._select()), today)
        handed = []
        app.process = lambda left, dry_run=False: handed.extend(left)
        with redirect_stdout(io.StringIO()) as out:
            app.cmd_resume()
        self.assertEqual(sorted(d.document_id for d in handed), today)
        self.assertIn("3 document(s) remaining", out.getvalue())


class OwnBrowser(unittest.TestCase):
    """Settings with no cdp_url open a browser of the app's own, and only
    through the core, which says so (#90). The sign-in opens on the port
    config.example.json names."""

    def test_a_run_without_cdp_url_opens_its_browser_through_the_core(self):
        import playwright.sync_api as sync_api
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--discover")
        app.config["cdp_url"] = ""
        app.config["profile_dir"] = str(Path(tmp) / "profile")
        called = {}

        class Ctx:
            pages = []

            def set_default_timeout(self, ms):
                called["timeout"] = ms

        class Chromium:
            def launch_persistent_context(self, *a, **k):
                called["direct"] = True
                return Ctx()

        class Pw:
            chromium = Chromium()

            def stop(self):
                pass

        class Starter:
            def start(self):
                return Pw()

        def launch(chromium, user_data_dir, **kw):
            called["core"] = (chromium, user_data_dir)
            return Ctx()
        originals = (sync_api.sync_playwright, docs.browser_launcher.launch_own_browser)
        sync_api.sync_playwright = lambda: Starter()
        docs.browser_launcher.launch_own_browser = launch
        try:
            app.browser()
        finally:
            sync_api.sync_playwright, docs.browser_launcher.launch_own_browser = originals
        self.assertNotIn("direct", called, "Playwright was asked for a browser directly")
        self.assertIsInstance(called["core"][0], Chromium)
        self.assertEqual(called["core"][1], app.config["profile_dir"])

        opened = {}
        original = docs.browser_launcher.open_signin_browser
        docs.browser_launcher.open_signin_browser = lambda profile, port, url, **kw: opened.update(port=port) or "Chrome"
        try:
            with redirect_stdout(io.StringIO()):
                app.cmd_open_browser()
        finally:
            docs.browser_launcher.open_signin_browser = original
        example = json.loads((HERE / "config.example.json").read_text())["cdp_url"]
        self.assertEqual(opened["port"], example.rsplit(":", 1)[1])


def without_the_folder(text, tmp):
    """text with the run's own temporary folder taken out however it is
    written. Its name is random and the console and the index print paths
    inside it, so it can hold any short run of digits a check looks for."""
    for written in (str(tmp), json.dumps(str(tmp))[1:-1], Path(tmp).as_posix()):
        text = text.replace(written, "<folder>")
    return text


class Privacy(Pressing):
    """Nothing that names the account reaches a log line, the console, the
    run's records or a diagnostic, and all of it is registered as private."""

    def test_account_details_stay_out_of_logs_stdout_records_and_diagnostics(self):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        original = receipt_pdf.print_html_inert_to_pdf
        receipt_pdf.print_html_inert_to_pdf = h1_pdf
        tab = Page(pages={"md.DisplayManageDirect": lambda: managedirect(TAXABLE_2025)})
        try:
            with redirect_stdout(seen):
                app.page = lambda: tab
                app.cmd_discover()
                app._delay = lambda *a, **k: None
                app._on_its_site = lambda: tab
                app.process(app._select())
                app.cmd_diagnose()
                with self.assertRaises(site.ListStopped):
                    site.collect_download_docs(Page(pages={"md.DisplayManageDirect": lambda: managedirect("<li>x</li>")}))
        finally:
            receipt_pdf.print_html_inert_to_pdf = original
            root.removeHandler(handler)
            root.setLevel(old)
        out = seen.getvalue() + app.paths.discovery_json.read_text() + app.paths.progress_json.read_text()
        out += "".join(p.read_text(errors="ignore") for p in app.paths.diagnostics.rglob("*.json"))
        out += "".join(p.read_text(errors="ignore") for p in app.paths.root.rglob("*.csv"))
        out = without_the_folder(out, tmp)
        for word in (FAKE_NAME, FAKE_ACCOUNT, FAKE_PROCESS, FAKE_CONFIRM, FAKE_TIN, "987-654", "6789"):
            self.assertNotIn(word, out, word)
        for word in (FAKE_NAME, FAKE_ACCOUNT, FAKE_PROCESS, FAKE_CONFIRM):
            self.assertIn(word, site.private_words(), word)
        self.assertIn("Tester", site.private_words(), "the owner's name is kept beside them")
        for word in ("Account", "Gift", "History", "TreasuryDirect", "Welcome", "Summary"):
            self.assertNotIn(word, site.private_words(), "a word of the page's own is not private")
        self.assertEqual(len(site.private_words()), len(set(site.private_words())), "nothing twice")
        names = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
        self.assertEqual(names, sorted([f"{TODAY} TreasuryDirect Current Holdings.pdf",
                                        f"{TODAY} TreasuryDirect Payment History.pdf",
                                        f"{TODAY} TreasuryDirect Security History.pdf"]))
        rec = app.progress.get(f"id:{MINE}:2025-1099")
        self.assertEqual(rec["state"], "Needs Manual Review", "a taxable year is shown, never pressed")
        self.assertFalse(any("Year" in p or "1099" in p for p in tab.pressed))
        for refused in ("Logoff", "BuyDirect", "Gift Box", "here", "Redeem", "Bank", "Linked", "InBox", "Account Info"):
            self.assertFalse(any(refused in p for p in tab.pressed), refused)


class NothingOpenedOrSubmitted(unittest.TestCase):
    def test_the_site_layer_never_opens_an_address_fills_or_submits(self):
        tree = ast.parse((HERE / "treasurydirect_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("dblclick", "tap", "fill", "type", "press", "select_option", "check", "uncheck",
                     "set_input_files", "dispatch_event", "press_sequentially", "goto", "go_back",
                     "go_forward", "reload", "post", "fetch", "evaluate", "submit", "new_page", "new_context"):
            self.assertNotIn(verb, called, verb)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertNotIn("request", attrs, "no address is asked with the session's cookies")
        # The one press, through the core guard.
        presses = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "click"]
        self.assertEqual(len(presses), 1)
        self.assertEqual(ast.unparse(presses[0].func), "pressing.click")


if __name__ == "__main__":
    unittest.main()


def test_a_log_in_tab_is_known_by_its_address():
    assert site.looks_like_login_url("https://www.treasurydirect.gov/log-in/")
    assert site.looks_like_login_url("https://caia.treasury.gov/as/authorization.oauth2?x=1")
    assert not site.looks_like_login_url("https://www.treasurydirect.gov/RS/RSGatewayRW?UIHandler=misc.DisplayWelcome")
