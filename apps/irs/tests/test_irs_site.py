"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only.

The transcript routes come from a read-only survey; what the survey did not
see is held to its boundaries here: the app reads only the shapes irs_site.py
names, stops on anything else, never presses, never touches the sign-in,
and keeps the taxpayer's details out of every log, record and file name."""
import ast
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
import irs_site as site  # noqa: E402
import irs_docs as docs  # noqa: E402

HOST = "sa.www4.irs.gov"
API = f"https://{HOST}/ola/api/shared/accounts/taxrecords/1.0/taxpayers/transcripts"
T_ACCT = f"{API}/account/202412/30"
# Invented taxpayer details, which must never leave through a log, the
# console, a record or a file name.
FAKE_SSN = "XXX-XX-9876"
FAKE_NAME = "Quillfeather"

ITEMS = [
    {"transcriptType": "account", "taxPeriod": "202412", "mft": "30", "taxForm": "1040", "availableLanguages": ["en", "es"]},
    {"transcriptType": "return", "taxPeriod": "202412", "mft": "30", "taxForm": "1040", "availableLanguages": ["en"]},
    {"transcriptType": "wageAndIncome", "taxPeriod": "202312", "mft": "00", "taxForm": "All Forms",
     "availableLanguages": ["en"]},
    {"transcriptType": "recordOfAccount", "taxPeriod": "202212", "mft": "30", "taxForm": "1040 Series",
     "availableLanguages": ["en"]},
]
NO_NOTICES = {"text": "Notices and letters There are no notices at this time.", "docs": 0}


class Resp:
    def __init__(self, status=200, ctype="application/pdf", body=b"%PDF-1.4 x", location=""):
        self.status, self.ok = status, status == 200
        self.headers = {"content-type": ctype, **({"location": location} if location else {})}
        self._body, self.url, self.disposed = body, "", False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


def jresp(data, status=200, ctype="application/json"):
    return Resp(status, ctype=ctype, body=json.dumps(data).encode())


class Req:
    """The session's request client. The transcript list answers `items`
    every time it is asked; anything else takes the next of `answers`."""

    def __init__(self, items, answers, list_answer=None):
        self.items, self.answers, self.list_answer, self.asked = items, list(answers), list_answer, []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_redirects")))
        if url == API:
            r = self.list_answer or jresp(self.items)
        else:
            r = self.answers.pop(0)
        r.url = url
        return r


class Locator:
    def __init__(self, n, text=""):
        self.n, self.text = n, text

    def count(self):
        return self.n

    def inner_text(self, **kw):
        return self.text


class Page:
    """The transcript and notices pages as surveyed, with nothing pressed."""

    def __init__(self, items=ITEMS, notices=NO_NOTICES, ready=True, settled=None, password=False,
                 answers=(), list_answer=None, start=f"https://{HOST}/ola/", body=""):
        self.notices, self.ready, self.settled, self.password = notices, ready, settled, password
        self.body = body
        self.url, self.gotos, self.pressed = start, [], []
        page = self

        class Ctx:
            request = Req(items, answers, list_answer)
            pages = [page]
        self.context = Ctx()

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = self.settled or url

    def wait_for_selector(self, sel, **kw):
        if not self.ready:
            raise TimeoutError("waited")

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        if "password" in sel:
            return Locator(1 if self.password else 0)
        return Locator(0, self.body)

    def title(self):
        return "IRS Online Account"

    def evaluate(self, js, arg=None):
        if "matchAll" in js:
            return [f"{FAKE_NAME} Example", FAKE_SSN]
        return self.notices

    def __getattr__(self, name):
        if name in ("click", "fill", "press", "type", "check", "select_option", "tap", "dblclick"):
            def pressed(*a, **k):
                self.pressed.append(name)
                raise AssertionError("the app pressed " + name)
            return pressed
        raise AttributeError(name)


class Dead:
    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")


