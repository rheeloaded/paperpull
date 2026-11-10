"""A provider goes by its name, and an example path fits the computer.

The File names picker, the Updated notice and File names' Stopped at line
said the folder's name, "Shop Docs", where every other page says the
provider's. These run the page's own script, in Playwright's own headless
Chromium, against the real panel on a free local port. Every setting is
under a temp folder, and no browser of the person's is started.
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

STORAGE = 'SPEC = dict(provider="Shop & Co", kind=DOCUMENT)\n'


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
    monkeypatch.setattr(app_module, "refresh_installs", lambda: {"Shop Docs": {}})
    app_module._RUNS.clear()
    folder = tmp_path / "apps" / "Shop Docs"
    folder.mkdir(parents=True)
    (folder / "shop_docs.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    (folder / "storage.py").write_text(STORAGE, encoding="utf-8")
    return folder


@pytest.fixture()
def tab(browser, base, shop):
    context = browser.new_context()
    page = context.new_page()
    page.goto(base + "/#/settings")
    page.wait_for_selector("#view-settings:not([hidden])")
    yield page
    context.close()


def test_the_updated_notice_says_the_providers_name(tab):
    said = tab.inner_text("#noticetext")
    assert said.startswith("Updated Shop & Co to this version")
    assert "Shop Docs" not in said


def test_the_picker_shows_the_name_and_keeps_the_folder_as_its_value(tab):
    tab.evaluate("location.hash = '#/names'")
    tab.wait_for_function("() => $('nmapp').options.length > 0")
    option = tab.evaluate("(() => { const o = $('nmapp').options[0]; return [o.textContent, o.value]; })()")
    assert option == ["Shop & Co", "Shop Docs"]


def test_two_folders_of_one_provider_can_be_told_apart(tab):
    tab.evaluate("""() => {
      META.apps['Shop Docs 2'] = META.apps['Shop Docs'];
      META.provider_names['Shop Docs 2'] = 'Shop & Co';
      openNames();
    }""")
    labels = tab.evaluate("[...$('nmapp').options].map(o => o.textContent)")
    assert labels == ["Shop & Co (Shop Docs)", "Shop & Co (Shop Docs 2)"]


def test_a_stopped_rename_says_the_providers_name(tab):
    tab.evaluate("location.hash = '#/names'")
    tab.wait_for_function("() => $('nmapp').options.length > 0")
    tab.evaluate("""() => { NM_OFFER = ['Shop Docs']; nmRename(false); }""")
    tab.wait_for_function("() => $('nmofferstate').textContent.startsWith('Stopped at')", timeout=60000)
    said = tab.inner_text("#nmofferstate")
    assert said.startswith("Stopped at Shop & Co,") and "Shop Docs" not in said


@pytest.mark.parametrize("root, example", [
    ("/Users/someone/PaperPull", "/Users/you/Documents/PaperPull"),
    ("C:\\Users\\someone\\PaperPull", "C:\\Users\\you\\Documents\\PaperPull")])
def test_the_folder_field_gives_an_example_for_this_computer(tab, root, example):
    tab.evaluate("r => { META.apps_root = r; renderSettings(); }", root)
    assert tab.get_attribute("#rootinput", "placeholder") == example


@pytest.mark.parametrize("count", ["1 receipt needs review.", "2 receipts need review."])
def test_review_names_says_its_count_once(tab, count):
    """The app's own count line, "1 receipt needs review." for one since
    counts read alike, is left out of what Review names says, which counts
    the receipts itself. A line about rows left out is kept."""
    receipts = [{"id": "C:/out/2026-05-14 Unsure Receipt.pdf", "number": "ORDER-0001", "date": "2026-05-14",
                 "file": "2026-05-14 Unsure Receipt.pdf", "summary": "Unsure", "items": ["Invented Hose"]}]
    left_out = "1 row marked for review has no receipt PDF in this app's folders to rename, so it is left out."
    tab.route("**/api/review-names", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"receipts": receipts, "said": [left_out, count]})))
    tab.evaluate("openReview({app: 'Shop Docs', account: 'primary', provider: 'Shop & Co', kind: 'receipts'})")
    tab.wait_for_function("() => $('rv-state').textContent.includes('waiting for a better name')")
    said = tab.inner_text("#rv-state")
    assert said.startswith("1 receipt waiting for a better name.")
    assert "left out" in said and "review." not in said
