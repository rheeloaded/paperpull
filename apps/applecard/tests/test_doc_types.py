"""Apple Card classification, the guard, dates, and the survey's promises.

The site layer is unverified (#52), so what these pin is everything that
must be true before a tester ever runs it. The guard refuses every control
that pays, transfers, moves money between the card and Savings, withdraws,
touches Daily Cash, disputes or changes a setting. A card statement and a
Savings statement of the same month are two documents with two names. A
date that could belong to two documents is refused rather than guessed.
The survey cannot leak a number.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds the AppSpec
from paperpull_core import doc_types
import applecard_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_titles_classify_the_way_the_filenames_need():
    for title, summary, cat in [
            ("Apple Card Statement - August 2026", "Statement", "STATEMENT"),
            ("Savings Statement - August 2026", "Savings Statement", "STATEMENT"),
            ("1099-INT - 2025", "1099-INT Tax Form", "TAX"),
            ("Tax Document - 2025", "Tax Document", "TAX"),
            ("Form 1099-INT", "1099-INT Tax Form", "TAX")]:
        got_cat, s, _ = doc_types.classify_document(title, RULES)
        assert got_cat == getattr(doc_types, cat), title
        assert s == summary, (title, s)


def test_every_title_discovery_writes_classifies_as_its_own_kind():
    """The title is the only thing that carries a document's kind from
    discovery to its download, so each kind's title must come back as that
    kind and file under the right name."""
    for kind in site.KINDS:
        title = site.title_for(kind, "2025-12-31")
        assert site.kind_of_title(title) == kind, title
        cat, _, _ = doc_types.classify_document(title, RULES)
        assert cat == (doc_types.TAX if kind == site.TAX else doc_types.STATEMENT), title
    assert site.title_for(site.TAX, "2025-12-31", "Download 1099-INT") == "1099-INT - 2025"
    assert site.kind_of_title("1099-INT - 2025") == site.TAX


def test_the_noise_and_the_exports_are_skipped():
    for t in ["Privacy Notice", "Apple Card Customer Agreement", "Export Transactions",
              "Transactions CSV", "OFX"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Apple Card Statement - August 2026", RULES)
    assert not doc_types.should_skip("Savings Statement - August 2026", RULES)


def test_a_card_and_a_savings_statement_of_one_month_get_two_names():
    storage.set_filename_owner("")
    card = build_pdf_filename("2026-08-31", "Statement", "")
    savings = build_pdf_filename("2026-08-31", "Savings Statement", "")
    assert card == "2026-08-31 Apple Card Statement.pdf"
    assert savings == "2026-08-31 Apple Card Savings Statement.pdf"
    assert build_pdf_filename("2025-12-31", "1099-INT Tax Form", "") == \
        "2025-12-31 Apple Card 1099-INT Tax Form.pdf"


def test_every_control_that_moves_money_or_changes_anything_is_refused():
    for label in [
            "Pay", "Make a Payment", "Pay Early", "Schedule Payment", "Payments",
            "Set up Autopay", "Transfer", "Transfer to Bank", "Transfer to Apple Cash",
            "Add Money", "Withdraw", "Withdraw to Bank", "Move money to Savings",
            "Deposit", "Daily Cash", "Change Daily Cash destination", "Apple Cash",
            "Dispute", "Dispute this charge", "Report an Issue", "Report lost or stolen",
            "Lock Card", "Card Number", "Card Details", "Show card information",
            "Security Code", "Request New Card", "Replace Card", "Titanium Card",
            "Request Credit Limit Increase", "Apple Card Family", "Share My Card",
            "Invite", "Bank Accounts", "Add Bank Account", "Linked Accounts",
            "Open Savings", "Open Savings Account", "Close Savings Account", "Close Account",
            "Notifications", "Manage alerts", "Contact Us", "Message", "Chat",
            "Settings", "Update address", "Edit", "Submit", "Confirm", "Sign Out",
            "Sign In", "Password"]:
        assert not site.is_safe_control(label), label


def test_an_export_is_never_mistaken_for_a_statement():
    """Apple offers transactions as CSV or OFX beside the statement PDFs.
    Neither is a statement, so neither may be pressed."""
    for label in ["Export Transactions", "Export", "Download CSV", "Download OFX",
                  "Download QFX", "Export to Quicken", "Download spreadsheet"]:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_document_are_allowed():
    for label in ["View", "Download", "Download PDF", "Download Statement", "View Statement",
                  "Statements", "Savings", "Savings Account", "Tax Documents", "Tax Forms",
                  "1099-INT", "Download 1099-INT", "Print", "See More Statements",
                  "Show older statements"]:
        assert site.is_safe_control(label), label


def test_a_document_control_that_also_moves_money_is_refused():
    for label in ["Download statement and pay", "View statement and Transfer",
                  "Savings transfer", "Savings withdraw", "Statements and Payments"]:
        assert not site.is_safe_control(label), label


def test_the_login_and_settings_vocabulary_is_refused_too():
    for label in ["Sign in", "Log in", "Remember me", "Preferences", "Settings", "Username"]:
        assert not site.is_safe_control(label), label


def test_a_statement_named_by_its_month_is_that_months_last_day():
    """Apple Card and Savings statements run for a calendar month."""
    assert site.document_date(site.CARD, "August 2026") == "2026-08-31"
    assert site.document_date(site.CARD, "February 2028 Download PDF") == "2028-02-29"
    assert site.document_date(site.SAVINGS, "Sep 2026") == "2026-09-30"


def test_a_statement_period_is_filed_at_its_close():
    assert site.document_date(site.CARD, "Aug 1, 2026 - Aug 31, 2026") == "2026-08-31"
    assert site.document_date(site.CARD, "Statement closing 08/31/2026") == "2026-08-31"


def test_a_row_that_names_two_documents_gives_no_date():
    """A container holding the whole list names every month in it. Taking
    the first would file this statement under another month."""
    assert site.document_date(site.CARD, "August 2026 Download July 2026 Download") is None
    assert site.document_date(site.CARD, "Jan 31, 2026 Mar 31, 2026") is None
    # a year heading alone is not a month
    assert site.document_date(site.CARD, "2026") is None
    assert site.document_date(site.CARD, "August") is None


def test_a_tax_form_is_filed_at_its_tax_year_and_never_the_year_it_was_issued():
    assert site.document_date(site.TAX, "Tax Year 2025 1099-INT") == "2025-12-31"
    assert site.document_date(site.TAX, "2025 Form 1099-INT") == "2025-12-31"
    assert site.document_date(site.TAX, "1099-INT 2025 Issued January 31, 2026") == "2025-12-31"
    assert site.document_date(site.TAX, "2025") == "2025-12-31"
    # issued in 2026 for 2025, so the lone year is the wrong one
    assert site.document_date(site.TAX, "1099-INT Issued January 31, 2026") is None
    # two years and no words to choose between them
    assert site.document_date(site.TAX, "2024 2025") is None


def test_dates_in_every_form_the_site_is_likely_to_print():
    assert site.parse_date("Aug 31, 2026 View statement") == "2026-08-31"
    assert site.parse_date("August 31, 2026") == "2026-08-31"
    assert site.parse_date("Statement 08/31/2026") == "2026-08-31"
    assert site.parse_date("08/31/26") == "2026-08-31"
    assert site.parse_date("2026-08-31") == "2026-08-31"
    assert site.parse_date("no date here") is None
    assert site.parse_period_date("August 2026") == ("2026-08-31", "August 2026")


def test_the_survey_masks_numbers_and_takes_no_screenshot():
    assert site.redact("account 123456789 statement") == "account ######### statement"
    assert site.redact("Aug 31, 2026") == "Aug 31, 2026"
    for fn in (site.survey, site._page_summary, site.collect_documents):
        assert ".screenshot(" not in inspect.getsource(fn)
    docs_src = (Path(site.__file__).parent / "applecard_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"rows": [{"amount": 12.5}], "n": 3}) == {"rows": ["1 item(s)", {"amount": "number"}], "n": "number"}


def test_the_survey_follows_only_section_links():
    for text in ["Statements", "Savings", "Savings Account", "Documents", "Tax Documents",
                 "Tax Forms", "Savings Statements", "View Statements"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Payments", "Pay", "Transfer", "Daily Cash", "Withdraw", "Add Money",
                 "Card Number", "Apple Card Family", "Bank Accounts", "Savings transfer"]:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_every_section_menu_step_is_a_word_the_guard_allows():
    """A step the guard would refuse can never be pressed, so a path made
    of one would be dead code pretending to be a route."""
    for kind, steps in site.SECTION_PATH.items():
        for step in steps:
            import re
            rx = re.compile(step, re.I)
            examples = [w for w in ["Statements", "Savings", "Tax Documents", "Documents"]
                        if rx.match(w)]
            assert examples, (kind, step)
            for w in examples:
                assert site.is_safe_control(w), (kind, w)


def test_only_card_apple_com():
    """apple.com as a whole would take in the Apple Store."""
    for u in ["https://card.apple.com/", "https://card.apple.com/statements"]:
        assert site.is_safe_url(u), u
    for u in ["https://www.apple.com/shop/buy-iphone", "https://apple.com/",
              "https://idmsa.apple.com/appleauth", "https://card.apple.com.evil.test/s.pdf",
              "http://card.apple.com/s.pdf", "https://user@card.apple.com/s.pdf",
              "https://card.apple.com:8443/s.pdf"]:
        assert not site.is_safe_url(u), u
    for urls in site.SECTION_URLS.values():
        assert all(site.is_safe_url(u) for u in urls)
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)
    assert all(site.is_safe_url(u) for u in site.URLS.values())


class _Frame:
    def __init__(self, url, fields=0, visible=True):
        self.url, self._n, self._visible = url, fields, visible

    def locator(self, sel):
        return self

    def count(self):
        return self._n

    def nth(self, i):
        return self

    def is_visible(self):
        return self._visible


class _Page:
    def __init__(self, url, frames=()):
        self.url, self.frames = url, list(frames)

    def locator(self, sel):
        return _Frame("", 0)


def test_apples_sign_in_frame_is_noticed_and_a_leftover_frame_is_not():
    """The Apple Account sign-in is a frame over card.apple.com, so the
    password field is never on the page itself. A frame with nothing to
    type into is not a sign-in, or Record could never start."""
    signing_in = _Page("https://card.apple.com/", [_Frame("https://idmsa.apple.com/appleauth/auth", 1)])
    assert site.looks_signed_out(signing_in)
    leftover = _Page("https://card.apple.com/", [_Frame("https://idmsa.apple.com/appleauth/auth", 1, False)])
    assert not site.looks_signed_out(leftover)
    assert site.looks_signed_out(_Page("https://idmsa.apple.com/appleauth/auth"))
    assert not site.looks_signed_out(_Page("https://card.apple.com/statements"))


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme
