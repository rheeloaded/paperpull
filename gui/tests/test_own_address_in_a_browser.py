"""The panel in a real browser, at 127.0.0.1 and at localhost.

The panel now answers only a request made to one of its own addresses and
refuses an Origin that names none, so these show the page still works at
both addresses people open it by, the list, a run and a request the page
sends with a body. The Browser Screen of PaperPull Server is a page that
shows noVNC's page in a frame, and every answer now says who may frame it,
so it is opened here too.

The API also refuses a request the browser marks Sec-Fetch-Site none,
which it sends when it opens an address by itself, for a link opened from
an email, a chat or a PDF. So an address of the API opened that way is
shown refused, with the header the browser really sent, and the page's own
spreadsheet and failure file on PaperPull Server, the two addresses of the
API the page sends the browser to, are shown still handed over. The
server's forms that choose a password and sign in and out ask the same
question as the API, so they are posted here too.

Playwright's own headless Chromium, never a browser of the person's,
against the real panel served on a free local port, with every setting
under a temp folder. The one app is a script that notes it ran.
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
sync_api = pytest.importorskip("playwright.sync_api")
import server_mode  # noqa: E402

PASSWORD = "an invented passphrase"
APP = '''
import os
from pathlib import Path
here = Path(__file__).resolve().parent
(here / "ran.txt").write_text("ran", encoding="utf-8")
print('PAPERPULL_RUN_RESULT ' + os.environ.get('PAPERPULL_RUN_MARK', '') + ' {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}')
'''


@pytest.fixture(scope="module")
def browser():
    """Playwright's own headless Chromium, with nothing of its own switched
    on that would reach the network."""
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=[
                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                "--disable-component-update", "--no-first-run"])
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        yield chromium
        chromium.close()


@pytest.fixture(scope="module")
def port():
    """The panel, served on a port the system chose, for the whole module.
    The socket is bound here and handed over, so no other program can take
    the port in between."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    number = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_module.app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield number
    server.should_exit = True
    thread.join(10)
    sock.close()


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """An apps root of its own holding the one app. Every setting is under
    tmp_path."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    # Somebody who has accepted the terms, so the dialog the panel shows the
    # first time it opens does not stand over what these tests press.
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "config"))
    for name in ("PAPERPULL_SERVER", "PAPERPULL_PASSWORD", "PAPERPULL_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    # Run with this Python, the way the packaged build runs every app.
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    server_mode._SESSIONS.clear()
    server_mode._FAILS.clear()
    folder = tmp_path / "apps" / "Shop Receipts"
    folder.mkdir(parents=True)
    (folder / "shop_receipts.py").write_text(APP, encoding="utf-8")
    (folder / "storage.py").write_text('SPEC = dict(provider="Shop", kind=RECEIPT)\n',
                                       encoding="utf-8")
    (folder / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    return folder


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_the_panel_works_at_its_own_addresses(browser, port, shop, name):
    context = browser.new_context()
    tab = context.new_page()
    answers = []
    tab.on("response", lambda r: answers.append((r.status, r.url)))
    try:
        base = "http://%s:%d" % (name, port)
        tab.goto(base + "/")
        assert tab.title() == "PaperPull"
        tab.wait_for_selector("#view-home .acct .who a")
        assert tab.inner_text("#view-home .acct .who a") == "Shop"

        tab.click("#view-home .acct .who a")
        tab.get_by_role("button", name="Try the newest few first").click()
        tab.wait_for_function("() => RUN.state === 'done'", timeout=60000)
        assert tab.inner_text("#r-title") == "Nothing new"
        assert (shop / "ran.txt").is_file(), "the run reached the app"

        sent = tab.evaluate("""async () => {
            const r = await fetch('/api/naming/preview', {method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({app: 'Shop Receipts', pattern: '{date} {provider}'})});
            return [r.status, await r.json()];
        }""")
        assert sent[0] == 200 and sent[1]["problem"] is None, sent
    finally:
        context.close()
    refused = [(status, url) for status, url in answers if status in (400, 401, 403)]
    assert not refused, refused
    assert any(url.startswith(base + "/api/run?") for _, url in answers)


def signed_in_context(browser, base: str, **options):
    """A context holding a session of PaperPull Server's, in a cookie made
    the way the server makes it."""
    context = browser.new_context(**options)
    context.add_cookies([{"name": server_mode.SESSION_COOKIE, "value": server_mode.new_session(),
                          "url": base, "httpOnly": True, "sameSite": "Strict"}])
    return context


def opened_by_the_browser(tab, url: str):
    """The answer to an address the browser opened by itself, which is what
    Playwright opening it is, after checking the browser said so."""
    answer = tab.goto(url)
    assert answer.request.header_value("sec-fetch-site") == "none"
    return answer


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_a_link_to_the_api_opened_from_outside_the_browser_starts_nothing(browser, port, shop,
                                                                          name):
    """A link to /api/run opened from an email, a chat or a PDF used to
    start that run. The panel itself still opens from a link."""
    base = "http://%s:%d" % (name, port)
    context = browser.new_context()
    try:
        tab = context.new_page()
        answer = opened_by_the_browser(tab, base + "/api/run?app=Shop%20Receipts&action=pilot")
        assert answer.status == 403, answer.text()
        assert "link" in answer.json()["detail"]
        answer = opened_by_the_browser(tab, base + "/")
        assert answer.status == 200 and tab.title() == "PaperPull"
    finally:
        context.close()
    assert not (shop / "ran.txt").exists(), "a link started a run"


def test_on_the_server_such_a_link_is_refused_in_a_signed_in_browser(browser, port, shop,
                                                                     monkeypatch):
    """The session cookie is SameSite=Strict, and the browser sends it all
    the same for an address it opened by itself, so the sign-in gate, which
    would answer 401, lets the link through. The API answers 403."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    base = "http://127.0.0.1:%d" % port
    context = signed_in_context(browser, base)
    try:
        tab = context.new_page()
        answer = opened_by_the_browser(tab, base + "/api/run?app=Shop%20Receipts&action=pilot")
        assert answer.status == 403, answer.text()
        assert "link" in answer.json()["detail"]
        answer = opened_by_the_browser(tab, base + "/")
        assert answer.status == 200 and tab.title() == "PaperPull"
    finally:
        context.close()
    assert not (shop / "ran.txt").exists(), "a link started a run"


