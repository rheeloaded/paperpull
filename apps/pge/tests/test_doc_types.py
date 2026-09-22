"""PG&E document classification + the READ-ONLY (utility billing) guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import pge_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_statements():
    for title, summary in [
            ("Energy Statement - July 22, 2026", "Energy Statement"),
            ("Account Statement", "Account Statement"),
            ("Monthly Account Statement - December 2025", "Monthly Statement"),
            ("Detailed Bill", "Detailed Bill"),
            ("Monthly Bill", "Monthly Statement"),
            ("Bill", "Bill")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_a_utility_has_no_brokerage_vocabulary():
    for title in ["Brokerage Statement", "Crypto Statement",
                  "Consolidated 1099", "1099-B", "1042-S"]:
        _, summary, _ = doc_types.classify_document(title, RULES)
        assert "Crypto" not in summary and "Brokerage" not in summary, title
        assert "1099" not in summary and "1042" not in summary, title


def test_generic_tax_catch_still_routes():
    cat, _, _ = doc_types.classify_document("Tax Document", RULES)
    assert cat == doc_types.TAX


def test_boilerplate_is_skipped():
    for t in ["Privacy Policy", "Terms of Service", "Regulatory Communication"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Energy Statement - July 22, 2026", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to PG&E", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_year_only():
    assert site.parse_period_date("2025 Annual Summary")[0] == "2025-12-31"


def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Monthly Statement", "") == \
        "2025-12-31 PG&E Monthly Statement.pdf"


def test_account_statement_filename():
    assert build_pdf_filename("2026-07-22", "Account Statement", "") == \
        "2026-07-22 PG&E Account Statement.pdf"


def test_payment_and_account_controls_are_never_safe():
    for label in ["Pay", "Pay bill", "Make a payment", "Payment", "AutoPay",
                  "Auto Pay", "Schedule payment", "One-time payment",
                  "Payment plan", "Budget billing", "Enroll", "Unenroll",
                  "Start service", "Stop service", "Transfer service",
                  "Add bank account", "Add card", "Update", "Change", "Edit",
                  "Delete", "Confirm", "Submit", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download Your Energy Statement PDF", "View bill",
                  "View statement", "Open PDF", "Download bill",
                  "Download report", "View document"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


def test_a_bare_save_is_refused_on_purpose():
    for label in ["Save", "Save Changes", "Save Settings"]:
        assert not site.is_safe_control(label), label


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    # "edit" with only a trailing boundary matched the end of "Credit", so a
    # bill row that carried a credit was refused. The verbs themselves must
    # still be refused.
    for label in ["View Bill PDF (Credit)", "Credit Statement PDF"]:
        assert site.is_safe_control(label), label
    for label in ["Edit profile", "Change address", "Update payment method",
                  "Editing preferences", "Changed"]:
        assert not site.is_safe_control(label), label


def test_a_bill_row_hands_over_the_pdf_control_and_never_pay():
    class El:
        def __init__(self, text="", aria=None):
            self.text, self.aria = text, aria
        def inner_text(self, timeout=None):
            return self.text
        def get_attribute(self, name):
            return self.aria if name == "aria-label" else None

    pay, view = El("Pay"), El("View Bill PDF")
    assert site.pick_document_control([pay, view]) is view
    assert site.pick_document_control([El("Pay bill"), El("Make a payment")]) is None
    assert site.pick_document_control([El(""), El("", aria="View Bill PDF")]).aria == "View Bill PDF"
    assert site.pick_document_control([]) is None
    assert site.pick_document_control(None) is None


def test_the_page_picker_is_the_only_control_outside_a_row():
    assert site.is_page_picker("1 | Jump to")
    assert site.is_page_picker("Page 2")
    assert not site.is_page_picker("Pay | Jump to")
    assert not site.is_page_picker("")
    assert site.is_page_option("3", 3)
    assert not site.is_page_option("3 Pay", 3)
    assert not site.is_page_option("", 3)


def test_the_history_page_is_the_only_place_that_counts_as_found():
    class Page:
        def __init__(self, url, title="Bill and payment history"):
            self.url, self._title = url, title
        def title(self):
            return self._title
    assert site.on_documents_page(Page("https://myaccount.pge.com/myaccount/s/bill-and-payment-history"))
    assert not site.on_documents_page(Page("https://myaccount.pge.com/myaccount/s/"))
    assert not site.on_documents_page(Page("https://evil.test/bill-and-payment-history"))
    assert not site.on_documents_page(Page(
        "https://myaccount.pge.com/myaccount/s/bill-and-payment-history", "Page Not Found"))


# -- #33, a page jump that did not take ---------------------------------------

class _Row:
    def __init__(self, text): self._text = text
    def inner_text(self, timeout=None): return self._text
    def query_selector_all(self, sel): return [_Ctl("Pay"), _Ctl("View Bill PDF")]


class _Ctl:
    def __init__(self, text): self._text = text
    def inner_text(self, timeout=None): return self._text
    def get_attribute(self, name): return None


class _Picker:
    """The Jump to combobox. `sticky` is the site as the tester saw it: the
    picker takes the value, the table never follows."""
    def __init__(self, history, pages, sticky):
        self.history, self.pages, self.sticky, self.value, self.shown = history, pages, sticky, 1, 1
    def evaluate(self, js):
        return self.pages if "options" in js else self.value
    def click(self): pass
    def inner_text(self, timeout=None): return str(self.value)
    def get_attribute(self, name): return "Jump to" if name == "aria-label" else None


class _Opt:
    def __init__(self, picker, n): self.picker, self.n = picker, n
    def inner_text(self, timeout=None): return str(self.n)
    def get_attribute(self, name): return None
    def click(self):
        self.picker.value = self.n
        if not self.picker.sticky:
            self.picker.shown = self.n


class _History:
    def __init__(self, pages_of_dates, sticky=False):
        self.by_page = pages_of_dates
        self.picker = _Picker(self, list(range(1, len(pages_of_dates) + 1)), sticky)
    def query_selector(self, sel):
        return self.picker if "combobox" in sel and "combobox-item" not in sel else None
    def query_selector_all(self, sel):
        if "combobox-item" in sel or "option" in sel:
            return [_Opt(self.picker, n) for n in self.picker.pages]
        return [_Row("%s View Bill PDF Pay" % d) for d in self.by_page[self.picker.shown - 1]]
    def wait_for_timeout(self, ms): pass


PAGES = [["08/20/2026", "07/21/2026", "06/21/2026", "05/21/2026"],
         ["04/21/2026", "03/21/2026", "02/20/2026", "01/21/2026"],
         ["12/20/2025", "11/20/2025", "10/21/2025", "09/20/2025"]]


def test_a_jump_that_does_not_take_is_reported_not_read_again(monkeypatch):
    """The tester's history had 7 pages and discovery reported 28 rows and
    4 bills, the first page read seven times, every bill filed under page
    7, and nothing found there at download time."""
    monkeypatch.setattr(site, "get_pagination_pages", lambda page: page.picker.pages)
    got = site.collect_download_docs(_History(PAGES, sticky=True))
    assert [d["date_text"] for d in got] == ["2026-08-20", "2026-07-21", "2026-06-21", "2026-05-21"]
    assert {d["page_number"] for d in got} == {1}, "a bill is filed where it was seen, never where a jump claimed to be"


def test_a_jump_that_takes_reads_every_page_once(monkeypatch):
    monkeypatch.setattr(site, "get_pagination_pages", lambda page: page.picker.pages)
    got = site.collect_download_docs(_History(PAGES))
    assert len(got) == 12
    assert [d["page_number"] for d in got] == [1] * 4 + [2] * 4 + [3] * 4
    assert got[4] == {"date_text": "2026-04-21", "title": "Energy Statement - 2026-04-21",
                      "page_number": 2, "row_index": 0, "summary": "Energy Statement"}


def test_a_bill_filed_under_the_wrong_page_is_still_found():
    hist = _History(PAGES)
    site.goto_page_number(hist, 3)
    assert hist.picker.shown == 3
    assert site._row_for_date(hist, "2025-11-20", 9) is not None
    assert site._row_for_date(hist, "2026-08-20", 0) is None
    site.goto_page_number(hist, 1)
    assert site._row_for_date(hist, "2026-08-20", 0) is not None


def test_a_jump_that_moves_the_rows_counts_even_if_the_picker_never_says_so(monkeypatch):
    """Round one of #33 waited for the picker's value to read the target.
    The tester's picker never did, and the walk stopped at page 1 again."""
    class _MutePicker(_Picker):
        def evaluate(self, js):
            return self.pages if "options" in js else 1     # the value never updates
    hist = _History(PAGES)
    hist.picker = _MutePicker(hist, [1, 2, 3], sticky=False)
    monkeypatch.setattr(site, "get_pagination_pages", lambda page: page.picker.pages)
    got = site.collect_download_docs(hist)
    assert [d["page_number"] for d in got] == [1] * 4 + [2] * 4 + [3] * 4