class Hosts(unittest.TestCase):
    def test_only_the_online_account_host_over_https(self):
        for u in [f"https://{HOST}/ola/", T_ACCT, API]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["https://www.irs.gov/your-account", f"http://{HOST}/ola/", f"https://user@{HOST}/ola/",
                  f"https://{HOST}@evil.test/ola/", f"https://x.{HOST}/ola/", f"https://{HOST}.evil.test/",
                  f"https://{HOST}:8443/ola/", "https://api.id.me/en/session/new", "https://secure.login.gov/",
                  "https://la.www4.irs.gov/", f"blob:https://{HOST}/0b1c", "javascript:alert(1)", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_a_transcript_address_is_one_shape_only(self):
        self.assertTrue(site.is_download_url(T_ACCT))
        self.assertEqual(site.download_url("account", "202412", "30"), T_ACCT)
        self.assertEqual(site.download_url("wageAndIncome", "202312", "00"), f"{API}/wageAndIncome/202312/00")
        self.assertTrue(site.is_list_url(API))
        for u in [T_ACCT + "?ssn=1", T_ACCT + "#x", T_ACCT.replace("https:", "http:"), T_ACCT + "/",
                  T_ACCT.replace(HOST, "www.irs.gov"), f"{API}/account/202412", f"{API}/Account/202412/30",
                  f"{API}/account/20241/30", f"{API}/account/202412/3000", f"{API}/account/%32%30/30",
                  f"{API}/../x/202412/30", API, f"blob:{T_ACCT}", "", None]:
            self.assertFalse(site.is_download_url(u), repr(u))
        for bad in [("", "202412", "30"), ("account", "", "30"), ("account", "202412", ""),
                    ("acc ount", "202412", "30"), ("account", "2024-12", "30"), ("account", "2024", "30"),
                    ("wage_income", "202412", "30"), ("WageAndIncome", "202412", "30"), (None, None, None)]:
            self.assertEqual(site.download_url(*bad), "", bad)
        self.assertFalse(site.is_list_url(API + "?page=2"))

    def test_tax_periods(self):
        self.assertEqual(site.period_date("202412"), "2024-12-31")
        self.assertEqual(site.period_date("202402"), "2024-02-29")
        for bad in ("202413", "202400", "2024", "20240415", "12", "189912", "", None, "2024-12"):
            self.assertIsNone(site.period_date(bad), repr(bad))


class Controls(unittest.TestCase):
    def test_own_documents_under_view_and_download(self):
        for label in ["View", "Download", "View PDF", "Download Transcript", "EN", "Account Transcript",
                      "View Return Transcript", "Download Wage and Income Transcript",
                      "2024 Account Transcript PDF will open in a new window",
                      "2023 Wage & Income Transcript PDF will open in a new window",
                      "2022 Record of Account Transcript PDF will open in a new window",
                      "View Record of Account Transcript"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_everything_else_is_refused(self):
        for label in ["Make a Payment", "Pay Now", "Direct Pay", "Payment Plan", "Schedule a payment",
                      "Cancel payment", "Add bank account", "Get an IP PIN", "Request IP PIN",
                      "Authorizations", "Approve request", "Form 2848", "Change address", "Profile",
                      "Language preference", "Go paperless for certain IRS notices", "Get transcript by mail",
                      "Request a transcript", "Logout", "Sign Out", "Sign in with ID.me", "Continue", "Submit",
                      "Account balance", "Payments", "Show more transcripts", "View your profile",
                      "Download 2024 and pay", "EN Pay", "Print", "", "   ", None]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Transcripts(unittest.TestCase):
    def test_items_by_their_own_fields(self):
        got = site.transcripts_of(ITEMS)
        self.assertEqual([(d.title, d.date_text, d.document_id, d.kind) for d in got], [
            ("IRS Account Transcript 202412", "2024-12-31", "transcript-account-202412-30", "transcript"),
            ("IRS Return Transcript 202412", "2024-12-31", "transcript-return-202412-30", "transcript"),
            ("IRS Wage and Income Transcript 202312", "2023-12-31", "transcript-wageAndIncome-202312-00",
             "transcript"),
            ("IRS Record of Account Transcript 202212", "2022-12-31", "transcript-recordOfAccount-202212-30",
             "transcript")])
        self.assertEqual(got[0].href, "/ola/api/shared/accounts/taxrecords/1.0/taxpayers/transcripts/account/202412/30")
        self.assertEqual(site.transcripts_of([]), [])

    def test_unreadable_items_stop_with_what_was_read(self):
        good = ITEMS[:1]
        for bad, why in [(dict(ITEMS[1], transcriptType="civil_penalty"), "a type not seen"),
                         (dict(ITEMS[1], transcriptType="Return"), "a type of another shape"),
                         (dict(ITEMS[1], transcriptType="wage_income"), "the old guessed spelling"),
                         (dict(ITEMS[1], taxPeriod="2024"), "a year alone"),
                         (dict(ITEMS[1], taxPeriod="202413"), "no such month"),
                         (dict(ITEMS[1], taxPeriod="2024-12"), "a period of another shape"),
                         (dict(ITEMS[1], mft=None), "no mft"),
                         (dict(ITEMS[1], availableLanguages=["es"]), "no English"),
                         (dict(ITEMS[1], availableLanguages=None), "no languages"),
                         (dict(ITEMS[0]), "twice"),
                         ("account", "not an item")]:
            with self.assertRaises(site.ListStopped, msg=why) as stop:
                site.transcripts_of(good + [bad])
            self.assertEqual([d.document_id for d in stop.exception.docs], ["transcript-account-202412-30"], why)

    def test_two_of_one_type_and_period_are_named_apart_by_their_own_fields(self):
        twin = dict(ITEMS[0], mft="29", taxForm="1040 Series")
        got = site.transcripts_of([ITEMS[0], twin, ITEMS[1]])
        self.assertEqual([(d.title, d.variant) for d in got],
                         [("IRS Account Transcript 202412 1040", "1040"),
                          ("IRS Account Transcript 202412 1040 Series", "1040 Series"),
                          ("IRS Return Transcript 202412", "")])
        # One form for both, or a form that is not plain, falls back to the MFT.
        for other in (dict(ITEMS[0], mft="29"), dict(ITEMS[0], mft="29", taxForm=""),
                      dict(ITEMS[0], mft="29", taxForm="1040/Sch C")):
            got = site.transcripts_of([ITEMS[0], other])
            self.assertEqual([d.variant for d in got], ["MFT 30", "MFT 29"], other)
            self.assertEqual(got[1].title, "IRS Account Transcript 202412 MFT 29")

    def test_a_form_that_is_not_an_irs_form_never_names_a_file(self):
        self.assertEqual([d.variant for d in site.transcripts_of(
            [dict(ITEMS[0], taxForm="1040 Series"), dict(ITEMS[0], mft="29", taxForm="5329")])],
            ["1040 Series", "5329"])
        for hostile in ("Jane Smith", "123 Main St", "123456789", "1040 Jane", "All Forms Jane", "1040\nSmith"):
            got = site.transcripts_of([dict(ITEMS[0], taxForm="1040"), dict(ITEMS[0], mft="29", taxForm=hostile)])
            self.assertEqual([d.variant for d in got], ["MFT 30", "MFT 29"], hostile)
            for d in got:
                self.assertNotIn(hostile, d.title + d.text + d.variant)

    def test_rules_name_each_type(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        for title, summary in [("IRS Account Transcript 202412", "Account Transcript"),
                               ("IRS Return Transcript 202412", "Return Transcript"),
                               ("IRS Wage and Income Transcript 202312", "Wage and Income Transcript"),
                               ("IRS Record of Account Transcript 202212", "Record of Account Transcript")]:
            self.assertEqual(doc_types.classify_document(title, rules)[:2], ("Tax Document", summary), title)
        self.assertFalse(doc_types.should_skip("IRS Record of Account Transcript 202212", rules))


class ListReady(unittest.TestCase):
    def test_the_page_is_opened_and_its_own_list_read_with_no_redirect(self):
        page = Page()
        got = site.collect_download_docs(page)
        self.assertEqual(len(got), 4)
        self.assertEqual(page.gotos, [site.DOCUMENTS_URL, site.NOTICES_URL])
        self.assertEqual(page.context.request.asked, [(API, 0)])
        self.assertTrue(site.bill_list_opens(Page()))

    def test_an_empty_account_is_empty(self):
        self.assertEqual(site.collect_download_docs(Page(items=[])), [])

    def test_a_list_of_another_shape_stops(self):
        for answer, why in [(jresp({"items": ITEMS}), "an object, not a list"),
                            (jresp(ITEMS, ctype="text/plain"), "not json"),
                            (Resp(500, ctype="application/json", body=b"{}"), "an error"),
                            (Resp(ctype="application/json", body=b"[{"), "broken json")]:
            with self.assertRaises(site.ListStopped, msg=why):
                site.collect_download_docs(Page(list_answer=answer))

    def test_a_signed_out_list_is_session_expired(self):
        for answer in [Resp(302, ctype="text/html", body=b"", location="https://www.irs.gov/"),
                       Resp(401, ctype="application/json", body=b"{}"),
                       Resp(403, ctype="text/plain", body=b"no"),
                       Resp(200, ctype="text/html", body=b"<html>Sign in</html>")]:
            page = Page(list_answer=answer)
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)
            self.assertEqual(len(page.context.request.asked), 1, "a redirect is never followed")

    def test_notices_only_as_seen(self):
        for seen, why in [({"text": "CP14 Balance due 03/14/2026 View", "docs": 1}, "a notice"),
                          ({"text": "There are no notices at this time.", "docs": 1}, "the sentence and a link"),
                          ({"text": "Notices and letters", "docs": 0}, "neither"),
                          ({"text": "There are no notices at this time. CP14 Balance due", "docs": 0},
                           "the sentence and a notice code in plain text"),
                          ({"text": "There are no notices at this time. Issued 03/14/2026", "docs": 0},
                           "the sentence and a date"),
                          (None, "no main area")]:
            page = Page(notices=seen)
            with self.assertRaises(site.ListStopped, msg=why) as stop:
                site.collect_download_docs(page)
            self.assertEqual(len(stop.exception.docs), 4, "the transcripts read are kept")
            self.assertNotIn("CP14", str(stop.exception))
            self.assertFalse(site.bill_list_opens(Page(notices=seen)))

    def test_a_page_that_does_not_settle_or_draw_stops(self):
        for page in (Page(ready=False), Page(settled=f"https://{HOST}/ola/")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)
            self.assertEqual(page.context.request.asked, [])

    def test_a_page_sent_off_the_online_account_is_signed_out(self):
        """A signed-out visit is sent on to another IRS host, among others.
        The account holder is asked to sign in again, not told the list
        stopped, and nothing there is read."""
        for where in ("https://la.www4.irs.gov/", "https://www.irs.gov/your-account",
                      f"http://{HOST}{site.TRANSCRIPTS_PATH}", "https://irs.example/ola/tax_records/transcripts"):
            page = Page(settled=where)
            with self.assertRaises(site.SessionExpired, msg=where) as stop:
                site.collect_download_docs(page)
            self.assertNotIsInstance(stop.exception, site.OtpRequired, where)
            self.assertEqual(page.context.request.asked, [], where)
            self.assertFalse(site.bill_list_opens(Page(settled=where)), where)

    def test_sign_in_pages_are_session_expired_and_id_me_is_otp(self):
        with self.assertRaises(site.OtpRequired):
            site.collect_download_docs(Page(settled="https://api.id.me/en/session/new"))
        for page in (Page(settled=f"https://{HOST}/secureaccess/ui/login"), Page(password=True)):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)
        self.assertTrue(issubclass(site.OtpRequired, site.SessionExpired))

    def test_a_dead_tab_is_not_live(self):
        class Gone(Page):
            def goto(self, url, **kw):
                raise RuntimeError("closed")

            @property
            def url(self):
                raise RuntimeError("closed")

            @url.setter
            def url(self, v):
                pass
        with self.assertRaises(site.NotLive):
            site.collect_download_docs(Gone())


class SignedOut(unittest.TestCase):
    def test_sign_in_shapes(self):
        for u in ["https://api.id.me/en/session/new", "https://secure.login.gov/", f"https://{HOST}/secureaccess/ui/",
                  f"https://{HOST}/ola/logout"]:
            self.assertTrue(site.looks_signed_out(Page(start=u)), u)
        self.assertTrue(site.looks_signed_out(Page(start=site.DOCUMENTS_URL, password=True)))
        self.assertFalse(site.looks_signed_out(Page(start=site.DOCUMENTS_URL)))
        self.assertFalse(site.on_identity_host("https://id.me.evil.test/"))

    def test_an_id_me_page_is_a_challenge_and_is_not_read(self):
        page = Page(start="https://api.id.me/en/multifactor", body="enter the code")
        self.assertIn("ID.me", site.detect_security_challenge(page))
        self.assertIsNone(site.detect_security_challenge(Page(start=site.DOCUMENTS_URL)))

    def test_a_dead_page_raises(self):
        with self.assertRaises(RuntimeError):
            site.looks_signed_out(Dead())


class Download(unittest.TestCase):
    HREF = "/ola/api/shared/accounts/taxrecords/1.0/taxpayers/transcripts/account/202412/30"

    def fetch(self, page, date="2024-12-31", doc_id="transcript-account-202412-30", href=None):
        out = Path(tempfile.mkdtemp()) / "o.pdf"
        ok = site.download_bill(page, None, date, out, trace=[], href=self.HREF if href is None else href,
                                document_id=doc_id)
        return ok, out

    def test_the_list_again_then_one_request_to_the_items_own_address(self):
        page = Page(answers=[Resp(ctype="Application/PDF; charset=binary")])
        ok, out = self.fetch(page)
        self.assertTrue(ok)
        self.assertEqual(page.context.request.asked, [(API, 0), (T_ACCT, 0)])
        self.assertEqual(page.gotos, [site.DOCUMENTS_URL], "only the transcript page is opened")
        self.assertTrue(out.read_bytes().startswith(b"%PDF-"))

    def test_no_recorded_address_means_no_request(self):
        for kw in [dict(doc_id=""), dict(doc_id="notice-cp14"), dict(href=""), dict(href=T_ACCT)]:
            page = Page(answers=[Resp()])
            ok, out = self.fetch(page, **kw)
            self.assertFalse(ok, kw)
            self.assertEqual(page.context.request.asked, [], kw)
            self.assertFalse(out.exists())

    def test_a_record_the_list_no_longer_holds_is_not_taken_and_stops_nothing(self):
        """The IRS moves each kind of transcript's years online forward every
        year, so a transcript discovery recorded can drop off the list. That
        record goes to review, and the run goes on."""
        for items, kw in [(ITEMS[1:], {}),
                          (ITEMS, dict(date="2023-12-31")),
                          (ITEMS, dict(doc_id="transcript-account-202312-30")),
                          (ITEMS, dict(href=self.HREF.replace("/account/", "/return/")))]:
            page = Page(items=items, answers=[Resp()])
            out = Path(tempfile.mkdtemp()) / "o.pdf"
            trace = []
            ok = site.download_bill(page, None, kw.get("date", "2024-12-31"), out, trace=trace,
                                    href=kw.get("href", self.HREF),
                                    document_id=kw.get("doc_id", "transcript-account-202412-30"))
            self.assertFalse(ok, kw)
            self.assertFalse(out.exists(), kw)
            self.assertEqual(page.context.request.asked, [(API, 0)], kw)
            self.assertEqual(trace, [{"note": "the record is gone from the list", "matches": 0}], kw)

    def test_a_list_that_cannot_be_read_again_stops(self):
        for page in (Page(items=ITEMS + [dict(ITEMS[0])], answers=[Resp()]),
                     Page(list_answer=Resp(500, ctype="application/json", body=b"{}"))):
            with self.assertRaises(site.ListStopped):
                self.fetch(page)
            self.assertNotIn((T_ACCT, 0), page.context.request.asked)

    def test_signed_out_answers_raise_and_save_nothing(self):
        for answer in [Resp(302, ctype="text/html", body=b"", location="https://api.id.me/"),
                       Resp(302, ctype="text/html", body=b"", location=f"{API}/return/202412/30"),
                       Resp(401, ctype="application/json", body=b'{"status":401}'),
                       Resp(200, ctype="text/html", body=b"<html>Sign in</html>"),
                       Resp(403, ctype="text/plain", body=b"no"),
                       Resp(body=b"<!doctype html>"), Resp(body=b' {"error":1}')]:
            page = Page(answers=[answer])
            with self.assertRaises(site.SessionExpired):
                self.fetch(page)
            self.assertEqual(page.context.request.asked[-1], (T_ACCT, 0), "a redirect is never followed")

    def test_other_non_pdfs_are_refused_without_a_file(self):
        for answer in [Resp(500, ctype="text/plain"), Resp(ctype="application/octet-stream"),
                       Resp(body=b"not a pdf")]:
            ok, out = self.fetch(Page(answers=[answer]))
            self.assertFalse(ok)
            self.assertFalse(out.exists())


def make_app(tmp, *args, **settings):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")}, **settings)
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class OwnBrowser(unittest.TestCase):
    def test_a_config_with_no_cdp_url_opens_its_browser_through_the_core(self):
        """A run whose settings name no cdp_url opens a browser of its own
        through the core, which says so (#90), never straight through
        Playwright."""
        import types
        from unittest import mock
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        app.config.update({"cdp_url": "", "profile_dir": str(Path(tmp) / "profile")})
        launched = []

        class Context:
            def set_default_timeout(self, ms):
                pass

        class Chromium:
            def launch_persistent_context(self, user_data_dir, **kw):
                launched.append(("playwright", user_data_dir))
                return Context()

        class Playwright:
            chromium = Chromium()

            def stop(self):
                pass

        class Starter:
            def start(self):
                return Playwright()
        fake = types.ModuleType("playwright.sync_api")
        fake.sync_playwright = Starter
        core_launch = docs.browser_launcher.launch_own_browser

        def own(chromium, user_data_dir, **kw):
            launched.append(("core", user_data_dir))
            return core_launch(chromium, user_data_dir, **kw)
        with mock.patch.dict(sys.modules, {"playwright.sync_api": fake}), \
                mock.patch.object(docs.browser_launcher, "launch_own_browser", own), \
                redirect_stdout(io.StringIO()) as said:
            self.assertIsInstance(app.browser(), Context)
        profile = str(Path(tmp) / "profile")
        self.assertEqual(launched, [("core", profile), ("playwright", profile)])
        self.assertIn("no cdp_url", said.getvalue())


class Orchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_records_and_names_follow_the_grammar(self):
        app = make_app(self.tmp, "--discover")
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        self.assertNotIn("?", app.paths.discovery_json.read_text())
        recs = dict(app.discovery.data)
        self.assertEqual(set(recs), {"id:transcript-account-202412-30", "id:transcript-return-202412-30",
                                     "id:transcript-wageAndIncome-202312-00",
                                     "id:transcript-recordOfAccount-202212-30"})
        names = sorted(docs.build_pdf_filename(r["date"], r["summary"], "", record=r) for r in recs.values())
        self.assertEqual(names, ["2022-12-31 IRS Record of Account Transcript.pdf",
                                 "2023-12-31 IRS Wage and Income Transcript.pdf",
                                 "2024-12-31 IRS Account Transcript.pdf",
                                 "2024-12-31 IRS Return Transcript.pdf"])
        self.assertEqual(docs.told_apart_by(recs["id:transcript-account-202412-30"]), "transcript-account-202412-30")

    def test_two_account_transcripts_of_one_period_get_two_names_and_no_suffix(self):
        app = make_app(self.tmp, "--all")
        items = [ITEMS[0], dict(ITEMS[0], mft="29", taxForm="1040 Series")]
        for r in site.collect_download_docs(Page(items=items)):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        pdf = b"%PDF-1.4 " + b"x" * 3000
        app._on_its_site = lambda: Page(items=items, answers=[Resp(body=pdf)])
        with redirect_stdout(io.StringIO()):
            app.process(app._select())
        self.assertEqual(sorted(p.name for p in app.paths.root.rglob("*.pdf")),
                         ["2024-12-31 IRS Account Transcript 1040 Series.pdf",
                          "2024-12-31 IRS Account Transcript 1040.pdf"])
        self.assertEqual(app.stats["duplicate_filenames"], 0)

    def test_a_hostile_form_reaches_no_title_file_record_or_csv(self):
        app = make_app(self.tmp, "--all")
        items = [dict(ITEMS[0], taxForm="Jane Smith"), dict(ITEMS[0], mft="29", taxForm="123 Main St")]
        for r in site.collect_download_docs(Page(items=items)):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        pdf = b"%PDF-1.4 " + b"x" * 3000
        app._on_its_site = lambda: Page(items=items, answers=[Resp(body=pdf)])
        with redirect_stdout(io.StringIO()):
            app.process(app._select())
        names = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
        self.assertEqual(names, ["2024-12-31 IRS Account Transcript MFT 29.pdf",
                                 "2024-12-31 IRS Account Transcript MFT 30.pdf"])
        everything = (app.paths.discovery_json.read_text() + app.paths.progress_json.read_text()
                      + app.paths.document_index_csv.read_text())
        for word in ("Jane", "Smith", "123 Main", "Main St"):
            self.assertNotIn(word, everything + " ".join(names), word)

    def test_a_list_that_cannot_be_read_again_stops_the_run(self):
        from paperpull_core import listing
        for later, why in [([ITEMS[0], dict(ITEMS[0])], "it is listed twice"),
                           (None, "the list does not answer")]:
            app = make_app(tempfile.mkdtemp(), "--all")
            listing.started(app)
            for r in site.collect_download_docs(Page()):
                app._record_rawdoc(r, site.BILLING_URL)
            listing.read_whole(app)
            self.assertEqual(listing.last(app), listing.COMPLETE)
            app.check_session = lambda p: None
            app._delay = lambda *a, **k: None
            app.write_failure = lambda *a, **k: None
            answer = Resp(500, ctype="application/json", body=b"{}") if later is None else None
            app._on_its_site = lambda: Page(items=later or [], list_answer=answer, answers=[Resp()])
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit, msg=why):
                app.process(app._select())
            self.assertEqual(listing.last(app), listing.STOPPED, why)
            self.assertIn("could not be read again", said.getvalue(), why)
            self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0, why)
            self.assertEqual(app.progress.data, {}, why)

    def test_a_transcript_that_drops_off_the_list_fails_and_the_run_goes_on(self):
        from types import SimpleNamespace
        from unittest import mock
        from paperpull_core import listing
        from paperpull_core.models import State
        app = make_app(self.tmp, "--all")
        listing.started(app)
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, site.BILLING_URL)
        listing.read_whole(app)
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        app.write_failure = lambda *a, **k: None
        pages = []

        def later():
            # The IRS no longer lists the 2024 account transcript.
            pages.append(Page(items=ITEMS[1:], answers=[Resp(body=b"%PDF-1.4 " + b"x" * 3000)]))
            return pages[-1]
        app._on_its_site = later
        gone = "id:transcript-account-202412-30"
        first = sorted(app._select(), key=lambda d: d.key != gone)
        self.assertEqual(first[0].key, gone)
        valid = SimpleNamespace(ok=True, reason="", size_bytes=3009, page_count=1)
        with mock.patch.object(docs.receipt_pdf, "validate_pdf", lambda *a, **k: valid):
            with redirect_stdout(io.StringIO()):
                app.process(first)
        # Nothing was saved, so it is a failure the next run tries again (#152).
        self.assertEqual(app.progress.get(gone)["state"], State.FAILED.value)
        self.assertEqual((app.stats["failed"], app.stats["manual_review"], app.stats["tax_documents"]),
                         (1, 0, 3))
        self.assertNotIn((T_ACCT, 0), pages[0].context.request.asked)
        self.assertEqual(listing.last(app), listing.COMPLETE)

    def test_a_record_saved_before_its_sibling_appeared_is_renamed_in_discovery(self):
        app = make_app(self.tmp, "--discover")
        for r in site.collect_download_docs(Page(items=[ITEMS[0]])):
            app._record_rawdoc(r, site.BILLING_URL)
        self.assertEqual(app.discovery.get("id:transcript-account-202412-30")["summary"], "Account Transcript")
        for r in site.collect_download_docs(Page(items=[ITEMS[0], dict(ITEMS[0], mft="29")])):
            app._record_rawdoc(r, site.BILLING_URL)
        self.assertEqual(app.discovery.get("id:transcript-account-202412-30")["summary"],
                         "Account Transcript MFT 30")

    def test_an_expired_session_stops_the_run_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def expired(*a, **k):
            raise site.OtpRequired("ID.me is waiting")
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

    def test_an_expired_session_during_discovery_stops_the_run(self):
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(start=site.DOCUMENTS_URL, settled="https://api.id.me/en/session/new")
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(app.discovery.data, {})
        self.assertNotIn("Press Enter", out.getvalue())

    def test_a_discovery_sent_off_the_online_account_asks_for_a_sign_in(self):
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(start=site.DOCUMENTS_URL, settled="https://la.www4.irs.gov/")
        app.write_failure = lambda *a, **k: None
        with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertIn("signed out", said.getvalue())
        self.assertNotIn("stopped partway", said.getvalue())
        self.assertEqual(app.discovery.data, {})

    def test_a_tab_on_id_me_is_never_prompted_about(self):
        app = make_app(self.tmp, "--all")
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            app.check_session(Page(start="https://api.id.me/en/multifactor"))
        self.assertIn("ID.me", out.getvalue())
        self.assertNotIn("Press Enter", out.getvalue())

    def test_a_stopped_list_keeps_what_was_read_and_stops_the_run(self):
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(start=site.DOCUMENTS_URL, notices={"text": "CP14", "docs": 1})
        app.write_failure = lambda *a, **k: None
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(len(app.discovery.data), 4)

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


