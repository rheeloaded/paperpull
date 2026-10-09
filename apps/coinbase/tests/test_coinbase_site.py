"""The checks that have to pass before this app touches a real account.
Run:  <bundled python> -m unittest discover -s tests   (from the install folder)
No browser, no network: pages, locators and HTTP answers are fakes."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import coinbase_site as site  # noqa: E402
import coinbase_docs as docs  # noqa: E402


class Guard(unittest.TestCase):
    def test_allows_document_controls(self):
        for label in ["PDF", "Download PDF", "Download statement", "Monthly statement",
                      "View document", "Download", "Load more", "Download\n\U000f0382"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_denies_everything_else(self):
        for label in ["Download and continue", "Generate custom statement", "Generate",
                      "Request report", "Settings", "Advanced trade", "Buy", "Sell", "Send",
                      "Convert", "Export CSV", "CSV", "HTML", "Create API key", "Sign in",
                      "Statement settings", "Mark as read", "", None, "   ", "Deposit",
                      "Manage funds", "Allow all", "Confirm my choices"]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Hosts(unittest.TestCase):
    def test_exact_hosts(self):
        for u in ["https://accounts.coinbase.com/statements", "https://accounts.coinbase.com/a/b.pdf",
                  "https://accounts.coinbase.com/", "https://www.coinbase.com/", "https://www.coinbase.com/home"]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["http://accounts.coinbase.com/statements", "https://accounts.coinbase.com:8443/statements",
                  "https://coinbase.com/statements", "https://login.coinbase.com/signin",
                  "https://api.coinbase.com/v2/accounts", "https://accounts.coinbase.com.evil.test/statements",
                  "https://accounts.coinbase.com@evil.test/statements", "https://notcoinbase.com/", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_list_calls_keep_to_their_paths(self):
        for u in ["https://accounts.coinbase.com/statements", "https://accounts.coinbase.com/taxes/documents",
                  "https://accounts.coinbase.com/v2/tax/forms?types=1099-DA&year=2025",
                  "https://accounts.coinbase.com/v2/tax/owner-info", "https://www.coinbase.com/"]:
            self.assertTrue(site.is_list_url(u), u)
        for u in ["https://accounts.coinbase.com/settings", "https://accounts.coinbase.com/v2/tax/forms/abc/mark-read",
                  "https://accounts.coinbase.com/v2/tax/transactions", "https://www.coinbase.com/advanced-markets",
                  "https://www.coinbase.com/settings", "https://login.coinbase.com/signin", ""]:
            self.assertFalse(site.is_list_url(u), repr(u))

    def test_download_hosts_exact(self):
        self.assertTrue(site.is_download_url("https://statements-report-persistent-production.s3.amazonaws.com/a_b__pdf.pdf"))
        self.assertTrue(site.is_download_url("https://tax-center-forms-production.s3.amazonaws.com/2025/x/y.pdf?X-Amz-Signature=abc"))
        for u in ["https://s3.amazonaws.com/statements-report-persistent-production/a.pdf",
                  "https://evil.s3.amazonaws.com/a.pdf", "http://tax-center-forms-production.s3.amazonaws.com/a.pdf",
                  "https://accounts.coinbase.com/statements", "https://tax-center-forms-production.s3.amazonaws.com.evil.test/a.pdf", ""]:
            self.assertFalse(site.is_download_url(u), u)


class Rows(unittest.TestCase):
    def test_month_to_iso(self):
        self.assertEqual(site.month_to_iso("September 2026"), "2026-09-30")
        self.assertEqual(site.month_to_iso("February 2024"), "2024-02-29")
        self.assertEqual(site.month_to_iso("Last 30 days"), "")
        self.assertEqual(site.month_to_iso(""), "")
        self.assertEqual(site.month_to_iso("Sept 2026"), "")

    def test_row_binding_is_exact(self):
        rows = [{"label": "Last 30 days", "button": "PDF", "i": 0},
                {"label": "September 2026", "button": "PDF", "i": 1},
                {"label": "August 2026", "button": "PDF", "i": 2}]
        self.assertEqual(site.row_index_for(rows, "August 2026"), (2, "PDF"))
        self.assertEqual(site.row_index_for(rows, "July 2026"), (-1, ""))
        twice = rows + [{"label": "August 2026", "button": "PDF", "i": 3}]
        self.assertEqual(site.row_index_for(twice, "August 2026"), (-1, ""),
                         "two rows with one label: nothing is chosen")

    def test_statement_title_roundtrip(self):
        d = site.RawDoc(title="Monthly Statement September 2026", date_text="2026-09-30")
        m = site._STATEMENT_TITLE_RE.match(d.title)
        self.assertEqual(site.month_to_iso(m.group(1)), d.date_text)


class TaxList(unittest.TestCase):
    def test_duplicate_forms_keep_both(self):
        forms = {2025: [{"id": "930a0ab0-3626-5828-8859-8ebd4d45f690", "form_type": "1099-DA"},
                        {"id": "aaaa1111-bbbb-2222-cccc-333344445555", "form_type": "1099-DA"},
                        {"id": "x", "form_type": "1099-MISC"}]}
        reports = [{"id": "e32dcf1e", "name": "PregeneratedGainLossPDF", "year": 2021,
                    "file": {"file_type": "PDF", "url": "https://tax-center-forms-production.s3.amazonaws.com/x?sig=1"}}]
        out = site.tax_rawdocs(forms, reports)
        titles = [d.title for d in out]
        self.assertEqual(titles, ["1099-DA Tax Year 2025 (#930a0ab03626582888598ebd4d45f690)",
                                  "1099-DA Tax Year 2025 (#aaaa1111bbbb2222cccc333344445555)",
                                  "1099-MISC Tax Year 2025", "Gain Loss Report Tax Year 2021"])
        two = reports + [dict(reports[0], id="ffff0000")]
        rt = [d.title for d in site.tax_rawdocs({}, two)]
        self.assertEqual(rt, ["Gain Loss Report Tax Year 2021 (#e32dcf1e)", "Gain Loss Report Tax Year 2021 (#ffff0000)"])
        same_prefix = {2025: [{"id": "930a0ab0-1111", "form_type": "1099-DA"}, {"id": "930a0ab0-2222", "form_type": "1099-DA"}]}
        self.assertEqual(len({d.title for d in site.tax_rawdocs(same_prefix, [])}), 2)
        for d in out:
            self.assertTrue(site._TAX_TITLE_RE.match(d.title), d.title)
            self.assertNotIn("?", d.href); self.assertNotIn("http", d.href)
            self.assertRegex(d.date_text, r"^\d{4}-12-31$")

    def test_unreadable_rows_stop_the_statement_list(self):
        class Page:
            url = site.STATEMENTS_URL
            def __init__(self, rows): self.rows = rows
            def locator(self, sel):
                class L:
                    def count(s): return 0
                    def is_visible(s): return False
                    @property
                    def first(s): return s
                return L()
            def evaluate(self, js): return self.rows
        ok = [{"label": "Last 30 days", "button": "PDF", "i": 0}, {"label": "September 2026", "button": "PDF", "i": 1}]
        self.assertEqual([d.date_text for d in site._collect_statements(Page(ok))], ["2026-09-30"])
        for bad in ([{"label": "", "button": "PDF", "i": 0}],
                    [{"label": "September 2026", "button": "PDF", "i": 0}, {"label": "September 2026", "button": "PDF", "i": 1}],
                    [{"label": "Credit Card", "button": "PDF", "i": 0}], []):
            with self.assertRaises(site.ListStopped):
                site._collect_statements(Page(bad))

    def test_tax_pages_that_cannot_be_exhausted_stop_the_list(self):
        answers = []
        class Resp:
            ok, status, url, headers = True, 200, "", {}
            def json(self): return answers.pop(0)
            def dispose(self): pass
        class Req:
            def get(self, url, **kw): return Resp()
        class Ctx: request = Req()
        class Page: context = Ctx()
        answers[:] = [{"data": [{"id": "a"}], "next_cursor": "c1"}, {"data": [{"id": "b"}], "next_cursor": "c1"}]
        with self.assertRaises(site.ListStopped):
            site._tax_forms_for(Page(), 2025)
        answers[:] = [{"data": [{"id": "x"}], "next_cursor": "c%d" % i} for i in range(1, 40)]
        with self.assertRaises(site.ListStopped):
            site._tax_forms_for(Page(), 2025)
        answers[:] = [{"data": [{"id": "a"}], "next_cursor": "c1"}, {"data": [{"id": "b"}], "next_cursor": ""}]
        self.assertEqual([i["id"] for i in site._tax_forms_for(Page(), 2025)], ["a", "b"])

    def test_unreadable_year_stops_the_list(self):
        class Resp:
            ok, status, url, headers = False, 500, "", {}
            def json(self): return {}
            def dispose(self): pass
        class Req:
            def get(self, url, **kw): return Resp()
        class Ctx: request = Req()
        class Page: context = Ctx()
        with self.assertRaises(site.ListStopped):
            site._tax_forms_for(Page(), 2025)
        with self.assertRaises(site.ListStopped):
            site._tax_reports(Page())

    def test_tax_pdf_link_off_host_is_refused(self):
        page = object()
        orig = site._tax_forms_for
        site._tax_forms_for = lambda p, y: [{"id": "abc", "form_type": "1099-DA",
                                            "files": [{"file_type": "pdf", "url": "https://evil.example/x.pdf"}]}]
        try:
            trace = []
            with tempfile.TemporaryDirectory() as td:
                ok = site._fetch_tax_pdf(page, "1099-DA Tax Year 2025", Path(td) / "out.pdf", trace)
            self.assertFalse(ok)
            self.assertEqual(trace[-1]["note"], "document link refused")
            self.assertNotIn("url", trace[-1]); self.assertEqual(trace[-1]["host"], "evil.example")
        finally:
            site._tax_forms_for = orig


class StatementDownload(unittest.TestCase):
    """The one PDF button is pressed; a download from any host but the exact one is refused."""

    def make_page(self, dl_url):
        site_ref = site
        class Download:
            url = dl_url; suggested_filename = "x.pdf"; cancelled = False; event_bytes = b"%PDF-1.4 fake"
            def cancel(self): self.cancelled = True
            def save_as(self, path): Path(path).write_bytes(self.event_bytes)
        dl = Download()
        class Resp:
            ok, status = True, 200
            def body(self): return b"%PDF-1.4 fetched"
        class Req:
            asked = []
            def get(self, url, **kw): self.asked.append((url, kw.get("max_redirects"))); return Resp()
        class Ctx: request = Req()
        class Loc:
            def __init__(self, n, page): self.n, self.page = n, page
            def count(self): return self.n
            def is_visible(self): return self.n > 0
            @property
            def first(self): return self
            def nth(self, i): return El(self.page)
        class El:
            def __init__(self, page): self.page = page
            def scroll_into_view_if_needed(self, **kw): pass
            def click(self, **kw):
                self.page.clicked += 1
                for cb in self.page.handlers: cb(dl)
        class Page:
            clicked = 0; handlers = []; context = Ctx()
            url = site_ref.STATEMENTS_URL
            def on(self, ev, cb): self.handlers.append(cb)
            def remove_listener(self, ev, cb): self.handlers.remove(cb)
            def locator(self, sel):
                return Loc(0, self) if sel == site_ref._LOAD_MORE else Loc(3, self)
            def evaluate(self, js):
                return [{"label": "Last 30 days", "button": "PDF", "i": 0},
                        {"label": "September 2026", "button": "PDF", "i": 1},
                        {"label": "August 2026", "button": "PDF", "i": 2}]
            def wait_for_timeout(self, ms): pass
        return Page(), dl

    def test_off_host_download_is_refused_and_cancelled(self):
        page, dl = self.make_page("https://evil.example/statement.pdf")
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
            self.assertFalse(ok); self.assertTrue(dl.cancelled); self.assertEqual(page.clicked, 1)
            self.assertFalse((Path(td) / "out.pdf").exists())
            self.assertEqual(trace[-1], {"note": "download refused", "host": "evil.example"})

    def test_exact_host_download_is_taken(self):
        page, dl = self.make_page("https://statements-report-persistent-production.s3.amazonaws.com/a__pdf.pdf")
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
            self.assertTrue(ok); self.assertEqual(page.clicked, 1)
            self.assertTrue((Path(td) / "out.pdf").read_bytes().startswith(b"%PDF-"))

    def test_present_row_needs_no_load_more(self):
        page, dl = self.make_page("https://statements-report-persistent-production.s3.amazonaws.com/a.pdf")
        page.load_more_presses = 0
        real_locator = page.locator
        class LM:
            def __init__(s, pg): s.pg = pg
            def count(s): return 1
            def is_visible(s): return True
            @property
            def first(s): return s
            def inner_text(s, **kw): return "Load more"
            def get_attribute(s, a): return None
            def click(s, **kw): s.pg.load_more_presses += 1
        page.locator = lambda sel: LM(page) if sel == site._LOAD_MORE else real_locator(sel)
        with tempfile.TemporaryDirectory() as td:
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
            self.assertTrue(ok); self.assertEqual(page.load_more_presses, 0)
        self.assertEqual(page.handlers, [], "the download listener was removed")

    def test_empty_event_file_is_not_a_document_and_nothing_else_is_taken(self):
        page, dl = self.make_page("https://statements-report-persistent-production.s3.amazonaws.com/a__pdf.pdf")
        dl.event_bytes = b""
        with tempfile.TemporaryDirectory() as td:
            dl_dir = Path(td) / "dl"; dl_dir.mkdir()
            (dl_dir / "stray.pdf").write_bytes(b"%PDF-1.4 not ours")
            trace = []
            ok = site._catch_statement(page, dl_dir, "September 2026", Path(td) / "out.pdf", trace)
            self.assertFalse(ok, "an empty event file and a stranger in the folder: nothing is taken")
            self.assertFalse((Path(td) / "out.pdf").exists())
            self.assertEqual(page.context.request.asked, [], "the document is never asked for a second time")
            self.assertTrue((dl_dir / "stray.pdf").exists())

    def test_off_host_event_is_never_fetched(self):
        page, dl = self.make_page("https://evil.example/a.pdf")
        with tempfile.TemporaryDirectory() as td:
            site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
            self.assertEqual(page.context.request.asked, [])

    def test_ambiguous_row_is_not_pressed(self):
        page, dl = self.make_page("https://statements-report-persistent-production.s3.amazonaws.com/a.pdf")
        page.evaluate = lambda js: [{"label": "August 2026", "button": "PDF", "i": 0},
                                    {"label": "August 2026", "button": "PDF", "i": 1}]
        with tempfile.TemporaryDirectory() as td:
            ok = site._catch_statement(page, Path(td) / "dl", "August 2026", Path(td) / "out.pdf", [])
            self.assertFalse(ok); self.assertEqual(page.clicked, 0)

    def test_unsafe_button_label_is_not_pressed(self):
        page, dl = self.make_page("https://statements-report-persistent-production.s3.amazonaws.com/a.pdf")
        page.evaluate = lambda js: [{"label": "August 2026", "button": "Generate", "i": 0}]
        with tempfile.TemporaryDirectory() as td:
            ok = site._catch_statement(page, Path(td) / "dl", "August 2026", Path(td) / "out.pdf", [])
            self.assertFalse(ok); self.assertEqual(page.clicked, 0)


class Persisted(unittest.TestCase):
    def test_persistable_strips_query_and_fragment(self):
        self.assertEqual(docs.persistable("https://x.s3.amazonaws.com/a.pdf?X-Amz-Signature=abc&token=1#f"),
                         "https://x.s3.amazonaws.com/a.pdf")
        self.assertEqual(docs.persistable("/v2/tax/forms/abc?token=1"), "/v2/tax/forms/abc")
        self.assertEqual(docs.persistable(""), ""); self.assertEqual(docs.persistable(None), "")

    def test_every_stored_url_goes_through_persistable(self):
        src = (HERE / "coinbase_docs.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("persistable("), 1 + 5, "def + five call sites")
        for raw in ['href=r.href,', '"href": r.href}', 'source_url=source_url)', '{"source_url": source_url}', '"Source URL": doc.href,']:
            self.assertNotIn(raw, src, raw)

    def test_rules_classify_coinbase_titles(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        for title, cat, summ in [("1099-DA Tax Year 2025", "Tax Document", "1099-DA Tax Form"),
                                 ("1099-MISC Tax Year 2024", "Tax Document", "1099-MISC Tax Form"),
                                 ("Gain Loss Report Tax Year 2021", "Tax Document", "Gain Loss Report"),
                                 ("Monthly Statement September 2026", "Statement", "Monthly Statement")]:
            c, s, _ = doc_types.classify_document(title, rules)
            self.assertEqual((c, s), (cat, summ), title)


if __name__ == "__main__":
    unittest.main()
