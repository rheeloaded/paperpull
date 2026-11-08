"""Restore deleted files, the panel's Download again, run by the page itself.

test_download_again.py reads the page's script. These run it, in
Playwright's own headless Chromium, against the real panel served on a free
local port, so what is tested is what the dialog, startRun() and postRun()
do rather than how they read. Every setting is under a temp folder, and the
one app is a script that writes down the arguments it was started with, and
reports a run that stopped partway when a file named stop sits beside it.
No browser of the person's is started, and nothing of theirs is read or
written.
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
ACCOUNT = "/#/a/Shop%20Docs/primary"

APP = '''
import json, os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
with open(here / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
counts = {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0,
          "stopped": 1 if (here / "stop").exists() else 0}
print("PAPERPULL_RUN_RESULT " + os.environ.get("PAPERPULL_RUN_MARK", "") + " " + json.dumps(counts))
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
    # Somebody who has accepted the terms, so the dialog the panel shows the
    # first time it opens does not stand over what these tests press.
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    # Run with this Python, the way the packaged build runs every app.
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    app_module._RUNS.clear()
    folder = tmp_path / "apps" / "Shop Docs"
    folder.mkdir(parents=True)
    (folder / "shop_docs.py").write_text(APP, encoding="utf-8")
    return folder


@pytest.fixture()
def panel(browser, base, shop):
    """The account's page in a browser context of its own, so nothing the
    page keeps in the browser is left from another test. Any question the
    browser itself is asked is noted and refused, since the panel asks its
    questions on the page now."""
    context = browser.new_context()
    tab = context.new_page()
    asked = []

    def answer(dialog):
        asked.append(dialog.message)
        dialog.dismiss()
    tab.on("dialog", answer)
    tab.goto(base + ACCOUNT)
    tab.wait_for_selector("#view-account [data-do=run][data-action=all]")
    yield SimpleNamespace(tab=tab, asked=asked, base=base)
    context.close()


def started(folder) -> list:
    """The arguments of every run the app was started for."""
    listed = folder / "argv.jsonl"
    if not listed.exists():
        return []
    return [json.loads(line) for line in listed.read_text(encoding="utf-8").splitlines()]


def finished(tab):
    tab.wait_for_function("() => RUN.state === 'done'", timeout=60000)


def back(panel):
    panel.tab.evaluate("location.hash = %r" % ACCOUNT[1:])
    panel.tab.wait_for_selector("#view-account [data-do=run][data-action=all]")


def open_restore(tab):
    tab.click("#view-account [data-do=menu]")
    tab.click(".menu [data-do=restore]")
    tab.wait_for_selector("#dlg-restore[open]")


def range_of(tab, start, end):
    tab.check("input[name=rsby][value=range]")
    if start:
        tab.fill("#rs-start", start)
    if end:
        tab.fill("#rs-end", end)


def test_a_restore_reaches_the_app_with_the_flag_once(panel, shop):
    tab = panel.tab
    open_restore(tab)
    tab.select_option("#rs-year", "2024")
    assert tab.inner_text("#rs-go") == "Restore missing files from 2024"
    tab.click("#rs-go")
    finished(tab)
    assert started(shop) == [["--all", "--yes", "--year", "2024", FLAG]]
    assert panel.asked == []
    assert tab.inner_text("#r-title") == "Nothing new"
    assert FLAG in tab.text_content("#console")
    assert not tab.is_visible("#dlg-restore")


def test_a_refusal_from_the_panel_is_shown_and_nothing_starts(panel, shop):
    tab = panel.tab
    open_restore(tab)
    tab.select_option("#rs-year", "2024")
    # The provider's folder goes after the page listed it, so the panel no
    # longer knows the app the page asks it to run.
    gone = shop.with_name("Shop Docs, moved away")
    shop.rename(gone)
    tab.click("#rs-go")
    finished(tab)
    assert tab.inner_text("#r-title") == "This run did not start"
    assert tab.inner_text("#statustext") == "unknown app"
    assert started(gone) == [] and panel.asked == []


def test_get_new_never_downloads_again_after_a_restore(panel, shop):
    """The old box stayed ticked across other buttons. Now nothing carries
    over, and every other run is an ordinary one."""
    tab = panel.tab
    open_restore(tab)
    tab.select_option("#rs-year", "2024")
    tab.click("#rs-go")
    finished(tab)
    back(panel)
    tab.get_by_role("button", name="Open sign-in window").click()
    finished(tab)
    back(panel)
    tab.get_by_role("button", name="Get new documents").click()
    finished(tab)
    assert started(shop) == [["--all", "--yes", "--year", "2024", FLAG], ["--login"], ["--all", "--yes"]]
    back(panel)
    open_restore(tab)
    # It opens fresh, last year chosen and nothing of the last restore kept.
    assert tab.input_value("#rs-year") == str(time.localtime().tm_year - 1)
    assert tab.is_checked("input[name=rsby][value=year]") and tab.is_checked("input[name=rshow][value=all]")


def test_a_restore_that_stops_partway_says_continue_will_not_download_again(panel, shop):
    (shop / "stop").write_text("", encoding="utf-8")
    tab = panel.tab
    open_restore(tab)
    range_of(tab, "2023-01-01", "2023-12-31")
    tab.check("input[name=rshow][value=pilot]")
    tab.click("#rs-go")
    finished(tab)
    assert started(shop) == [["--pilot", "--start-date", "2023-01-01",
                              "--end-date", "2023-12-31", FLAG]]
    assert tab.inner_text("#r-title") == "Stopped before finishing"
    said = tab.inner_text("#statustext")
    assert said.startswith("Continue will not download again"), said
    assert "fetches again what this run already restored, so choose the dates that are left" in said
    assert tab.locator("#view-run [data-action=resume]").count() == 0
    # An ordinary run that stops still offers Continue, which is right for it.
    back(panel)
    tab.get_by_role("button", name="Try the newest few first").click()
    finished(tab)
    assert tab.inner_text("#r-title") == "Stopped before finishing"
    assert "If Shop Docs signed you out, sign in again, then continue." in tab.inner_text("#statustext")
    assert tab.locator("#view-run [data-action=resume]").count() == 1


def test_a_discover_that_stops_offers_to_check_again_never_continue(panel, shop):
    """Continue downloads, and somebody who pressed Only check what's there
    asked only to see what the provider has."""
    (shop / "stop").write_text("", encoding="utf-8")
    tab = panel.tab
    tab.get_by_role("button", name="Only check what's there").click()
    finished(tab)
    assert started(shop) == [["--discover"]]
    assert tab.inner_text("#r-title") == "Stopped before finishing"
    assert tab.inner_text("#statustext").endswith("sign in again, then check again.")
    assert tab.locator("#view-run [data-action=resume]").count() == 0
    assert tab.locator("#view-run [data-action=discover]").count() == 1


def test_one_end_of_a_range_stops_it_in_the_dialog(panel, shop):
    tab = panel.tab
    open_restore(tab)
    range_of(tab, "", "2026-10-06")
    tab.click("#rs-go")
    assert tab.is_visible("#rs-err")
    assert tab.inner_text("#rs-err") == "Choose a year, or both a From and a To date."
    assert tab.is_visible("#dlg-restore")
    assert started(shop) == [] and panel.asked == []
    tab.fill("#rs-start", "2026-12-01")
    tab.click("#rs-go")
    assert tab.inner_text("#rs-err") == "The From date is after the To date."
    assert started(shop) == []
