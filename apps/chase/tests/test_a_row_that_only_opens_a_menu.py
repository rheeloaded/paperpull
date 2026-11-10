"""A statement row whose only control opens a menu is never taken as one.

With Chase's document API answering nothing, the fallback read a business
account's documents off the page, and each row's words carried its control,
"Opens document menu". The row was recorded with no card and no document id,
the press looked for "opens document" and so took that control, and no
download ever came. Nine such records failed on every later run for good,
since a record with no file is always tried again.

Such a row's statement is still on the list and is not taken here, so the
list it was read from is never noted whole. The run takes what else it
read and stops at its end, as it does for a year or a card it could not
choose.

In a real browser. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import chase_docs as app_mod  # noqa: E402
import chase_site as site  # noqa: E402
from chase_docs import App, Document, MENU_ROW_NOTE, State, retire_menu_rows  # noqa: E402
from paperpull_core import listing  # noqa: E402
from storage import JsonStore  # noqa: E402

DOCUMENTS = "https://secure.chase.com/web/auth/dashboard"
DATE = "2026-08-31"

PAGE = """<!doctype html><html><body><main><h1>Statements</h1><table>
<tr><td>Statement 4 pages Aug 31, 2026</td><td>
  <a href="#" id="menu" aria-label="Aug 31, 2026 Statement 4 pages Opens document menu">Opens document menu</a>
</td></tr>
<tr><td>Statement Jul 31, 2026</td><td>
  <a href="#" id="plain" aria-label="Jul 31, 2026 Statement opens document">opens document</a>
</td></tr>
</table></main><script>
window.pressed = [];
for (const a of document.querySelectorAll('a')) a.addEventListener('click', (e) => {
  e.preventDefault(); window.pressed.push(a.id);
});
</script></body></html>"""

MENU_TITLE = "Statement 4 pages Opens document menu Open as PDF Save as PDF"


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(DOCUMENTS, lambda r: r.fulfill(status=200, content_type="text/html", body=PAGE))
    tab = ctx.new_page()
    tab.goto(DOCUMENTS)
    yield tab
    browser.close()
    driver.stop()


def test_the_menu_control_is_not_pressed(page, tmp_path):
    out = tmp_path / "statement.pdf"
    assert site._click_row_and_capture(page, page.context, "", DATE, out) is False
    assert page.evaluate("window.pressed") == []
    assert not out.exists()


def test_a_control_that_opens_the_document_still_matches():
    name = "Jul 31, 2026 Statement opens document"
    assert site.row_label_re("2026-07-31", "", "opens document").search(name)
    assert not site.row_label_re("2026-07-31", "", "opens document").search(name + " menu")


def test_the_fallback_does_not_list_a_menu_row(page, monkeypatch):
    monkeypatch.setattr(site, "account_select", lambda p: (None, []))
    monkeypatch.setattr(site, "year_select", lambda p: (None, []))
    monkeypatch.setattr(site, "next_page", lambda p: False)
    listed = site.chase_collect(page)
    assert [d["date"] for d in listed] == ["2026-07-31"]
    # Its statement is on the list and is not taken, so the list is not whole.
    assert listed.passed_over == (site.DOCUMENT_MENU,)


# -- Run All over a list with such a row ------------------------------------------

def _run_all(tmp_path, monkeypatch, passed_over):
    """Run All with the API answering nothing and the page's text reading
    listing one plain statement, its passed_over as given."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Test Person", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
        "document_types": ["Statement"], "default_start_date": "",
        "min_pdf_bytes": 2000, "max_path_length": 240,
        "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}), encoding="utf-8")
    pressed = []
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "chase_collect_via_api", lambda page, keep=None: site._listed([]))
    monkeypatch.setattr(site, "chase_collect", lambda page: site._listed(
        [{"account": "", "date": "2026-07-31", "title": "Statement opens document"}], passed_over))
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", "--all"]))
    monkeypatch.setattr(app, "page", lambda: None)
    monkeypatch.setattr(app, "_on_its_site", lambda: None)
    monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    monkeypatch.setattr(app, "download_one", lambda _page, doc, _name: pressed.append(doc.date))
    return app, pressed


