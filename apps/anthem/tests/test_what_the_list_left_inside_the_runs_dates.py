"""What the EOB list could not give is counted only where the run would take it.

A claim type whose own list did not come, an answer other than 200 or a call
that failed in the page, is not an empty list. It was passed over and the
list was still noted whole, on main as well. Now it counts as failed, is
named by its claim type and how it failed and never by the page's words, and
the list is not taken as whole.

Two statements of one date, and a row whose claim number cannot be read, are
counted only when the run would take an EOB of that day, inside its year and
dates and of a kind it takes. One outside them would otherwise keep every
listing not whole for as long as Anthem lists it, up to 24 months, and every
Resume would stop on it. A row whose day cannot be read is counted, since
nothing says it is outside. What Discover says of two statements is only
what is true, even when an earlier run saved one of that date.

Every claim number, token, date and name here is invented.
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
EOB = "Medical|%s|EOB|2" % CLAIM_NUMBER
PAGE_WORDS = "Dana Example's claim for invented words"


class Partly(FakePage):
    """The summary as FakePage answers it, but for the claim types in
    `refused`, each answered with a status or failing in the page."""

    def __init__(self, rows_by_type, refused):
        super().__init__(rows_by_type)
        self.refused = refused

    def evaluate(self, js, arg=None):
        if "eob.v1.summary" in js and arg["claimType"] in self.refused:
            how = self.refused[arg["claimType"]]
            if isinstance(how, Exception):
                raise how
            return {"status": how}
        return super().evaluate(js, arg)


def statement(token, created):
    return {"identifier": token, "created": created, "name": "Invented Pharmacy EOB"}


def unreadable(created="2026-03-04"):
    row = claim_row(claim_number="9000000AA0007", eob_id="Z_" + "6a" * 95)
    for e in row["claim"][0]["identifier"]:
        e.pop("display")
    row["created"] = row["checkDate"] = created
    return row


# -- a claim type whose list did not come ------------------------------------

@pytest.mark.parametrize("how, said", [
    (500, "status 500"), (429, "status 429"), (None, "status None"),
    (RuntimeError("TypeError: " + PAGE_WORDS), "RuntimeError"),
    (TimeoutError("Timeout 30000ms exceeded " + PAGE_WORDS), "TimeoutError"),
])
def test_a_claim_type_whose_list_did_not_come_is_named_by_its_type(monkeypatch, caplog, how,
                                                                    said):
    signed_in(monkeypatch)
    with caplog.at_level(logging.WARNING):
        rows = site.collect_documents(Partly({"Medical": [claim_row()]}, {"Pharmacy": how}))
    assert [r["doc_id"] for r in rows] == [EOB]
    assert rows.unlisted == ["Pharmacy"]
    assert "Pharmacy EOB list did not come (%s)" % said in caplog.text
    assert PAGE_WORDS not in caplog.text


def test_a_sign_in_still_stops_the_listing_at_once(monkeypatch):
    signed_in(monkeypatch)
    with pytest.raises(site.SessionExpired):
        site.collect_documents(Partly({"Medical": [claim_row()]}, {"Pharmacy": 401}))


def test_a_download_whose_claim_types_list_did_not_come_asks_for_nothing(monkeypatch, tmp_path):
    signed_in(monkeypatch)
    page = Partly({"Medical": [claim_row()]}, {"Medical": 500})
    assert site.download_document(page, EOB, tmp_path / "eob.pdf") is False
    assert page.downloads == []


@pytest.fixture
def run(tmp_path, monkeypatch):
    """The app's own Discover with the flags and settings given."""
    signed_in(monkeypatch)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"

    def ran(page, *flags, **settings):
        cfg.write_text(json.dumps(dict(config, **settings)), encoding="utf-8")
        app = app_mod.App(app_mod.build_parser().parse_args(
            ["--config", str(cfg), "--discover", *flags]))
        app.page = lambda: page
        app.check_session = lambda *_a, **_kw: None
        app.stats["mode"] = "discover"
        app.cmd_discover(quiet=True)
        return app
    return ran


def failure_text(app):
    return "".join(p.read_text(encoding="utf-8") for p in Path(app.paths.diagnostics).rglob("*")
                   if p.is_file() and "failure" in p.name)


