"""The terms of use, accepted once from the panel.

TERMS.md is what someone using PaperPull agrees to, and the panel asks the
first time it opens and again whenever the terms change. These pin the
answer to the settings file and to the version of the terms, keep the
version tied to the date TERMS.md carries, check every package ships the
terms, and drive the dialog in a real browser, where only I understand may
end it and a page that cannot save the answer still goes on.
"""
import asyncio
import importlib.util
import json
import re
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

REPO = Path(__file__).resolve().parents[2]


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _accept(body):
    return asyncio.run(app_module.api_terms(_Req(body)))


@pytest.fixture
def settings(tmp_path, monkeypatch):
    p = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: p)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    return p


def _asks(html: str) -> bool:
    m = re.search(r"const TERMS_DUE = '(\w+)' === 'true';", html)
    assert m, "the page carries no answer to whether the terms are due"
    return m.group(1) == "true"


def test_a_new_panel_asks_and_stops_asking_once_accepted(settings):
    assert app_module.terms_due()
    assert _asks(app_module.index())
    assert _accept({"accepted": app_module.TERMS_VERSION}) == {"accepted": app_module.TERMS_VERSION}
    assert json.loads(settings.read_text(encoding="utf-8"))["terms_accepted"] == app_module.TERMS_VERSION
    assert not app_module.terms_due()
    assert not _asks(app_module.index())
    assert "const TERMS_VERSION = '%s';" % app_module.TERMS_VERSION in app_module.index()


def test_terms_accepted_before_a_change_are_asked_for_again(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"terms_accepted": "2000-01-01"}), encoding="utf-8")
    assert app_module.terms_due()
    assert _asks(app_module.index())


def test_accepting_keeps_every_other_setting(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"apps_root": "C:/somewhere"}), encoding="utf-8")
    _accept({"accepted": app_module.TERMS_VERSION})
    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "apps_root": "C:/somewhere", "terms_accepted": app_module.TERMS_VERSION}


@pytest.mark.parametrize("body", [{"accepted": "2000-01-01"}, {"accepted": True}, {}, [],
                                  ["accepted", "x"]])
def test_only_the_current_terms_can_be_accepted(settings, body):
    """A page left open across an update, which still carries the old
    version, is told to reload rather than accepting terms it never showed."""
    with pytest.raises(fastapi.HTTPException) as e:
        _accept(body)
    assert e.value.status_code == 409
    assert not settings.exists()
    assert app_module.terms_due()


def test_the_version_is_the_date_at_the_top_of_the_terms():
    """Changing the terms means changing both, or the panel would go on
    taking an answer to terms it no longer shows, or ask about none."""
    text = (REPO / "TERMS.md").read_text(encoding="utf-8")
    m = re.search(r"^Effective (\w+ \d{1,2}, \d{4})\.$", text, re.M)
    assert m, "TERMS.md does not open with the date it took effect"
    assert datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d") == app_module.TERMS_VERSION