def test_on_the_server_the_page_still_hands_over_its_spreadsheet_and_failure_file(
        browser, port, shop, tmp_path, monkeypatch):
    """PaperPull Server's page hands both to the browser by sending itself
    to their address under /api/, a navigation its own script starts, which
    the browser marks same-origin. Refused, the browser would show the
    refusal instead and download nothing."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    # Beside the installs, where both exports write it.
    sheet = shop.parent / "All Purchases.xlsx"
    sheet.write_bytes(b"an invented spreadsheet")
    monkeypatch.setattr(app_module, "_LAST_EXPORT", sheet)
    (shop / "Diagnostics").mkdir()
    (shop / "Diagnostics" / "failure-run-1.json").write_text('{"step": "a step"}',
                                                             encoding="utf-8")
    base = "http://127.0.0.1:%d" % port
    context = signed_in_context(browser, base, accept_downloads=True)
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        tab.wait_for_selector("#view-home .acct")
        with tab.expect_download(timeout=15000) as handed:
            tab.evaluate("revealSpreadsheet()")
        assert Path(handed.value.path()).read_bytes() == b"an invented spreadsheet"
        tab.evaluate("failureApp = 'Shop Receipts'")
        with tab.expect_download(timeout=15000) as handed:
            tab.evaluate("revealFailure()")
        assert Path(handed.value.path()).read_bytes() == b'{"step": "a step"}'
    finally:
        context.close()


def test_on_the_server_a_download_refused_is_said_on_the_panel_it_was_asked_from(
        browser, port, shop, tmp_path, monkeypatch):
    """A spreadsheet that is no longer the one the export wrote, here a file
    outside the folder it writes into, and a failure file that is not there.
    The page stays the panel and says why, where the refusal's JSON used to
    replace it (the release review of 0.57.1)."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    elsewhere = tmp_path / "Elsewhere" / "All Purchases.xlsx"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"not the export")
    monkeypatch.setattr(app_module, "_LAST_EXPORT", elsewhere)
    base = "http://127.0.0.1:%d" % port
    context = signed_in_context(browser, base, accept_downloads=True)
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        tab.wait_for_selector("#view-home .acct")
        handed = []
        tab.on("download", lambda download: handed.append(download))
        tab.evaluate("revealSpreadsheet()")
        assert tab.url == base + "/" and tab.title() == "PaperPull"
        assert "Create it again" in tab.inner_text("#noticetext")
        tab.evaluate("failureApp = 'Shop Receipts'")
        tab.evaluate("revealFailure()")
        assert tab.url == base + "/" and tab.title() == "PaperPull"
        assert "There is no recent file about what went wrong." in tab.inner_text("#noticetext")
        assert handed == []
    finally:
        context.close()


