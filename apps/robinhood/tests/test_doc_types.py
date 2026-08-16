"""Robinhood document classification + the READ-ONLY (brokerage) safety guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doc_types
import robinhood_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_statements():
    for title, summary in [
            ("Account Statement", "Account Statement"),
            ("Monthly Account Statement - December 2025", "Monthly Statement"),
            ("Brokerage Statement", "Brokerage Statement"),
            ("Crypto Statement", "Crypto Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms():
    for title, summary in [
            ("Consolidated 1099", "Consolidated 1099 Tax Form"),
            ("Consolidated Form 1099", "Consolidated 1099 Tax Form"),
            ("Robinhood Crypto 1099", "Crypto 1099 Tax Form"),
            ("1099-B", "1099-B Tax Form"),
            ("Form 1099-DIV", "1099-DIV Tax Form"),
            ("1042-S", "1042-S Tax Form")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_trade_confirmations_are_skipped():
    assert doc_types.should_skip("Trade Confirmation", RULES)
    assert doc_types.should_skip("Trade Confirmation - AAPL", RULES)
    assert not doc_types.should_skip("Account Statement", RULES)


def test_other_skips():
    for t in ["Customer Agreement", "Prospectus for VTI", "Privacy Policy",
              "Options Agreement Disclosure"]:
        assert doc_types.should_skip(t, RULES), t


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to Robinhood", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- period dates ---------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_year_only():
    assert site.parse_period_date("2025 Consolidated 1099")[0] == "2025-12-31"


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    assert build_pdf_filename("2025-12-31", "Monthly Statement", "") == \
        "2025-12-31 Robinhood Monthly Statement.pdf"


def test_tax_filename():
    assert build_pdf_filename("2025-12-31", "Consolidated 1099 Tax Form", "") == \
        "2025-12-31 Robinhood Consolidated 1099 Tax Form.pdf"


# -- SAFETY: the read-only brokerage guard --------------------------------

def test_trading_and_money_controls_are_never_safe():
    for label in ["Buy", "Sell", "Buy AAPL", "Sell all", "Trade", "Place order",
                  "Review order", "Cancel order", "Transfer", "Withdraw",
                  "Deposit", "Move money", "Send", "Receive", "Convert",
                  "Swap", "Stake", "Exercise", "Close position", "Trade options",
                  "Enable margin", "Apply for Gold", "Open an account",
                  "Add money", "Link bank", "Confirm", "Continue", "Agree"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download PDF", "View statement", "View document",
                  "Open PDF", "Save", "View 1099", "Export", "Download report"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")