def test_the_next_control_is_only_ever_next():
    assert site.is_next_control("Next") and site.is_next_control("Next page") and site.is_next_control(">")
    assert not site.is_next_control("Next: Pay") and not site.is_next_control("") and not site.is_next_control("Previous")


def test_a_row_whose_pdf_control_is_not_an_anchor_still_hands_it_over():
    class _El:
        def __init__(self, text): self._text = text
        def inner_text(self, timeout=None): return self._text
        def get_attribute(self, name): return None
    class _Handle:
        """The JS walk's answer, a td and the span inside it, innermost first."""
        def __init__(self, els): self._els = els
        def get_properties(self): return {str(i): _H(e) for i, e in enumerate(self._els)}
    class _H:
        def __init__(self, e): self._e = e
        def as_element(self): return self._e
    class _Row:
        def query_selector_all(self, sel):
            if sel.startswith("a, button"): return [_El("Pay")]
            return []
        def evaluate_handle(self, js):
            assert "view" in js and "children" in js and "querySelectorAll" not in js, "the walk uses children, never the patched querySelectorAll"
            return _Handle([_El("View Bill PDF"), _El("View Bill PDF")])
        def inner_text(self): return "09/20/2026 View Bill PDF Pay"
    ctrls = site.row_controls(_Row())
    assert [c._text for c in ctrls] == ["View Bill PDF", "View Bill PDF", "Pay"], "the walk answers first, the queries after"
    # and the guard hands over the PDF control, never Pay
    assert site.pick_document_control(ctrls)._text == "View Bill PDF"
    assert site.pick_document_control(ctrls)._text == "View Bill PDF"
    assert "View Bill PDF" in site._describe_row(_Row())
