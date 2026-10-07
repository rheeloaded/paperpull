"""Nelnet classification, the guard, the list reader and the survey's promises.

Every date, subject and id here is made up. What these pin: the guard refuses
every control that moves money or changes anything and reads the control's own
wording instead of the document's title, the pager is the only thing pressed
while the list is read, and nothing the survey writes can carry a number.
"""
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds the AppSpec
from paperpull_core import doc_types
import nelnet_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [
        ("04/15/2024 Statement", "Statement", "STATEMENT"),
        ("1098-E Tax Year 2024", "1098-E Tax Form", "TAX"),
        ("Income-Driven Repayment Annual Notice", "Document", "OTHER"),
    ]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_the_noise_is_skipped():
    for t in ["Privacy notice", "Terms and conditions", "FAQ"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("04/15/2024 Statement", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    assert build_pdf_filename("2024-04-15", "Statement", "") == "2024-04-15 Nelnet Statement.pdf"
    assert build_pdf_filename("2024-12-31", "1098-E Tax Form", "") == "2024-12-31 Nelnet 1098-E Tax Form.pdf"


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in [
        "Make a Payment", "Payment Activity", "Manage Automatic Payments",
        "Saved Payment Methods", "Authorized Payers", "Special Payment Instructions",
        "Estimated Payoff Amount", "Payment Schedule", "Upload Documents",
        "Change Password", "Contact Information", "Edit profile", "Pay now",
        "Set up auto debit", "Request forbearance", "Apply for deferment",
        "Submit", "Cancel", "Confirm", "Save Changes", "Chat with us",
        "Recertify income", "Consolidate your loans", "Appeal",
    ]:
        assert not site.is_safe_control(label), label


def test_the_login_and_settings_vocabulary_is_refused_too():
    for label in ["Sign in", "Log in", "Log Out", "Remember me", "Preferences", "Settings", "Username"]:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_or_turn_the_list_are_allowed():
    for label in [
        "Download document with subject 04/15/2024 Statement",
        "Download document to your device",
        "View document in new tab",
        "Next Page", "Previous Page", "Go to first page", "Go to last page",
        "2024 1098-E Form",
    ]:
        assert site.is_safe_control(label), label


def test_a_label_with_credit_in_it_is_not_edit_profile():
    assert site.is_safe_control("View credit statement")
    assert not site.is_safe_control("Edit profile")


def test_the_guard_reads_the_control_and_not_the_title_of_its_document():
    # The subject is the document's own name. A notice about a repayment
    # plan or a payment is still a document to download.
    for subject in ["Income-Driven Repayment Annual Notice", "Payment Confirmation",
                    "Auto Debit Enrollment Letter", "Forbearance Approval"]:
        assert site.is_safe_control("Download document with subject " + subject), subject
    # And a control that does something else is refused whatever follows.
    for label in ["Make a payment with subject Statement",
                  "Pay now with subject 04/15/2024 Statement"]:
        assert not site.is_safe_control(label), label


def test_a_document_control_that_also_pays_is_refused():
    for label in ["View statement and pay", "Pay and download statement"]:
        assert not site.is_safe_control(label), label


def test_dates_in_every_form_the_site_is_likely_to_print():
    assert site.parse_date("04/15/2024") == "2024-04-15"
    assert site.parse_date("04/15/2024 Statement") == "2024-04-15"
    assert site.parse_date("Apr 15, 2024 View statement") == "2024-04-15"
    assert site.parse_date("2024-04-15") == "2024-04-15"
    assert site.parse_date("no date here") is None
    assert site.parse_period_date("April 2024") == ("2024-04-30", "April 2024")
    assert site.parse_period_date("2024 tax documents")[0] == "2024-12-31"


def test_the_survey_masks_numbers_and_takes_no_screenshot():
    assert site.redact("account 123456789 statement") == "account ######### statement"
    for fn in (site.survey, site._page_summary, site.collect_documents):
        assert ".screenshot(" not in inspect.getsource(fn)
    docs_src = (Path(site.__file__).parent / "nelnet_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["1 item(s)", {"amount": "number"}], "n": "number"}


def test_the_survey_follows_only_documents_links():
    for text in ["Inbox & Statements", "Tax Info", "Statements", "Documents"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Make a Payment", "Payment Schedule", "Apply", "Home", "Help", "My Loans"]:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_only_the_providers_own_hosts():
    for u in ["https://nelnet.studentaid.gov/documents/inbox-statements",
              "https://mmaapi.nelnet.studentaid.gov/api/1/statements"]:
        assert site.is_safe_url(u), u
    for u in ["https://studentaid.gov/", "https://www.studentaid.gov/x",
              "https://nelnet.studentaid.gov.evil.test/s.pdf",
              "http://nelnet.studentaid.gov/s.pdf",
              "https://user@nelnet.studentaid.gov/s.pdf",
              "https://nelnet.studentaid.gov:8443/s.pdf"]:
        assert not site.is_safe_url(u), u
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)
    assert site.is_safe_url(site.TAX_URL)


# ---------------------------------------------------------------------------
# The list reader, against a page that is only what the reader asks of it.
# ---------------------------------------------------------------------------

def _row(date, subject, n):
    return {"date": date, "subject": subject, "cy": "document-download-statement-%032d" % n,
            "label": "Download document with subject " + subject}


class _Button:
    def __init__(self, page, label, kind):
        self.page, self.label, self.kind = page, label, kind

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_attribute(self, name):
        if name == "aria-label":
            return self.label
        if name == "aria-disabled":
            last = self.page.index >= len(self.page.pages) - 1
            first = self.page.index == 0
            return "true" if (self.kind == "next" and last) or (self.kind == "first" and first) else "false"
        return None

    def click(self, timeout=0):
        self.page.pressed.append(self.label)
        self.page.index = 0 if self.kind == "first" else self.page.index + 1


class _Page:
    """Three pages of an inbox list. It records everything pressed."""

    def __init__(self, pages):
        self.pages, self.index, self.pressed = pages, 0, []

    def evaluate(self, js):
        return [dict(r) for r in self.pages[self.index]]

    def locator(self, selector):
        if selector == site._NEXT_PAGE:
            return _Button(self, "Next Page", "next")
        if selector == site._FIRST_PAGE:
            return _Button(self, "Go to first page", "first")
        m = re.search(r'data-cy="([^"]+)"', selector)
        assert m, selector
        return _Button(self, m.group(1), "download")

    def wait_for_timeout(self, ms):
        pass


def _three_pages():
    dates = ["%02d/%02d/2024" % (i // 28 + 1, i % 28 + 1) for i in range(25)]
    rows = [_row(d, d + " Statement", i) for i, d in enumerate(dates)]
    rows[3]["subject"] = "Income-Driven Repayment Annual Notice"
    rows[3]["label"] = "Download document with subject Income-Driven Repayment Annual Notice"
    rows[3]["date"] = "09/09/2024"
    return [rows[:10], rows[10:20], rows[20:]]


def test_the_reader_walks_every_page_and_presses_only_the_pager():
    page = _Page(_three_pages())
    page.index = 2
    docs = site._collect_inbox(page)
    assert len(docs) == 25
    assert {p for p in page.pressed} <= {"Next Page", "Go to first page"}
    assert any(d.title == "Income-Driven Repayment Annual Notice" and d.date_text == "2024-09-09"
               for d in docs)
    assert {d.title: d.kind for d in docs if d.kind != "statement"} == {
        "Income-Driven Repayment Annual Notice": "letter"}


def test_the_control_for_a_row_on_the_last_page_is_found_by_date_and_subject():
    page = _Page(_three_pages())
    el, label = site._inbox_control(page, "2024-01-15", "01/15/2024 Statement")
    assert el is not None
    assert site.is_safe_control(label)
    assert page.index == 1
    assert site._inbox_control(page, "2031-01-01", "01/01/2031 Statement") == (None, "")


def test_a_row_whose_id_is_not_a_plain_id_is_never_turned_into_a_selector():
    rows = [_row("04/15/2024", "04/15/2024 Statement", 1)]
    rows[0]["cy"] = 'document-download-x"] , button[title="Pay'
    page = _Page([rows])
    assert site._inbox_control(page, "2024-04-15", "04/15/2024 Statement") == (None, "")


def test_a_pager_button_the_guard_refuses_is_not_pressed():
    page = _Page(_three_pages())
    assert site._press_pager(page, site._NEXT_PAGE)
    page.locator = lambda selector: _Button(page, "Pay now", "next")
    assert not site._press_pager(page, site._NEXT_PAGE)


def test_the_status_is_stated_where_a_reader_will_find_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "mapped and run against a signed-in account" in src.split('"""')[1]


# ---------------------------------------------------------------------------
# The 1098-E, in a real browser. The page is invented: a button that, once
# pressed, lays out the form for print and calls window.print(), the way
# Tax Info's own button does.
# ---------------------------------------------------------------------------

TAX_PAGE = """<!doctype html><html><head><title>Tax Info</title><style>
@media print { .site-nav, .card { display: none } body.form-ready .form { display: block } }
.form { display: none }
</style></head><body>
<nav class="site-nav">Site navigation and announcements</nav>
<div class="card"><button id="loadEdTaxForm" aria-label="2024 1098-E Form">2024 1098-E Form</button></div>
<div class="form"><h1>Form 1098-E Student Loan Interest Statement</h1><p>Interest paid 1.00 invented</p></div>
<script>
document.getElementById('loadEdTaxForm').addEventListener('click', () => {
  %(press)s
});
</script></body></html>"""


def _browser():
    pytest = __import__("pytest")
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    return pytest, sync_playwright


def _print_with(press, tmp_path):
    pytest, sync_playwright = _browser()
    out = tmp_path / "1098.pdf"
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            pytest.skip("no browser to drive")
        page = b.new_page()
        page.set_content(TAX_PAGE % {"press": press})
        got = site._print_tax_form(page, page.locator("#loadEdTaxForm"),
                                   "2024 1098-E Form", out, [])
        b.close()
    return got, out


def test_the_1098e_is_the_page_printed_after_the_press(tmp_path):
    from paperpull_core import receipt_pdf
    got, out = _print_with("document.body.classList.add('form-ready'); window.print();", tmp_path)
    assert got and out.read_bytes()[:5] == b"%PDF-"
    text = receipt_pdf.pdf_text(out)
    assert "Form 1098-E" in text
    assert "Site navigation" not in text


def test_a_press_that_never_prints_saves_nothing(tmp_path):
    got, out = _print_with("/* nothing happens */", tmp_path)
    assert not got
    assert not out.exists()