def _module(path: Path):
    spec = importlib.util.spec_from_file_location("terms_check_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_package_carries_the_terms():
    """The panel's dialog says a copy comes with the program."""
    sys.path.insert(0, str(REPO / "packaging"))
    try:
        assert "TERMS.md" in _module(REPO / "packaging" / "build_windows.py").INCLUDE_TOP
    finally:
        sys.path.remove(str(REPO / "packaging"))
    assert "TERMS.md" in _module(REPO / "server" / "build.py").ALLOWED
    copy = [line for line in (REPO / "server" / "Dockerfile").read_text(encoding="utf-8").splitlines()
            if line.startswith("COPY ") and "NOTICE.md" in line]
    assert copy and "TERMS.md" in copy[0].split()


# --- what the panel answers before the terms ------------------------------------
#
# The sample can be looked at before the terms, so the dialog is no longer
# all that stands before a run. The panel itself refuses everything real
# until I understand, whatever its page shows, and lets the sample through,
# where nothing can be changed or run.

def test_every_route_of_the_api_waits_for_the_terms_but_the_few_the_dialog_needs():
    """A route added later waits too, unless it is named as one the page
    needs to draw itself behind the dialog or to open the sample."""
    seen, wrong = set(), []
    for route in app_module.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        waits = app_module._terms_first in {d.call for d in route.dependant.dependencies}
        for method in route.methods:
            seen.add((method, path))
            if waits == ((method, path) in app_module.BEFORE_THE_TERMS):
                wrong.append((method, path))
    assert not wrong, "not as BEFORE_THE_TERMS says, %s" % wrong
    assert app_module.BEFORE_THE_TERMS <= seen


def test_before_the_terms_only_the_sample_is_let_through(settings, monkeypatch):
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    with pytest.raises(fastapi.HTTPException) as e:
        app_module._terms_first()
    assert e.value.status_code == 409 and "Accept the Terms of Use first" in e.value.detail
    monkeypatch.setattr(app_module, "_SAMPLE", settings.parent / "sample")
    app_module._terms_first()
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    _accept({"accepted": app_module.TERMS_VERSION})
    app_module._terms_first()


def test_terms_of_another_version_let_nothing_through(settings):
    with pytest.raises(fastapi.HTTPException):
        _accept({"accepted": "2000-01-01"})
    with pytest.raises(fastapi.HTTPException):
        app_module._terms_first()


def test_an_answer_that_could_not_be_saved_lets_the_page_go_on(settings, monkeypatch):
    """The page goes on once I understand is pressed, so the panel does
    too, and the terms are asked again the next time the page opens."""
    def full(data):
        raise OSError("the disk is full")
    monkeypatch.setattr(app_module, "_write_settings", full)
    with pytest.raises(fastapi.HTTPException) as e:
        _accept({"accepted": app_module.TERMS_VERSION})
    assert e.value.status_code == 500
    assert app_module.terms_due()
    app_module._terms_first()


# --- the dialog, in a browser ---------------------------------------------------

sync_api = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")


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
    """The panel, served on a port the system chose, for the whole module."""
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


@pytest.fixture()
def panel(tmp_path, monkeypatch, browser, port):
    """A panel nobody has used yet, every setting under tmp_path, and a tab
    on it."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    (tmp_path / "apps").mkdir()
    for name in ("PAPERPULL_SERVER", "PAPERPULL_PASSWORD", "PAPERPULL_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    context = browser.new_context()
    tab = context.new_page()
    tab.base = "http://127.0.0.1:%d/" % port
    yield tab
    context.close()


def _open(tab) -> bool:
    return tab.evaluate("document.getElementById('dlg-terms').open")


def test_the_dialog_stands_until_i_understand_and_is_not_asked_again(panel):
    panel.goto(panel.base)
    panel.wait_for_selector("#dlg-terms[open]")
    panel.keyboard.press("Escape")
    panel.wait_for_timeout(300)
    assert _open(panel), "Escape ended the terms"
    panel.evaluate("document.getElementById('dlg-terms').close()")
    panel.wait_for_timeout(300)
    assert _open(panel), "closing the dialog by script ended the terms"
    assert app_module.terms_due()

    panel.get_by_role("button", name="I understand").click()
    panel.wait_for_function("!document.getElementById('dlg-terms').open")
    for _ in range(100):
        if not app_module.terms_due():
            break
        time.sleep(0.05)
    assert not app_module.terms_due()
    panel.reload()
    panel.wait_for_selector("#tm-go", state="attached")
    panel.wait_for_timeout(300)
    assert not _open(panel)


def test_a_page_that_cannot_save_the_answer_goes_on_and_asks_next_time(panel):
    panel.route("**/api/terms", lambda route: route.fulfill(
        status=500, content_type="application/json", body='{"detail": "the disk is full"}'))
    panel.goto(panel.base)
    panel.wait_for_selector("#dlg-terms[open]")
    panel.get_by_role("button", name="I understand").click()
    panel.wait_for_function("!document.getElementById('dlg-terms').open")
    panel.get_by_text("could not be saved").wait_for()
    assert app_module.terms_due()
    panel.unroute("**/api/terms")
    panel.reload()
    panel.wait_for_selector("#dlg-terms[open]")


def _ask(tab, method: str, path: str, body=None) -> dict:
    """What the panel answers a request of its own page's."""
    return tab.evaluate("""async ([method, path, body]) => {
        const r = await fetch(path, method === 'GET' ? {} : {
            method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
        let detail = '';
        try { detail = (await r.json()).detail || ''; } catch (e) { /* not JSON */ }
        return {status: r.status, detail: String(detail)};
    }""", [method, path, body])


def _real_requests(tmp_path) -> list:
    """A request for each kind of real use. Adding a provider, which writes
    its install and the folder to the settings, a sign-in, choosing the
    folder, a spreadsheet and the one documents folder."""
    return [("POST", "/api/create", {"root": str(tmp_path / "apps"), "providers": ["kroger"]}),
            ("GET", "/api/run?app=Kroger%20Receipts&action=login", None),
            ("POST", "/api/root", {"root": str(tmp_path / "apps")}),
            ("POST", "/api/export", {}),
            ("POST", "/api/documents/root", {"folder": str(tmp_path / "Documents")})]


def _nothing_real_happened(tmp_path):
    assert list((tmp_path / "apps").iterdir()) == []
    assert not (tmp_path / "Documents").exists()
    settings = app_module._settings_path()
    assert not settings.exists() or "apps_root" not in json.loads(settings.read_text(encoding="utf-8"))
    assert app_module.terms_due()


def _sample_button(tab):
    return tab.get_by_role("button", name="Just look at the sample")


def _until(tab, script: str, seconds: float = 60) -> None:
    """Wait for the page to say yes, asked from outside it, since the
    panel's policy for scripts refuses the one wait_for_function polls with."""
    end = time.monotonic() + seconds
    while not tab.evaluate(script):
        assert time.monotonic() < end, "the page never said %s" % script
        time.sleep(0.1)


def _wait_for_accounts(tab):
    _until(tab, "typeof META !== 'undefined' && META !== null")


def test_the_sample_opens_before_the_terms_and_nothing_real_does(panel, tmp_path):
    panel.goto(panel.base)
    panel.wait_for_selector("#dlg-terms[open]")
    _wait_for_accounts(panel)
    for method, path, body in _real_requests(tmp_path):
        said = _ask(panel, method, path, body)
        assert said["status"] == 409 and "Accept the Terms of Use first" in said["detail"], (path, said)
    _nothing_real_happened(tmp_path)

    _sample_button(panel).click()
    _until(panel, "!document.getElementById('dlg-terms').open")
    assert app_module._SAMPLE is not None
    assert panel.locator("#samplebar").is_visible()
    # In the sample the terms let things through, and the sample refuses
    # every change.
    said = _ask(panel, *_real_requests(tmp_path)[0])
    assert said["status"] == 409 and "sample archive" in said["detail"], said
    _nothing_real_happened(tmp_path)

    panel.locator("#samplebar").get_by_role("button", name="Leave the sample").click()
    panel.wait_for_selector("#dlg-terms[open]")
    assert app_module._SAMPLE is None
    _nothing_real_happened(tmp_path)


def test_a_page_left_on_the_sample_has_the_dialog_back(panel, tmp_path):
    """Another tab left the sample, or the panel started again, while this
    page still shows it with no dialog. The panel refuses its requests, and
    the next time it reads the accounts the dialog is back."""
    panel.goto(panel.base)
    panel.wait_for_selector("#dlg-terms[open]")
    _sample_button(panel).click()
    _until(panel, "!document.getElementById('dlg-terms').open")
    app_module._SAMPLE = None
    for method, path, body in _real_requests(tmp_path):
        said = _ask(panel, method, path, body)
        assert said["status"] == 409 and "Accept the Terms of Use first" in said["detail"], (path, said)
    _nothing_real_happened(tmp_path)
    panel.evaluate("load()")
    panel.wait_for_selector("#dlg-terms[open]")
    panel.wait_for_timeout(300)
    assert _open(panel)


def test_a_sample_that_cannot_be_opened_leaves_the_dialog_standing(panel, tmp_path):
    why = "This copy of PaperPull has no sample archive. Download PaperPull again to repair it."
    panel.route("**/api/sample", lambda route: route.fulfill(
        status=500, content_type="application/json", body=json.dumps({"detail": why})))
    panel.goto(panel.base)
    panel.wait_for_selector("#dlg-terms[open]")
    _wait_for_accounts(panel)
    _sample_button(panel).click()
    panel.locator("#tm-say").get_by_text(why).wait_for()
    panel.wait_for_timeout(300)
    assert _open(panel)
    assert app_module._SAMPLE is None
    _nothing_real_happened(tmp_path)


def test_somebody_with_accounts_is_not_offered_the_sample(panel, tmp_path):
    app_module.create_install(tmp_path / "apps", "kroger")
    panel.goto(panel.base)
    panel.wait_for_selector("#dlg-terms[open]")
    _wait_for_accounts(panel)
    panel.wait_for_timeout(300)
    assert not _sample_button(panel).is_visible()
    assert panel.get_by_role("button", name="I understand").is_visible()
