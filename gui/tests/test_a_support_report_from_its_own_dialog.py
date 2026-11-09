"""The support report's dialog, its own sign-in, and the name its problem
report carries.

The dialog opens the sign-in window itself and stays open, so the person
signs in and makes the report without leaving it. On PaperPull Server the
sign-in window is docked in the page, and nothing outside a dialog that is
open can be pressed, so a sign-in started there opened a window that could
not be used until the dialog was closed. And Make the report pressed while
that sign-in was still going closed the dialog, and the run was refused.

A row's slug goes into a link to GitHub. It is read from the entry script's
name in the person's own folder, and a script named by hand could carry any
words, so only a provider PaperPull ships has one, and a row the panel could
not read keeps it too.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")


def _page(server: bool):
    sync_api = pytest.importorskip("playwright.sync_api")
    html = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
            .replace("__SERVER_BAR__", "").replace("__SERVER__", "true" if server else "false"))
    return sync_api, html


def _open(server: bool):
    """The panel's own page in Playwright's own Chromium, from an invented
    address with nothing else answered, and the support dialog opened for
    one account, as its More menu opens it."""
    sync_api, html = _page(server)
    pw = sync_api.sync_playwright().start()
    try:
        chromium = pw.chromium.launch(args=[
            "--disable-extensions", "--disable-sync", "--disable-background-networking",
            "--disable-component-update", "--no-first-run"])
    except sync_api.Error as e:
        pw.stop()
        pytest.skip("Playwright's own Chromium is not installed here, %s"
                    % str(e).strip().splitlines()[0])
    tab = chromium.new_page()

    def answer(route):
        if route.request.url == "http://panel.test/":
            route.fulfill(status=200, content_type="text/html", body=html)
        else:
            route.abort()
    tab.route("**/*", answer)
    tab.goto("http://panel.test/")
    tab.evaluate("""() => {
        ROWS = [{app: 'Chase Statements', account: 'primary', provider: 'Chase', slug: 'chase',
                 kind: 'DOCUMENT', state: 'current', runnable: true, documents: 1, gaps: [],
                 latest: [], runs: []}];
        DO['support']({dataset: {key: keyOf(ROWS[0])}});
    }""")
    return pw, chromium, tab


@pytest.mark.parametrize("server", [False, True], ids=["desktop", "server"])
def test_the_dialog_offers_its_own_sign_in_only_where_it_can_be_used(server):
    pw, chromium, tab = _open(server)
    try:
        assert tab.evaluate("() => $('dlg-support').open")
        shown = tab.locator("#dlg-support [data-do=sp-signin]").is_visible()
        assert shown is (not server)
        if server:
            # Pressed anyway, by a key or a script, it starts nothing.
            started = tab.evaluate("""() => {
                let asked = null;
                const real = startRun;
                startRun = (row, action) => { asked = action; return true; };
                DO['sp-signin']();
                startRun = real;
                return asked;
            }""")
            assert started is None
            assert tab.evaluate("() => $('sp-signsay').textContent").startswith("Sign in to the provider first")
    finally:
        chromium.close()
        pw.stop()


def test_make_the_report_waits_while_the_sign_in_it_started_is_going():
    pw, chromium, tab = _open(False)
    try:
        go = tab.locator("#dlg-support [data-do=sp-go]")
        assert go.is_enabled()
        tab.evaluate("() => { RUN.state = 'running'; lockStarts(); }")
        assert go.is_disabled(), "pressed now, it closed the dialog and the report was refused"
        tab.evaluate("() => { RUN.state = 'done'; lockStarts(); }")
        assert go.is_enabled()
    finally:
        chromium.close()
        pw.stop()


# -- the slug a problem report carries ----------------------------------------

STANDIN = "print('a stand-in')\n"


@pytest.fixture
def apps(tmp_path, monkeypatch):
    """An apps root with a provider PaperPull ships and a folder whose
    script was named by hand."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    root = tmp_path / "apps"
    monkeypatch.setenv("APPS_ROOT", str(root))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    monkeypatch.setattr(app_module, "_STATUS_MOD", None)
    chase = root / "Chase Statements"
    chase.mkdir(parents=True)
    (chase / "chase_docs.py").write_text(STANDIN, encoding="utf-8")
    (chase / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    mine = root / "My Bank"
    mine.mkdir()
    (mine / "Jordan Avery Credit Union_docs.py").write_text(STANDIN, encoding="utf-8")
    (mine / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    return root


def _slugs():
    return {r["app"]: r["slug"] for r in app_module.account_rows()}


def test_only_a_provider_paperpull_ships_gives_a_row_its_slug(apps):
    assert "chase" in app_module._provider_notes(), "providers.json names chase"
    assert _slugs() == {"Chase Statements": "chase", "My Bank": ""}


def test_a_row_the_panel_could_not_read_keeps_its_slug(apps, monkeypatch):
    def unreadable(*a, **k):
        raise ValueError("a config written by hand")
    monkeypatch.setattr(app_module, "_account_row", unreadable)
    rows = {r["app"]: r for r in app_module.account_rows()}
    assert rows["Chase Statements"]["state"] == "nostatus"
    assert _slugs() == {"Chase Statements": "chase", "My Bank": ""}