def test_a_list_with_a_menu_row_is_not_noted_whole(tmp_path, monkeypatch, capsys):
    """The plain statement is taken, and the run stops at its end with a
    failure file that says why, rather than finish with a statement on
    the list never taken."""
    app, pressed = _run_all(tmp_path, monkeypatch, (site.DOCUMENT_MENU,))
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert pressed == ["2026-07-31"]
    assert listing.last(app) == listing.STOPPED
    said = " ".join(capsys.readouterr().out.split())
    assert "Chase's statement list was not read whole." in said
    assert "A statement on it is saved only through a menu, which this app never presses." in said
    assert "could not be chosen" not in said
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(path.read_text(encoding="utf-8"))
    assert (report["step"], report["reason"]) == (
        "read the statement list", "a statement on the list is saved only through a menu")


def test_a_list_with_no_menu_row_is_noted_whole(tmp_path, monkeypatch):
    app, pressed = _run_all(tmp_path, monkeypatch, ())
    app.cmd_run("all")
    assert pressed == ["2026-07-31"]
    assert listing.last(app) == listing.COMPLETE


def _stores(tmp_path, *records):
    progress = JsonStore(tmp_path / "progress.json", tmp_path / "backups")
    discovery = JsonStore(tmp_path / "discovery.json", tmp_path / "backups")
    progress.load()
    discovery.load()
    for rec in records:
        doc = Document.from_dict(rec)
        progress.update(doc.key, doc.to_dict(), save=False)
        discovery.update(doc.key, doc.to_dict(), save=False)
    return progress, discovery


def _app(discovery):
    app = App.__new__(App)
    app.args = SimpleNamespace(type=None, year=None, start_date=None, max_docs=None,
                               redownload=False)
    app.config = {"wanted_categories": None}
    app.discovery = discovery
    return app


@pytest.mark.parametrize("state", [State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value,
                                   State.DISCOVERED.value])
def test_a_menu_row_left_by_an_older_version_is_set_down(tmp_path, state, monkeypatch):
    stuck = dict(category="Statement", date=DATE, title=MENU_TITLE, account="", state=state,
                 notes="Could not capture the document PDF (see the log)")
    progress, discovery = _stores(tmp_path, stuck)
    key = Document.from_dict(stuck).key
    assert retire_menu_rows(progress, discovery) == 1
    assert progress.get(key)["state"] == State.NO_LONGER_LISTED.value
    assert MENU_ROW_NOTE in progress.get(key)["notes"]
    assert discovery.get(key)["state"] == State.NO_LONGER_LISTED.value
    assert retire_menu_rows(progress, discovery) == 0

    app = _app(discovery)
    monkeypatch.setattr(App, "_in_scope", lambda self, d: True)
    assert app._select() == []
    app.args.redownload = True
    assert app._select() == []


@pytest.mark.parametrize("change", [
    {"account": "INVENTED CARD (...1234)"},
    {"document_id": "invented-document-id"},
    {"downloaded_ok": True},
    {"pdf_path": "/invented/statement.pdf"},
    {"state": State.COMPLETED.value},
    {"title": "Statement 4 pages"},
])
def test_any_other_record_stays_as_it_is(tmp_path, change):
    rec = dict(dict(category="Statement", date=DATE, title=MENU_TITLE, account="",
                    state=State.NEEDS_MANUAL_REVIEW.value), **change)
    progress, discovery = _stores(tmp_path, rec)
    key = Document.from_dict(rec).key
    assert retire_menu_rows(progress, discovery) == 0
    assert progress.get(key)["state"] == rec["state"]


@pytest.mark.parametrize("value", [None, 7, ["list"], {"a": 1}])
def test_a_record_value_that_is_not_text_is_passed_over(tmp_path, value):
    rec = dict(category="Statement", date=DATE, title=MENU_TITLE, account="",
               state=State.FAILED.value)
    progress, discovery = _stores(tmp_path, rec)
    key = Document.from_dict(rec).key
    discovery.update(key, {"title": value}, save=False)
    assert retire_menu_rows(progress, discovery) == 0
    discovery.update(key, {"title": MENU_TITLE}, save=False)
    progress.update(key, {"notes": value}, save=False)
    assert retire_menu_rows(progress, discovery) == 1
    assert progress.get(key)["notes"] == MENU_ROW_NOTE
