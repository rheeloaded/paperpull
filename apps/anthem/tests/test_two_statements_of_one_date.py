"""Two Pharmacy statements of one date are both refused, and only Pharmacy's own
statement shape is taken for a statement.

A statement for a month has no claim, so its identity is its claim type and
its date, Pharmacy|YYYYMMDD|Statement|0. Two statements made the same day,
one for each member say, give that one identity, and nothing in either row
tells which is which. Keeping the first and dropping the other quietly would
file one under the other's identity for good, and a download would take
whichever the summary happened to list first. So neither is kept, both are
named in the log, the list is not taken as whole, and a download of that
identity refuses too.

Only a Pharmacy row holding its identifier, its date and its name and
nothing else is a statement. A claim row whose claim key was renamed is
refused as a row whose claim number cannot be read, as before #210, never
fetched as a statement with no claim. Every name, number and token here is
invented.
"""
import json
import logging
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core import listing  # noqa: E402
from test_a_claim_number_shown_beside_its_token import (  # noqa: E402
    CLAIM_NUMBER, FakePage, claim_row, signed_in)

site = app_mod.site
STATEMENT = "Pharmacy|20260301|Statement|0"


def statement(token, created="2026-03-01", name="Mar 2026 Pharmacy EOB (2026 YTD)"):
    return {"identifier": token, "created": created, "name": name}


ONE, TWO, LATER = statement("aa" * 86), statement("bb" * 86), statement("cc" * 86, "2026-04-01")


# -- the listing -------------------------------------------------------------

def test_two_statements_of_one_date_are_neither_kept_and_are_named(monkeypatch, caplog):
    signed_in(monkeypatch)
    page = FakePage({"Medical": [claim_row()], "Pharmacy": [ONE, TWO, LATER]})
    with caplog.at_level(logging.WARNING):
        rows = site.collect_documents(page)
    assert sorted(r["doc_id"] for r in rows) == [
        "Medical|%s|EOB|2" % CLAIM_NUMBER, "Pharmacy|20260401|Statement|0"]
    assert rows.alike == {STATEMENT: 2}
    assert STATEMENT in caplog.text and "2 Pharmacy statements dated 20260301" in caplog.text
    for token in ("aa" * 86, "bb" * 86):
        assert token not in caplog.text


def test_three_statements_of_one_date_are_counted_as_three(monkeypatch):
    signed_in(monkeypatch)
    rows = site.collect_documents(FakePage({"Pharmacy": [ONE, TWO, statement("dd" * 86)]}))
    assert list(rows) == [] and rows.alike == {STATEMENT: 3}


def test_one_statement_of_a_date_is_kept_and_nothing_is_alike(monkeypatch):
    signed_in(monkeypatch)
    rows = site.collect_documents(FakePage({"Pharmacy": [ONE, LATER]}))
    assert [r["doc_id"] for r in rows] == ["Pharmacy|20260401|Statement|0", STATEMENT]
    assert rows.alike == {}


def test_a_download_of_a_date_two_statements_have_asks_for_neither(monkeypatch, tmp_path, caplog):
    signed_in(monkeypatch)
    for listed in ([ONE, TWO], [TWO, ONE]):
        page = FakePage({"Pharmacy": listed})
        out = tmp_path / "s.pdf"
        with caplog.at_level(logging.WARNING):
            assert site.download_document(page, STATEMENT, out) is False
        assert page.downloads == []
        assert not out.exists()
    assert "2 Pharmacy statements dated 20260301" in caplog.text


# -- the run -----------------------------------------------------------------

@pytest.fixture
def discover(tmp_path, monkeypatch):
    """The app's own Discover, on a page answering the summary as given."""
    signed_in(monkeypatch)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")

    def ran(rows_by_type):
        app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), "--discover"]))
        page = FakePage(rows_by_type)
        app.page = lambda: page
        app.check_session = lambda *_a, **_kw: None
        app.cmd_discover(quiet=True)
        return app
    return ran


def test_a_list_with_two_statements_of_one_date_is_not_taken_as_whole(discover, capsys):
    app = discover({"Medical": [claim_row()], "Pharmacy": [ONE, TWO]})
    assert {r["document_id"] for r in app.discovery.data.values()} == {
        "Medical|%s|EOB|2" % CLAIM_NUMBER}
    assert listing.last(app) == listing.STOPPED
    assert app.stats["alike"] == 2
    said = capsys.readouterr().out
    assert "2 Pharmacy statements dated 2026-03-01" in said and "not taken as whole" in said


def test_a_list_with_one_statement_of_each_date_is_whole(discover):
    app = discover({"Medical": [claim_row()], "Pharmacy": [ONE, LATER]})
    assert {r["document_id"] for r in app.discovery.data.values()} == {
        "Medical|%s|EOB|2" % CLAIM_NUMBER, STATEMENT, "Pharmacy|20260401|Statement|0"}
    assert listing.last(app) == listing.COMPLETE
    assert not app.stats.get("alike")


# -- what a statement is -----------------------------------------------------

def renamed_claim(claim_type_row):
    row = claim_type_row
    row["claims"] = row.pop("claim")
    return row


@pytest.mark.parametrize("claim_type, row", [
    ("Medical", renamed_claim(claim_row())),
    ("Pharmacy", renamed_claim(claim_row())),
    ("Chiropractic", renamed_claim(claim_row())),
    ("Medical", statement("aa" * 86)),
    ("Chiropractic", statement("aa" * 86)),
    ("Pharmacy", dict(statement("aa" * 86), patient={"name": {"given": ["DANA"]}})),
    ("Pharmacy", dict(statement("aa" * 86), eobSequenceNbr=1)),
    ("Pharmacy", {"identifier": "aa" * 86, "created": "2026-03-01"}),
    ("Pharmacy", statement("aa" * 86, created="2026-02-30")),
    ("Pharmacy", statement("aa" * 86, created="")),
    ("Pharmacy", statement("", created="2026-03-01")),
    ("Pharmacy", statement(["aa" * 86])),
    ("Pharmacy", statement("aa" * 86, name=None)),
])
def test_only_pharmacys_own_statement_shape_is_a_statement(monkeypatch, caplog, claim_type, row):
    signed_in(monkeypatch)
    with caplog.at_level(logging.ERROR):
        assert site._extract_row(row, claim_type) is None
    assert "missing a claim number" in caplog.text
    page = FakePage({claim_type: [row]})
    assert list(site.collect_documents(page)) == []


def test_a_medical_row_whose_claim_moved_is_never_asked_for_with_no_claim(monkeypatch, tmp_path):
    signed_in(monkeypatch)
    row = renamed_claim(claim_row())
    page = FakePage({"Medical": [row]})
    assert site.download_document(page, "Medical|20260304|Statement|0", tmp_path / "m.pdf") is False
    assert page.downloads == []


@pytest.mark.parametrize("doc_id", [
    "Medical|20260304|Statement|0",
    "Chiropractic|20260304|Statement|0",
    "Pharmacy|20260230|Statement|0",
    "Pharmacy|2026030|Statement|0",
    "Pharmacy|9000000AA0001|Statement|0",
])
def test_the_guard_takes_a_statement_only_as_pharmacys_of_a_real_day(doc_id):
    assert site.parse_doc_id(doc_id) is None
    assert site.parse_doc_id(STATEMENT) == ("Pharmacy", "20260301", "Statement", 0)
