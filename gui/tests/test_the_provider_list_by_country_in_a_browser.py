"""The provider list starts on the computer's country, and Amazon's kind
of provider asks which store, in the page's own script.

Runs the real panel on a free local port in Playwright's own headless
Chromium, each browser given a language setting of its own. Every setting
and folder is under a temp folder, and every provider is invented.
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

TEMPLATES = {
    "bank": ('provider="Bank",\n    countries=("DE",),\n    kind=DOCUMENT,', {}),
    "usb": ('provider="Usb",\n    countries=("US",),\n    kind=DOCUMENT,', {}),
    "pay": ('provider="Pay",\n    countries=("US",),\n    may_work_elsewhere=True,\n    kind=DOCUMENT,', {}),
    "mart": ('provider="Mart",\n    countries=("US", "DE", "GB"),\n'
             '    stores={"mart.com": "US", "mart.de": "DE", "mart.co.uk": "GB"},\n'
             '    store_setting="site",\n    kind=RECEIPT,', {"site": "mart.com"}),
}


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
    """One account already there, so the list opens as Add providers, and
    the four invented templates to choose from."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    root = tmp_path / "PaperPull"
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION,
                                "apps_root": str(root)})
    monkeypatch.delenv("APPS_ROOT", raising=False)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    monkeypatch.setattr(app_module, "refresh_installs", lambda: {})
    monkeypatch.setattr(app_module, "_provider_notes", lambda: {})
    app_module._RUNS.clear()
    old = root / "Old Statements"
    old.mkdir(parents=True)
    (old / "old_docs.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    (old / "storage.py").write_text('SPEC = dict(provider="Old", kind=DOCUMENT)\n', encoding="utf-8")
    templates = tmp_path / "templates" / "apps"
    for n, (slug, (spec, extra)) in enumerate(TEMPLATES.items()):
        d = templates / slug
        d.mkdir(parents=True)
        (d / ("%s_docs.py" % slug)).write_text("# entry\n", encoding="utf-8")
        (d / "storage.py").write_text("SPEC = AppSpec(\n    %s\n)\n" % spec, encoding="utf-8")
        (d / "config.example.json").write_text(json.dumps(dict(
            {"cdp_url": "http://127.0.0.1:%d" % (9291 + n), "output_dir": "."}, **extra)),
            encoding="utf-8")
    monkeypatch.setattr(app_module, "_templates_root", lambda: templates)
    return root


def opened(browser, base, locale):
    context = browser.new_context(locale=locale)
    page = context.new_page()
    page.goto(base + "/#/add")
    page.wait_for_selector("#providers .ptile")
    return context, page


def tiles(page) -> list:
    return page.eval_on_selector_all("#providers .ptile b", "els => els.map(e => e.textContent)")


def pressed(page) -> str:
    return page.inner_text('#w-countries .fchip[aria-pressed="true"]')


def test_a_german_browser_starts_on_germany(browser, base, apps):
    context, page = opened(browser, base, "de-DE")
    try:
        assert pressed(page).startswith("Germany")
        assert tiles(page) == ["Bank", "Mart", "Pay"], \
            "Germany's own first, then Mart's several countries, then Pay's one site worldwide, never Usb"
        assert page.inner_text("#providers .ptile:has(b:text-is('Bank')) .where") == "Germany"
        assert page.inner_text("#providers .ptile:has(b:text-is('Mart')) .where") == "3 countries"
        assert page.inner_text("#providers .ptile:has(b:text-is('Pay')) .where") == \
            "United States, may work elsewhere"
        page.click('#w-countries .fchip[data-country="all"]')
        assert sorted(tiles(page)) == ["Bank", "Mart", "Pay", "Usb"]
    finally:
        context.close()


def test_a_search_finds_a_provider_of_another_country(browser, base, apps):
    context, page = opened(browser, base, "de-DE")
    try:
        page.fill("#w-search", "usb")
        assert tiles(page) == ["Usb"]
    finally:
        context.close()


def test_an_american_browser_starts_on_the_united_states(browser, base, apps):
    context, page = opened(browser, base, "en-US")
    try:
        assert pressed(page).startswith("United States")
        assert tiles(page) == ["Pay", "Usb", "Mart"], \
            "the United States' own first, Pay among them since it was built there, then Mart"
    finally:
        context.close()


def test_a_country_with_no_provider_of_its_own_starts_on_all(browser, base, apps):
    """en-GB on a US account, say. Only Mart has a British store, and it is
    a provider of several countries, so nothing is hidden."""
    context, page = opened(browser, base, "en-GB")
    try:
        assert pressed(page) == "All countries"
        assert sorted(tiles(page)) == ["Bank", "Mart", "Pay", "Usb"]
    finally:
        context.close()


def test_the_store_starts_on_the_home_country_and_is_set_up(browser, base, apps):
    context, page = opened(browser, base, "de-DE")
    try:
        page.click("#providers .ptile:has(b:text-is('Mart'))")
        page.click("#w-next2")
        page.wait_for_selector("#w-store-mart")
        assert page.eval_on_selector("#w-store-mart", "s => s.value") == "mart.de"
        assert page.inner_text("label[for=w-store-mart]") == "Which Mart store?"
        page.select_option("#w-store-mart", "mart.co.uk")
        page.click("#w-create")
        page.wait_for_function("() => !location.hash.startsWith('#/add')", timeout=15000)
        cfg = json.loads((apps / "Mart Receipts (mart.co.uk)" / "config.json").read_text(encoding="utf-8"))
        assert cfg["site"] == "mart.co.uk"
    finally:
        context.close()


def test_a_store_already_set_up_is_not_offered_again(browser, base, apps):
    folder = apps / "Mart Receipts"
    folder.mkdir()
    (folder / "mart_docs.py").write_text("# entry\n", encoding="utf-8")
    (folder / "config.json").write_text(json.dumps({"site": "mart.de"}), encoding="utf-8")
    context, page = opened(browser, base, "de-DE")
    try:
        assert "Set up for mart.de" in page.inner_text("#providers .ptile:has(b:text-is('Mart'))")
        page.click("#providers .ptile:has(b:text-is('Mart'))")
        page.click("#w-next2")
        page.wait_for_selector("#w-store-mart")
        options = page.eval_on_selector_all("#w-store-mart option", "os => os.map(o => o.value)")
        assert options == ["mart.com", "mart.co.uk"]
        assert page.eval_on_selector("#w-store-mart", "s => s.value") == "mart.com"
    finally:
        context.close()