def test_the_documents_folder_page_says_when_a_run_will_refuse_their_folder(
        browser, port, shop, tmp_path):
    """The folder for every provider, saved by an earlier version inside a
    folder of the spouse's own. The page used to promise the person with no
    setting their folder in it from their next download, which that run
    refuses (the fresh review of minors-0571)."""
    own = tmp_path / "Docs"
    (shop.parent / "Shop Receipts - spouse").mkdir()
    (shop / "config.spouse.json").write_text(json.dumps({
        "output_dir": "../Shop Receipts - spouse", "documents_dir": str(own)}), encoding="utf-8")
    settings = app_module._read_settings()
    settings["documents_root"] = str(own / "PaperPull")
    app_module._write_settings(settings)
    base = "http://127.0.0.1:%d" % port
    context = browser.new_context()
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        tab.wait_for_selector("#view-home .acct")
        tab.evaluate("openDocuments()")
        tab.evaluate("async () => { $('dcpick').value = 'Shop Receipts\\nprimary'; await dcLoad(); }")
        said = tab.text_content("#dcnow")
        assert "will not use" in said and "Shop Receipts, spouse" in said, said
        assert "from their next download" not in said, said
        tab.evaluate("async () => { $('dcpick').value = 'Shop Receipts\\nspouse'; await dcLoad(); }")
        assert "Set for them alone" in tab.text_content("#dcnow")
    finally:
        context.close()


