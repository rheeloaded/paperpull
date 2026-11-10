"""A statement list read without a kind its dropdown offers is never noted
whole.

The Documents page shows statements through a native dropdown, Statements
first and then Quarterly Statements. A kind it would not choose was logged
and passed over, and the list was noted as read whole all the same, so a
run that read no statements at all could finish clean.

An account with no quarterly statements has no such option, which leaves
nothing out, and it is told at once, where asking for the missing option
waited out Playwright's time twice and ended on a press of an option that
never shows. Driven in a real browser against a made-up page. Every label
on it is invented or Wealthfront's own general words.
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import wealthfront_docs as app_mod
import wealthfront_site as site
from paperpull_core import listing

PAGE = """<!doctype html><html><body>
<select name="selectedDocumentType"><option value="VIEW_ALL">All Document Types</option>%s</select>
<table><tbody></tbody></table></body></html>"""

STATEMENTS = "<option>Statements</option>"
QUARTERLY = "<option>Quarterly Statements</option>"
NO_DROPDOWN = "<!doctype html><html><body><table></table></body></html>"


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
        return app

    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "collect_documents", statement_rows)
    return build


# An invented statement of each kind, the one the dropdown shows.
SHOWN = {"Statements": "Monthly Statement", "Quarterly Statements": "Quarterly Statement"}


def statement_rows(pg):
    """The rows the list shows for the kind the dropdown is on, one
    statement of that kind, and none for any other or with no dropdown."""
    sel = pg.locator("select")
    title = SHOWN.get(sel.input_value()) if sel.count() else None
    return [site.RawDoc(title=title, date_text="06/30/2031", kind="dated",
                        href="https://www.wealthfront.com/documents/invented",
                        text="06/30/2031 %s" % title)] if title else []


def failures(tmp_path):
    return list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


def type_will_not_take(monkeypatch, label):
    real = site.set_document_type
    monkeypatch.setattr(site, "set_document_type",
                        lambda pg, kind: False if kind == label else real(pg, kind))


def test_the_kinds_the_dropdown_offers_are_read(page):
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    assert site.document_types_offered(page) == {
        "all document types", "statements", "quarterly statements"}


def test_a_kind_turned_off_is_not_offered(page):
    page.set_content(PAGE % (STATEMENTS + "<option disabled>Quarterly Statements</option>"))
    assert "quarterly statements" not in site.document_types_offered(page)


def test_no_dropdown_says_nothing_of_what_is_offered(page):
    page.set_content(NO_DROPDOWN)
    assert site.document_types_offered(page) is None


def test_a_dropdown_under_another_name_is_still_read(page):
    page.set_content(PAGE.replace("selectedDocumentType", "kind") % STATEMENTS)
    assert site.document_types_offered(page) == {"all document types", "statements"}


def test_a_kind_not_offered_is_told_at_once(page):
    page.set_content(PAGE % STATEMENTS)
    started = time.monotonic()
    assert site.set_document_type(page, "Quarterly Statements") is False
    assert time.monotonic() - started < 5


def test_a_kind_offered_is_chosen(page):
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    assert site.set_document_type(page, "Quarterly Statements") is True
    assert page.locator("select").input_value() == "Quarterly Statements"


def test_both_kinds_read_is_a_whole_list(make_app, page, tmp_path):
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    app = make_app("--discover")
    app.cmd_discover()
    assert listing.last(app) == listing.COMPLETE and failures(tmp_path) == []


def test_an_account_with_no_quarterly_statements_is_a_whole_list(make_app, page, tmp_path):
    """The dropdown has no such option, as on an account of monthly
    statements alone, so nothing was left out."""
    page.set_content(PAGE % STATEMENTS)
    app = make_app("--discover")
    app.cmd_discover()
    assert listing.last(app) == listing.COMPLETE and failures(tmp_path) == []


def test_quarterly_statements_offered_and_not_taken_is_not_whole(
        make_app, page, monkeypatch, tmp_path, capsys):
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    type_will_not_take(monkeypatch, "Quarterly Statements")
    app = make_app("--discover")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_discover()
    assert stopped.value.code == 0
    assert listing.last(app) == listing.STOPPED
    assert "was not read whole" in " ".join(capsys.readouterr().out.split())
    [path] = failures(tmp_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert (report["step"], report["reason"]) == ("read the document list",
                                                  "some of the list could not be chosen")


def test_statements_not_on_the_dropdown_is_not_whole(make_app, page):
    """Every account has statements, so a dropdown without them has changed
    its words, and a run reading no statements must not read as clean."""
    page.set_content(PAGE % QUARTERLY)
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED


def test_no_dropdown_at_all_is_not_whole(make_app, page):
    page.set_content(NO_DROPDOWN)
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED


@pytest.mark.parametrize("empty", ["Statements", "Quarterly Statements"])
def test_a_kind_chosen_that_shows_no_statement_is_not_whole(make_app, page, monkeypatch, tmp_path,
                                                            capsys, empty):
    """The dropdown took the kind and the list showed nothing of it, which
    a page still drawing, or a press that chose something else, looks like
    too. Every account has statements, and quarterly ones are offered only
    to an account that has them."""
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    monkeypatch.setattr(site, "collect_documents", lambda pg: [] if (
        pg.locator("select").input_value() == empty) else statement_rows(pg))
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert "showed no statement once chosen" in " ".join(capsys.readouterr().out.split())
    assert len(failures(tmp_path)) == 1


def test_a_first_page_drawn_late_is_still_read_whole(make_app, page, monkeypatch, tmp_path):
    page.set_content(PAGE % STATEMENTS)
    asked = []

    def late(pg):
        asked.append(1)
        return [] if len(asked) == 1 else statement_rows(pg)
    monkeypatch.setattr(site, "collect_documents", late)
    app = make_app("--discover")
    app.cmd_discover()
    assert listing.last(app) == listing.COMPLETE and failures(tmp_path) == []
    assert [d["summary"] for d in app.discovery.data.values()]


# Before Quarterly Statements is asked for, the dropdown redrawn as `shape`,
# so Statements was read from a whole dropdown and the second kind is asked
# of whatever the page shows by then.
def redrawn_before_quarterly(monkeypatch, page, shape):
    real = site.set_document_type

    def ask(pg, kind):
        if kind == "Quarterly Statements":
            pg.set_content(shape)
        return real(pg, kind)
    monkeypatch.setattr(site, "set_document_type", ask)


TURNED_OFF = "<option disabled>Quarterly Statements</option>"
NO_KIND_YET = PAGE % ""


def test_the_dropdown_says_an_account_has_no_quarterly_statements_only_when_read_whole(page):
    """Only a dropdown that lists some other kind and no Quarterly
    Statements at all, turned off or not, says the account has none."""
    page.set_content(PAGE % STATEMENTS)
    assert site.has_no_kind(page, "Quarterly Statements") is True
    page.set_content(PAGE.replace("selectedDocumentType", "kind") % STATEMENTS)
    assert site.has_no_kind(page, "Quarterly Statements") is True
    for shape in (PAGE % (STATEMENTS + QUARTERLY), PAGE % (STATEMENTS + TURNED_OFF),
                  PAGE % (STATEMENTS + "<option>  Quarterly\n Statements </option>"),
                  NO_KIND_YET, NO_DROPDOWN):
        page.set_content(shape)
        assert site.has_no_kind(page, "Quarterly Statements") is False, shape


def test_quarterly_statements_turned_off_is_not_whole(make_app, page):
    """The dropdown lists the kind and will not let it be chosen, which says
    nothing of whether the account has any."""
    page.set_content(PAGE % (STATEMENTS + TURNED_OFF))
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED


@pytest.mark.parametrize("shape", [NO_KIND_YET, NO_DROPDOWN], ids=["no kind listed", "no dropdown"])
def test_a_dropdown_not_read_whole_when_quarterly_is_asked_is_not_whole(make_app, page, monkeypatch,
                                                                        tmp_path, shape):
    """Statements was read, and by the time Quarterly Statements is asked
    the dropdown lists no kind, as one still drawing does, or is gone. That
    is no account without quarterly statements, so the list is not whole."""
    page.set_content(PAGE % (STATEMENTS + QUARTERLY))
    redrawn_before_quarterly(monkeypatch, page, shape)
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert len(failures(tmp_path)) == 1
    assert [d["summary"] for d in app.discovery.data.values()]


def test_an_account_whose_dropdown_lists_other_kinds_and_no_quarterly_is_whole(make_app, page, monkeypatch,
                                                                                tmp_path):
    """As on the contributor's account, whose dropdown lists Statements and
    Trade Confirmations, every run that reads Statements whole finishes."""
    page.set_content(PAGE % (STATEMENTS + "<option>Trade Confirmations</option>"))
    for _ in range(2):
        app = make_app("--discover")
        app.cmd_discover()
        assert listing.last(app) == listing.COMPLETE and failures(tmp_path) == []
