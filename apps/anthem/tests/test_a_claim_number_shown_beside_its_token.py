"""Anthem's EOB summary gives each claim number as a token beside the number.

Each claim identifier carries a `type` ("claimUid" or "claimNumber"), a
`value` that is an opaque token ("e_" and hex, made new on every call) and a
`display` that holds the claim number a person reads. The patient's name is a
FHIR HumanName, {given: [...], family}. A Pharmacy statement for a month comes
as a row with no claim at all, only its identifier, its date and its name.

The identity kept between runs is the claim number from `display`, never the
token, so an EOB downloaded once still matches on the next run. The download
asks with the token the current summary gives, which the site itself sends as
claimId. Every name, claim number and token here is invented.
"""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import anthem_site as site

CLAIM_NUMBER = "9000000AA0001"
UID_TOKEN = "e_" + "1f" * 80
CLAIM_TOKEN = "e_" + "2e" * 67
EOB_ID = "Z_" + "3d" * 95
STATEMENT_ID = "4c" * 86


def claim_row(claim_number=CLAIM_NUMBER, claim_token=CLAIM_TOKEN, eob_id=EOB_ID,
              given=("DANA Q EXAMPLE",), family=""):
    return {
        "identifier": eob_id,
        "created": "2026-03-04",
        "eobSequenceNbr": 2,
        "checkDate": "2026-03-04",
        "patient": {"name": {"given": list(given), "family": family}, "identifier": []},
        "legacyId": "x_" + "5b" * 63,
        "supportingInfo": {"eobSubType": "ClaimEOB", "eobLevelType": "Claim"},
        "name": "Mar 2026 Medical EOB",
        "claim": [{
            "identifier": [
                {"type": "claimUid", "value": UID_TOKEN, "display": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"},
                {"type": "claimNumber", "value": claim_token, "display": claim_number},
            ],
        }],
    }


def statement_row():
    return {"identifier": STATEMENT_ID, "created": "2026-03-01",
            "name": "Mar 2026 Pharmacy EOB (2026 YTD)"}


class FakePage:
    """Answers the summary call with the rows given per claim type, and
    notes the input of each download call."""

    def __init__(self, rows_by_type):
        self.rows_by_type = rows_by_type
        self.downloads = []

    def evaluate(self, js, arg=None):
        if "eob.v1.summary" in js:
            return {"status": 200,
                    "body": {"result": {"data": self.rows_by_type.get(arg["claimType"], [])}}}
        if "eob.v1.download" in js:
            self.downloads.append(dict(arg))
            return {"status": 200, "b64": base64.b64encode(b"%PDF-1.4 invented").decode()}
        raise AssertionError("an unexpected call into the page")


def signed_in(monkeypatch):
    monkeypatch.setattr(site, "is_anthem_owned_page", lambda page: True)
    monkeypatch.setattr(site, "prime_session", lambda page, force=False: True)


# -- the summary row ---------------------------------------------------------

def test_the_claim_number_is_the_display_never_the_token():
    row = site._extract_row(claim_row(), "Medical")
    assert row["claim_id"] == CLAIM_NUMBER
    assert "e_" not in site.make_doc_id("Medical", row["claim_id"], row["doc_kind"], row["seq"])


def test_an_all_digit_claim_number_is_read_from_display_too():
    row = site._extract_row(claim_row(claim_number="2026000000001"), "Medical")
    assert row["claim_id"] == "2026000000001"


def test_a_claim_with_only_a_token_is_refused_not_kept_by_its_token(caplog):
    raw = claim_row()
    for e in raw["claim"][0]["identifier"]:
        e.pop("display")
    assert site._extract_row(raw, "Medical") is None
    assert "missing a claim number" in caplog.text


def test_the_patient_name_is_read_from_a_fhir_human_name():
    assert site._patient_name(claim_row()) == "DANA Q EXAMPLE"
    assert site._patient_name(claim_row(given=("Dana", "Q"), family="Example")) == "Dana Q Example"


def test_a_pharmacy_statement_with_no_claim_is_kept_by_its_date():
    row = site._extract_row(statement_row(), "Pharmacy")
    assert row["claim_id"] == "20260301"
    assert row["doc_kind"] == "Statement"
    doc_id = site.make_doc_id("Pharmacy", row["claim_id"], row["doc_kind"], row["seq"])
    assert doc_id == "Pharmacy|20260301|Statement|0"
    assert site.parse_doc_id(doc_id) == ("Pharmacy", "20260301", "Statement", 0)


def test_the_identity_guard_still_refuses_a_token_or_a_tampered_value():
    for bad in ["Medical|%s|EOB|2" % CLAIM_TOKEN,
                "Medical|%s|Statement|0" % CLAIM_TOKEN,
                "Medical|9000000AA0001|Letter|0",
                "Pharmacy|../20260301|Statement|0"]:
        assert site.parse_doc_id(bad) is None, bad


# -- the listing -------------------------------------------------------------

def test_the_listing_names_the_claim_and_the_patient_and_the_statement(monkeypatch):
    signed_in(monkeypatch)
    page = FakePage({"Medical": [claim_row()], "Pharmacy": [statement_row()]})
    rows = {r["doc_id"]: r for r in site.collect_documents(page)}
    assert set(rows) == {"Medical|%s|EOB|2" % CLAIM_NUMBER, "Pharmacy|20260301|Statement|0"}
    eob = rows["Medical|%s|EOB|2" % CLAIM_NUMBER]
    assert eob["title"] == "Medical Explanation of Benefits"
    assert eob["account"] == "Dana Q Example - Medical claim %s" % CLAIM_NUMBER
    statement = rows["Pharmacy|20260301|Statement|0"]
    assert statement["title"] == "Pharmacy Explanation of Benefits"
    assert statement["date"] == "2026-03-01"
    assert "{" not in statement["account"] and "e_" not in statement["account"]


def test_an_eob_kept_on_an_earlier_run_still_matches_when_the_token_changes(monkeypatch):
    signed_in(monkeypatch)
    first = site.collect_documents(FakePage({"Medical": [claim_row(claim_token="e_" + "aa" * 67)]}))
    later = site.collect_documents(FakePage({"Medical": [claim_row(claim_token="e_" + "bb" * 67)]}))
    assert [r["doc_id"] for r in first] == [r["doc_id"] for r in later]


# -- the download ------------------------------------------------------------

def test_an_eob_is_asked_for_with_the_token_the_current_summary_gives(monkeypatch, tmp_path):
    signed_in(monkeypatch)
    page = FakePage({"Medical": [claim_row()]})
    out = tmp_path / "eob.pdf"
    assert site.download_document(page, "Medical|%s|EOB|2" % CLAIM_NUMBER, out)
    assert page.downloads == [{"claimId": CLAIM_TOKEN, "claimType": "Medical", "eobId": EOB_ID}]
    assert out.read_bytes().startswith(b"%PDF")


def test_a_pharmacy_statement_is_asked_for_with_no_claim(monkeypatch, tmp_path):
    signed_in(monkeypatch)
    page = FakePage({"Pharmacy": [statement_row()]})
    assert site.download_document(page, "Pharmacy|20260301|Statement|0", tmp_path / "s.pdf")
    assert page.downloads == [{"claimId": "", "claimType": "Pharmacy", "eobId": STATEMENT_ID}]


# -- a patient's name in each shape it comes in ------------------------------

def named(name):
    row = claim_row()
    row["patient"]["name"] = name
    return row


def test_a_list_of_human_names_is_read_as_the_name_it_holds():
    assert site._patient_name(named([{"given": ["DANA"], "family": "EXAMPLE"}])) == "DANA EXAMPLE"
    assert site._patient_name(named([{"given": ["Dana", "Q"], "family": "Example"},
                                     {"given": ["DANA", "Q"], "family": "EXAMPLE"}])) == "Dana Q Example"
    assert site._patient_name(named([{"use": "official", "given": ["Dana"], "family": "Example"},
                                     {"use": "old", "given": ["Dana"], "family": "Sample"}])) \
        == "Dana Example, Dana Sample"
    assert site._patient_name(named(["Dana Example"])) == "Dana Example"
    assert site._patient_name(named([{"text": "Dana Q Example"}])) == "Dana Q Example"


@pytest.mark.parametrize("name", [
    [], [None], [7], [[{"given": ["DANA"]}]], [{"given": [["DANA"]], "family": {"x": 1}}],
    {"given": None, "family": None}, {"given": [3, None]}, [{"use": "official"}],
])
def test_a_name_with_nothing_readable_gives_no_name_rather_than_its_shape(name):
    assert site._patient_name(named(name)) == ""


@pytest.mark.parametrize("name", [
    [{"given": ["DANA"], "family": "EXAMPLE"}],
    [{"given": ["DANA"], "family": "EXAMPLE"}, {"given": ["DEE"], "family": "EXAMPLE"}],
    {"given": "DANA", "family": "EXAMPLE"},
    [{"given": ["DANA"], "family": ["EXAMPLE"]}, None, 4],
])
def test_no_name_puts_a_list_or_a_dict_into_a_filename(monkeypatch, name):
    signed_in(monkeypatch)
    (row,) = site.collect_documents(FakePage({"Medical": [named(name)]}))
    for mark in "[]{}'\"":
        assert mark not in row["account"], row["account"]
    assert row["account"].startswith("Dana")


@pytest.mark.parametrize("name, read", [
    ({"given": ["DANA", None, "Q"], "family": "EXAMPLE"}, "DANA Q EXAMPLE"),
    ({"given": ["Dana"], "family": ["Example", "Sample"]}, "Dana Example Sample"),
    ([{"given": [None, "Dana"], "family": ["Example"]}], "Dana Example"),
    ({"text": "Dana Q Example"}, "Dana Q Example"),
    ([{"text": "Dana Q Example"}, {"given": ["Dana", "Q"], "family": "Example"}], "Dana Q Example"),
])
def test_each_part_of_a_human_name_is_read_in_each_shape_it_comes_in(name, read):
    assert site._patient_name(named(name)) == read


# -- an EOB kept before Anthem put a token beside the number -----------------

def old_shape(claim_number=CLAIM_NUMBER, typed=True):
    """The row as Anthem gave it before the token, the claim number itself
    in the claimNumber entry's value, with no display."""
    row = claim_row(claim_number=claim_number)
    uid, number = row["claim"][0]["identifier"]
    uid.pop("display")
    number.pop("display")
    number["value"] = claim_number
    if not typed:
        uid.pop("type")
        number.pop("type")
    return row


@pytest.mark.parametrize("claim_number", [CLAIM_NUMBER, "2026000000001"])
@pytest.mark.parametrize("typed", [True, False])
def test_an_eob_listed_in_the_old_shape_and_the_new_has_one_identity(monkeypatch, claim_number,
                                                                     typed):
    """An EOB downloaded while Anthem gave the number as the value still
    matches its record now the number is the display beside a token."""
    signed_in(monkeypatch)
    before = site.collect_documents(FakePage({"Medical": [old_shape(claim_number, typed)]}))
    now = site.collect_documents(FakePage({"Medical": [claim_row(claim_number=claim_number)]}))
    assert [r["doc_id"] for r in before] == [r["doc_id"] for r in now] == [
        "Medical|%s|EOB|2" % claim_number]
