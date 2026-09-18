"""Synthetic fixtures for the guard, the URL check and the survey's masking.
Nothing here touches tsp.gov."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401, binds the AppSpec the rules loader needs
from paperpull_core import doc_types
import tsp_site as site

RULES = doc_types.load_rules()


def test_statements_and_tax_forms_classify_by_tsp_names():
    for title, cat, summary in [
            ("Annual Participant Statement 2025", doc_types.STATEMENT, "Annual Participant Statement"),
            ("Quarterly Statement Q2 2026", doc_types.STATEMENT, "Quarterly Participant Statement"),
            ("Form 1099-R", doc_types.TAX, "1099-R Tax Form"),
            ("Your statement is available", doc_types.STATEMENT, "Account Statement")]:
        c, s, _ = doc_types.classify_document(title, RULES)
        assert (c, s) == (cat, summary), title


def test_boilerplate_is_skipped():
    for t in ["Privacy Notice", "Fund Fact Sheet", "Summary of the Thrift Savings Plan"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Annual Participant Statement", RULES)


def test_moving_money_is_never_safe():
    for label in ["Interfund Transfer", "Change contribution allocation", "Request a withdrawal",
                  "Apply for a loan", "Start an installment", "Rollover into TSP",
                  "Update beneficiaries", "Direct deposit", "Financial institution",
                  "Required minimum distribution", "Mutual Fund Window", "Submit", "Confirm",
                  "Log out", "Change password", "ThriftLine PIN"]:
        assert not site.is_safe_control(label), label


def test_reading_a_document_is_safe():
    for label in ["Download statement", "View PDF", "Annual Participant Statement",
                  "Tax Forms", "Messages", "Mailbox", "Document History", "1099-R"]:
        assert site.is_safe_control(label), label


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit history statement")
    assert not site.is_safe_control("Edit contact info")


def test_only_tsp_gov_and_its_subdomains_are_allowed():
    for ok in ["https://www.tsp.gov/", "https://my.tsp.gov/s/documents",
               "https://onboarding.tsp.gov/onboarding/s/"]:
        assert site.is_safe_url(ok), ok
    for bad in ["http://www.tsp.gov/", "https://tsp.gov.evil.test/", "https://evil.test/tsp.gov",
                "https://www.tsp.gov@evil.test/", "https://login.gov/", ""]:
        assert not site.is_safe_url(bad), bad


def test_the_survey_follows_only_exact_document_words():
    for text in ["Documents", "Statements", "Tax Forms", "Messages", "Mailbox", "Document History"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Interfund Transfer", "Statements and Withdrawals", "Loans", "Contributions",
                 "Beneficiaries", "Documents you must sign"]:
        assert not site.SURVEY_LINK_RE.match(text), text


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("https://my.tsp.gov/s/account/1234567890/statements") == \
        "https://my.tsp.gov/s/account/##########/statements"
    assert site.redact("Q2 2026") == "Q2 2026"


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"balance": 123456.78, "docs": [{"id": "abc", "date": "2026-06-30"}]})
    assert shape == {"balance": "float", "docs": ["list of 1", {"id": "str", "date": "str"}]}


def test_nothing_is_collected_until_the_site_is_mapped():
    assert site.DOCUMENT_TYPES == {}
    assert site.collect_documents(page=None) == []
