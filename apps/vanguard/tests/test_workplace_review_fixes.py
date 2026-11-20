"""Fixes from the independent review of #234.

Each test failed on cc4dead5 for the reason it names and passes with the
fix. Every plan, account and period is invented."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vanguard_docs as docs
import vanguard_site as site
from paperpull_core import shared_folder
from paperpull_core.testkit import text_pdf
from test_workplace_statements import END, PLAN, START, WorkplacePage
from test_downloads_and_names import _app

API = "https://personal1.vanguard.com/usa/api/lah-statements-consumer/statements/consumer"


# -- 1. the year the page loads with, asked for with no year= -------------------

class _Brokerage:
    url = site.URLS["documents"]

    def __init__(self, load_url):
        self.load_url = load_url
        self.listener = None

    def on(self, _event, listener):
        self.listener = listener

    def answer(self, url, body=b'{"statements": []}'):
        self.listener(SimpleNamespace(url=url, ok=True, headers={}, body=lambda: body))

    def reload(self, **_kw):
        if self.load_url is None:
            return
        self.answer(self.load_url, json.dumps({"statements": [{
            "statementId": "NEWEST", "accountId": "10001111", "accountNumber": "1111",
            "endDate": "2032-04-30", "statementDescription": "Synthetic Brokerage 1111"}]}).encode())

    def wait_for_timeout(self, _ms):
        pass

    def remove_listener(self, _event, _listener):
        self.listener = None


def _brokerage_discover(tmp_path, monkeypatch, load_url, older_url):
    app = _app(tmp_path)
    page = _Brokerage(load_url)
    app.page = lambda: page
    app.check_session = lambda _p: None
    app.write_failure = lambda *_: None
    visited = []
    monkeypatch.setattr(site, "ensure_statements", lambda _p: True)
    monkeypatch.setattr(site, "year_options", lambda _p: ["2032", "2031"])
    # The picker shows the year the page loaded with. Choosing it again
    # makes the page ask nothing, as a page holding that year's answer does.
    monkeypatch.setattr(site, "_year_select",
                        lambda _p: SimpleNamespace(evaluate=lambda _js: "2032"))

    def select(_p, year):
        visited.append(year)
        if year == "2031":
            page.answer(older_url)
        return True

    monkeypatch.setattr(site, "select_year", select)
    return app, visited


def test_the_load_answer_with_no_year_counts_for_the_year_the_picker_shows(tmp_path, monkeypatch):
    app, visited = _brokerage_discover(tmp_path, monkeypatch, API, API + "?year=2031")
    assert app.cmd_discover(quiet=True) == 1
    assert visited == ["2031"]
    assert json.loads(app.paths.last_listing.read_text())["complete"] is True


def test_an_answer_with_no_year_during_the_walk_still_answers_no_year(tmp_path, monkeypatch):
    # The control. Only the answer the page loads with is the shown year's.
    app, visited = _brokerage_discover(tmp_path, monkeypatch, API + "?year=2032", API)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert visited == ["2031"]
    assert json.loads(app.paths.last_listing.read_text())["complete"] is False


def test_a_page_that_answers_nothing_on_load_still_needs_the_shown_years_answer(tmp_path, monkeypatch):
    # The control. The shown year counts as answered only when an answer came.
    app, visited = _brokerage_discover(tmp_path, monkeypatch, None, API + "?year=2031")
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert visited == ["2032", "2031"]
    assert json.loads(app.paths.last_listing.read_text())["complete"] is False


# -- 2. one plan's statements that end on one day ------------------------------

def _workplace_row(start, end=END):
    return {"account": f"Vanguard Workplace Plan {PLAN}", "account_id": PLAN, "last4": PLAN[-4:],
            "date": end, "period": end[:7], "title": f"Account Statement - Vanguard Workplace Plan {PLAN}",
            "category": "Statement", "statement_id": f"workplace-{start}-{end}",
            "document_id": f"workplace-{start}-{end}", "doc_type": site.WORKPLACE_STATEMENT,
            "occurrence": 0, "ambiguous": False}


def _discover_rows(tmp_path, monkeypatch, app, rows):
    page = SimpleNamespace(url=f"https://ownyourfuture.vanguard.com/main/manage?planId={PLAN}")
    app.page = lambda: page
    app.check_session = lambda _p: None
    monkeypatch.setattr(site, "ensure_statements", lambda _p: True)
    monkeypatch.setattr(site, "collect_documents", lambda _p, keep=None: [dict(r) for r in rows])
    app.cmd_discover(quiet=True)
    return {k: r["document_id"] for k, r in app.discovery.data.items()}


def test_statements_ending_on_one_day_keep_their_records_when_the_list_turns(tmp_path, monkeypatch):
    app = _app(tmp_path)
    quarter, year = _workplace_row("2032-01-01"), _workplace_row("2031-04-01")
    first = _discover_rows(tmp_path, monkeypatch, app, [quarter, year])
    assert len(first) == 2
    assert _discover_rows(tmp_path, monkeypatch, app, [year, quarter]) == first
    # A third that ends that day too takes a number of its own.
    third = _workplace_row("2031-10-01")
    after = _discover_rows(tmp_path, monkeypatch, app, [third, year, quarter])
    assert {k: v for k, v in after.items() if k in first} == first
    assert sorted(after.values()) == sorted([*first.values(), third["document_id"]])


def test_a_new_period_never_takes_the_number_of_one_this_list_left_out(tmp_path, monkeypatch):
    app = _app(tmp_path)
    quarter, year = _workplace_row("2032-01-01"), _workplace_row("2031-04-01")
    first = _discover_rows(tmp_path, monkeypatch, app, [quarter, year])
    third = _workplace_row("2031-10-01")
    after = _discover_rows(tmp_path, monkeypatch, app, [third, quarter])
    assert {k: v for k, v in after.items() if k in first} == first
    assert len(after) == 3 and third["document_id"] in after.values()


def test_brokerage_numbering_is_as_it_was(tmp_path, monkeypatch):
    # The control. Two brokerage rows of one title and date take #0 and #1
    # with no id, and a row left keeps the number its record holds.
    app = _app(tmp_path)
    row = {"account": "Synthetic Brokerage 1111", "account_id": "10001111", "last4": "1111",
           "date": END, "period": END[:7], "title": "Account Statement - Synthetic Brokerage 1111",
           "category": "Statement", "statement_id": "", "doc_type": "Statement", "occurrence": 0}
    keys = _discover_rows(tmp_path, monkeypatch, app, [row, dict(row)])
    assert len(keys) == 2 and any(k.endswith("#1") for k in keys) and set(keys.values()) == {""}
    del app.discovery.data[next(k for k in keys if not k.endswith("#1"))]
    after = _discover_rows(tmp_path, monkeypatch, app, [dict(row)])
    assert list(after) == [k for k in keys if k.endswith("#1")]


# -- 3. Resume on the other portal's tab ---------------------------------------

def test_resume_on_a_brokerage_tab_says_the_workplace_statements_still_wait(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    app._record_vanguard_doc(_workplace_row(START), set())
    app.page = lambda: SimpleNamespace(url=site.URLS["documents"])
    monkeypatch.setattr(docs.listing, "last", lambda _a: docs.listing.COMPLETE)
    app.process = lambda left, dry_run=False: pytest.fail("nothing here is this portal's")
    app.cmd_resume()
    said = capsys.readouterr().out
    assert "everything in scope is complete" not in said
    assert "1 statement waits for another Vanguard portal or plan" in said
    assert PLAN not in said


# -- 4. a workplace tab with no plan is not a brokerage run's tab ----------------

def test_a_brokerage_run_does_not_take_a_workplace_tab_with_no_plan(monkeypatch):
    app = _app()
    app.config["output_dir"] = "."
    workplace = SimpleNamespace(is_closed=lambda: False, url="https://ownyourfuture.vanguard.com/main/dashboard",
                                evaluate=lambda _js: "")
    brokerage = SimpleNamespace(is_closed=lambda: False, url="https://investor.vanguard.com/home")
    app.browser = lambda: SimpleNamespace(pages=[workplace, brokerage])
    app._cdp_mode = True
    app._requests = object()
    monkeypatch.setattr(docs.capture, "clear_archived_copies", lambda *_: None)
    monkeypatch.setattr(site, "_brokerage_statements_portal", lambda _p: False)
    assert app.page() is brokerage


# -- 5. a tab that moves while its plan is read ----------------------------------

def test_a_tab_that_moves_while_its_plan_is_read_stops_as_an_unread_list():
    page = WorkplacePage()

    def moved(_js):
        raise RuntimeError("Execution context was destroyed")

    page.evaluate = moved
    assert site.workplace_plan(page) == ""
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert page.requests == []


# -- 6. a write that stops half way -----------------------------------------------

def test_a_write_that_stops_half_way_leaves_nothing_under_the_statements_name(tmp_path, monkeypatch):
    page = WorkplacePage()
    page.pdf = {"0": text_pdf([f"Plan {PLAN}", "January 1, 2032 through March 31, 2032"])}
    doc = site.collect_documents(page)[0]

    def half(path, data):
        Path(path).write_bytes(data[: len(data) // 2])
        raise OSError("the disk filled")

    monkeypatch.setattr(shared_folder, "write_bytes", half)
    out = tmp_path / "statement.pdf"
    try:
        saved = site.download_document(page, PLAN, False, doc["doc_type"], doc["title"], END, out,
                                       document_id_hint=doc["document_id"])
    except OSError:
        saved = "raised"
    assert saved is False
    assert not out.exists()
