"""Synthetic fixtures for the guard, the URL check and the survey's masking.
Nothing here touches tsp.gov."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401, binds the AppSpec the rules loader needs
from paperpull_core import doc_types
import tsp_site as site

RULES = doc_types.load_rules()


def test_real_mailbox_subjects_classify_the_way_the_folders_expect():
    """Every subject seen in a real mailbox on 2026-09-18, as the site
    truncates them (60 characters), and where each must land."""
    for title, cat, summary in [
            ("Annual Account Statement - Thrift Savings Plan - Uniformed S", doc_types.STATEMENT, "Annual Account Statement"),
            ("Quarterly Account Statement - Thrift Savings Plan - Uniforme", doc_types.STATEMENT, "Quarterly Account Statement"),
            ("Online Account Statement - Thrift Savings Plan - Uniformed S", doc_types.STATEMENT, "Online Account Statement"),
            ("Account Statement Supplement - Thrift Savings Plan - Uniform", doc_types.STATEMENT, "Account Statement Supplement"),
            ("Lifetime Income Illustration - Thrift Savings Plan - Uniform", doc_types.STATEMENT, "Lifetime Income Illustration"),
            ("2022 Q2 Participant Statement", doc_types.STATEMENT, "Quarterly Account Statement"),
            ("2021 Annual Participant Statement", doc_types.STATEMENT, "Annual Account Statement"),
            ("2025 Form 1099-R - Thrift Savings Plan", doc_types.TAX, "1099-R Tax Form")]:
        c, s, _ = doc_types.classify_document(title, RULES)
        assert (c, s) == (cat, summary), title


def test_notices_are_other_documents_and_out_of_scope_by_default():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    for title in ["Payment Confirmation - Thrift Savings Plan - Uniformed Servi",
                  "Payment Rights Notice - Thrift Savings Plan - Uniformed Serv",
                  "Your Rollover Contribution Status",
                  "Next Steps for your Rollover - Thrift Savings Plan - Uniform"]:
        c, _, _ = doc_types.classify_document(title, RULES)
        assert c == doc_types.OTHER, title
        assert not doc_types.wanted(c, cfg)


def test_the_delivery_date_parses_and_nothing_else_does():
    assert site.parse_date("Feb 9, 2026") == "2026-02-09"
    assert site.parse_date("Sep 17, 2026") == "2026-09-17"
    assert site.parse_date("2026-02-09") == ""
    assert site.parse_date("") == ""


def test_ids_are_checked_before_they_reach_a_url():
    import pytest
    with pytest.raises(ValueError):
        site.fetch_pdf(None, "../evil", "06437")
    with pytest.raises(ValueError):
        site.fetch_pdf(None, "6aacb3d1234567890abcdef0", "06437&x=1")


def test_only_the_myaccount_host_counts_as_the_documents_page():
    class Page:
        def __init__(self, url):
            self.url = url
        def locator(self, sel):
            class L:
                def count(self):
                    return 0
            return L()
    assert site.on_documents_page(Page("https://api.rk.tsp.gov/api/angularfirst-app/x#/web/converge/gmc"))
    assert not site.on_documents_page(Page("https://www.tsp.gov/"))
    assert not site.on_documents_page(Page("https://api.rk.tsp.gov/login"))


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


def test_the_content_call_only_ever_goes_to_the_myaccount_host():
    assert "api.rk.tsp.gov" in site._FETCH_JS
    assert "Refusing an off-host request" in site._FETCH_JS
    assert "sessionStorage.getItem('alightPersonSessionToken')" in site._FETCH_JS
    # and the headers never come back out of the page
    assert "return {status: r.status, total" in site._FETCH_JS
    assert "alightpersonsessiontoken" not in site._FETCH_JS.split("return")[1]


def test_a_print_stream_prefix_is_dropped_and_a_non_pdf_is_refused():
    """The 1099-R came with '%%UC_CLIENT_INPUT_FILE_NAME' in front of the
    PDF header and was refused as not a PDF. Statements came clean."""
    pdf = b"%PDF-1.3\nrest"
    assert site.strip_print_stream_prefix(pdf) == pdf
    assert site.strip_print_stream_prefix(b"%%UC_CLIENT_INPUT_FILE_NAME\n" + pdf) == pdf
    assert site.strip_print_stream_prefix(b"<html>not a pdf</html>") == b""
    assert site.strip_print_stream_prefix(b"x" * 2000 + pdf) == b""
