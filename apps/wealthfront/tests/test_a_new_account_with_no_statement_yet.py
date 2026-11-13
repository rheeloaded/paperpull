"""A new account with no statement yet is told why its runs stop.

Wealthfront shows a new account no statement until it posts the first one.
Nothing PaperPull has seen of the Documents page tells that apart from a
page still drawing, since no page from an account with none has been seen,
so such an account's runs still stop until its first statement, as a page
still drawing must. They used to end saying to run again later, which
stopped again the same way. Now the stop says that a new account stops
there on every run until its first statement, that nothing needs fixing,
and what to do when the page in the browser does show one.

An account that has listed a statement before is told to run again, as
before, since its page showing none is a page that did not draw. Driven in
a real browser against a made-up page. Every label on it is invented or
Wealthfront's own general words.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import wealthfront_docs as app_mod
import wealthfront_site as site
from paperpull_core import listing
from paperpull_core.run_reporting import MARK_ENV

PAGE = """<!doctype html><html><body>
<select name="selectedDocumentType"><option value="VIEW_ALL">All Document Types</option>%s</select>
<table><tbody></tbody></table></body></html>"""

STATEMENTS = "<option>Statements</option>"
QUARTERLY = "<option>Quarterly Statements</option>"
TRADES = "<option>Trade Confirmations</option>"

NEW_ACCOUNT = "as on a new account before Wealthfront posts its first statement"
EVERY_RUN = "A new account stops here on every run until then"
RUN_AGAIN = "Run it again later to read the rest."
# What a page that did not open said before, and still says to an account
# that has listed a statement or wants none.
OLD_UNOPENED = ("Could not open the Documents page. Run --diagnose. If it shows no documents "
                "yet, there is nothing to download until the first one is posted.")


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    shortened = pg.wait_for_timeout
    pg.wait_for_timeout = lambda ms: shortened(min(ms, 50))
    yield pg
    browser.close()
    driver.stop()


@pytest.fixture
def make_app(tmp_path, monkeypatch, page):
    pressed = []
    monkeypatch.delenv(MARK_ENV, raising=False)

    def build(*argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, _name: pressed.append(doc.summary))
        return app

    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "collect_documents", lambda pg: [])
    build.pressed = pressed
    return build


# An invented statement of each kind, the one the dropdown shows.
SHOWN = {"Statements": "Monthly Statement", "Quarterly Statements": "Quarterly Statement"}


def statement_rows(pg):
    """One statement of the kind the dropdown is on, none for any other."""
    sel = pg.locator("select")
    title = SHOWN.get(sel.input_value()) if sel.count() else None
    return [site.RawDoc(title=title, date_text="06/30/2031", kind="dated",
                        href="https://www.wealthfront.com/documents/invented",
                        text="06/30/2031 %s" % title)] if title else []


def failures(tmp_path):
    return list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def run_all_stops(app):
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert listing.last(app) == listing.STOPPED


@pytest.mark.parametrize("kinds", [STATEMENTS + TRADES, TRADES],
                         ids=["Statements chosen shows none", "no Statements on the dropdown"])
def test_a_new_account_with_no_statement_still_stops_and_is_told_why(make_app, page, tmp_path,
                                                                     capsys, kinds):
    """Its dropdown lists Statements and shows none once chosen, or lists
    no Statements at all, either of which a page still drawing looks like
    too. The run stops as before, and says why it will on every run until
    the first statement, and what to do."""
    page.set_content(PAGE % kinds)
    app = make_app("--all")
    run_all_stops(app)
    out = said(capsys)
    assert "No statement showed, " + NEW_ACCOUNT in out
    assert EVERY_RUN in out and "nothing needs fixing" in out
    assert "The first run after the statement is posted reads it." in out
    assert ("If Wealthfront's Documents page in the browser window does show a statement, "
            "run it again. If it stops here again, run paperpull wealthfront diagnose and "
            "attach the survey file it saves to the Wealthfront issue on GitHub.") in out
    assert RUN_AGAIN not in out
    assert len(failures(tmp_path)) == 1 and make_app.pressed == []


def test_under_the_panel_it_names_the_report_button(make_app, page, monkeypatch, capsys):
    page.set_content(PAGE % (STATEMENTS + TRADES))
    monkeypatch.setenv(MARK_ENV, "0" * 32)
    run_all_stops(make_app("--all"))
    out = said(capsys)
    assert EVERY_RUN in out
    assert ("If it stops here again, press Make the report (More, then Get help) and attach "
            "the survey file it saves") in out
    assert "paperpull wealthfront diagnose" not in out


def test_a_discover_and_a_pilot_say_it_too(make_app, page, capsys):
    page.set_content(PAGE % (STATEMENTS + TRADES))
    for argv, command in (("--discover", "cmd_discover"), ("--pilot", "cmd_pilot")):
        app = make_app(argv)
        with pytest.raises(SystemExit):
            getattr(app, command)()
        assert listing.last(app) == listing.STOPPED
        assert EVERY_RUN in said(capsys), argv


def test_a_documents_page_that_showed_no_document_says_a_new_account_stops_there(
        make_app, page, monkeypatch, capsys):
    """A new account with no document of any kind lists nothing at all,
    which a page that did not load looks like too."""
    page.set_content(PAGE % "")
    monkeypatch.setattr(site, "goto_documents", lambda pg: False)
    app = make_app("--all")
    run_all_stops(app)
    out = said(capsys)
    assert "Could not open the Documents page." in out
    assert "It showed no document, " + NEW_ACCOUNT in out
    assert EVERY_RUN in out
    assert "does show a document, run it again." in out


def test_an_account_that_listed_a_statement_before_is_told_to_run_again(make_app, page,
                                                                        monkeypatch, capsys):
    """Its page showing none now is a page that did not draw, not a new
    account, so it is told what it was told before."""
    page.set_content(PAGE % (STATEMENTS + TRADES))
    monkeypatch.setattr(site, "collect_documents", statement_rows)
    app = make_app("--all")
    app.cmd_run("all")
    assert listing.last(app) == listing.COMPLETE and make_app.pressed == ["Monthly Statement"]
    capsys.readouterr()

    monkeypatch.setattr(site, "collect_documents", lambda pg: [])
    run_all_stops(make_app("--all"))
    out = said(capsys)
    assert RUN_AGAIN in out and "new account" not in out

    monkeypatch.setattr(site, "goto_documents", lambda pg: False)
    run_all_stops(make_app("--all"))
    out = said(capsys)
    assert OLD_UNOPENED in out and "new account" not in out


def test_a_history_moved_here_with_a_statement_saved_is_no_new_account(make_app, page, capsys):
    """Export and Import history bring the saved records alone, so a
    statement saved on another computer counts as well."""
    page.set_content(PAGE % (STATEMENTS + TRADES))
    app = make_app("--all")
    app.progress.update("Statement:2031-06-30:Monthly Statement", {
        "category": "Statement", "date": "2031-06-30", "title": "Monthly Statement",
        "state": "Completed", "downloaded_ok": True})
    assert app.discovery.data == {}
    run_all_stops(app)
    out = said(capsys)
    assert RUN_AGAIN in out and "new account" not in out


def test_a_list_cut_short_with_a_statement_read_says_nothing_of_a_new_account(
        make_app, page, monkeypatch, capsys):
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    monkeypatch.setattr(site, "collect_documents", statement_rows)
    real = site.set_document_type
    monkeypatch.setattr(site, "set_document_type", lambda pg, kind: False if (
        kind == "Quarterly Statements") else real(pg, kind))
    run_all_stops(make_app("--all"))
    out = said(capsys)
    assert RUN_AGAIN in out and "new account" not in out


def test_an_account_asking_for_tax_documents_alone_is_not_told_of_statements(
        make_app, page, monkeypatch, tmp_path, capsys):
    page.set_content(PAGE % "")
    monkeypatch.setattr(site, "goto_documents", lambda pg: False)
    app = make_app("--all")
    app.config["document_types"] = ["Tax Document"]
    run_all_stops(app)
    out = said(capsys)
    assert OLD_UNOPENED in out and "new account" not in out
