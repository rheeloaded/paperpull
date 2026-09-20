"""Citi, the site layer. The guard, the host allowlist, the date shapes,
the card label, and the API's list answer read from a made-up body. No
real account, no real id, no network."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import citi_site as site
from paperpull_core import doc_types


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Citi"
    assert storage.SPEC.routes["Statement"] == "statements"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


@pytest.mark.parametrize("title,category,summary", [
    ("Monthly Statement - September 15, 2026", "Statement", "Monthly Statement"),
    ("Statement", "Statement", "Statement"),
])
def test_the_titles_discovery_writes_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


def test_dates_in_the_shapes_the_api_and_the_page_use():
    assert site.parse_date("09/15/2026") == "2026-09-15"
    assert site.parse_date("2026-09-15") == "2026-09-15"
    assert site.parse_date("September 15, 2026") == "2026-09-15"
    assert site.parse_date("statement ending on Sep 15, 2026") == "2026-09-15"
    assert site.parse_date("yesterday") is None
    assert site.api_date("2026-09-15") == "09/15/2026"
    assert site.parse_period_date("September 2026") == ("2026-09-30", "September 2026")


def test_the_card_label_drops_the_last_four_and_the_boilerplate():
    assert site.account_label("Costco Anywhere Visa Card by Citi - 1234") == "Costco Anywhere Visa"
    assert site.account_label("Citi Double Cash® Card - 5678") == "Citi Double Cash"
    assert site.account_label("Custom Cash Card by Citi - x9012") == "Custom Cash"
    assert site.account_label("") == "Card"


def test_the_list_answer_is_read_newest_first_and_deduplicated():
    listing = {
        "statementsByYear": [
            {"displayYearTitle": "2026", "statementsByMonth": [
                {"displayDate": "September 15", "statementDate": "09/15/2026"},
                {"displayDate": "August 15", "statementDate": "08/15/2026"}]},
            {"displayYearTitle": "2025", "statementsByMonth": [
                {"displayDate": "December 15", "statementDate": "12/15/2025"},
                {"displayDate": "December 15", "statementDate": "12/15/2025"},
                {"displayDate": "bad", "statementDate": ""}]},
        ],
        "archivedStatementsEligibleFlag": True,
    }
    assert site.statement_dates(listing) == ["2026-09-15", "2026-08-15", "2025-12-15"]
    assert site.statement_dates({}) == []


class _Page:
    """A signed-in citi.com tab whose fetch answers from a script."""
    url = "https://online.citi.com/US/nga/accstatement?accountInstanceId=abc"

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, args):
        url, body, headers = args
        assert headers["channelid"] == "CBOL"
        self.calls.append((url, body))
        return self.answers[url]


def test_discovery_walks_every_card_and_carries_the_opaque_id():
    pdf = base64.b64encode(b"%PDF-1.7 fake").decode()
    page = _Page({
        site.API_ACCOUNTS: {"status": 200, "ct": "application/json", "json": {"eligibleAccounts": {"cardAccounts": [
            {"accountId": "uuid-one", "accountNickname": "Costco Anywhere Visa Card by Citi - 1234", "accountType": "CARDS"},
            {"accountId": "uuid-two", "accountNickname": "Citi Double Cash Card - 5678", "accountType": "CARDS"},
            {"accountNickname": "no id, skipped"}]}}},
        site.API_LIST: {"status": 200, "ct": "application/json", "json": {"statementsByYear": [
            {"displayYearTitle": "2026", "statementsByMonth": [{"statementDate": "09/15/2026"}]}]}},
        site.API_PDF: {"status": 200, "ct": "application/pdf", "b64": pdf},
    })
    docs = site.collect_download_docs(page)
    assert [(d.account, d.date_text, d.href, d.title) for d in docs] == [
        ("Costco Anywhere Visa", "2026-09-15", "uuid-one", "Monthly Statement - September 15, 2026"),
        ("Citi Double Cash", "2026-09-15", "uuid-two", "Monthly Statement - September 15, 2026"),
    ]
    assert page.calls[0] == (site.API_ACCOUNTS, {"transactionCode": "1079_statements"})
    assert page.calls[1] == (site.API_LIST, {"accountId": "uuid-one"})


def test_the_download_posts_the_api_date_and_writes_only_a_pdf(tmp_path):
    pdf = base64.b64encode(b"%PDF-1.7 fake").decode()
    page = _Page({
        site.API_PDF: {"status": 200, "ct": "application/pdf", "b64": pdf},
    })
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, None, "2026-09-15", out, account_id="uuid-one", account="Costco Anywhere Visa")
    assert out.read_bytes().startswith(b"%PDF-")
    assert page.calls[-1] == (site.API_PDF, {"accountId": "uuid-one", "statementDate": "09/15/2026",
                                             "requestType": "RECENT STATEMENTS"})

    page.answers[site.API_PDF] = {"status": 200, "ct": "application/json", "json": {"errors": ["nope"]}}
    out2 = tmp_path / "t.pdf"
    assert not site.download_bill(page, None, "2026-08-15", out2, account_id="uuid-one")
    assert not out2.exists()


def test_a_record_without_an_id_is_matched_to_its_card_by_label(tmp_path):
    pdf = base64.b64encode(b"%PDF-1.7 fake").decode()
    page = _Page({
        site.API_ACCOUNTS: {"status": 200, "ct": "application/json", "json": {"eligibleAccounts": {"cardAccounts": [
            {"accountId": "uuid-two", "accountNickname": "Citi Double Cash Card - 5678"}]}}},
        site.API_PDF: {"status": 200, "ct": "application/pdf", "b64": pdf},
    })
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, None, "2026-09-15", out, account="Citi Double Cash")
    assert page.calls[-1][1]["accountId"] == "uuid-two"
    assert not site.download_bill(page, None, "2026-09-15", tmp_path / "u.pdf", account="Unknown")


def test_a_sign_in_answer_stops_the_run_instead_of_filing_a_failure():
    page = _Page({site.API_ACCOUNTS: {"status": 403, "ct": "text/html", "json": None}})
    with pytest.raises(site.SessionExpired):
        site.accounts(page)
    page.url = "https://online.citi.com/login"
    with pytest.raises(site.SessionExpired):
        site.accounts(page)


def test_the_fetch_refuses_any_other_host():
    page = _Page({})
    with pytest.raises(ValueError):
        site._post(page, "https://evil.test/gcgapi", {})


def test_moving_money_and_card_controls_are_never_safe():
    for name in ["Make a Payment", "Pay Bill", "Balance Transfer", "Cash Advance", "Redeem Points",
                 "Request Credit Line Increase", "Add Authorized User", "Lock Card", "Replace Card",
                 "Flex Loan", "Plan It", "Request Older Statements", "Spend Summary",
                 "Log out", "Change password", "Go paperless", "Sign On"]:
        assert not site.is_safe_control(name), name


def test_reading_a_statement_is_safe():
    for name in ["Download", "View statement", "Statements", "Download PDF", "View All Statements"]:
        assert site.is_safe_control(name), name


def test_only_citi_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://online.citi.com/US/nga/accstatement")
    assert site.is_safe_url(site.API_PDF)
    assert not site.is_safe_url("http://online.citi.com/")
    assert not site.is_safe_url("https://citi.com.example/")
    assert not site.is_safe_url("https://notciti.com/")
    assert not site.is_safe_url("https://user:pw@online.citi.com/")


def test_redaction_masks_long_digit_runs_and_query_strings():
    assert site.redact("card 4111222233334444 at https://online.citi.com/x?tok=abc") == \
        "card ################ at https://online.citi.com/x?..."


def test_the_diagnose_list_carries_no_account_id():
    page = _Page({
        site.API_ACCOUNTS: {"status": 200, "ct": "application/json", "json": {"eligibleAccounts": {"cardAccounts": [
            {"accountId": "uuid-one", "accountNickname": "Costco Anywhere Visa Card by Citi - 1234"}]}}},
        site.API_LIST: {"status": 200, "ct": "application/json", "json": {"statementsByYear": [
            {"displayYearTitle": "2026", "statementsByMonth": [{"statementDate": "09/15/2026"}]}]}},
    })
    docs = site.collect_documents(page)
    assert len(docs) == 1 and docs[0].href == "" and docs[0].account == "Costco Anywhere Visa"