@pytest.mark.parametrize("how", [500, RuntimeError("TypeError: " + PAGE_WORDS)])
def test_discover_counts_a_claim_type_whose_list_did_not_come_as_failed(run, capsys, how):
    app = run(Partly({"Medical": [claim_row()]}, {"Pharmacy": how}))
    assert {r["document_id"] for r in app.discovery.data.values()} == {EOB}
    assert app.stats["failed"] == 1
    assert listing.last(app) == listing.STOPPED
    said = capsys.readouterr().out
    assert "Anthem's Pharmacy EOB list did not come" in said and PAGE_WORDS not in said
    text = failure_text(app)
    assert "a claim type list was not read" in text and PAGE_WORDS not in text


def test_a_claim_type_whose_list_did_not_come_ends_the_run_unclean(tmp_path, monkeypatch):
    signed_in(monkeypatch)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9"})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    page = Partly({"Medical": [claim_row()]}, {"Chiropractic": 503})
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "check_session", lambda *_a, **_kw: None)
    assert app_mod.main(["--config", str(cfg), "--discover"]) == 1


def test_a_claim_type_the_run_takes_no_eob_of_is_not_counted(run):
    page = Partly({"Medical": [claim_row()]}, {"Pharmacy": 500})
    app = run(page, document_types=["Tax Document"])
    assert not app.stats["failed"]
    assert listing.last(app) == listing.COMPLETE


# -- only inside the run's dates ---------------------------------------------

PAIR_2025 = [statement("aa" * 86, "2025-01-01"), statement("bb" * 86, "2025-01-01")]


@pytest.mark.parametrize("flags, settings", [
    (("--year", "2026"), {}),
    (("--start-date", "2025-06-01"), {}),
    (("--end-date", "2024-12-31"), {}),
    ((), {"default_start_date": "2025-06-01"}),
])
def test_two_statements_outside_the_runs_dates_leave_the_list_whole(run, capsys, flags, settings):
    app = run(FakePage({"Medical": [claim_row()], "Pharmacy": PAIR_2025}), *flags, **settings)
    assert not app.stats.get("alike")
    assert listing.last(app) != listing.STOPPED
    assert "statements dated" not in capsys.readouterr().out


def test_two_statements_inside_the_runs_dates_leave_it_not_whole(run):
    app = run(FakePage({"Medical": [claim_row()], "Pharmacy": PAIR_2025}), "--year", "2025")
    assert app.stats["alike"] == 2
    assert listing.last(app) == listing.STOPPED


@pytest.mark.parametrize("flags, settings", [
    (("--year", "2026"), {}),
    ((), {"default_start_date": "2026-01-01"}),
])
def test_a_row_it_cannot_read_outside_the_runs_dates_is_not_counted(run, flags, settings):
    app = run(FakePage({"Medical": [claim_row(), unreadable("2025-05-05")]}), *flags, **settings)
    assert not app.stats["failed"]
    assert listing.last(app) != listing.STOPPED


def test_a_row_it_cannot_read_inside_the_runs_dates_is_counted(run):
    app = run(FakePage({"Medical": [claim_row(), unreadable("2026-05-05")]}), "--year", "2026")
    assert app.stats["failed"] == 1
    assert listing.last(app) == listing.STOPPED


def test_a_row_with_no_day_it_can_read_is_counted_in_a_scoped_run(run):
    row = unreadable()
    for key in ("created", "checkDate"):
        row.pop(key)
    app = run(FakePage({"Medical": [claim_row(), row]}), "--year", "2026")
    assert app.stats["failed"] == 1
    assert listing.last(app) == listing.STOPPED


# -- what Discover says of two statements ------------------------------------

def test_what_is_said_of_two_statements_is_true_when_one_was_saved_before(run, capsys):
    pair = [statement("aa" * 86, "2026-03-01"), statement("bb" * 86, "2026-03-01")]
    first = run(FakePage({"Pharmacy": pair[:1]}))
    key = "id:Pharmacy|20260301|Statement|0"
    first.progress.update(key, dict(first.discovery.get(key), state="Completed",
                                    downloaded_ok=True, pdf_path="/invented/saved.pdf"))
    first.progress.save()
    capsys.readouterr()
    run(FakePage({"Pharmacy": pair}))
    said = capsys.readouterr().out
    assert "2 Pharmacy statements dated 2026-03-01" in said
    assert "this run fetches none of them" in said
    assert "an earlier run saved is kept as it is" in said
    assert "none of them is saved" not in said


def test_what_is_said_of_two_statements_none_saved_before(run, capsys):
    pair = [statement("aa" * 86, "2026-03-01"), statement("bb" * 86, "2026-03-01")]
    run(FakePage({"Pharmacy": pair}))
    said = capsys.readouterr().out
    assert "this run fetches none of them" in said
    assert "earlier run saved" not in said
