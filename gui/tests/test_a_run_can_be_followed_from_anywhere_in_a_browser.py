"""A run says how it is going to somebody who is not looking at its page.

The tab's title stayed "PaperPull" through a run, which is when the person
is in the provider's window and has only the tab strip to look at. A run
that ended while they were on another page of PaperPull only lost its bar.
A round of Get new for all pulled them back to the Run page at each account,
and ended on "2 of 3 finished with nothing to look at", which made an account
that saved documents and set one aside read as one that failed. These run
the page's own script, in Playwright's own headless Chromium, against the
real panel on a free local port. Each app is a script that says it is on
step 1 of 2 and waits for a file named go. Every setting is under a temp
folder, and no browser of the person's is started.
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

APP = '''
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
print("[1/2] Saving a document", flush=True)
for _ in range(1200):
    if (here / "go").exists():
        break
    time.sleep(0.05)
counts = {"manual_review": 1 if (here / "aside").exists() else 0, "failed": 0,
          "validation_failures": 0, "new_files": 4, "stopped": 0}
print("PAPERPULL_RUN_RESULT " + os.environ.get("PAPERPULL_RUN_MARK", "") + " " + json.dumps(counts), flush=True)
'''


@pytest.fixture(scope="module")
def browser():
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
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


@pytest.fixture()
def apps(tmp_path, monkeypatch):
    """An apps root of its own holding two apps nothing has run yet."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    app_module._RUNS.clear()
    folders = []
    for name in ("Shop Docs", "Store Docs"):
        folder = tmp_path / "apps" / name
        folder.mkdir(parents=True)
        (folder / (name.lower().replace(" ", "_") + ".py")).write_text(APP, encoding="utf-8")
        app_module._account_root({"dir": str(folder)}, "primary").mkdir(parents=True, exist_ok=True)
        folders.append(folder)
    return folders


@pytest.fixture()
def panel(browser, base, apps):
    context = browser.new_context()
    tab = context.new_page()
    tab.goto(base + "/#/a/Shop%20Docs/primary")
    tab.wait_for_selector("#view-account [data-do=run][data-action=all]")
    yield SimpleNamespace(tab=tab, name=tab.evaluate("rowByKey(ROWS[0] && keyOf(ROWS[0])).provider"))
    context.close()


def release(folder):
    (folder / "go").write_text("", encoding="utf-8")


def title_is(tab, title):
    tab.wait_for_function("t => document.title === t", arg=title, timeout=60000)


def get_new(panel):
    panel.tab.click("#view-account [data-do=run][data-action=all]")
    title_is(panel.tab, "(1/2) %s · PaperPull" % panel.name)


def test_the_title_says_the_progress_then_the_end_then_goes_back(panel, apps):
    tab = panel.tab
    get_new(panel)
    release(apps[0])
    title_is(tab, "%s done · PaperPull" % panel.name)
    tab.evaluate("location.hash = '#/settings'")
    title_is(tab, "PaperPull")


def test_the_title_keeps_up_while_the_tab_is_out_of_sight(panel, apps):
    """A browser holds back animation frames for a tab nobody can see."""
    tab = panel.tab
    tab.evaluate("window.requestAnimationFrame = () => 0")
    get_new(panel)
    release(apps[0])


def test_a_document_set_aside_is_said_in_the_title(panel, apps):
    (apps[0] / "aside").write_text("", encoding="utf-8")
    get_new(panel)
    release(apps[0])
    title_is(panel.tab, "%s needs a look · PaperPull" % panel.name)


def test_a_run_ending_on_another_page_links_to_its_outcome(panel, apps):
    tab = panel.tab
    get_new(panel)
    tab.evaluate("location.hash = '#/settings'")
    tab.wait_for_selector("#view-settings:not([hidden])")
    release(apps[0])
    tab.wait_for_selector("#noticelink:not([hidden])", timeout=60000)
    said = tab.inner_text("#noticetext")
    assert "4 new documents saved" in said and panel.name in said
    assert tab.get_attribute("#noticelink", "href") == "#/run"
    tab.click("#noticelink")
    tab.wait_for_selector("#view-run:not([hidden]) #r-title")
    assert tab.is_hidden("#notice"), "the link's work is done once it has been followed"


def test_a_run_ending_on_its_own_page_says_nothing_more(panel, apps):
    tab = panel.tab
    get_new(panel)
    release(apps[0])
    title_is(tab, "%s done · PaperPull" % panel.name)
    assert tab.is_hidden("#notice")


