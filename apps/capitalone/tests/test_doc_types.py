"""Synthetic fixtures for provider parsing, filing and control checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import capitalone_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_a_card_statement_files_on_its_display_date():
    cat, date, period, title = site.classify_document(
        {"description": "Savor...1234", "datasetId": "00000000-0000-4000-8000-000000000001",
         "documentCategory": "STATEMENT", "documentType": "CARD_STATEMENT",
         "documentId": "00000000-0000-4000-8000-000000000002",
         "extendedDescription": "Savor...1234",
         "documentDisplayDate": "2026-08-15", "documentSource": "EFIT",
         "documentDate": "2026-08-15", "documentName": "August card statement",
         "documentAssociations": {},
         "_links": {"rawURL": "/documents/00000000-0000-4000-8000-000000000002/raw?documentType=CARD_STATEMENT&datasetId=00000000-0000-4000-8000-000000000001"},
         "account": {"accountReferenceId": "AbCd+eF/gH1234567890iJkLmNoPqRsTuVwXyZ0=",
                     "accountType": "CARD_ACCOUNT"}})
    assert cat == "Statement"
    assert date == "2026-08-15"
    assert period == ""
    assert title == "August card statement"


def test_a_bank_statement_files_on_its_closing_date_not_period_start():
    cat, date, _p, title = site.classify_document(
        {"documentCategory": "STATEMENT", "documentType": "BANK_STATEMENT",
         "multipleAccounts": False, "documentDisplayDate": "2026-07-31",
         "documentDate": "2026-07-01", "documentName": "July bank statement",
         "account": {"accountType": "BANK_ACCOUNT",
                     "accountReferenceId": "zY9xW8vU7t+S6rQ5pO4nM3lK2jI1hG0fEdCbA="},
         "_links": {"rawURL": "/documents/w87dSYNTHETIC%2Bid%3B7/raw?documentType=BANK_STATEMENT"},
         "documentSource": "eStatements", "description": "Kids Savings Account...5678",
         "extendedDescription": "Kids Savings Account...5678",
         "documentId": "w87dSYNTHETIC%2Bid%3B7"})
    assert cat == "Statement"
    assert date == "2026-07-31"
    assert title == "July bank statement"


def test_a_tax_form_reads_its_year_from_the_name():
    cat, date, period, _t = site.classify_document(
        {"documentCategory": "TAX", "documentType": "TAX_FORM",
         "documentDisplayDate": "2027-01-20", "documentDate": "2027-01-20",
         "documentName": "1099-INT 2026", "description": "360 Performance Savings...5678",
         "account": {"accountReferenceId": "zY9xW8vU7tS6rQ5p="},
         "documentId": "synthetic"})
    assert cat == "Tax Document"
    assert date == "2027-01-20"
    assert period == "2026"
    assert doc_types.classify_document("1099-INT 2026", RULES)[:2] == \
        (doc_types.TAX, "1099-INT Tax Form")


def test_a_letter_is_its_own_category():
    cat, _d, _p, _t = site.classify_document(
        {"documentCategory": "LETTER", "documentType": "LETTER",
         "documentDisplayDate": "2026-05-05", "documentDate": "2026-05-05",
         "documentName": "Account notice", "description": "Savor...1234",
         "account": {"accountReferenceId": "AbCd="}, "documentId": "synthetic"})
    assert cat == "Letter"


def test_an_unknown_category_is_kept_not_dropped():
    cat, _d, _p, _t = site.classify_document(
        {"documentCategory": "NOTICE", "documentType": "NOTICE",
         "documentDate": "2026-05-05", "documentName": "Margin Notice",
         "description": "Savor...1234", "documentId": "synthetic"})
    assert cat == "Other Document"


def test_a_yearly_statement_period_is_the_year_it_summarizes():
    cat, date, period, title = site.classify_ease_document(
        {"datasetId": "00000000-0000-4000-8000-000000000003",
         "datasetVersion": "1.0", "documentId": "70ceb204-synthetic",
         "documentCreatedTimestamp": "2026-01-22T00:00:00+0000",
         "imageSize": "22668", "imageMimeType": "afp",
         "documentLifecycleTags": [],
         "documentMetadata": [
             {"itemName": "documentDate", "itemValue": "2026-01-22", "isMultiValue": False},
             {"itemName": "product", "itemValue": "CC", "isMultiValue": False},
             {"itemName": "sourceDocumentGroup", "itemValue": "brandedCard-yearly-statements-daily", "isMultiValue": False},
             {"itemName": "documentType", "itemValue": "Card Yearly Statement", "isMultiValue": False},
             {"itemName": "year", "itemValue": "2025", "isMultiValue": False},
             {"itemName": "accountReferenceId", "itemValue": "AbCd+eF/gH123=", "isMultiValue": False},
             {"itemName": "contentSubCategory", "itemValue": "Yearly", "isMultiValue": False},
             {"itemName": "creationDate", "itemValue": "2026-01-22", "isMultiValue": False},
             {"itemName": "contentCategory", "itemValue": "Statement", "isMultiValue": False},
             {"itemName": "documentSource", "itemValue": "EFIT-COMP", "isMultiValue": False}]},
        site.TYPE_CARD_YEARLY)
    assert cat == "Statement"
    assert date == "2026-01-22"
    assert period == "2025"
    assert title == "Card Yearly Statement"


def test_a_quarterly_statement_is_a_statement():
    cat, date, period, title = site.classify_ease_document(
        {"datasetId": "ddc90929-61fc-4b02-8f39-279f2f1ff94c",
         "documentId": "synthetic",
         "imageMimeType": "application/vnd.ibm.modcap",
         "documentMetadata": [
             {"itemName": "documentDate", "itemValue": "2026-07-10", "isMultiValue": False},
             {"itemName": "documentType", "itemValue": "Card Quarterly Statement", "isMultiValue": False}]},
        site.TYPE_CARD_QUARTERLY)
    assert cat == "Statement"
    assert date == "2026-07-10"
    assert period == ""
    assert title == "Card Quarterly Statement"


def test_document_descriptor_is_what_identifies_a_document():
    assert site.document_descriptor("CARD_STATEMENT", "August card statement",
                                    "2026-08-15", "Savor...1234") == \
        ("CARD_STATEMENT", "August card statement", "2026-08-15", "Savor...1234")


def test_account_labels_from_descriptions():
    assert site.account_label("Savor...1234") == "Savor (...1234)"
    assert site.account_label("Kids Savings Account...5678") == \
        "Kids Savings Account (...5678)"
    assert site.account_label("Spark Cash Select...4321") == \
        "Spark Cash Select (...4321)"
    assert site.account_last4("Savor...1234") == "1234"


def test_card_accounts_are_learned_from_the_statement_records():
    docs = [
        {"documentType": "CARD_STATEMENT", "description": "Savor...1234",
         "account": {"accountReferenceId": "refA="}},
        {"documentType": "CARD_STATEMENT", "description": "Savor...1234",
         "account": {"accountReferenceId": "refA="}},
        {"documentType": "CARD_STATEMENT", "description": "Spark Cash Select...4321",
         "account": {"accountReferenceId": "refB="}},
        {"documentType": "BANK_STATEMENT", "description": "Kids Savings Account...5678",
         "account": {"accountReferenceId": "refC="}},
    ]
    accounts = site.card_accounts_from_docs(docs)
    assert [a["account_ref"] for a in accounts] == ["refA=", "refB="]
    assert accounts[0]["label"] == "Savor (...1234)"


def test_filename():
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-08-15", "August card statement - Savor (...1234)", "") == \
        "2026-08-15 Capital One August Card Statement - Savor (...1234).pdf"


def test_all_three_kinds_are_in_scope_by_default():
    cfg = {"document_types": storage.ALL_CATEGORIES}
    for cat in ["Statement", "Tax Document", "Letter"]:
        assert doc_types.wanted(cat, cfg), cat
    assert not doc_types.wanted("Other Document", cfg)


def test_the_lookback_window_is_seven_years():
    from datetime import date
    assert site.lookback_window(date(2026, 8, 21)) == ("2019-08-21", "2026-08-21")
    assert site.LOOKBACK_YEARS == 7


def test_the_deposits_path_double_encodes_the_account_ref():
    assert site._double_encode("ab+cd/ef=") == "ab%252Bcd%252Fef%253D"


def test_the_multipart_pdf_part_is_extracted():
    body = (b"--BOUNDARY\r\n"
            b'Content-Disposition: form-data; name="metadata"\r\n'
            b"Content-Type: application/json\r\n\r\n"
            b'{"documentId": "x"}\r\n'
            b"--BOUNDARY\r\n"
            b'Content-Disposition: form-data; name="contents"\r\n'
            b"Content-Type: application/pdf\r\n\r\n"
            b"%PDF-1.5 fake pdf bytes\r\n"
            b"--BOUNDARY--\r\n")
    assert site._extract_multipart_pdf(body) == b"%PDF-1.5 fake pdf bytes"
    assert site._extract_multipart_pdf(b"no pdf part here") == b""


def test_the_ease_datasets_are_the_recorded_ones():
    assert site.EASE_DATASETS["CARD_YEARLY_STATEMENT"] == \
        (["bd8e025e-affc-42b3-8d62-75ab194fb54b"], ["YEAR_ENDING_STATEMENT_v1"])
    assert site.EASE_DATASETS["CARD_QUARTERLY_STATEMENT"] == \
        (["ddc90929-61fc-4b02-8f39-279f2f1ff94c"], ["QUARTER_ENDING_STATEMENT_v1"])


def test_dates_parse():
    assert site.parse_date("2026-08-15") == "2026-08-15"
    assert site.parse_date("August 2026") is None
    assert site.parse_date("") is None


def test_payment_actions_are_never_safe():
    for label in ["Pay bill", "Make a payment", "Transfer Money",
                  "Transfer money", "Automatic savings", "Manage AutoPay",
                  "Deposit a check", "Set up direct deposit", "Zelle"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_card_money_features_are_never_safe():
    for label in ["Get your Virtual Card", "Create & Manage Virtual Cards",
                  "Redeem rewards", "Balance transfer", "Cash advance",
                  "Lock card", "Replace card", "Report lost or stolen"]:
        assert not site.is_safe_control(label), label


def test_offer_actions_are_never_safe():
    for label in ["Activate shopping offers", "Earn now", "View all offers",
                  "Refer now", "Explore offer", "Decline"]:
        assert not site.is_safe_control(label), label


def test_account_management_actions_are_never_safe():
    for label in ["Close this account", "Manage beneficiaries",
                  "Manage external accounts", "Open a new account",
                  "Open an account", "Apply now", "Dispute a charge",
                  "Add authorized user"]:
        assert not site.is_safe_control(label), label


def test_settings_actions_are_never_safe():
    for label in ["Manage paperless", "Update email", "Edit profile",
                  "Set up alerts", "Change username", "Enroll",
                  "Log Out", "Submit", "Confirm", "I Agree"]:
        assert not site.is_safe_control(label), label


def test_document_actions_are_safe():
    for label in ["View statement", "View statements", "View tax forms",
                  "Download", "Download PDF", "View my statement",
                  "Filter", "Search"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")
    assert not site.is_safe_control("Give us a call")


def test_the_keepalive_is_safe_but_plain_continue_is_not():
    assert site.is_safe_control("Continue session")
    assert not site.is_safe_control("Continue")


def test_payment_pickers_are_refused():
    for identity in ["fromAccount | From account | Transfer Money",
                     "amount | Amount | Payment",
                     "autopay-settings | Manage AutoPay",
                     "offer-tile | Earn now"]:
        assert site.is_money_control(identity), identity


def test_the_real_document_pickers_are_allowed():
    for identity in ["year-select | Tax year | 2025",
                     "statement-picker | Monthly Quarterly Yearly"]:
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
        url = "https://verified.capitalone.com/auth/signin"
    assert site.looks_signed_out(_Q())
