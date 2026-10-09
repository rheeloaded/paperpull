"""Checks for the control finder and the statement sources. No browser."""
import sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import robinhood_site as site  # noqa: E402


class FakePage:
    """evaluate() answers the page-side pass; the marked element verifies (or not)."""
    def __init__(self, hit, verify=True, marked=1):
        self.hit, self.verify, self.marked = hit, verify, marked
        self.evaluated = []
    def evaluate(self, js, arg=None):
        self.evaluated.append(arg); return self.hit
    def locator(self, sel):
        page = self
        class Handle:
            def evaluate(self, js, arg=None): return page.verify
        class El:
            def element_handle(self, **kw): return Handle() if page.marked else None
        class L:
            def count(self): return page.marked
            @property
            def first(self): return El()
        return L()


class FindControl(unittest.TestCase):
    def test_plain_download_link_is_found_once(self):
        page = FakePage({"own": "Monthly Statement - March 2026", "hasDl": True})
        self.assertIsNotNone(site.find_control(page, "Monthly Statement - March 2026"))
        self.assertEqual(page.evaluated[0][:2], ["Monthly Statement - March 2026", ""], "one pass, needle cut to 30 chars")
        self.assertEqual(len(page.evaluated[0]), 4, "needle, year, one-time token, mark attribute")

    def test_guard_refuses_forbidden_and_csv_and_non_download(self):
        long = "Download PDF " + "x" * 200 + " then Transfer funds"
        for own, dl in [("Download CSV", False), ("Transfer funds Download", False), ("Monthly Statement", False),
                        ("Sell and download", False), (long, False)]:
            page = FakePage({"i": 0, "own": own, "hasDl": dl})
            self.assertIsNone(site.find_control(page, "Monthly Statement"), own)

    def test_nothing_found_or_changed_page_presses_nothing(self):
        self.assertIsNone(site.find_control(FakePage(None), "Monthly Statement"))
        hit = {"own": "Download PDF", "hasDl": False}
        self.assertIsNone(site.find_control(FakePage(hit, verify=False), "Form 1099"), "the live element no longer matches")
        self.assertIsNone(site.find_control(FakePage(hit, marked=0), "Form 1099"), "a re-render dropped the mark")
        self.assertIsNone(site.find_control(FakePage(hit, marked=2), "Form 1099"), "two marks: nothing is pressed")
        self.assertIsNone(site.find_control(FakePage(hit), ""))

    def test_year_is_passed_to_the_page(self):
        page = FakePage({"own": "Download PDF", "hasDl": False})
        self.assertIsNotNone(site.find_control(page, "Form 1099-B", year="2024"))
        self.assertEqual(page.evaluated[0][1], "2024")
        self.assertTrue(site.has_control(page, "Form 1099-B", "2024"))


class Challenge(unittest.TestCase):
    def test_challenge_text_reads_the_page_even_with_rows(self):
        class Page:
            def __init__(self, body): self.body = body
            def title(self): return "Statements | Robinhood"
            def locator(self, sel):
                page = self
                class L:
                    def inner_text(self, **kw): return page.body
                    def count(self): return 68
                return L()
        self.assertIsNone(site.challenge_text(Page("March 2026 Statement Download")))
        self.assertIn("challenge", site.challenge_text(Page("Please enter the code we sent to your phone")).lower())
        self.assertIsNotNone(site.challenge_text(Page("Too many requests, try again later")))
        late = ("March 2026 Statement Download\n" * 80) + "Enter the code we sent"
        self.assertGreater(len(late), 1500)
        self.assertIsNotNone(site.challenge_text(Page(late)), "a prompt after a long list is still a prompt")


class Duplicates(unittest.TestCase):
    def test_only_the_crypto_page_is_refused_a_duplicate(self):
        import robinhood_docs as docs
        listed = {("March 2026 Statement", "2026-03-31")}
        key = ("March 2026 Statement", "2026-03-31")
        self.assertTrue(docs.is_crypto_duplicate("https://robinhood.com/account/reports-statements/crypto", key, listed))
        self.assertFalse(docs.is_crypto_duplicate("https://robinhood.com/account/reports-statements/retirement", key, listed))
        self.assertFalse(docs.is_crypto_duplicate("https://robinhood.com/account/reports-statements/individual", key, listed))
        self.assertFalse(docs.is_crypto_duplicate("https://robinhood.com/account/reports-statements/crypto", ("other", "2026-03-31"), listed))
        self.assertFalse(docs.is_crypto_duplicate("https://robinhood.com/account/reports-statements/crypto", key, None))


class Order(unittest.TestCase):
    def test_documents_are_taken_page_by_page_newest_first(self):
        import robinhood_docs as docs
        I, R, C, T = site.STATEMENT_URLS[0], site.STATEMENT_URLS[1], site.STATEMENT_URLS[2], site.TAX_URL
        items = [(C, "2026-03-31"), (I, "2026-03-31"), (T, "2025-12-31"), (R, "2026-03-31"), (I, "2026-02-28"),
                 (R, "2026-02-28"), (C, "2026-02-28"), (I, ""), ("", "2026-01-31")]
        ordered = sorted(items, key=lambda it: (docs.source_rank(it[0]), docs.date_desc_key(it[1])))
        self.assertEqual(ordered, [(I, "2026-03-31"), (I, "2026-02-28"), (I, ""), (R, "2026-03-31"), (R, "2026-02-28"),
                                   (C, "2026-03-31"), (C, "2026-02-28"), (T, "2025-12-31"), ("", "2026-01-31")])


class PilotOrder(unittest.TestCase):
    def test_pilot_takes_the_newest_across_pages(self):
        import robinhood_docs as docs
        I, R, C = site.STATEMENT_URLS[0], site.STATEMENT_URLS[1], site.STATEMENT_URLS[2]
        items = [(I, "2026-03-31"), (I, "2026-02-28"), (R, "2026-03-31"), (C, "2026-03-31"), (I, "2026-01-31")]
        newest = sorted(items, key=lambda it: docs.date_desc_key(it[1]))[:3]
        self.assertEqual({src for src, _ in newest}, {I, R, C}, "a pilot of three sees all three pages")
        grouped = sorted(items, key=lambda it: (docs.source_rank(it[0]), docs.date_desc_key(it[1])))[:3]
        self.assertEqual({src for src, _ in grouped}, {I}, "a run takes a page at a time")


class Sources(unittest.TestCase):
    def test_retirement_page_is_read(self):
        urls = dict(site.STATEMENT_PAGES)
        self.assertEqual(urls["https://robinhood.com/account/reports-statements/retirement"], "Retirement")
        self.assertEqual(site.account_for("https://robinhood.com/account/reports-statements/retirement"), "Retirement")
        self.assertEqual(site.account_for("https://robinhood.com/account/reports-statements/individual"), "")
        self.assertEqual([lbl for _, lbl in site.document_source_urls()],
                         ["statements", "retirement statements", "crypto statements", "tax"])
        for u in site.STATEMENT_URLS + [site.TAX_URL]:
            self.assertTrue(site.is_safe_url(u), u)


if __name__ == "__main__":
    unittest.main()
