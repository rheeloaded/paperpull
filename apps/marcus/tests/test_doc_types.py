"""Marcus document classification, the rows it reads, and the READ-ONLY
(savings account) safety guard. Every account, date and name is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import marcus_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_statements():
    for title, summary in [
            ("Online Savings Statement", "Online Savings Statement"),
            ("High-Yield CD Statement", "CD Statement"),
            ("Account Statement", "Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms():
    for title, summary in [
            ("1099-INT", "1099-INT Tax Form"),
            ("Tax Document", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_disclosures_and_agreements_are_skipped():
    for t in ["Deposit Account Agreement", "Privacy Notice", "Disclosure",
              "Terms and Conditions", "Change in Terms"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Online Savings Statement", RULES)


def test_wanted_respects_config():
    cfg = {"document_types": ["Statement"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert not doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, s, conf = doc_types.classify_document("Welcome to Marcus", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


# -- dates ----------------------------------------------------------------

def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_slash_date():
    assert site.parse_period_date("Statement 11/30/2025")[0] == "2025-11-30"


def test_a_link_that_is_a_date_and_nothing_else():
    assert site._iso_from_label("08/31/2026") == "2026-08-31"
    assert site._iso_from_label(" 2/28/2026 ") == "2026-02-28"


def test_a_link_that_says_more_than_a_date_is_not_a_statement():
    for label in ["Transfer 08/31/2026", "08/31/2026 Edit", "", "02/30/2026",
                  "Statement"]:
        assert site._iso_from_label(label) is None, label


# -- accounts -------------------------------------------------------------

def test_a_masked_account_keeps_the_digits_that_tell_it_apart():
    assert site.account_label("****4417") == "x4417"
    assert site.account_label("•••• 0926") == "x0926"
    assert site.account_label("") == ""


# -- filenames ------------------------------------------------------------

def test_statement_filename():
    assert build_pdf_filename("2026-08-31", "Online Savings Statement x4417", "") == \
        "2026-08-31 Marcus Online Savings Statement X4417.pdf"


# -- SAFETY: the read-only savings-account guard --------------------------

def test_money_and_account_controls_are_never_safe():
    for label in ["Transfer", "Transfer money", "Make a transfer", "Withdraw",
                  "Deposit", "Add money", "Move money", "Send", "Wire",
                  "Fund your account", "Link a bank", "Link bank",
                  "Link an account", "Add account", "Add a bank",
                  "Open an account", "Open a CD", "Open account",
                  "Open a No-Penalty CD", "Open a High-Yield CD", "Renew CD",
                  "Rollover", "Break CD",
                  "Close account", "Rename account", "Add beneficiary",
                  "Manage beneficiaries", "Add joint owner", "Apply",
                  "Apply now", "Get started", "Enroll", "Go paperless",
                  "Refer a friend", "Claim bonus", "Edit profile",
                  "Change password", "Update address", "Account settings",
                  "Manage", "Confirm", "Continue", "Submit", "Agree",
                  "Accept", "Cancel"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "Download PDF", "View statement", "View document",
                  "Open PDF", "Account Statements", "Tax Forms",
                  "Download statement (PDF)"]:
        assert site.is_safe_control(label), label


def test_a_statement_link_is_only_its_date_and_that_is_safe():
    """The link carries no word, so a date alone is a document control here
    and a date beside anything the guard refuses is not."""
    assert site.is_safe_control("08/31/2026")
    assert not site.is_safe_control("Transfer on 08/31/2026")
    assert not site.is_safe_control("2026")


def test_the_verb_edit_is_not_found_inside_credit():
    assert site.is_safe_control("Credit Card Statement")
    assert not site.is_safe_control("Edit statement preferences")
    assert not site.is_safe_control("Edit profile")


def test_empty_or_ambiguous_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


# -- the year picker and a run's scope ------------------------------------

class _Page:
    url = site.DOCUMENTS_URL


def _row(date, account="x4417", index=0):
    label = "%s/%s/%s" % (date[5:7], date[8:10], date[:4])
    return site.Row(index=index, account=account, product="Online Savings",
                    date=date, label=label,
                    href=site.BASE + "/api/invented/document/1", links=1)


@pytest.fixture
def picker(monkeypatch):
    """A table of two years, the newer on show, with no browser."""
    state = {"year": "2026", "selected": [], "refuse": set()}
    tables = {"2026": [_row("2026-08-31"), _row("2026-07-31", index=1)],
              "2025": [_row("2025-12-31"), _row("2025-12-31", "x0926", 1)],
              "2024": []}
    monkeypatch.setattr(site, "_list_shows", lambda page: True)
    monkeypatch.setattr(site, "_rows", lambda page: tables[state["year"]])
    monkeypatch.setattr(site, "_shown_year", lambda page: state["year"])
    monkeypatch.setattr(site, "_year_options",
                        lambda page: ["2026", "2025", "2024"])

    def select(page, year):
        state["selected"].append(year)
        if year in state["refuse"]:
            return False
        state["year"] = year
        return True
    monkeypatch.setattr(site, "_select_year", select)
    return state


def test_every_year_is_read_and_the_year_on_show_is_not_selected(picker):
    docs = site.collect_download_docs(_Page(), keep=None)
    assert picker["selected"] == ["2025", "2024"]
    assert [(d.date_text, d.account) for d in docs] == [
        ("2026-08-31", "x4417"), ("2026-07-31", "x4417"),
        ("2025-12-31", "x4417"), ("2025-12-31", "x0926")]
    assert {d.title for d in docs} == {"Online Savings Statement"}
    assert not any(d.href for d in docs), "an address was kept in the record"


def test_a_scoped_run_never_selects_a_year_it_will_throw_away(picker):
    site.collect_download_docs(_Page(), keep=lambda y: y == "2025")
    assert picker["selected"] == ["2025"]


def test_two_accounts_with_a_statement_of_one_day_are_two_documents(picker):
    docs = site.collect_download_docs(_Page(), keep=lambda y: y == "2025")
    same_day = [d.account for d in docs if d.date_text == "2025-12-31"]
    assert same_day == ["x4417", "x0926"]


def test_a_picker_that_could_not_be_read_stops_the_listing(picker, monkeypatch):
    """With no years read, only the year on show would be listed."""
    monkeypatch.setattr(site, "_year_options", lambda page: [])
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(_Page(), keep=None)


def test_a_row_that_names_no_account_stops_the_listing(picker, monkeypatch):
    monkeypatch.setattr(site, "_rows", lambda page: [_row("2026-08-31", "")])
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(_Page(), keep=None)


def test_a_year_the_table_would_not_show_stops_the_listing(picker):
    """A list short of a year is not a whole list, and is not called one."""
    picker["refuse"].add("2025")
    with pytest.raises(site.ListStopped) as stopped:
        site.collect_download_docs(_Page(), keep=None)
    kept = [d.date_text for d in stopped.value.docs]
    assert kept == ["2026-08-31", "2026-07-31"], "what was read is kept"