A_NOTICE = {"text": "Notices and letters CP14 Balance due", "docs": 1}


class NoticesInScope(unittest.TestCase):
    """A notice the app has not seen stops the listing, so the notices page
    is read only when notices are in scope, and with them in scope Run All
    then Resume saves every transcript."""

    def run_app(self, app, command):
        from types import SimpleNamespace
        from unittest import mock
        valid = SimpleNamespace(ok=True, reason="", size_bytes=3009, page_count=1)
        pdf = b"%PDF-1.4 " + b"x" * 3000
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        app.write_failure = lambda *a, **k: None
        app._on_its_site = lambda: Page(notices=A_NOTICE, answers=[Resp(body=pdf)])
        with mock.patch.object(docs.receipt_pdf, "validate_pdf", lambda *a, **k: valid):
            with redirect_stdout(io.StringIO()) as said:
                try:
                    command()
                    code = None
                except SystemExit as e:
                    code = e.code
        return code, said.getvalue()

    def test_with_notices_out_of_scope_a_notice_never_stops_run_all(self):
        from paperpull_core import listing
        app = make_app(tempfile.mkdtemp(), "--all", "--yes", document_types=["Tax Document"])
        page = Page(notices=A_NOTICE)
        app.page = lambda: page
        code, said = self.run_app(app, lambda: app.cmd_run("all"))
        self.assertIsNone(code, said)
        self.assertNotIn(site.NOTICES_URL, page.gotos)
        self.assertEqual(listing.last(app), listing.COMPLETE)
        self.assertEqual(app.stats["tax_documents"], 4)

    def test_with_notices_out_of_scope_login_reads_the_transcript_list_alone(self):
        app = make_app(tempfile.mkdtemp(), "--login", document_types=["Tax Document"])
        page = Page(notices=A_NOTICE)
        app.page = lambda: page
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_login()
        self.assertIn("Success. Connected, and the transcript list can be read.", said.getvalue())
        self.assertEqual(page.gotos, [site.DOCUMENTS_URL])

    def test_with_notices_in_scope_a_notice_means_run_all_then_resume(self):
        from paperpull_core import listing
        app = make_app(tempfile.mkdtemp(), "--all", "--yes")
        self.assertTrue(app._reads_notices())
        page = Page(notices=A_NOTICE)
        app.page = lambda: page
        code, said = self.run_app(app, lambda: app.cmd_run("all"))
        self.assertEqual(code, 1, said)
        self.assertIn(site.NOTICES_URL, page.gotos)
        self.assertEqual((len(app.discovery.data), app.stats["tax_documents"]), (4, 0))
        self.assertNotIn("CP14", said)
        self.assertEqual(listing.last(app), listing.STOPPED)
        app.args = docs.build_parser().parse_args(["--resume", "--config", app.args.config])
        code, said = self.run_app(app, app.cmd_resume)
        self.assertEqual(app.stats["tax_documents"], 4, said)
        self.assertEqual(code, 0, said)