def test_a_run_you_stopped_is_said_as_that(panel, apps):
    tab = panel.tab
    get_new(panel)
    tab.click("#view-run [data-do=stop-run]")
    title_is(tab, "%s: You stopped this run · PaperPull" % panel.name)
    release(apps[0])


def test_a_run_the_page_lost_touch_with_is_not_said_to_have_stopped(panel, apps):
    """It read "stopped", for a run that may still be going."""
    tab = panel.tab
    get_new(panel)
    tab.evaluate("es.onerror()")
    title_is(tab, "%s: Lost touch with this run · PaperPull" % panel.name)
    release(apps[0])


def test_a_run_that_never_started_is_not_said_to_have_stopped(panel, apps):
    """An import going holds every run back, and the panel refuses one."""
    assert app_module._IMPORTING.acquire(blocking=False)
    try:
        panel.tab.click("#view-account [data-do=run][data-action=all]")
        title_is(panel.tab, "%s: This run did not start · PaperPull" % panel.name)
    finally:
        app_module._IMPORTING.release()


def test_a_run_a_dialog_started_is_not_announced_over_it(panel, apps):
    tab = panel.tab
    tab.evaluate("""() => {
      const sink = document.createElement('pre');
      sink.id = 'testsink';
      document.body.appendChild(sink);
      startRun(ROWS[0], 'all', {stay: true, sink: '#testsink'.slice(1)});
    }""")
    title_is(tab, "(1/2) %s · PaperPull" % panel.name)
    release(apps[0])
    title_is(tab, "%s done · PaperPull" % panel.name)
    assert tab.is_hidden("#notice")


def start_a_round(panel, apps):
    """Both accounts stopped partway last time, so both are in the round."""
    tab = panel.tab
    for folder in apps:
        root = app_module._account_root({"dir": str(folder)}, "primary")
        (root / app_module.RUN_LOG).write_text(json.dumps([
            {"action": "all", "exit_code": 0, "ended": "2026-10-28T09:00:00",
             "result": {"stopped": 1}}]), encoding="utf-8")
    tab.evaluate("location.hash = '#/'")
    tab.reload()
    tab.wait_for_selector("[data-do=queue]")
    tab.click("[data-do=queue]")


def round_of_two(panel, apps):
    tab = panel.tab
    (apps[1] / "aside").write_text("", encoding="utf-8")
    start_a_round(panel, apps)
    tab.wait_for_selector("#view-run:not([hidden])")
    tab.wait_for_function("() => RUN.state === 'running'")
    tab.evaluate("location.hash = '#/settings'")
    tab.wait_for_selector("#view-settings:not([hidden])")
    first = tab.evaluate("RUN.app")
    release(apps[0] if first == "Shop Docs" else apps[1])
    tab.wait_for_function("f => RUN.state === 'running' && RUN.app !== f", arg=first, timeout=60000)


def test_a_round_does_not_pull_you_back_and_says_how_each_went(panel, apps):
    round_of_two(panel, apps)
    tab = panel.tab
    assert tab.evaluate("location.hash") == "#/settings", "the second run moved the person"
    assert tab.is_visible("#view-settings")
    assert tab.is_hidden("#notice"), "the round is still going"
    release(apps[0])
    release(apps[1])
    tab.wait_for_selector("#noticelink:not([hidden])", timeout=60000)
    assert tab.inner_text("#noticetext") == "The round is done."
    title_is(tab, "Round done · PaperPull")
    tab.click("#noticelink")
    tab.wait_for_selector(".roundend li")
    lines = tab.locator(".roundend li").all_inner_texts()
    assert len(lines) == 2
    aside = [line for line in lines if "some need a look" in line]
    assert len(aside) == 1 and "4 new documents saved" in aside[0], lines
    assert all("4 new documents saved" in line for line in lines), lines
    assert "finished with nothing to look at" not in tab.inner_text("#view-run")
    hrefs = [a.get_attribute("href") for a in tab.locator(".roundend a").all()]
    assert sorted(hrefs) == ["#/a/Shop%20Docs/primary", "#/a/Store%20Docs/primary"]


def test_a_paused_round_says_so_on_another_page(panel, apps):
    tab = panel.tab
    start_a_round(panel, apps)
    tab.wait_for_function("() => RUN.state === 'running'")
    tab.evaluate("location.hash = '#/settings'")
    tab.wait_for_selector("#view-settings:not([hidden])")
    tab.evaluate("stopRun()")
    tab.wait_for_selector("#noticelink:not([hidden])")
    assert tab.inner_text("#noticetext").startswith("Paused at ")
    assert tab.inner_text("#noticelink") == "See what it needs"
