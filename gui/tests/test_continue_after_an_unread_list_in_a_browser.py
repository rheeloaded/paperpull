"""After a Resume that had nothing more to carry on with, the page offers
Get new documents, never Continue, run by the page itself.

Chase's Continue went round and round (#124). A run stopped before it read
the whole list, and every Resume after it said the list was not read to its
end and to run Pilot or Run All, then stopped as a run that stopped. The
page took that as any stop and offered Continue again. These run the page's
own script, in Playwright's own headless Chromium, against the real panel
served on a free local port. The one app is a script that writes down the
arguments it was started with, and whose Resume stops as one only a run
that lists carries on from when a file named unread sits beside it, or as
any other stop when it does not. Every setting is under a temp folder, and
no browser of the person's is started.
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
import json, os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
with open(here / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
resume = "--resume" in sys.argv
counts = {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0,
          "stopped": 1 if resume else 0}
if resume and (here / "unread").exists():
    counts["list_not_read"] = 1
print("PAPERPULL_RUN_RESULT " + os.environ.get("PAPERPULL_RUN_MARK", "") + " " + json.dumps(counts))
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
    """An apps root of its own holding the one app, whose last run, a Run
    All, stopped partway, so its page offers Continue."""
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
    root = app_module._account_root({"dir": str(folder)}, "primary")
    root.mkdir(parents=True, exist_ok=True)
    (root / app_module.RUN_LOG).write_text(json.dumps([
        {"action": "all", "exit_code": 0, "ended": "2026-10-28T09:00:00",
         "result": {"stopped": 1}}]), encoding="utf-8")
    return folder


@pytest.fixture()
def panel(browser, base, shop):
    context = browser.new_context()
    tab = context.new_page()
    asked = []

    def answer(dialog):
        asked.append(dialog.message)
        dialog.dismiss()
    tab.on("dialog", answer)
    tab.goto(base + ACCOUNT)
    tab.wait_for_selector("#view-account [data-do=run][data-action=resume]")
    yield SimpleNamespace(tab=tab, asked=asked, base=base)
    context.close()


def started(folder) -> list:
    listed = folder / "argv.jsonl"
    if not listed.exists():
        return []
    return [json.loads(line) for line in listed.read_text(encoding="utf-8").splitlines()]


def finished(tab):
    tab.wait_for_function("() => RUN.state === 'done'", timeout=60000)


def back(panel):
    panel.tab.evaluate("location.hash = %r" % ACCOUNT[1:])
    panel.tab.wait_for_selector("#view-account [data-do=run][data-action=all]")


def continue_from_the_account(panel):
    panel.tab.click("#view-account [data-do=run][data-action=resume]")
    finished(panel.tab)


def test_a_resume_with_nothing_more_to_carry_on_with_offers_get_new(panel, shop):
    (shop / "unread").write_text("", encoding="utf-8")
    tab = panel.tab
    continue_from_the_account(panel)
    assert tab.inner_text("#r-title") == "Stopped before finishing"
    said = tab.inner_text("#statustext")
    assert "list was not read to its end" in said and "signed you out" not in said
    steps = tab.locator(".nextsteps")
    assert steps.locator("[data-action=resume]").count() == 0
    steps.locator("[data-action=all]").click()
    finished(tab)
    assert started(shop) == [["--resume", "--yes"], ["--all", "--yes"]]
    assert panel.asked == []


def test_the_account_and_home_pages_offer_get_new_after_it(panel, shop):
    (shop / "unread").write_text("", encoding="utf-8")
    tab = panel.tab
    continue_from_the_account(panel)
    back(panel)
    band = tab.locator("#view-account .band")
    assert band.locator("[data-action=resume]").count() == 0
    assert "Get new reads the list again" in band.inner_text()
    assert tab.locator("#view-account [data-action=resume]").count() == 0
    tab.evaluate("location.hash = '#/'")
    tab.wait_for_selector("#view-home [data-key]")
    home = tab.locator("#view-home")
    assert home.locator("[data-do=run][data-action=resume]").count() == 0
    home.locator(".summary [data-do=run][data-action=all]").click()
    finished(tab)
    assert started(shop) == [["--resume", "--yes"], ["--all", "--yes"]]


def test_any_other_stop_is_still_continued(panel, shop):
    """The other side. A Resume that stopped any other way, for a sign-in
    say, is carried on with Continue as before."""
    tab = panel.tab
    continue_from_the_account(panel)
    assert "signed you out" in tab.inner_text("#statustext")
    assert tab.locator(".nextsteps [data-action=resume]").count() == 1
    assert tab.locator(".nextsteps [data-action=all]").count() == 0
    back(panel)
    assert tab.locator("#view-account .band [data-action=resume]").count() == 1


def test_get_new_for_all_reads_the_list_of_each_such_account(panel, shop):
    """The round of runs for every account that needs one took Continue for
    every stopped account, so it too would have gone round again."""
    tab = panel.tab
    bank = shop.with_name("Bank Docs")
    bank.mkdir()
    (bank / "bank_docs.py").write_text(APP, encoding="utf-8")
    for folder in (shop, bank):
        root = app_module._account_root({"dir": str(folder)}, "primary")
        root.mkdir(parents=True, exist_ok=True)
        (root / app_module.RUN_LOG).write_text(json.dumps([
            {"action": "resume", "exit_code": 0, "ended": "2026-10-28T09:00:00",
             "result": {"stopped": 1, "list_not_read": 1}}]), encoding="utf-8")
    tab.evaluate("location.hash = '#/'")
    tab.reload()
    tab.wait_for_selector("#view-home [data-do=queue]")
    tab.click("#view-home [data-do=queue]")
    tab.wait_for_function("() => QUEUE && QUEUE.finished", timeout=120000)
    assert started(shop) == [["--all", "--yes"]] and started(bank) == [["--all", "--yes"]]