def without_the_folder(text, tmp):
    """text with the run's own temporary folder taken out however it is
    written. Its name is random and the console prints paths inside it,
    so it can hold any short run of digits a check looks for."""
    for written in (str(tmp), json.dumps(str(tmp))[1:-1], Path(tmp).as_posix()):
        text = text.replace(written, "<folder>")
    return text


class Privacy(unittest.TestCase):
    """Nothing that names the taxpayer reaches a log line, the console, a
    record or a file name, and all of it is registered as private words."""

    def test_taxpayer_details_stay_out_of_logs_records_and_names(self):
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
                for r in site.collect_download_docs(Page()):
                    app._record_rawdoc(r, site.BILLING_URL)
                app.discovery.save()
                app.check_session = lambda p: None
                app._delay = lambda *a, **k: None
                pdf = b"%PDF-1.4 " + b"x" * 3000
                app._on_its_site = lambda: Page(answers=[Resp(body=pdf)])
                app.process(app._select())
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        out = without_the_folder(
            seen.getvalue() + app.paths.discovery_json.read_text() + app.paths.progress_json.read_text(), tmp)
        for word in (FAKE_SSN, "9876", FAKE_NAME):
            self.assertNotIn(word, out, word)
            self.assertIn(word, site.private_words(), word)
        self.assertIn("Tester", site.private_words())
        self.assertIn("CAPTCHA", site.redact("CAPTCHA Statement"))
        names = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
        self.assertEqual(names, ["2022-12-31 IRS Record of Account Transcript.pdf",
                                 "2023-12-31 IRS Wage and Income Transcript.pdf",
                                 "2024-12-31 IRS Account Transcript.pdf",
                                 "2024-12-31 IRS Return Transcript.pdf"])


    def test_a_short_name_part_is_guarded(self):
        site._register(["Bo Quillfeather"])
        self.assertIn("Bo", site.private_words())
        self.assertNotIn("Bo", site.redact("signed in as Bo"))
        self.assertEqual(len(site.private_words()), len(set(site.private_words())), "nothing twice")

    def test_a_failure_records_only_its_kind_and_logs_it_redacted(self):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        for r in site.collect_download_docs(Page()):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        app._on_its_site = lambda: Page()
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        root = logging.getLogger()
        root.addHandler(handler)
        original = site.download_bill

        def boom(*a, **k):
            raise RuntimeError(f"page said {FAKE_NAME} {FAKE_SSN}")
        site.download_bill = boom
        try:
            with redirect_stdout(io.StringIO()):
                app.process(app._select(limit=1))
        finally:
            site.download_bill = original
            root.removeHandler(handler)
        rec = next(iter(app.progress.data.values()))
        self.assertEqual(rec["notes"], "RuntimeError")
        self.assertIn("RuntimeError", seen.getvalue())
        for word in (FAKE_NAME, FAKE_SSN, "9876"):
            self.assertNotIn(word, seen.getvalue() + app.paths.progress_json.read_text())


    def test_an_exception_or_a_failed_validation_leaves_no_text_anywhere(self):
        from types import SimpleNamespace
        # A house number of four digits no date or time of day holds. A
        # part of three is one a log line's milliseconds or 07:42 spells.
        address, notice = "6987 Evergreen Terrace", "NOTICE-REF-55501234"
        for how in ("exception", "validation"):
            tmp = tempfile.mkdtemp()
            app = make_app(tmp, "--all")
            for r in site.collect_download_docs(Page()):
                app._record_rawdoc(r, site.BILLING_URL)
            app.check_session = lambda p: None
            app._delay = lambda *a, **k: None
            app.write_failure = lambda *a, **k: None
            pdf = b"%PDF-1.4 " + b"x" * 3000
            app._on_its_site = lambda: Page(answers=[Resp(body=pdf)])
            seen = io.StringIO()
            handler = logging.StreamHandler(seen)
            root = logging.getLogger()
            root.addHandler(handler)
            old_level = root.level
            root.setLevel(logging.DEBUG)
            originals = (site.download_bill, docs.receipt_pdf.validate_pdf)

            def boom(*a, **k):
                raise RuntimeError(f"page said {address} {notice}")
            if how == "exception":
                site.download_bill = boom
            else:
                docs.receipt_pdf.validate_pdf = lambda *a, **k: SimpleNamespace(
                    ok=False, reason=f"pypdf: {address} {notice}", size_bytes=0, page_count=0)
            try:
                with redirect_stdout(seen):
                    app.process(app._select(limit=1))
            finally:
                site.download_bill, docs.receipt_pdf.validate_pdf = originals
                root.removeHandler(handler)
                root.setLevel(old_level)
            csv = app.paths.document_index_csv
            everything = without_the_folder(seen.getvalue() + app.paths.progress_json.read_text() + (
                csv.read_text() if csv.exists() else ""), tmp)
            for word in ("Evergreen", "6987", "55501234", "NOTICE-REF"):
                self.assertNotIn(word, everything, (how, word))
            rec = next(iter(app.progress.data.values()))
            self.assertIn(rec["notes"], ("RuntimeError", "PDF validation failed"), how)