def test_on_the_server_its_own_forms_still_set_the_password_and_sign_in_and_out(
        browser, port, shop, monkeypatch):
    """Each is a form a page of the server's posts, which the browser marks
    same-origin, and each asks the same question as the API. Refused, nobody
    could choose a password or sign in."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    base = "http://127.0.0.1:%d" % port
    context = browser.new_context()
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        assert tab.url == base + "/setup"
        tab.fill("#code", server_mode.setup_code())
        tab.fill("#password", PASSWORD)
        tab.fill("#again", PASSWORD)
        with tab.expect_navigation():
            tab.get_by_role("button", name="Set the password").click()
        assert tab.url == base + "/"
        with tab.expect_navigation():
            tab.get_by_role("button", name="Sign out").click()
        assert tab.url == base + "/login"
        tab.fill("#password", PASSWORD)
        with tab.expect_navigation():
            tab.get_by_role("button", name="Sign in").click()
        assert tab.url == base + "/" and tab.title() == "PaperPull"
    finally:
        context.close()


def test_the_browser_screen_still_shows_novnc_in_its_frame(browser, port, shop, tmp_path,
                                                            monkeypatch):
    """noVNC's page is the one answer that may be framed, and only by a
    page of the panel's own. Framed by nobody, the screen would be blank."""
    (tmp_path / "novnc").mkdir()
    (tmp_path / "novnc" / "vnc.html").write_text(
        "<!doctype html><title>noVNC</title><p id=screen>the screen</p>", encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    base = "http://127.0.0.1:%d" % port
    context = browser.new_context()
    context.add_cookies([{"name": server_mode.SESSION_COOKIE, "value": server_mode.new_session(),
                          "url": base}])
    try:
        tab = context.new_page()
        tab.goto(base + "/screen")
        assert tab.title() == "PaperPull Browser Screen"
        screen = tab.frame_locator("iframe").locator("#screen")
        assert screen.inner_text(timeout=15000) == "the screen"
    finally:
        context.close()
    assert json.dumps(server_mode._FAILS) == "{}"


def test_the_sign_in_window_docks_beside_the_accounts_on_the_server(browser, port, shop, tmp_path,
                                                                     monkeypatch):
    """On the server every sign-in happens on the server's screen. The page
    shows it in a panel of its own when a sign-in starts, and the header's
    Sign-in window button opens it at any time, so nobody hunts for a tab.
    That works only because noVNC's page may be framed by the panel's own."""
    (tmp_path / "novnc").mkdir()
    (tmp_path / "novnc" / "vnc.html").write_text(
        "<!doctype html><title>noVNC</title><p id=screen>the screen</p>", encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    base = "http://127.0.0.1:%d" % port
    context = browser.new_context()
    context.add_cookies([{"name": server_mode.SESSION_COOKIE, "value": server_mode.new_session(),
                          "url": base}])
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        tab.wait_for_selector("#view-home .acct")
        assert not tab.is_visible("#dock")
        tab.click("#screenbtn")
        assert tab.is_visible("#dock") and tab.url == base + "/"
        screen = tab.frame_locator("#dockframe").locator("#screen")
        assert screen.inner_text(timeout=15000) == "the screen"
        tab.get_by_role("button", name="Done", exact=True).click()
        assert not tab.is_visible("#dock")
    finally:
        context.close()
    assert json.dumps(server_mode._FAILS) == "{}"


def test_the_panels_page_runs_under_its_script_policy_and_nothing_else_does(browser, port, shop):
    """The page carries a policy that lets only its own script run, named by
    its hash. A hash that missed the script the browser read would stop the
    whole panel, and a handler that found its way into the page, through a
    name or a title shown in it, has to stay a dead letter."""
    base = "http://127.0.0.1:%d" % port
    context = browser.new_context()
    # Put in by the browser itself, which no page policy stops, to hear of
    # every refusal.
    context.add_init_script("window.__refused = [];"
                            "document.addEventListener('securitypolicyviolation',"
                            " e => window.__refused.push(e.violatedDirective));")
    try:
        tab = context.new_page()
        answer = tab.goto(base + "/")
        policies = [h["value"] for h in answer.headers_array()
                    if h["name"].lower() == "content-security-policy"]
        assert any(p.startswith("script-src 'sha256-") for p in policies), policies
        tab.wait_for_selector("#view-home .acct .who a")
        for view in ("#/settings", "#/"):
            tab.evaluate("location.hash = %r" % view)
            tab.wait_for_timeout(300)
        assert tab.evaluate("window.__refused") == []
        tab.evaluate("document.body.insertAdjacentHTML('beforeend',"
                     " '<img src=\"data:,\" onerror=\"window.__ran = 1\">')")
        tab.wait_for_function("() => window.__refused.length > 0", timeout=10000)
        assert tab.evaluate("window.__ran") is None
        assert all(d.startswith("script-src") for d in tab.evaluate("window.__refused"))
    finally:
        context.close()


def test_a_panel_signed_out_while_open_goes_to_the_sign_in(browser, port, shop, monkeypatch):
    """PaperPull Server signs a session out after hours without use, and the
    open page then met 401 on its next request and showed it as an error.
    It goes to the sign-in instead."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    base = "http://127.0.0.1:%d" % port
    token = server_mode.new_session()
    context = browser.new_context()
    context.add_cookies([{"name": server_mode.SESSION_COOKIE, "value": token, "url": base}])
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        tab.wait_for_selector("#view-home .acct")
        server_mode.end_session(token)
        with tab.expect_navigation(url=base + "/login", timeout=15000):
            tab.evaluate("getJSON('/api/apps').catch(() => null)")
        assert tab.title() == "PaperPull"
    finally:
        context.close()


def test_the_docked_window_asks_for_the_password_again_after_a_gap(browser, port, shop, tmp_path,
                                                                    monkeypatch):
    """The sign-in window docked beside the accounts was opened once and
    kept, so one that closed after going unused stayed closed in the dock.
    Opened again, it asks for the password, and the password opens it. A
    window still showing the screen is left as it is."""
    (tmp_path / "novnc").mkdir()
    (tmp_path / "novnc" / "vnc.html").write_text(
        "<!doctype html><html class=noVNC_connected><title>noVNC</title>"
        "<p id=screen>the screen</p></html>", encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    base = "http://127.0.0.1:%d" % port
    token = server_mode.new_session()
    context = browser.new_context()
    context.add_cookies([{"name": server_mode.SESSION_COOKIE, "value": token, "url": base}])
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        tab.wait_for_selector("#view-home .acct")
        dock = tab.frame_locator("#dockframe")
        tab.click("#screenbtn")
        assert dock.locator("#screen").inner_text(timeout=15000) == "the screen"
        tab.get_by_role("button", name="Done", exact=True).click()
        tab.frame(url=lambda u: "vnc.html" in u).evaluate("window.__kept = 1")
        loads = []
        tab.on("request", lambda r: loads.append(r.url) if "vnc.html" in r.url else None)
        tab.click("#screenbtn")
        # Long enough for the page to be asked for again from this computer,
        # had the panel opened it again.
        tab.wait_for_timeout(1500)
        assert not loads, "a window showing the screen was opened again"
        assert tab.frame(url=lambda u: "vnc.html" in u).evaluate("window.__kept") == 1
        tab.get_by_role("button", name="Done", exact=True).click()

        # The screen closed after going unused, and noVNC shows so.
        server_mode._SESSIONS[token]["screen"] -= server_mode.SCREEN_IDLE_SECONDS + 1
        tab.frame(url=lambda u: "vnc.html" in u).evaluate(
            "document.documentElement.classList.remove('noVNC_connected')")
        tab.click("#screenbtn")
        assert "asks for your password again" in dock.locator("main").inner_text(timeout=15000)
        dock.locator("#password").fill(PASSWORD)
        dock.get_by_role("button", name="Open the sign-in window").click()
        assert dock.locator("#screen").inner_text(timeout=15000) == "the screen"
        assert server_mode.screen_open(token)
    finally:
        context.close()
    assert json.dumps(server_mode._FAILS) == "{}"
