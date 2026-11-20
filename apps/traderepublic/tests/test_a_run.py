"""Login, Discover, a run, Resume and Diagnose, through the real App over a
stand-in tab. Every value is invented."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fakes  # noqa: E402
from _fakes import (CANARY_ACCOUNT, CANARY_TEXT, FakeTab, all_text, body,  # noqa: E402
                    every_file, make_app, pdf_answer, statement, status)
import traderepublic_docs as app_mod  # noqa: E402
import traderepublic_site as site  # noqa: E402
from paperpull_core import listing  # noqa: E402
from paperpull_core.models import State  # noqa: E402
from paperpull_core.testkit import sample_pdf  # noqa: E402

T0 = date(2026, 11, 20)
THREE = ("2026-10", "2026-09", "2026-08")


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(site, "today", lambda: T0)


def right(*periods):
    return {p: pdf_answer(statement(p)) for p in periods}


def state(app, period):
    return (app.progress.get("id:" + period) or {}).get("state")


def pdfs(app):
    return sorted(p.name for p in every_file(app.paths.root) if p.suffix == ".pdf")


def run(app, *how):
    with pytest.raises(SystemExit) as stop:
        how[0](*how[1:])
    return stop.value


# -- Login ------------------------------------------------------------------------

def test_login_says_success_only_after_a_statement_answered(tmp_path, capsys):
    tab = FakeTab(right("2026-10"))
    make_app(tmp_path, tab, "--login").cmd_login()
    said = capsys.readouterr().out
    assert "Success" in said and tab.asked == ["2026-10"]
    assert tab.queries[0][2] == {"fromDate": ["2026-10-01"], "toDate": ["2026-10-31"]}
    assert not pdfs(make_app(tmp_path, tab))


@pytest.mark.parametrize("answers, words", [
    ({"2026-10": status(401)}, "not signed in"),
    ({"2026-10": status(403)}, "not signed in"),
    ({"2026-10": status(429)}, "limiting"),
    ({}, "Could not confirm"),
    ({p: body(b"<html><input type=password>PPCANARYHTML</html>") for p in THREE}, "Could not confirm"),
    ({p: body(b'{"errorCode":"PPCANARYJSON"}', "application/json") for p in THREE}, "Could not confirm"),
    ({p: RuntimeError("TypeError: Failed to fetch") for p in THREE}, "Could not confirm"),
])
def test_login_never_says_success_without_a_statement(tmp_path, capsys, answers, words):
    tab = FakeTab(answers)
    make_app(tmp_path, tab, "--login").cmd_login()
    said = capsys.readouterr().out
    assert "Success" not in said and words in said
    assert "PPCANARY" not in said
    assert len(tab.asked) <= 3


@pytest.mark.parametrize("url", ["https://app.traderepublic.com/settings",
                                 "https://app.traderepublic.com/login"])
def test_login_off_the_home_page_asks_nothing(tmp_path, capsys, url):
    tab = FakeTab(right("2026-10"), url=url)
    make_app(tmp_path, tab, "--login").cmd_login()
    said = capsys.readouterr().out
    assert "Success" not in said and tab.asked == []


# -- Discover -----------------------------------------------------------------------

def test_discover_records_every_month_in_reach_once_a_statement_answered(tmp_path):
    tab = FakeTab(right("2026-10"))
    app = make_app(tmp_path, tab, "--discover")
    assert app.cmd_discover() == 36
    keys = sorted(app.discovery.data)
    assert keys[0] == "id:2023-11" and keys[-1] == "id:2026-10" and len(keys) == 36
    rec = app.discovery.get("id:2024-02")
    assert (rec["document_id"], rec["period"], rec["date"]) == ("2024-02", "2024-02", "2024-02-29")
    assert listing.last(app) == listing.COMPLETE
    assert tab.asked == ["2026-10"]
    # A second Discover adds nothing and leaves states as they were.
    app.discovery.update("id:2026-09", {"state": State.FAILED.value})
    assert app.cmd_discover() == 0
    assert app.discovery.get("id:2026-09")["state"] == State.FAILED.value


@pytest.mark.parametrize("answers", [{"2026-10": status(401)}, {}, {"2026-10": status(429)}])
def test_discover_records_nothing_without_a_proven_session(tmp_path, answers):
    tab = FakeTab(answers)
    app = make_app(tmp_path, tab, "--discover")
    run(app, app.cmd_discover)
    assert not app.discovery.data
    assert listing.last(app) == listing.STOPPED


def test_discover_keeps_to_the_start_date_floor(tmp_path):
    tab = FakeTab(right("2026-10"))
    app = make_app(tmp_path, tab, "--discover", default_start_date="2025-03-31")
    app.cmd_discover()
    assert "id:2025-03" in app.discovery.data and "id:2025-02" not in app.discovery.data
    app2 = make_app(tmp_path / "b", tab, "--discover", default_start_date="2025-04-01")
    app2.cmd_discover()
    assert "id:2025-03" not in app2.discovery.data


@pytest.mark.parametrize("url", ["https://app.traderepublic.com/settings",
                                 "https://example.test/boards"])
def test_discover_from_a_tab_off_the_home_page_stops_with_nothing_asked(tmp_path, url):
    tab = FakeTab(right("2026-10"), url=url)
    app = make_app(tmp_path, tab, "--discover")
    run(app, app.cmd_discover)
    assert tab.asked == [] and not app.discovery.data


# -- a run --------------------------------------------------------------------------

def pilot(tmp_path, answers, *argv):
    tab = FakeTab(answers)
    app = make_app(tmp_path, tab, "--pilot", *argv)
    app.stats["mode"] = "pilot"
    return app, tab


def test_a_pilot_saves_the_three_newest_months(tmp_path):
    app, tab = pilot(tmp_path, right(*THREE))
    app.cmd_pilot()
    assert [state(app, p) for p in THREE] == [State.COMPLETED.value] * 3
    assert tab.asked == ["2026-10", "2026-10", "2026-09", "2026-08"]
    assert pdfs(app) == ["2026-08-31 Trade Republic Account Statement.pdf",
                         "2026-09-30 Trade Republic Account Statement.pdf",
                         "2026-10-31 Trade Republic Account Statement.pdf"]
    assert tab.navigated == 0


@pytest.mark.parametrize("answer", [
    status(404), status(204, ""), body(b""), status(500),
    body(b"<html><input type=password>PPCANARYHTML</html>"),
    body(b'{"errors":[{"errorMessage":"PPCANARYJSON"}]}', "application/json"),
    RuntimeError("TypeError: Failed to fetch"),
    body(b"<html>x</html>", "application/pdf"),
], ids=["404", "204", "empty", "500", "html", "json", "fetch-failed", "html-as-pdf"])
def test_a_month_with_no_statement_is_recorded_and_the_run_goes_on(tmp_path, answer):
    answers = right("2026-10", "2026-08")
    answers["2026-09"] = answer
    app, tab = pilot(tmp_path, answers)
    app.cmd_pilot()
    rec = app.progress.get("id:2026-09")
    assert rec["state"] == State.FAILED.value and rec["notes"] == app_mod.NO_STATEMENT_NOTE
    assert app.stats["no_statement"] == 1 and app.stats["failed"] == 1
    assert state(app, "2026-08") == State.COMPLETED.value
    assert not app._already_done(app_mod.Document.from_dict(rec))
    assert not any("2026-09-30" in name for name in pdfs(app))
    assert "PPCANARY" not in all_text(app.paths.root)


def test_a_month_with_no_statement_is_asked_again_and_saved_next_time(tmp_path):
    answers = right("2026-10", "2026-08")
    answers["2026-09"] = status(404)
    app, tab = pilot(tmp_path, answers)
    app.cmd_pilot()
    tab.answers["2026-09"] = pdf_answer(statement("2026-09"))
    tab.asked.clear()
    app2 = make_app(tmp_path, tab, "--pilot")
    app2.stats["mode"] = "pilot"
    app2.cmd_pilot()
    assert tab.asked == ["2026-10", "2026-09"]
    rec = app2.progress.get("id:2026-09")
    assert rec["state"] == State.COMPLETED.value and rec["notes"] == ""
    assert app2.stats["no_statement"] == 0


@pytest.mark.parametrize("code", [401, 403])
def test_a_sign_out_stops_the_run_with_the_month_left_for_resume(tmp_path, code):
    answers = right(*THREE)
    answers["2026-09"] = status(code)
    app, tab = pilot(tmp_path, answers)
    run(app, app.cmd_pilot)
    assert state(app, "2026-10") == State.COMPLETED.value
    assert state(app, "2026-09") == State.DISCOVERED.value
    assert state(app, "2026-08") is None
    assert tab.asked == ["2026-10", "2026-10", "2026-09"]
    # Resume carries on from the month it stopped at, and only that far.
    tab.answers["2026-09"] = pdf_answer(statement("2026-09"))
    tab.asked.clear()
    again = make_app(tmp_path, tab, "--resume")
    again.stats["mode"] = "resume"
    again.cmd_resume()
    assert "2026-10" not in tab.asked and tab.asked[:2] == ["2026-09", "2026-08"]
    assert state(again, "2026-09") == State.COMPLETED.value


def test_a_limit_stops_the_run_with_the_month_pending(tmp_path, capsys):
    answers = right(*THREE)
    answers["2026-09"] = status(429)
    app, tab = pilot(tmp_path, answers)
    run(app, app.cmd_pilot)
    assert "limiting" in capsys.readouterr().out
    assert state(app, "2026-09") is None and state(app, "2026-08") is None
    # Noted as a run that stopped, so neither it nor a Resume reads as whole.
    assert listing.last(app) == listing.STOPPED
    assert tab.asked.count("2026-09") == 1 and "2026-08" not in tab.asked


def test_a_tab_closed_mid_run_stops_with_the_month_pending(tmp_path):
    answers = right(*THREE)

    def close(t):
        t.closed = True
        raise RuntimeError("Target closed")
    answers["2026-09"] = close
    app, tab = pilot(tmp_path, answers)
    run(app, app.cmd_pilot)
    assert state(app, "2026-09") is None and app.stats["no_statement"] == 0


def test_a_tab_moved_off_the_home_page_stops_before_the_next_month(tmp_path):
    answers = right(*THREE)
    app, tab = pilot(tmp_path, answers)

    def move(t):
        t.url = "https://app.traderepublic.com/settings"
        return pdf_answer(statement("2026-10"))
    calls = {"n": 0}

    def first_then_move(t):
        calls["n"] += 1
        if calls["n"] == 2:
            return move(t)
        return pdf_answer(statement("2026-10"))
    tab.answers["2026-10"] = first_then_move
    run(app, app.cmd_pilot)
    assert state(app, "2026-10") == State.COMPLETED.value
    assert "2026-09" not in tab.asked and state(app, "2026-09") is None


@pytest.mark.parametrize("pdf, outcome", [
    (lambda: statement("2026-08"), "refused"),
    (lambda: statement("2026-09", days=("01.09.2026", "15.09.2026")), "unchecked"),
    (lambda: sample_pdf(), "unreadable"),
])
def test_a_pdf_that_is_not_this_month_is_never_written(tmp_path, pdf, outcome):
    answers = right("2026-10", "2026-08")
    answers["2026-09"] = pdf_answer(pdf())
    app, tab = pilot(tmp_path, answers)
    app.cmd_pilot()
    assert state(app, "2026-09") == State.FAILED.value
    assert not any("2026-09-30" in name for name in pdfs(app))
    assert not any(p.suffix in (".pdf", ".part", ".tmp") and "2026-09" in p.name
                   for p in every_file(app.paths.root))
    assert app.stats["no_statement"] == 0
    assert bool(app.stats.get("wrong_document")) == (outcome == "refused")
    failure = [p for p in every_file(app.paths.diagnostics) if p.name.startswith("failure-")]
    assert failure, "no failure file for a refused statement"
    text = failure[0].read_text(encoding="utf-8")
    assert outcome in text
    for value in (CANARY_TEXT, CANARY_ACCOUNT, "30.09.2026", "01.08.2026"):
        assert value not in text


def test_an_interrupt_leaves_the_month_untried_and_resumable(tmp_path):
    answers = right(*THREE)
    answers["2026-09"] = KeyboardInterrupt()
    app, tab = pilot(tmp_path, answers)
    with pytest.raises(KeyboardInterrupt):
        app.cmd_pilot()
    assert state(app, "2026-10") == State.COMPLETED.value
    assert state(app, "2026-09") is None


def test_a_deleted_statement_is_not_asked_again(tmp_path):
    app, tab = pilot(tmp_path, right(*THREE))
    app.cmd_pilot()
    for p in every_file(app.paths.root):
        if p.suffix == ".pdf":
            p.unlink()
    tab.asked.clear()
    again = make_app(tmp_path, tab, "--pilot")
    again.stats["mode"] = "pilot"
    again.cmd_pilot()
    assert tab.asked == ["2026-10"]


def test_a_dry_run_asks_only_for_the_session_proof(tmp_path):
    tab = FakeTab(right(*THREE))
    app = make_app(tmp_path, tab, "--dry-run")
    app.cmd_run("dry-run")
    assert tab.asked == ["2026-10"] and not pdfs(app)


def test_a_month_past_reach_is_not_asked(tmp_path, monkeypatch, capsys):
    tab = FakeTab(right("2026-10"))
    app = make_app(tmp_path, tab, "--discover")
    app.cmd_discover()
    monkeypatch.setattr(site, "today", lambda: date(2026, 12, 20))
    later = make_app(tmp_path, tab, "--resume")
    assert "id:2023-11" not in [d.key for d in later._select()]
    assert "past the 1100 days" in capsys.readouterr().out


def test_nothing_leaves_in_the_run_files(tmp_path, caplog, capsys):
    caplog.set_level("DEBUG")
    answers = right("2026-10")
    answers["2026-09"] = body(b"<html>PPCANARYHTML</html>")
    answers["2026-08"] = pdf_answer(statement("2026-07"))
    app, tab = pilot(tmp_path, answers)
    app.cmd_pilot()
    app.write_run_summary()
    text = all_text(app.paths.root) + caplog.text + capsys.readouterr().out
    for value in ("PPCANARY", CANARY_ACCOUNT, "fromDate", "toDate", "api.traderepublic.com/api"):
        assert value not in text, value


# -- Diagnose -------------------------------------------------------------------------

def diagnose(tmp_path, tab):
    app = make_app(tmp_path, tab, "--diagnose")
    app.cmd_diagnose()
    return json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))


def test_diagnose_reports_what_the_newest_statement_holds_as_counts(tmp_path, capsys):
    found = diagnose(tmp_path, FakeTab(right("2026-10")))
    asked = found["newest_months_asked"]
    assert found["statements_read"] == 1 and found["on_home_page"] is True
    assert asked[0]["answer"] == "pdf" and asked[0]["status_class"] == "2xx"
    assert asked[0]["first_day_found"] is True and asked[0]["last_day_found"] is True
    assert asked[0]["dates_day_month_year"] == 2
    said = capsys.readouterr().out
    assert "Attach diagnose-documents.json" in said
    flat = json.dumps(found)
    for value in (CANARY_TEXT, "DE00", "31.10.2026", "fromDate"):
        assert value not in flat


def test_diagnose_signed_out_says_so(tmp_path):
    found = diagnose(tmp_path, FakeTab({"2026-10": status(401)}))
    assert found["signed_out"] is True and found["statements_read"] == 0
    assert found["newest_months_asked"][0]["status_class"] == "4xx"


def test_diagnose_html_is_not_a_sign_out(tmp_path):
    found = diagnose(tmp_path, FakeTab({p: body(b"<html>PPCANARYHTML</html>") for p in THREE}))
    assert found["signed_out"] is False and len(found["newest_months_asked"]) == 3
    assert "PPCANARY" not in json.dumps(found)


def test_diagnose_off_the_home_page_asks_nothing(tmp_path, capsys):
    tab = FakeTab(right("2026-10"), url="https://app.traderepublic.com/settings")
    found = diagnose(tmp_path, tab)
    assert tab.asked == [] and found["on_home_page"] is False
    assert "nothing was asked" in capsys.readouterr().out