class Diagnose(unittest.TestCase):
    def test_a_sign_in_tab_is_not_read_at_all(self):
        for where in ("https://api.id.me/en/session/new", "https://secure.login.gov/",
                      f"https://{HOST}/secureaccess/ui/login", "https://www.irs.gov/"):
            app = make_app(tempfile.mkdtemp(), "--diagnose")

            class Watched(Page):
                touched = []

                def locator(self, sel):
                    Watched.touched.append("locator")
                    return super().locator(sel)

                def evaluate(self, js, arg=None):
                    Watched.touched.append("evaluate")
                    return super().evaluate(js, arg)

                def title(self):
                    Watched.touched.append("title")
                    return super().title()
            page = Watched(settled=where)
            app.page = lambda: page
            with redirect_stdout(io.StringIO()) as said:
                self.assertFalse(app.cmd_diagnose())
            self.assertEqual(Watched.touched, [], where)
            self.assertIn("sign-in page", said.getvalue())


class Docs(unittest.TestCase):
    """What the docs say of this app agrees with the code and with the live
    run, where Discover listed 26 transcripts and a Pilot and a Run All saved
    all 26."""
    REPO = HERE.parent.parent

    def read(self, *parts):
        return self.REPO.joinpath(*parts).read_text(encoding="utf-8")

    def changelog_entry(self):
        # The app came after 0.51.0, so its bullet is above that heading,
        # in Unreleased or the version it became.
        text = self.read("CHANGELOG.md")
        start = text.index("- **IRS Online Account")
        self.assertLess(start, text.index("## [0.51.0]"))
        return text[start:text.index("\n\n", start)]

    def providers_rows(self):
        return [line for line in self.read("PROVIDERS.md").splitlines() if line.startswith("| [`")]

    def test_every_count_of_the_live_run_is_26(self):
        import re
        row = next(r for r in self.providers_rows() if r.startswith("| [`irs`]"))
        for name, text in [("CHANGELOG.md", self.changelog_entry()), ("PROVIDERS.md", row),
                           ("README.md", self.read("apps", "irs", "README.md")),
                           ("irs_site.py", site.__doc__ + self.read("apps", "irs", "irs_site.py"))]:
            counts = set(re.findall(r"\b([0-9]+) transcripts\b", " ".join(text.split())))
            self.assertEqual(counts, {"26"}, name)

    def test_no_semicolon_and_no_untested_title_where_it_ran_in_full(self):
        entry = self.changelog_entry()
        self.assertNotIn("untested", entry.split("**")[1].lower())
        row = next(r for r in self.providers_rows() if r.startswith("| [`irs`]"))
        for name, text in [("CHANGELOG.md", entry), ("PROVIDERS.md", row),
                           ("README.md", self.read("apps", "irs", "README.md"))]:
            self.assertNotIn(";", text, name)

    def test_the_row_follows_ibkr_and_the_card_is_with_the_bills(self):
        slugs = [r.split("`")[1] for r in self.providers_rows()]
        self.assertEqual(slugs[slugs.index("ibkr") + 1], "irs")
        cards = json.loads(self.read("gui", "providers.json"))
        self.assertEqual(cards["providers"]["irs"]["group"], "bills")

    def test_login_and_the_private_words_claim_say_what_the_code_does(self):
        self.assertNotIn("notice PDF", self.read("apps", "irs", "login.bat"))
        doc = " ".join(site.__doc__.split())
        self.assertNotIn("address, and the reference numbers a notice carries", doc)
        self.assertIn("an address or a notice's reference numbers included", doc)
        # What it does say is registered, is.
        page = Page()
        site._guard_identity(page)
        for word in (FAKE_NAME, FAKE_SSN, "9876"):
            self.assertIn(word, site.private_words(), word)


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "irs_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)

    def test_the_survey_presses_nothing_and_reports_both_pages(self):
        page = Page()
        page.get_by_role = lambda role: Locator(0)
        report = site.survey(page, dwell_ms=0)
        self.assertEqual([p["list"] for p in report["pages"]], ["transcript", "notice"])
        t, n = report["pages"]
        self.assertEqual((t["items"], t["documents_read"], t["period_shapes"]), (4, 4, ["999999"]))
        self.assertTrue(n["says_no_notices"])
        self.assertEqual(page.pressed, [])
        self.assertEqual(site._path_shape(T_ACCT + "?ref=1"),
                         f"{HOST}/ola/api/shared/accounts/taxrecords/9.9/taxpayers/transcripts/account/999999/99?ref=")

    def test_the_survey_stops_at_id_me(self):
        report = site.survey(Page(settled="https://api.id.me/en/session/new"), dwell_ms=0)
        self.assertEqual(len(report["pages"]), 1)
        self.assertIn("ID.me", report["pages"][0]["stopped"])


if __name__ == "__main__":
    unittest.main()
