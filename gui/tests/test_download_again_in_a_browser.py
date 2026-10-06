"""Download again, run by the page itself in a real browser.

test_download_again.py reads the page's script. These run it, in
Playwright's own headless Chromium, against the real panel served on a free
local port, so what is tested is what run() and postRun() do rather than
how they read. Every setting is under a temp folder, and the one app is a
script that writes down the arguments it was started with, and reports a
run that stopped partway when a file named stop sits beside it. No browser
of the person's is started, and nothing of theirs is read or written.
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
sync_api = pytest.importorskip("playwright.sync_api")

FLAG = "--redownload"

APP = '''
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
with open(here / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
counts = {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0,
          "stopped": 1 if (here / "stop").exists() else 0}
print("PAPERPULL_RUN_RESULT " + json.dumps(counts))
'''


@pytest.fixture(scope="module")
def browser():
    """Playwright's own headless Chromium. Module wide, so it starts before
    any test moves the settings folders, and is found where Playwright put it."""
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        yield chromium
        chromium.close()


@pytest.fixture(scope="module")
def base():
    """The panel, served on a free local port for the whole module."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Asked until it says so, for up to thirty seconds, since a machine
    # running a whole suite can be slow to start anything.
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """An apps root of its own holding the one app. Every setting is under
    tmp_path."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    # Run with this Python, the way the packaged build runs every app.
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    folder = tmp_path / "apps" / "Shop Docs"
    folder.mkdir(parents=True)
    (folder / "shop_docs.py").write_text(APP, encoding="utf-8")
    return folder


@pytest.fixture()
def panel(browser, base, shop):
    """The panel's page in a browser context of its own, so nothing the page
    keeps in the browser is left from another test, with every question it
    asks answered yes and kept."""
    context = browser.new_context()
    tab = context.new_page()
    asked = []

    def answer(dialog):
        asked.append(dialog.message)
        dialog.accept()
    tab.on("dialog", answer)
    tab.goto(base + "/")
    tab.wait_for_function("() => document.getElementById('app').options.length > 0")
    yield SimpleNamespace(tab=tab, asked=asked)
    context.close()


def started(folder) -> list:
    """The arguments of every run the app was started for."""
    listed = folder / "argv.jsonl"
    if not listed.exists():
        return []
    return [json.loads(line) for line in listed.read_text(encoding="utf-8").splitlines()]


def press(tab, name):
    """Press one of the panel's buttons and wait for the run it starts to end."""
    tab.get_by_role("button", name=name, exact=True).click()
    tab.wait_for_function("() => !document.getElementById('dot').classList.contains('run')",
                          timeout=60000)


def status(tab) -> str:
    return tab.inner_text("#statustext")


def test_a_run_that_downloads_again_reaches_the_app_with_the_flag_once(panel, shop):
    tab = panel.tab
    tab.select_option("#year", "2024")
    tab.check("#again")
    press(tab, "Run All")
    assert started(shop) == [["--all", "--yes", "--year", "2024", FLAG]]
    assert len(panel.asked) == 1, panel.asked
    assert "Run All goes through every document dated 2024 again" in panel.asked[0]
    assert "Nothing is overwritten." in panel.asked[0]
    assert status(tab) == "finished, no issues reported"
    assert not tab.is_checked("#again")
    assert FLAG in tab.inner_text("#console")


def test_a_refusal_from_the_panel_is_shown_and_nothing_starts(panel, shop):
    tab = panel.tab
    tab.select_option("#year", "2024")
    tab.check("#again")
    # The provider's folder goes after the page listed it, so the panel no
    # longer knows the app the page asks it to run.
    gone = shop.with_name("Shop Docs, moved away")
    shop.rename(gone)
    press(tab, "Run All")
    assert len(panel.asked) == 1
    assert status(tab) == "unknown app"
    assert "unknown app" in tab.inner_text("#console")
    assert started(gone) == []


def test_another_button_leaves_the_box_ticked_and_says_so(panel, shop):
    """Tick, Login, then Run All, the order somebody signing in first takes."""
    tab = panel.tab
    tab.select_option("#year", "2024")
    tab.check("#again")
    press(tab, "Login")
    assert started(shop) == [["--login"]]
    assert panel.asked == []
    assert tab.is_checked("#again")
    assert ("Download again stays ticked. It applies only to Pilot and Run All, "
            "so this Login runs as usual.") in tab.inner_text("#console")
    press(tab, "Run All")
    assert started(shop)[-1] == ["--all", "--yes", "--year", "2024", FLAG]
    assert len(panel.asked) == 1
    assert not tab.is_checked("#again")


def test_a_run_that_stops_partway_says_resume_will_not_download_again(panel, shop):
    (shop / "stop").write_text("", encoding="utf-8")
    tab = panel.tab
    tab.fill("#start", "2023-01-01")
    tab.fill("#end", "2023-12-31")
    tab.dispatch_event("#end", "change")
    tab.check("#again")
    press(tab, "Pilot")
    assert started(shop) == [["--pilot", "--start-date", "2023-01-01",
                              "--end-date", "2023-12-31", FLAG]]
    said = status(tab)
    assert said.startswith("stopped before finishing. Resume will not download again"), said
    assert "fetches again what this run already restored, so choose the range that is left" in said
    assert "This download again ended before it was through." in tab.inner_text("#console")
    # An ordinary run that stops still points at Resume, which is right for it.
    press(tab, "Pilot")
    assert status(tab) == "stopped before finishing, see the output, then press Resume"


def test_one_end_of_a_range_stops_it_on_the_page(panel, shop):
    tab = panel.tab
    tab.fill("#end", "2026-10-06")
    tab.dispatch_event("#end", "change")
    tab.check("#again")
    press(tab, "Run All")
    assert "a year, or both a From and a To date" in status(tab)
    assert started(shop) == [] and panel.asked == []
    assert tab.is_checked("#again")
