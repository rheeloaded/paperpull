import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import pytest
import amexbanking_site as site
from amexbanking_site import parse_banking_document_list


def test_parse_monthly_statements():
    payload = {
        "totalCount": 2,
        "statements": [
            {
                "documentSize": "145 KB",
                "statementMonth": "08",
                "statementYear": "2026",
                "tag": "doc-tag-aug-2026",
            },
            {
                "documentSize": "130 KB",
                "statementMonth": "2",
                "statementYear": "2024",  # leap year
                "tag": "doc-tag-feb-2024",
            }
        ]
    }

    docs = parse_banking_document_list(payload, account_label="Business Checking", account_token="tok-123")
    assert len(docs) == 2
    assert docs.passed_over == ()

    # August 2026 ends on the 31st
    assert docs[0].category == "Statement"
    assert docs[0].date_text == "2026-08-31"
    assert docs[0].tag == "doc-tag-aug-2026"
    assert docs[0].account_token == "tok-123"
    assert docs[0].document_size == "145 KB"

    # February 2024 (leap year) ends on the 29th
    assert docs[1].category == "Statement"
    assert docs[1].date_text == "2024-02-29"
    assert docs[1].tag == "doc-tag-feb-2024"


def test_parse_month_name():
    payload = {
        "totalCount": 1,
        "statements": [
            {
                "statementMonth": "September",
                "statementYear": "2026",
                "tag": "doc-tag-sep-2026",
            }
        ]
    }
    docs = parse_banking_document_list(payload)
    assert len(docs) == 1
    assert docs[0].date_text == "2026-09-30"


def test_parse_tax_documents():
    payload = {
        "totalCount": 2,
        "statements": [
            {
                "documentSize": "85 KB",
                "taxYear": "2025",
                "taxFormType": "1099-INT",
                "tag": "tax-tag-1099int-2025",
            },
            {
                "documentSize": "90 KB",
                "taxYear": "2024",
                "taxFormType": "1099-MISC",
                "tag": "tax-tag-1099misc-2024",
            }
        ]
    }

    docs = parse_banking_document_list(payload, account_token="tok-abc")
    assert len(docs) == 2

    assert docs[0].category == "Tax Document"
    assert docs[0].title == "1099-INT Tax Form"
    assert docs[0].date_text == "2025-12-31"
    assert docs[0].tag == "tax-tag-1099int-2025"
    assert docs[0].account_token == "tok-abc"

    assert docs[1].category == "Tax Document"
    assert docs[1].title == "1099-MISC Tax Form"
    assert docs[1].date_text == "2024-12-31"


def test_parse_empty_and_malformed():
    assert parse_banking_document_list({}).passed_over == (site.NOT_A_LIST,)
    assert parse_banking_document_list({"statements": "not-a-list"}).passed_over == (site.NOT_A_LIST,)
    empty = parse_banking_document_list({"statements": [], "totalCount": 0})
    assert list(empty) == [] and empty.passed_over == (site.EMPTY_LIST,)


def test_a_list_that_says_no_count_is_not_whole():
    """Nothing else says the page asked for all of the list in one answer."""
    docs = parse_banking_document_list({"statements": [
        {"statementMonth": "1", "statementYear": "2026", "tag": "a"}]})
    assert [d.document_id for d in docs] == ["a"]
    assert docs.passed_over == (site.NO_COUNT,)


@pytest.mark.parametrize("item, part", [
    # A month or a year that cannot be read is never made into a date.
    ({"statementMonth": "Sept", "statementYear": "2026", "tag": "a"}, site.NO_DATE),
    ({"statementMonth": "13", "statementYear": "2026", "tag": "a"}, site.NO_DATE),
    ({"statementMonth": "10", "statementYear": "26", "tag": "a"}, site.NO_DATE),
    ({"taxYear": "TY2025", "taxFormType": "1099-INT", "tag": "a"}, site.NO_DATE),
    ({"statementMonth": "10", "statementYear": "2026"}, site.NO_ID),
    ({"invalid": True, "tag": "a"}, site.UNKNOWN_KIND),
    ("not a document", site.NOT_A_LIST),
])
def test_a_document_that_cannot_be_read_is_passed_over_and_said(item, part):
    payload = {"totalCount": 2, "statements": [item, {"statementMonth": "1", "statementYear": "2026",
                                                      "tag": "kept"}]}
    docs = parse_banking_document_list(payload)
    assert [d.document_id for d in docs] == ["kept"]
    assert docs.passed_over == (part,)


@pytest.mark.parametrize("count", [3, "3", 1])
def test_a_list_its_own_count_disagrees_with_is_not_whole(count):
    payload = {"totalCount": count, "statements": [
        {"statementMonth": "1", "statementYear": "2026", "tag": "a"},
        {"statementMonth": "2", "statementYear": "2026", "tag": "b"}]}
    docs = parse_banking_document_list(payload)
    assert len(docs) == 2
    assert docs.passed_over == (site.SHORT_OF_COUNT,)
