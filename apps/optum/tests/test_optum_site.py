"""The checks that have to pass before this app touches a real account. No browser, no network."""
import sys, tempfile, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import optum_site as site  # noqa: E402
import optum_docs as docs  # noqa: E402

PID = "12345678"
S = lambda d, i="900001": {"text": d, "path": f"/account/products/{PID}/statements/{i}.pdf", "host": "account.optumbank.com", "how": "link"}
T = {"text": "Rendered EOY 5498-SA Notices-2025", "path": f"/account/products/{PID}/tax_documents/777.pdf", "host": "account.optumbank.com", "how": "link"}
NAV = [{"text": "Overview", "path": f"/account/products/{PID}", "host": "account.optumbank.com", "how": "link"},
       {"text": "Download IRS Form 8889", "path": "/pub/irs-pdf/f8889.pdf", "host": "www.irs.gov", "how": "link"}]


class Guard(unittest.TestCase):
    def test_allows_document_labels(self):
        for label in ["Download latest statement", "View all statements", "Download", "Tax documents",
                      "Account statements", "Download IRS Form 5498-SA", "1099-SA"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_denies_hsa_money_and_settings(self):
        for label in ["Pay a bill", "Reimburse myself", "Make a contribution", "Invest", "Transfer", "Order a card",
                      "Manage card", "File a claim", "Add payee", "Go paperless", "Settings", "Download and continue",
                      "Request a form", "", None, "Upload receipt", "Pay", "View rollover form",
                      "Download distribution history", "Download rollover/transfer form", "Spend", "Use your funds",
                      "Send money", "Download correction request form", "Download account closure request form",
                      "Download direct deposit form", "Download name change form", "Manage Beneficiaries",
                      "Export to Quicken", "Download .CSV", "Chat with us", "Make a Deposit", "Make a Payment"]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Hosts(unittest.TestCase):
    def test_exact_hosts(self):
        for u in ["https://account.optumbank.com/account?portalIndicator=CAP&portal=optum",
                  "https://account.optumbank.com/account/help/forms", "https://account.optumbank.com/a/b.pdf",
                  f"https://account.optumbank.com/account/products/{PID}/statements", "https://www.optumbank.com/"]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["http://account.optumbank.com/account/help/forms", "https://account.optumbank.com:8443/account/help/forms",
                  "https://optumbank.com/account/help/forms", "https://account.optumbank.com.evil.test/account/help/forms",
                  "https://account.optumbank.com@evil.test/account/help/forms", "https://healthsafe-id.com/login",
                  "https://identity.onehealthcareid.com/app/index.html", "https://secure.optumbank.com/x",
                  "https://www.optum.com/content/dam/x.pdf", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_download_urls(self):
        self.assertTrue(site.is_download_url(f"https://account.optumbank.com/account/products/{PID}/statements/900001.pdf"))
        self.assertTrue(site.is_download_url(f"https://account.optumbank.com/account/products/{PID}/tax_documents/777.pdf"))
        for u in [f"https://account.optumbank.com/account/products/{PID}/statements", "https://account.optumbank.com/account/help/forms",
                  f"https://www.optumbank.com/account/products/{PID}/statements/1.pdf", "https://healthsafe-id.com/a.pdf",
                  f"https://account.optumbank.com/account/products/{PID}/statements/abc.pdf",
                  f"https://account.optumbank.com/account/products/{PID}/statements/1.pdf/../../x", ""]:
            self.assertFalse(site.is_download_url(u), u)

    def test_identity_hosts_read_as_signed_out(self):
        class Page:
            def __init__(self, url): self.url = url
            def locator(self, sel):
                class L:
                    def count(s): return 0
                return L()
        for u in ["https://healthsafe-id.com/login?x=1", "https://identity.onehealthcareid.com/app/", "https://account.optumbank.com/login"]:
            self.assertTrue(site.looks_signed_out(Page(u)), u)
        self.assertFalse(site.looks_signed_out(Page("https://account.optumbank.com/account/help/forms")))


class Listing(unittest.TestCase):
    def test_products_and_documents(self):
        entries = NAV + [S("2026-08-31", "1"), S("2026-07-31", "2"), {**S("2026-02-28", "3"), "how": "option"},
                         {**S("2026-08-31", "1"), "how": "option"}, T]
        self.assertEqual(site.product_ids(entries), [PID])
        docs_ = site.documents_of(entries, PID)
        self.assertEqual([(d.title, d.date_text, d.kind) for d in docs_],
                         [("HSA Statement 2026-08-31", "2026-08-31", "statement"), ("HSA Statement 2026-07-31", "2026-07-31", "statement"),
                          ("HSA Statement 2026-02-28", "2026-02-28", "statement"),
                          ("Rendered EOY 5498-SA Notices-2025", "2025-12-31", "tax")])
        for d in docs_:
            self.assertNotIn("?", d.href); self.assertNotIn("http", d.href)

    def test_unreadable_entries_stop_the_list(self):
        for bad, why in [([S("August 2026")], "not a date"),
                         ([S("2026-08-31", "1"), S("2026-08-31", "2")], "two statements one date"),
                         ([{**S("2026-08-31"), "host": "evil.example"}], "off host"),
                         ([{**S("2026-08-31"), "path": "/account/products/99999999/statements/1.pdf"}], "other product"),
                         ([{**T, "text": ""}], "untitled tax doc")]:
            with self.assertRaises(site.ListStopped, msg=why):
                site.documents_of(NAV + bad, PID)
        self.assertEqual(site.documents_of(NAV, PID), [])

    def test_calendar_dates_only(self):
        self.assertTrue(site.valid_iso("2026-02-28")); self.assertTrue(site.valid_iso("2024-02-29"))
        for bad in ("2026-02-30", "2023-02-29", "2026-13-01", "2026-00-10", "2026-2-8", "20260228", "", None, "August 2026"):
            self.assertFalse(site.valid_iso(bad), repr(bad))
        with self.assertRaises(site.ListStopped):
            site.documents_of(NAV + [S("2026-02-30")], PID)
        with self.assertRaises(site.ListStopped):
            site.documents_of(NAV + [{**S("2026-02-30", "3"), "how": "option"}], PID)
        ph = {"text": "2026-02-30", "path": "", "host": "account.optumbank.com", "how": "option", "disabled": False}
        self.assertEqual(site.documents_of(NAV + [ph], PID), [], "an empty, non-date option is a placeholder")

    def test_select_options_are_documents_or_placeholders(self):
        ph = {"text": "Select a statement", "path": "", "host": "account.optumbank.com", "how": "option", "disabled": True}
        ok = site.documents_of(NAV + [ph, {**S("2026-02-28", "3"), "how": "option"}], PID)
        self.assertEqual([d.date_text for d in ok], ["2026-02-28"])
        for bad in ({**S("2026-02-28"), "how": "option", "path": f"https://account.optumbank.com/account/products/{PID}/statements/3.pdf"},
                    {**S("2026-02-28"), "how": "option", "path": f"/account/products/{PID}/statements/3.pdf?token=1"},
                    {"text": "2026-02-28", "path": "", "host": "account.optumbank.com", "how": "option", "disabled": False},
                    {**S("2026-02-28"), "how": "option", "path": f"/account/products/{PID}/statements/3"}):
            with self.assertRaises(site.ListStopped, msg=str(bad)):
                site.documents_of(NAV + [bad], PID)

    def test_two_products_get_a_suffix(self):
        d = site.documents_of([S("2026-08-31")], PID, suffix="5678")
        self.assertEqual(d[0].title, "HSA Statement 2026-08-31 (product 5678)")
        m = site._STATEMENT_TITLE_RE.match(d[0].title); self.assertEqual((m.group(1), m.group(2)), ("2026-08-31", "5678"))

    def test_rules_classify(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        for title, cat, summ in [("Rendered EOY 5498-SA Notices-2025", "Tax Document", "5498-SA Tax Form"),
                                 ("1099-SA 2025", "Tax Document", "1099-SA Tax Form"),
                                 ("HSA Statement 2026-08-31", "Statement", "Monthly Statement")]:
            self.assertEqual(doc_types.classify_document(title, rules)[:2], (cat, summ), title)


class Binding(unittest.TestCase):
    """download_bill fetches only the one entry that carries the recorded path, title and date."""

    def make_page(self, entries, settled=None, start="https://account.optumbank.com/account"):
        site_ref = site
        class Resp:
            ok, status, headers = True, 200, {"content-type": "application/pdf"}
            def body(s): return b"%PDF-1.4 x"
        class Req:
            asked = []
            def get(self, url, **kw): self.asked.append(url); return Resp()
        class Ctx: request = Req()
        class Page:
            context = Ctx(); url = start
            def goto(self, url, **kw): self.url = settled or url
            def wait_for_timeout(self, ms): pass
            def wait_for_selector(self, sel, **kw): pass
            def locator(self, sel):
                class L:
                    def count(s): return 0
                return L()
            def evaluate(self, js): return entries
        return Page()

    def test_fetches_the_recorded_entry_only(self):
        page = self.make_page(NAV + [S("2026-08-31", "1"), S("2026-07-31", "2"), T])
        with tempfile.TemporaryDirectory() as td:
            ok = site.download_bill(page, None, "2026-07-31", Path(td) / "o.pdf", title="HSA Statement 2026-07-31",
                                    trace=[], href=f"/account/products/{PID}/statements/2.pdf")
            self.assertTrue(ok); self.assertEqual(page.context.request.asked, [f"https://account.optumbank.com/account/products/{PID}/statements/2.pdf"])
            ok = site.download_bill(page, None, "2025-12-31", Path(td) / "t.pdf", title="Rendered EOY 5498-SA Notices-2025",
                                    trace=[], href=f"/account/products/{PID}/tax_documents/777.pdf")
            self.assertTrue(ok)

    def test_mismatch_or_missing_record_fetches_nothing(self):
        page = self.make_page(NAV + [S("2026-08-31", "1"), T])
        with tempfile.TemporaryDirectory() as td:
            for kw in [dict(iso_date="2026-08-31", title="HSA Statement 2026-08-31", href=""),
                       dict(iso_date="2026-08-30", title="HSA Statement 2026-08-31", href=f"/account/products/{PID}/statements/1.pdf"),
                       dict(iso_date="2026-08-31", title="HSA Statement 2026-08-31", href=f"/account/products/{PID}/statements/9.pdf"),
                       dict(iso_date="2026-08-31", title="HSA Statement 2026-08-31", href=f"/account/products/99999999/statements/1.pdf"),
                       dict(iso_date="2024-12-31", title="Rendered EOY 5498-SA Notices-2025", href=f"/account/products/{PID}/tax_documents/777.pdf")]:
                self.assertFalse(site.download_bill(page, None, kw["iso_date"], Path(td) / "o.pdf", title=kw["title"], trace=[], href=kw["href"]), kw)
            self.assertEqual(page.context.request.asked, [])

    def test_navigation_that_settles_elsewhere_reads_nothing(self):
        page = self.make_page(NAV + [S("2026-08-31", "1")], settled="https://identity.onehealthcareid.com/app/")
        self.assertFalse(site.goto_documents(page))
        page = self.make_page(NAV + [S("2026-08-31", "1")], settled="https://account.optumbank.com/account/help/forms")
        self.assertFalse(site._goto_statements(page, PID), "settled on a page that is not a product's")


class Download(unittest.TestCase):
    def make_page(self, status=200, body=b"%PDF-1.4 x", ct="application/pdf"):
        class Resp:
            ok = status == 200
            def __init__(s): s.status = status; s.headers = {"content-type": ct}
            def body(s): return body
        class Req:
            asked = []
            def get(self, url, **kw): self.asked.append((url, kw.get("max_redirects"))); return Resp()
        class Ctx: request = Req()
        class Page: context = Ctx(); url = site.FORMS_URL
        return Page()

    def test_fetch_is_a_get_of_the_exact_path_with_no_redirect(self):
        page = self.make_page()
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._fetch_document(page, f"/account/products/{PID}/statements/900001.pdf", Path(td) / "o.pdf", trace)
            self.assertTrue(ok); self.assertEqual(page.context.request.asked, [(f"https://account.optumbank.com/account/products/{PID}/statements/900001.pdf", 0)])
            self.assertTrue((Path(td) / "o.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertNotIn("url", trace[-1])

    def test_bad_paths_and_non_pdfs_are_refused(self):
        page = self.make_page()
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(site._fetch_document(page, f"/account/products/{PID}/beneficiaries", Path(td) / "o.pdf", []))
            self.assertEqual(page.context.request.asked, [])
            page = self.make_page(body=b"<html>login</html>", ct="text/html")
            self.assertFalse(site._fetch_document(page, f"/account/products/{PID}/statements/1.pdf", Path(td) / "o.pdf", []))
            self.assertFalse((Path(td) / "o.pdf").exists())


class Persisted(unittest.TestCase):
    def test_every_stored_url_goes_through_persistable(self):
        src = (HERE / "optum_docs.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("persistable("), 1 + 7, "def + seven call sites (href twice)")
        self.assertEqual(docs.persistable("https://x/a.pdf?sig=1#f"), "https://x/a.pdf")

    def test_discovery_keeps_the_path_and_the_download_gets_it(self):
        src = (HERE / "optum_docs.py").read_text(encoding="utf-8")
        self.assertIn('href=persistable(getattr(r, "href", "") or "")', src)
        self.assertIn("href=doc.href)", src)

    def test_pilot_gate(self):
        from paperpull_core.models import State
        class D:
            def __init__(self, k): self.key = k
        done = {"a": {"state": State.COMPLETED.value}}
        self.assertFalse(docs.pilot_failed(done, [D("a")]))
        self.assertTrue(docs.pilot_failed({"a": {"state": State.FAILED.value}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({"a": {"state": "Needs Manual Review"}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({}, [D("a")])); self.assertTrue(docs.pilot_failed(done, []))

    def test_nothing_in_the_site_layer_clicks(self):
        src = (HERE / "optum_site.py").read_text(encoding="utf-8")
        for verb in (".click(", ".fill(", ".select_option(", ".check(", ".type(", ".dblclick(", ".tap("):
            self.assertNotIn(verb, src, verb)
        self.assertNotIn(".press(", src)


if __name__ == "__main__":
    unittest.main()
