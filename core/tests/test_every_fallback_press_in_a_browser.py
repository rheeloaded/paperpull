"""Every app's capture presses through pressing.press_once, and in a real
browser none of them presses a control under a cover or presses one twice.

Twelve apps pressed their document's control through the page, el.click()
inside an evaluate, whenever Playwright's own click raised. That press
reached the control under whatever covered it, since Playwright's error
said so and nothing read it, and after a press of Playwright's that had
landed before it raised it was a second press. Each app's own _catch_pdf
is pressed here against a page made for it, three ways.

  * Something covers the control. Playwright says so, nothing is pressed,
    the cover least of all, and the run stops.
  * Playwright's press lands and raises before it says how it ended. The
    run stops, and the control was pressed once.
  * Playwright's press lands and raises after it says the press was done.
    Nothing is pressed again, and the statement the press brought is saved.

The two presses that raise are made by Playwright's own press, which then
raises the way Playwright does in each case, since a page cannot make
Playwright raise after a press at will. Every word here is made up.
"""
import ast
import importlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from paperpull_core import pressing

sync_api = pytest.importorskip("playwright.sync_api")

REPO = Path(__file__).resolve().parents[2]

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style>
<script>window.presses = 0; window.coverPresses = 0;</script></head>
<body><main><h1>Statements</h1>
<table><tr><td>June 30, 2026</td>
<td><button id="get" type="button" style="width: 220px; height: 40px"
  onclick="window.presses++; fetch('/statement.pdf');">Download statement</button></td>
</tr></table></main>%s</body></html>"""

COVER = '<div class="cover" onclick="window.coverPresses++">Chat with us</div>'

# Playwright's account of a press it began and never finished, and of one
# it finished before its time ran out waiting on what the press started.
BEGUN = ('ElementHandle.click: Timeout 500ms exceeded.\nCall log:\n'
         '  - attempting click action\n'
         '    - waiting for element to be visible, enabled and stable\n'
         '    - element is visible, enabled and stable\n'
         '    - scrolling into view if needed\n'
         '    - done scrolling\n'
         '    - performing click action\n')
DONE = BEGUN + '    - click action done\n    - waiting for scheduled navigations to finish\n'


def presses_through_press_once(app: Path) -> bool:
    """Whether the app's capture, _catch_pdf, presses through press_once."""
    path = app / ("%s_site.py" % app.name)
    if not path.exists():
        return False
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="ignore"))):
        if isinstance(node, ast.FunctionDef) and node.name == "_catch_pdf":
            return any(isinstance(n, ast.Attribute) and n.attr == "press_once"
                       and isinstance(n.value, ast.Name) and n.value.id == "pressing"
                       for n in ast.walk(node))
    return False


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(("_", ".")) and presses_through_press_once(d))


def site_of(app: Path):
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    body = b""

    def do_GET(self):
        if self.path.startswith("/statement.pdf"):
            body, kind = _PDF, "application/pdf"
        else:
            body, kind = self.server.page.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def capture(browser, tmp_path, monkeypatch):
    """Run an app's own _catch_pdf on the statements page, with `extra` on
    the page, on a site of the test's own. Playwright is given half a second
    for its press, which a cover takes whole."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    context = browser.new_context(viewport={"width": 1000, "height": 600})
    monkeypatch.setattr(pressing, "PRESS_MS", 500)

    def run(app, extra=""):
        site = site_of(app)
        monkeypatch.setattr(site, "is_safe_url", lambda url: (
            urlsplit(url or "").hostname == "127.0.0.1" and urlsplit(url).port == port))
        if hasattr(site, "CLICK_TIMEOUT_MS"):
            monkeypatch.setattr(site, "CLICK_TIMEOUT_MS", 500)
        httpd.page = PAGE % extra
        page = context.new_page()
        page.goto("http://127.0.0.1:%d/statements" % port)
        out = tmp_path / app.name / "2026-06-30 Statement.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = tmp_path / app.name / "downloads"
        staging.mkdir()
        page.result = {}
        try:
            page.result["saved"] = site._catch_pdf(page, page.query_selector("#get"),
                                                   "Download statement", out, [], staging)
        except pressing.Stop as stop:
            page.result["stop"] = stop
        page.result["out"] = out
        return page

    yield run
    context.close()
    httpd.shutdown()
    httpd.server_close()


def raising_after_the_press(monkeypatch, account):
    """Playwright's own press, which then raises with `account` once the
    statement the press asked for has answered, so the capture has heard
    it by the time it looks."""
    real = sync_api.ElementHandle.click

    def click(self, *args, **kwargs):
        # Its own time, so a slow machine still makes the press it is about.
        kwargs["timeout"] = 15000
        with self.owner_frame().page.expect_response(lambda r: "statement.pdf" in r.url):
            real(self, *args, **kwargs)
        raise sync_api.TimeoutError(account)
    monkeypatch.setattr(sync_api.ElementHandle, "click", click)


def test_every_app_that_pressed_through_the_page_is_here():
    """Not vacuous. The twelve whose capture had the page press, by what the
    capture does."""
    assert {d.name for d in APPS} >= {"adp", "amfam", "applecard", "att", "etrade", "golden1",
                                       "newrez", "sba", "smud", "statefarm", "verizonmobile",
                                       "wellsfargo"}


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_covered_control_is_not_pressed_and_the_run_stops(capture, app):
    page = capture(app, COVER)
    assert isinstance(page.result.get("stop"), pressing.Covered), page.result
    assert page.evaluate("window.presses") == 0, "the control was pressed under the cover"
    assert page.evaluate("window.coverPresses") == 0
    assert not page.result["out"].exists()


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_press_that_landed_and_raised_unfinished_is_not_made_again(capture, app, monkeypatch):
    raising_after_the_press(monkeypatch, BEGUN)
    page = capture(app)
    assert isinstance(page.result.get("stop"), pressing.Unsure), page.result
    assert page.evaluate("window.presses") == 1, "the control was pressed twice"


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_press_that_landed_and_raised_done_saves_what_it_brought(capture, app, monkeypatch):
    raising_after_the_press(monkeypatch, DONE)
    page = capture(app)
    assert "stop" not in page.result, page.result
    assert page.result["saved"] is True
    assert page.result["out"].read_bytes() == _PDF
    assert page.evaluate("window.presses") == 1, "the control was pressed twice"
