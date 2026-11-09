"""Discover Bank document classification, host filtering, and safety guards."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import discoverbank_site as site

RULES = doc_types.load_rules()


def test_bank_statement_classification():
    for title, summary in [
        ("Checking Statement", "Checking Statement"),
        ("Savings Statement", "Savings Statement"),
        ("Money Market Statement", "Money Market Statement"),
        ("CD Statement", "CD Statement"),
        ("Monthly Statement - October 2026", "Monthly Statement"),
        ("Year-End Summary 2025", "Year-End Summary"),
        ("Statement", "Statement"),
    ]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_deposit_paperwork_is_skipped():
    for title in ["Deposit Account Agreement", "Fee Schedule", "Privacy Notice"]:
        assert doc_types.should_skip(title, RULES), title
    assert not doc_types.should_skip("Checking Statement", RULES)


def test_tax_document_classification():
    cat, s, _ = doc_types.classify_document("2025 1099-INT Tax Form", RULES)
    assert cat == doc_types.TAX
    assert s == "1099-INT Tax Form"


def test_host_filtering():
    assert site.is_safe_url("https://bank.discover.com/web/deposits/documents/statements")
    assert site.is_safe_url("https://www.discover.com/")
    assert not site.is_safe_url("https://card.discover.com/cardmembersvcs/statements")
    assert not site.is_safe_url("https://cards.discover.com/")
    assert not site.is_safe_url("https://capitalone.com")
    assert not site.is_safe_url("http://bank.discover.com")
    assert not site.is_safe_url("https://user:pass@bank.discover.com")
    assert not site.is_safe_url("https://bank.discover.com:8443/")


def test_forbidden_banking_controls():
    forbidden = [
        "Transfer Funds",
        "Wire Transfer",
        "Send Money with Zelle",
        "Deposit Checks",
        "Pay Bills",
        "Set Up Autopay",
        "Order Checks",
        "Close Account",
        "Freeze Debit Card",
        "Replace Card",
        "Overdraft Protection Settings",
        "Withdraw from Checking",
        "Deposit to Savings",
        "Open Checking Account",
        "Apply for Savings Account",
        "Checking Account Settings",
        "Delete Checking Account",
        "Dispute Checking Transaction",
    ]
    for action in forbidden:
        assert not site.is_safe_control(action), f"Expected forbidden: {action}"


def test_safe_document_controls():
    safe = [
        "Checking (••••)",
        "Savings (••••)",
        "Money Market (••••)",
        "CD (••••)",
        "Year 2026 Accordion Section",
        "October 2026 Statement (PDF)",
        "Statements",
        "Tax Forms",
        "Download PDF",
    ]
    for action in safe:
        assert site.is_safe_control(action), f"Expected safe: {action}"


def test_dropdown_context_allows_checking_and_savings():
    assert not site.is_forbidden_control_context(
        "accountSelector | Choose an account | Statements",
        ["Checking (••••1234)", "Savings (••••5678)"],
    )
    assert not site.is_forbidden_control_context(
        "accountSelector | Account | Statements",
        ["Online Checking", "Online Savings"],
    )


def test_payment_widgets_are_refused():
    for identity in [
        "fromAccount | fromAccount | Select an account",
        "payFromAccount | Pay from | Make a payment",
        "payee | Select a payee | Bill Pay",
        "transferTo | To | Transfer funds",
    ]:
        assert site.is_forbidden_control_context(identity), identity


def test_product_pickers_are_refused_by_options():
    opts = [
        "Select an Account",
        "Credit Card",
        "Student Loans",
        "Personal Loans",
        "Home Loans",
    ]
    assert site.is_forbidden_control_context("innocent-looking-id", opts)


def test_mixed_product_picker_options_are_refused():
    opts = ["Checking", "Credit Card", "Student Loans"]
    assert site.is_forbidden_control_context("innocent-looking-id", opts)


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("   ")
    assert not site.is_safe_control("More")


def test_unreadable_identity_fails_closed():
    assert site.is_forbidden_control_context("")
    assert site.is_forbidden_control_context(None)


def test_looks_public_or_error():
    from unittest.mock import MagicMock
    page = MagicMock()
    page.url = "https://www.discover.com/login/?Aff=Bank&link=/web/deposits/documents/statements"
    assert not site.looks_public_or_error(page)

    page.url = "https://www.discover.com/"
    assert site.looks_public_or_error(page)

    page.url = "https://bank.discover.com/error404"
    assert site.looks_public_or_error(page)


def test_on_documents_page():
    from unittest.mock import MagicMock
    page = MagicMock()
    page.url = "https://bank.discover.com/web/deposits/documents/statements"
    
    def mock_locator(selector):
        mock = MagicMock()
        if "password" in selector:
            mock.count.return_value = 0
        else:
            mock.count.return_value = 1
        return mock
        
    page.locator.side_effect = mock_locator
    assert site.on_documents_page(page)

    # Signed out page should never count as documents page
    page.url = "https://www.discover.com/login/?Aff=Bank"
    assert not site.on_documents_page(page)
