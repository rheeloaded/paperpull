"""Synthetic fixtures for the guard, the URL check, the lists and the CSV
check. Nothing here touches strike.me, and every value is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401, binds the AppSpec the rules loader needs
from paperpull_core import doc_types
import strike_docs as app_mod
import strike_site as site

RULES = doc_types.load_rules()
HEADER = ",".join(site.CSV_COLUMNS)


def _csv(*dates):
    rows = [HEADER] + ["00000000-0000-4000-8000-%012d,%s,Deposit,10.00,,,,,,,," % (i, d)
                       for i, d in enumerate(dates)]
    return ("\n".join(rows) + "\n").encode()


# -- what each document is called and where it goes -------------------------

def test_each_kind_of_document_classifies_the_way_the_folders_expect():
    month = app_mod.App.statement_doc({"type": "Month", "year": 2026, "month": 10})
    year = app_mod.App.statement_doc({"type": "Year", "year": 2025, "month": None})
    for title, cat, summary in [
            (month.title, doc_types.STATEMENT, "Account Statement"),
            (year.title, doc_types.STATEMENT, "Annual Transactions"),
            ("2025 Form 1099-B.pdf", doc_types.TAX, "1099-B Tax Form"),
            ("Strike 1099-MISC 2025", doc_types.TAX, "1099-MISC Tax Form"),
            ("1099-DA", doc_types.TAX, "1099-DA Tax Form")]:
        c, s, _ = doc_types.classify_document(title, RULES)
        assert (c, s) == (cat, summary), title


def test_a_month_is_dated_by_its_last_day_and_a_year_by_its_last():
    oct_ = app_mod.App.statement_doc({"type": "Month", "year": 2026, "month": 10})
    feb = app_mod.App.statement_doc({"type": "Month", "year": 2024, "month": 2})
    year = app_mod.App.statement_doc({"type": "Year", "year": 2025, "month": None})
    assert (oct_.date, oct_.period, oct_.title) == ("2026-10-31", "2026-10",
                                                     "Account Statement October 2026")
    assert feb.date == "2024-02-29"
    assert (year.date, year.kind) == ("2025-12-31", "Year")
    assert oct_.key != app_mod.App.statement_doc({"type": "Month", "year": 2026,
                                                  "month": 9}).key


def test_a_monthly_statement_is_checked_by_its_closing_day():
    doc = app_mod.App.statement_doc({"type": "Month", "year": 2026, "month": 10})
    who = site.identity_for(doc)
    assert (who.date, who.start) == ("2026-10-31", "")
    assert not site.identity_for(app_mod.App.tax_doc(
        {"id": "a1", "year": 2025, "file_name": "1099-B"})).is_checkable()


# -- the lists ------------------------------------------------------------------

def test_the_statements_list_reads_months_and_years():
    body = {"items": [{"type": "Month", "year": 2026, "month": 1},
                      {"type": "Year", "year": 2025},
                      {"type": "Month", "year": 2025, "month": 12}], "count": 3}
    assert site.statements_from(body, this_year=2026) == [
        {"type": "Month", "year": 2026, "month": 1},
        {"type": "Year", "year": 2025, "month": None},
        {"type": "Month", "year": 2025, "month": 12}]
    assert site.statements_from({"items": [], "count": 0}, this_year=2026) == []


@pytest.mark.parametrize("body", [
    {"items": [{"type": "Month", "year": 2026, "month": 1}], "count": 2},   # more than it holds
    {"items": [{"type": "Quarter", "year": 2026, "month": 1}]},            # an unknown kind
    {"items": [{"type": "Month", "year": 2026, "month": 13}]},
    {"items": [{"type": "Month", "year": "2026", "month": 1}]},
    {"items": [{"type": "Month", "year": 2026, "month": 1}] * 2},          # one statement twice
    {"statements": []},
    None,
])
def test_a_statements_list_it_cannot_read_whole_stops_the_listing(body):
    with pytest.raises(site.ListStopped):
        site.statements_from(body, this_year=2026)


def test_the_tax_list_reads_id_year_and_name():
    body = [{"id": "f-1", "year": 2025, "fileName": "  2025  1099-B.pdf "},
            {"id": 7, "year": "2024", "fileName": "1099-MISC"}]
    assert site.tax_documents_from(body, this_year=2026) == [
        {"id": "f-1", "year": 2025, "file_name": "2025 1099-B.pdf"},
        {"id": "7", "year": 2024, "file_name": "1099-MISC"}]
    assert site.tax_documents_from({"items": [], "count": 0}) == []


@pytest.mark.parametrize("item", [
    {"id": "../x", "year": 2025, "fileName": "a"},
    {"id": None, "year": 2025, "fileName": "a"},
    {"id": "a", "year": 1999, "fileName": "a"},
    {"id": "a", "year": 2025, "fileName": ""},
])
def test_a_tax_form_it_cannot_read_stops_the_listing(item):
    with pytest.raises(site.ListStopped):
        site.tax_documents_from([item], this_year=2026)


# -- the requests ---------------------------------------------------------------

def test_only_the_documents_paths_are_ever_asked_for():
    for ok in ["/api/documents/account-statements",
               "/api/documents/account-statements/2026/10/download",
               "/api/documents/account-statements/2025/download",
               "/api/documents/tax-documents",
               "/api/documents/tax-documents/f-1/download"]:
        assert site.API_PATH_RE.match(ok), ok
    for bad in ["/api/documents/account-statements/2026/13/download",
                "/api/documents/loan-documents",
                "/api/documents/tax-documents/../x/download",
                "/api/user/info", "/api/payment-methods/types",
                "https://evil.test/api/documents/tax-documents", ""]:
        assert not site.API_PATH_RE.match(bad), bad
    with pytest.raises(ValueError):
        site._api(None, "/api/user/info", "json")


def test_the_annual_entry_is_never_asked_for_as_a_pdf():
    with pytest.raises(ValueError):
        site.statement_bytes(None, 2025, None, "pdf")


def test_a_tax_id_is_checked_before_it_reaches_a_path():
    with pytest.raises(ValueError):
        site.tax_bytes(None, "../evil")


def test_the_fetch_stays_on_the_dashboard_and_follows_no_redirect():
    assert "target.hostname !== 'dashboard.strike.me'" in site._FETCH_JS
    assert "redirect: 'error'" in site._FETCH_JS
    assert "ppRead(r)" in site._FETCH_JS


def test_only_the_dashboard_host_is_allowed():
    for ok in ["https://dashboard.strike.me/", "https://dashboard.strike.me/documents"]:
        assert site.is_safe_url(ok), ok
    for bad in ["http://dashboard.strike.me/", "https://strike.me/", "https://auth.strike.me/",
                "https://x.dashboard.strike.me/", "https://dashboard.strike.me.evil.test/",
                "https://dashboard.strike.me@evil.test/", ""]:
        assert not site.is_safe_url(bad), bad


def test_the_sign_in_host_reads_as_signed_out():
    class Page:
        def __init__(self, url):
            self.url = url

        def locator(self, sel):
            class L:
                def count(self):
                    return 0
            return L()
    assert site.looks_signed_out(Page("https://auth.strike.me/strike-auth/Account/Login"))
    assert not site.looks_signed_out(Page("https://dashboard.strike.me/documents"))
    assert site.on_dashboard(Page("https://dashboard.strike.me/"))
    assert not site.on_dashboard(Page("https://strike.me/"))


def test_a_pdfs_name_becomes_its_csvs_name_as_text():
    assert app_mod.as_csv("2026-10-31 Strike Account Statement.pdf") == \
        "2026-10-31 Strike Account Statement.csv"
    assert app_mod.as_csv("a.b.PDF") == "a.b.csv"


# -- the CSV check --------------------------------------------------------------

def test_a_months_csv_is_accepted_only_for_that_month():
    data = _csv("Oct 01 2026 09:15:00", "Oct 31 2026 23:59:59")
    assert site.csv_problem(data, 2026, 10) == ""
    assert site.csv_problem(data, 2026, 9) == "a row is dated in another month"
    assert site.csv_problem(data, 2025, 10) == "a row is dated in another year"


def test_a_month_with_no_transactions_is_a_header_alone():
    assert site.csv_problem((HEADER + "\n").encode(), 2026, 10) == ""
    assert site.csv_problem(("﻿" + HEADER + "\r\n").encode(), 2026, 10) == ""


def test_a_years_csv_takes_every_month_of_that_year():
    assert site.csv_problem(_csv("Jan 02 2025 00:00:00", "Dec 31 2025 12:00:00"), 2025) == ""
    assert site.csv_problem(_csv("Jan 02 2026 00:00:00"), 2025) != ""


@pytest.mark.parametrize("data", [
    b"",
    b"%PDF-1.7 not a csv",
    b"<html><body>Sign in</body></html>",
    (",".join(site.CSV_COLUMNS[:-1]) + "\n").encode(),
    (HEADER + "\nshort,row\n").encode(),
    (HEADER + "\nx,2026-10-01,Deposit,1,,,,,,,,\n").encode(),
    "\udcff".encode("utf-8", "surrogatepass"),
])
def test_anything_else_is_not_a_statement_csv(data):
    assert site.csv_problem(data, 2026, 10)


# -- the guard ------------------------------------------------------------------

def test_moving_money_is_never_safe():
    for label in ["Buy", "Sell", "Send", "Receive", "Deposit", "Withdraw", "Open a loan",
                  "Add a stack", "Add a target order", "Recurring purchases",
                  "Biweekly purchase", "Link a bank account", "Pay with Lightning",
                  "Bitcoin balance details", "USD balance details", "Submit", "Confirm",
                  "Log out", "Change password", "Edit profile", "Beneficiary",
                  "Export statement and send"]:
        assert not site.is_safe_control(label), label


def test_reading_a_document_is_safe():
    for label in ["Documents", "Statements", "Taxes", "Export as PDF", "Export as CSV",
                  "Download statement", "2025 annual transactions", "1099-B"]:
        assert site.is_safe_control(label), label


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit statement")
    assert not site.is_safe_control("Edit statement")


def test_the_survey_follows_only_exact_document_words():
    for text in ["Documents", "Statements", "Taxes", "Tax documents"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Activity", "Banking", "Cost basis", "Statements and payments", "Loans"]:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"balance": 123456.78, "items": [{"year": 2026, "type": "Month"}]})
    assert shape == {"balance": "number",
                     "items": ["1 item(s)", {"year": "number", "type": "string"}]}
