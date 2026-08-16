"""Document classification, period-date parsing, and the read-only safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doc_types
import wealthfront_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_monthly_statement():
    cat, summary, conf = doc_types.classify_document("Monthly Statement - December 2025", RULES)
    assert cat == doc_types.STATEMENT
    assert summary == "Monthly Statement"
    assert conf == doc_types.HIGH


def test_quarterly_statement():
    cat, summary, _ = doc_types.classify_document("Q4 2025 Quarterly Statement", RULES)
    assert cat == doc_types.STATEMENT and summary == "Quarterly Statement"


def test_tax_forms():
    for title, expect in [
            ("2025 Form 1099-B", "1099-B Tax Form"),
            ("1099-DIV for 2025", "1099-DIV Tax Form"),
            ("Consolidated 1099 (2025)", "Consolidated 1099 Tax Form"),
            ("2025 1099-INT", "1099-INT Tax Form")]:
        cat, summary, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert summary == expect, (title, summary)


def test_tax_beats_statement_when_both_words_present():
    cat, summary, _ = doc_types.classify_document("1099-B Tax Statement 2025", RULES)
    assert cat == doc_types.TAX and summary.startswith("1099-B")


def test_unknown_document_is_low_confidence():
    cat, summary, conf = doc_types.classify_document("Welcome Letter", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


def test_skip_patterns():
    assert doc_types.should_skip("Trade Confirmation - Jan 5 2025", RULES)
    assert doc_types.should_skip("Form ADV Part 2", RULES)
    assert not doc_types.should_skip("Monthly Statement - March 2025", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Monthly Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("Statement for February 2024")[0] == "2024-02-29"  # leap
    assert site.parse_period_date("Statement for February 2025")[0] == "2025-02-28"
    assert site.parse_period_date("April 2025 Statement")[0] == "2025-04-30"


def test_quarter_files_on_quarter_end():
    assert site.parse_period_date("Q1 2025 Statement")[0] == "2025-03-31"
    assert site.parse_period_date("Q4 2025 Statement")[0] == "2025-12-31"


def test_year_only_files_on_year_end():
    assert site.parse_period_date("2025 Form 1099-B")[0] == "2025-12-31"


def test_exact_date_wins():
    assert site.parse_period_date("Generated on March 5, 2025")[0] == "2025-03-05"


def test_no_date_returns_none():
    assert site.parse_period_date("Account Notice")[0] is None


# -- filenames ------------------------------------------------------------

def test_document_filename_has_no_trailing_type():
    name = build_pdf_filename("2025-12-31", "Monthly Statement", "")
    assert name == "2025-12-31 Wealthfront Monthly Statement.pdf"


def test_tax_document_filename():
    name = build_pdf_filename("2025-12-31", "1099-B Tax Form", "")
    assert name == "2025-12-31 Wealthfront 1099-B Tax Form.pdf"


# -- row parsing (real shapes captured from the live page 2026-07) --------

def test_parse_tax_row():
    d = site.parse_row(["Joint Cash Account", "Form 1099"])
    assert d.kind == "tax"
    assert d.account == "Joint Cash Account"
    assert d.title == "Form 1099"
    assert d.date_text == ""


def test_parse_consolidated_tax_row():
    d = site.parse_row(["Joint Automated Investing Account", "Consolidated Form 1099"])
    assert d.kind == "tax" and d.title == "Consolidated Form 1099"
    cat, summary, _ = doc_types.classify_document(d.title, RULES)
    assert cat == doc_types.TAX and summary == "Consolidated 1099 Tax Form"


def test_parse_dated_row_extracts_account():
    d = site.parse_row(["07/20/2026", "Trade Confirmation for Joint Automated Investing Account"],
                       href="/documents/10573077/document/DOCD-AA18")
    assert d.kind == "dated"
    assert d.date_text == "07/20/2026"
    assert d.account == "Joint Automated Investing Account"
    assert d.href.startswith("/documents/")
    assert doc_types.should_skip(d.title, RULES)  # trade confirmations excluded


def test_account_custodian_parenthetical_is_trimmed():
    """Real title: 'Quarterly Statement for Emma's 529 Account (from
    Wealthfront Brokerage Corp)' - the custodian suffix must not bloat the
    filename."""
    d = site.parse_row(
        ["06/30/2026",
         "Quarterly Statement for Emma's 529 Account (from Wealthfront Brokerage Corp)"])
    assert d.account == "Emma's 529 Account"


def test_parse_statement_row():
    d = site.parse_row(["01/05/2025", "Monthly Statement for You's Roth IRA"])
    assert d.kind == "dated"
    cat, summary, _ = doc_types.classify_document(d.title, RULES)
    assert cat == doc_types.STATEMENT and summary == "Monthly Statement"
    assert site.parse_period_date(d.date_text)[0] == "2025-01-05"


def test_download_cell_is_stripped():
    cells = site._row_cells("Joint Cash Account\n\t\nForm 1099\n\t\nDownload")
    assert cells == ["Joint Cash Account", "Form 1099"]


def test_prospectus_noise_row_is_ignored():
    # "07/17/2026 | LQD | iShares ... ETF | Link" is not a document row
    d = site.parse_row(["07/17/2026", "LQD", "iShares iBoxx USD Corporate Bond ETF"])
    assert d is None or not doc_types.wanted(
        doc_types.classify_document(d.title, RULES)[0],
        {"document_types": ["Statement", "Tax Document"]})


# -- SAFETY: the read-only guard -----------------------------------------

def test_money_moving_controls_are_never_safe():
    for label in ["Transfer funds", "Deposit", "Withdraw", "Move money",
                  "Sell shares", "Buy", "Place order", "Rebalance",
                  "Change allocation", "Close account", "Edit beneficiary",
                  "Update payment method", "Link bank account", "Submit",
                  "Confirm transfer", "Invest now"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_live_page_write_controls_are_blocked():
    """Real control labels seen on the live Documents page that must never
    be clicked. 'Upload a document' and 'Open new account' both scored safe
    before this guard was tightened (2026-07)."""
    for label in ["Upload a document", "Open new account", "Get started",
                  "Transfer money", "Client Agreement for Joint Cash Account",
                  "Portfolio Line of Credit Agreement", "Learn more & purchase"]:
        assert not site.is_safe_control(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download PDF", "View statement",
                  "Open document", "1099-B", "Monthly Statement"]:
        assert site.is_safe_control(label), label


def test_empty_or_unknown_control_is_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("Continue")
