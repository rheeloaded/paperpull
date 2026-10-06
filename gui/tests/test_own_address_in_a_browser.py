"""The panel in a real browser, at 127.0.0.1 and at localhost.

The panel now answers only a request made to one of its own addresses and
refuses an Origin that names none, so these show the page still works at
both addresses people open it by, the list, a run and a request the page
sends with a body. The Browser Screen of PaperPull Server is a page that
shows noVNC's page in a frame, and every answer now says who may frame it,
so it is opened here too.

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
from pathlib import Path
here = Path(__file__).resolve().parent
(here / "ran.txt").write_text("ran", encoding="utf-8")
print('PAPERPULL_RUN_RESULT {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}')
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
        tab.wait_for_function("() => document.getElementById('app').options.length > 0")
        assert tab.input_value("#app") == "Shop Receipts"

        tab.get_by_role("button", name="Pilot", exact=True).click()
        tab.wait_for_function("() => !document.getElementById('dot').classList.contains('run')",
                              timeout=60000)
        assert tab.inner_text("#statustext") == "finished, no issues reported"
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
