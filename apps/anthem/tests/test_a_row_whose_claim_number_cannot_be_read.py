"""An EOB row whose claim number cannot be read leaves the run unfinished.

A Medical, Pharmacy or Chiropractic row that is not a Pharmacy statement and
whose claim number cannot be read is no document this app can keep. It was
passed over with a log line, the list was called whole and the run ended
clean, so an EOB Anthem listed could go missing for good with nothing on the
panel to say so. Now each such row counts as failed, Discover says how many
and of which claim type, a failure file is written, and the list is not taken
as whole. The rest of the list is kept as before.

collect_documents keeps its signature, since core's census stubs and older
tests call it with the page alone. It answers a Collected, a list carrying
the rows it could not read. Every claim number, token and name is invented.
"""
import json
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


def unreadable():
    """A claim row whose claim number entry carries only its token."""
    row = claim_row(claim_number="9000000AA0007", eob_id="Z_" + "6a" * 95)
    for e in row["claim"][0]["identifier"]:
        e.pop("display")
    return row


def test_a_row_with_no_claim_number_is_carried_as_unread(monkeypatch):
    signed_in(monkeypatch)
    rows = site.collect_documents(FakePage({"Medical": [claim_row(), unreadable()],
                                            "Chiropractic": [unreadable(), unreadable()]}))
    assert [r["doc_id"] for r in rows] == ["Medical|%s|EOB|2" % CLAIM_NUMBER]
    assert rows.unread == {"Medical": 1, "Chiropractic": 2}
    assert rows.alike == {}


def test_a_whole_list_carries_nothing_unread(monkeypatch):
    signed_in(monkeypatch)
    rows = site.collect_documents(FakePage({"Medical": [claim_row()]}))
    assert rows.unread == {}


@pytest.fixture
def discover(tmp_path, monkeypatch):
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
        app.stats["mode"] = "discover"
        app.cmd_discover(quiet=True)
        return app
    return ran


def failure_files(app):
    return [p for p in Path(app.paths.diagnostics).rglob("*") if p.is_file() and "failure" in p.name]


def test_discover_counts_a_row_it_could_not_read_as_failed(discover, capsys):
    app = discover({"Medical": [claim_row(), unreadable()]})
    assert {r["document_id"] for r in app.discovery.data.values()} == {
        "Medical|%s|EOB|2" % CLAIM_NUMBER}
    assert app.stats["failed"] == 1
    assert listing.last(app) == listing.STOPPED
    said = capsys.readouterr().out
    assert "1 Medical EOB row" in said and "could not be read" in said
    (written,) = failure_files(app)
    text = written.read_text(encoding="utf-8")
    assert "a row had no claim number" in text and "read the eob list" in text
    for token in ("6a" * 95, "2e" * 67, "9000000AA0007"):
        assert token not in text


def test_discover_with_every_row_read_finishes_whole(discover):
    app = discover({"Medical": [claim_row()]})
    assert not app.stats["failed"]
    assert listing.last(app) == listing.COMPLETE
    assert failure_files(app) == []


def test_a_run_with_a_row_it_could_not_read_does_not_end_clean(tmp_path, monkeypatch):
    signed_in(monkeypatch)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    page = FakePage({"Medical": [unreadable()]})
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "check_session", lambda *_a, **_kw: None)
    assert app_mod.main(["--config", str(cfg), "--discover"]) == 1


@pytest.mark.parametrize("key", ["claimId", "claimNumber", "claimReferenceNumber"])
@pytest.mark.parametrize("value", ["e_" + "2e" * 67, "x_" + "5b" * 63, "ABC12", "9000000AA0001-2",
                                   "9" * 21])
def test_a_token_at_a_top_level_claim_key_is_no_claim_number(monkeypatch, key, value):
    """A reshape that moves the token to a top-level claim key leaves the row
    unread, counted and never a record the guard refuses."""
    signed_in(monkeypatch)
    row = {"identifier": "Z_" + "3d" * 95, "created": "2026-03-04", key: value}
    rows = site.collect_documents(FakePage({"Medical": [row]}))
    assert list(rows) == []
    assert rows.unread == {"Medical": 1}


def test_a_claim_number_at_a_top_level_key_is_still_read(monkeypatch):
    signed_in(monkeypatch)
    row = {"identifier": "Z_" + "3d" * 95, "created": "2026-03-04", "claimId": "9000000AA0001"}
    (got,) = site.collect_documents(FakePage({"Medical": [row]}))
    assert got["doc_id"] == "Medical|9000000AA0001|EOB|0"
