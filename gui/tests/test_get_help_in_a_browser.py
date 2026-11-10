"""One Get help under More, run by the page itself.

Make a support report and Record steps for support were two items and two
dialogs, and the file a failed run had just written was a third place to
look. These run the page's own script, in Playwright's own headless
Chromium, against the real panel on a free local port. The one app is a
script that writes down the arguments it was started with. Every setting
is under a temp folder, and no browser of the person's is started.
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

ACCOUNT = "/#/a/Shop%20Docs/primary"

APP = '''
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
with open(here / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
if "--diagnose" in sys.argv and (here / "signed-out").exists():
    # core run_reporting.NOTHING_READ
    sys.exit(8)
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
def shop(tmp_path, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    app_module._RUNS.clear()
    folder = tmp_path / "apps" / "Shop Docs"
    folder.mkdir(parents=True)
    (folder / "shop_docs.py").write_text(APP, encoding="utf-8")
    app_module._account_root({"dir": str(folder)}, "primary").mkdir(parents=True, exist_ok=True)
    return folder


@pytest.fixture()
def panel(browser, base, shop):
    context = browser.new_context()
    tab = context.new_page()
    tab.goto(base + ACCOUNT)
    tab.wait_for_selector("#view-account [data-do=run][data-action=all]")
    yield SimpleNamespace(tab=tab, base=base)
    context.close()


def left_a_failure(shop):
    inside = app_module._account_root({"dir": str(shop)}, "primary") / "Diagnostics"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "failure-all-20261108-090000.json").write_text("{}", encoding="utf-8")


def open_get_help(tab):
    tab.click("#view-account [data-do=menu]")
    tab.click("[data-do=support]")
    tab.wait_for_selector("#dlg-support[open]")


def started(shop) -> list:
    listed = shop / "argv.jsonl"
    if not listed.exists():
        return []
    return [json.loads(line) for line in listed.read_text(encoding="utf-8").splitlines()]


def test_more_has_one_get_help_and_not_the_two_it_replaces(panel):
    tab = panel.tab
    tab.click("#view-account [data-do=menu]")
    items = tab.locator(".menu [role=menuitem] b").all_inner_texts()
    assert items.count("Get help") == 1
    assert "Make a support report" not in items and "Record steps for support" not in items
    assert tab.locator("[data-do=record]").count() == 0


def test_with_no_recent_failure_file_the_report_comes_first(panel):
    tab = panel.tab
    open_get_help(tab)
    tab.wait_for_load_state("networkidle")
    assert tab.is_hidden("#sp-failure")
    assert tab.is_visible("[data-do=sp-go]") and tab.is_visible("[data-do=sp-signin]")


def test_a_recent_failure_file_is_offered_before_the_report(panel, shop):
    left_a_failure(shop)
    tab = panel.tab
    open_get_help(tab)
    tab.wait_for_selector("#sp-failure:not([hidden]) [data-do=sp-failure]")
    order = tab.evaluate("""() => ['#sp-failure', '[data-do=sp-go]', '[data-do=rc-go]'].map(
        s => document.querySelector(s).getBoundingClientRect().top)""")
    assert order == sorted(order), "failure file, then report, then recording"
    assert tab.get_attribute("#sp-failacts a", "href").startswith(
        "https://github.com/rheeloaded/paperpull/issues")

    asked = []

    def answer(route):
        asked.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body="{}")
    tab.route("**/api/failure/reveal", answer)
    tab.click("[data-do=sp-failure]")
    for _ in range(100):
        if asked:
            break
        tab.wait_for_timeout(50)
    assert asked == [{"app": "Shop Docs", "account": "primary"}]


def test_the_privacy_words_are_in_a_closed_disclosure(panel):
    tab = panel.tab
    open_get_help(tab)
    assert tab.inner_text(".spwhat summary") == "What's in the file?"
    assert tab.is_hidden("#sp-diagnose"), "it is there for whoever asks"
    tab.click(".spwhat summary")
    said = tab.inner_text("#sp-diagnose")
    for words in ("survey-", "counts and page states", "fixed list", "stays on this computer"):
        assert words in said


def test_its_sign_in_button_keeps_the_dialog_open(panel, shop):
    tab = panel.tab
    open_get_help(tab)
    tab.click("[data-do=sp-signin]")
    tab.wait_for_function("() => $('sp-signsay').textContent.startsWith('Opening the sign-in window.')")
    assert tab.evaluate("$('dlg-support').open")


def test_make_the_report_runs_the_support_report(panel, shop):
    tab = panel.tab
    open_get_help(tab)
    tab.click("[data-do=sp-go]")
    tab.wait_for_function("() => RUN.state === 'done' && RUN.action === 'diagnose'", timeout=60000)
    assert not tab.evaluate("$('dlg-support').open")
    assert any("--diagnose" in args for args in started(shop))


def test_a_report_that_read_nothing_says_so_and_offers_the_way_on(panel, shop):
    signed_out = shop / "signed-out"
    signed_out.write_text("", encoding="utf-8")
    tab = panel.tab
    open_get_help(tab)
    tab.click("[data-do=sp-go]")
    tab.wait_for_function("() => RUN.state === 'done'", timeout=60000)
    assert tab.inner_text("#r-title") == "Nothing was read"
    said = tab.inner_text("#statustext")
    assert "Sign in" in said and "page that has your documents" in said and "make the report again" in said
    steps = tab.locator(".nextsteps [data-do=run]")
    assert [b.get_attribute("data-action") for b in steps.all()] == ["login"]
    assert "Support report saved" not in tab.inner_text("#view-run")
    assert tab.locator("[data-do=report-reveal][data-kind=diagnose]").count() == 1, \
        "the file is there, and a sign-in check can be wrong"
    signed_out.unlink()
    tab.click(".nextsteps [data-do=support]")
    tab.click("[data-do=sp-go]")
    tab.wait_for_function("() => RUN.state === 'done' && $('r-title').textContent === 'Support report saved'",
                          timeout=60000)


def test_record_steps_starts_a_recording_from_the_same_dialog(panel, shop):
    tab = panel.tab
    open_get_help(tab)
    tab.click("[data-do=rc-go]")
    tab.wait_for_function("() => RUN.action === 'record'", timeout=60000)
    assert not tab.evaluate("$('dlg-support').open")
    assert tab.locator("#dlg-record").count() == 0
