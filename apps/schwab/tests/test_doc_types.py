"""Synthetic fixtures for provider parsing, filing and control checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import schwab_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_a_brokerage_statement_files_on_its_own_date():
    cat, date, period, title = site.classify_document(
        {"date": "07/31/2026", "documentId": "opaque~700chars",
         "documentName": "Brokerage Statement", "downloadOptions": ["PDF"],
         "type": "Statements", "onDemandDocumentType": "Statements",
         "accountDisplayName": "1234-5678", "insertFormNumbers": []})
    assert cat == "Statement"
    assert date == "2026-07-31"
    assert period == ""
    assert title == "Brokerage Statement"


def test_a_daf_statement_is_still_a_statement():
    cat, _d, _p, title = site.classify_document(
        {"date": "06/30/2026", "documentName": "DAF Account Statement",
         "type": "Statements", "onDemandDocumentType": "Statements",
         "accountDisplayName": "8765-4321"})
    assert cat == "Statement"
    assert title == "DAF Account Statement"


def test_a_tax_form_keeps_its_issue_date_and_tax_year_period():
    cat, date, period, title = site.classify_document(
        {"date": "05/15/2021", "taxYear": "2020",
         "documentName": "5498 - 2020", "downloadOptions": ["PDF"],
         "type": "Tax Forms", "onDemandDocumentType": "TaxForms",
         "accountDisplayName": "1234-5678", "insertFormNumbers": []})
    assert cat == "Tax Document"
    assert date == "2021-05-15"
    assert period == "2020"

    assert doc_types.classify_document("5498 - 2020", RULES)[:2] == \
        (doc_types.TAX, "5498 Tax Form")
    assert doc_types.classify_document(
        "1099 Composite and Year-End Summary - 2024", RULES)[:2] == \
        (doc_types.TAX, "1099 Composite Tax Form")


def test_a_tax_form_without_taxyear_reads_it_from_the_name():
    cat, _d, period, _t = site.classify_document(
        {"date": "02/15/2025", "documentName": "1099R - 2024",
         "type": "Tax Forms", "onDemandDocumentType": "TaxForms",
         "accountDisplayName": "1234-5678"})
    assert cat == "Tax Document"
    assert period == "2024"


def test_a_trade_confirm_is_its_own_category():
    cat, date, _p, title = site.classify_document(
        {"date": "02/15/2026", "documentName": "Confirm - EXAMPLE - Bought",
         "type": "Trade Confirms", "onDemandDocumentType": "TradeConfirms",
         "accountDisplayName": "1234-5678"})
    assert cat == "Trade Confirmation"
    assert date == "2026-02-15"
    assert title == "Confirm - EXAMPLE - Bought"


def test_a_letter_files_on_its_own_date():
    cat, date, _p, _t = site.classify_document(
        {"date": "10/15/2020", "documentName": "Account Verification",
         "type": "Letters", "onDemandDocumentType": "Letters",
         "accountDisplayName": "1234-5678",
         "insertFormNumbers": ["BDL00000REG-00"]})
    assert cat == "Letter"
    assert date == "2020-10-15"


def test_an_unknown_document_kind_is_kept_not_dropped():
    cat, date, _p, title = site.classify_document(
        {"date": "05/05/2026", "documentName": "Margin Notice",
         "type": "Notices", "accountDisplayName": "1234-5678"})
    assert cat == "Other Document"
    assert date == "2026-05-05"


def test_document_descriptor_is_what_identifies_a_document():
    doc = {"documentId": "opaque==", "date": "07/31/2026",
           "documentName": "Brokerage Statement", "type": "Statements",
           "accountDisplayName": "1234-5678"}
    assert site.document_descriptor(doc) == \
        ("Statements", "Brokerage Statement", "2026-07-31", "1234-5678")
    assert "opaque" not in "".join(site.document_descriptor(doc))


def test_account_display_maps_back_to_the_account_id():
    assert site.account_id_from_display("1234-5678") == "12345678"


def test_account_label_shape():
    assert site.account_label("Example Trust", "5678") == "Example Trust (...5678)"


def test_filename():
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-02-15", "Confirm - EXAMPLE - Bought - Example Trust (...5678)", "") == \
        "2026-02-15 Charles Schwab Confirm - EXAMPLE - Bought - Example Trust (...5678).pdf"


def test_all_five_kinds_are_in_scope_by_default():
    cfg = {"document_types": storage.ALL_CATEGORIES}
    for cat in ["Statement", "Tax Document", "Letter", "Trade Confirmation",
                "Report"]:
        assert doc_types.wanted(cat, cfg), cat
    assert not doc_types.wanted("Other Document", cfg)


def test_the_documents_call_asks_for_all_five_types():
    url = site._documents_url("08/20/2016", "08/20/2026")
    for t in ["STATEMENTS", "TAXFORMS", "LETTERS", "REPORTS_AND_PLANNING",
              "CONFIRMS"]:
        assert f"documentTypes={t}" in url, t
    assert "timeFrame=Last10Years" in url
    assert "fromDate=08/20/2016" in url and "toDate=08/20/2026" in url


def test_the_daf_rides_in_its_own_header():
    accounts = [{"account_id": "12345678", "charitable": False},
                {"account_id": "23456789", "charitable": False},
                {"account_id": "87654321", "charitable": True}]
    h = site._id_headers(accounts)
    assert h["schwab-client-ids"] == "12345678,23456789"
    assert h["schwab-client-charitable-ids"] == "87654321"


def test_the_ten_year_window_shape():
    from datetime import date
    frm, to = site.lookback_window(date(2026, 8, 20))
    assert (frm, to) == ("08/20/2016", "08/20/2026")


def test_dates_round_trip():
    assert site.parse_date("07/31/2026") == "2026-07-31"
    assert site.mdy("2026-07-31") == "07/31/2026"
    assert site.mdy("") == ""


def test_trading_actions_are_never_safe():
    for label in ["Trade", "Buy", "Sell", "Sell short", "Place Order",
                  "Launch the SnapTicket order form", "All-In-One Trade Ticket",
                  "Review", "Edit", "Place order", "Preview order",
                  "+ Add Order", "+ Add Conditional", "I Agree",
                  "Full Page Ticket", "Exercise options", "Rebalance"]:
        assert not site.is_safe_control(label), label


def test_money_actions_are_never_safe():
    for label in ["Transfer Funds", "Move Money", "Wire transfer", "Deposit",
                  "Withdraw", "Journal", "Send money", "Pay bills",
                  "Make a payment", "Add funds"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_daf_grant_actions_are_never_safe():
    for label in ["Recommend a grant", "Grant", "Donate", "Gift shares",
                  "Contribute to your DAF"]:
        assert not site.is_safe_control(label), label


def test_settings_actions_are_never_safe():
    for label in ["Update paperless preferences", "Paperless",
                  "Change cost basis method", "Tax Lot Optimizer",
                  "Edit nickname", "Update profile", "Enroll",
                  "Generate a balance letter", "Log Out", "Submit", "Confirm",
                  "Authorize", "Open an account", "Apply now",
                  "Margin"]:
        assert not site.is_safe_control(label), label


def test_document_actions_are_safe():
    for label in ["Click to Download PDF", "Download",
                  "Click to view document Brokerage Statement for account on 07/31/2026",
                  "Statements", "Tax Forms", "Letters", "Reports & Plans",
                  "Trade Confirms", "Search", "View PDF"]:
        assert site.is_safe_control(label), label


def test_trade_confirms_chip_is_safe_but_trade_is_not():
    assert site.is_safe_control("Trade Confirms")
    assert not site.is_safe_control("Trade")
    assert not site.is_safe_control("Trading")


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")
    assert not site.is_safe_control("Give us a call")


def test_trade_ticket_pickers_are_refused():
    for identity in [
            "order-control-action-0-select-id | Select action | Buy Sell",
            "snap_symbolcontrol | Symbol | ",
            "fromAccount | From account | Transfer Money",
            "amount | Amount | Payment",
            "order-component-strategy | Stock/ETF | quantity shares"]:
        assert site.is_money_control(identity), identity


def test_the_real_statement_picker_is_allowed():
    for identity in ["Example IRA ...123 | Account ending in 1 2 3",
                     "date-range-select-id | Date range | Last 3 months",
                     "Example Trust ...678 | Account ending in 6 7 8"]:
        assert not site.is_money_control(identity), identity


def test_unreadable_identity_fails_closed():
    assert site.is_money_control("")


def test_a_maintenance_notice_is_not_rate_limiting():
    notice = ("Transfers: Most new transfers can be submitted, but some features "
              "may be temporarily unavailable. Bill pay, mobile check deposit")
    assert not any(rx.search(notice) for rx in site.RATE_LIMIT_MARKERS)


def test_real_throttling_is_still_detected():
    for text in ["Too many requests", "Our service is temporarily unavailable",
                 "The site is currently unavailable", "HTTP error 429",
                 "We're experiencing technical difficulties",
                 "unusual traffic from your network"]:
        assert any(rx.search(text) for rx in site.RATE_LIMIT_MARKERS), text


def test_the_documents_url_is_not_read_as_signed_out():
    class _P:
        url = site.URLS["documents"]
        def locator(self, _s):
            class _L:
                def count(self): return 0
            return _L()
    assert not site.looks_signed_out(_P())

    class _Q(_P):
        url = "https://client.schwab.com/Areas/Access/Login?SessionTimeOut=y"
    assert site.looks_signed_out(_Q())


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    # "edit" sits inside "Credit" and "update" inside nothing common, but the
    # unanchored stems refused any label containing them. The verbs
    # themselves must still be refused.
    for label in ["Line of Credit Statement", "View Credit Card Statement",
                  "Accredited Investor Letter"]:
        assert site.is_safe_control(label), label
    for label in ["Edit nickname", "Change delivery option", "Update address",
                  "Editing preferences", "Changed mind"]:
        assert not site.is_safe_control(label), label
