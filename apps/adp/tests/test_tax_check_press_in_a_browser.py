"""The Tax Statements card's View statement is pressed only when it shows
with nothing over it, in a real browser.

ADP asks for an identity check before it hands over a tax statement, and
the app presses the card's own View statement so that ADP shows its prompt
to the person. That press used to be el.click() run inside the page, which
reaches the button under whatever covers it and presses it hidden. Now the
button is found as the element itself, through the shadow roots it sits in,
and pressing.press_once presses it. A cover or a button that does not show
stops the run, and the run says no prompt is showing then.

The made-up page puts each card's SDF-BUTTON in the shadow root of a shell
of its own, and each SDF-BUTTON draws its own button in a shadow root of
its own around the words it is given, the way the Workforce Now page is
built of web components. Every word and number here is made up.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds the AppSpec
import adp_site as site
from paperpull_core import pressing

sync_api = pytest.importorskip("playwright.sync_api")

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40

# What the page's own viewer fetches once the check is passed, which here
# is the moment the button is pressed.
VIEWER = "/payroll/v1/workers/G0000000000EXAMP/tax-statements/T1/images/w2.pdf"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Pay &amp; Tax Statements</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style>
<script>window.pressed = []; window.coverPresses = 0;</script></head>
<body>
<template id="cards">
  <section><h2>My Pay</h2><sdf-button data-card="pay">View statement</sdf-button></section>
  <section %(card)s><h2>Tax Statements</h2><p>2030 W-2</p>
    <sdf-button data-card="tax" %(button)s>View statement</sdf-button></section>
</template>
<wfn-shell></wfn-shell>
%(extra)s
<script>
class SdfButton extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'}).innerHTML =
      '<style>:host { display: inline-block; } button { width: 200px; height: 40px; }</style>' +
      '<button type="button"><slot></slot></button>';
    this.addEventListener('click', (e) => {
      window.pressed.push([this.dataset.card, e.isTrusted]);
      if (this.dataset.card === 'tax') fetch('%(viewer)s');
    });
  }
}
customElements.define('sdf-button', SdfButton);
class WfnShell extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'}).appendChild(
      document.getElementById('cards').content.cloneNode(true));
  }
}
customElements.define('wfn-shell', WfnShell);
</script>
</body></html>"""

COVER = '<div class="cover" onclick="window.coverPresses++">Chat with us</div>'

# The ways the button can be on the page.
SHOWS = {"card": "", "button": "", "extra": ""}
COVERED = dict(SHOWS, extra=COVER)
HIDDEN = {"button itself": dict(SHOWS, button='style="display: none"'),
          "its card": dict(SHOWS, card='style="display: none"')}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == VIEWER:
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
def statements(browser, monkeypatch):
    """The statements page drawn the way `how` says, on a site of the
    test's own that the app takes for ADP's. Playwright is given half a
    second for its press, which a cover or a hidden button takes whole."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    context = browser.new_context(viewport={"width": 1000, "height": 600})
    monkeypatch.setattr(pressing, "PRESS_MS", 500)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (
        urlsplit(url or "").hostname == "127.0.0.1" and urlsplit(url).port == port))
    # The page is already open, as it is once ADP has refused the statement.
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def open_(how):
        httpd.page = PAGE % dict(how, viewer=VIEWER)
        page = context.new_page()
        page.goto("http://127.0.0.1:%d/statements" % port)
        return page

    yield open_
    context.close()
    httpd.shutdown()
    httpd.server_close()


def test_the_tax_cards_own_button_is_pressed_once_by_playwright(statements):
    page = statements(SHOWS)
    assert site.open_tax_statement_check(page) is True
    # The Tax Statements card's, not the My Pay card's before it, pressed
    # by the browser itself rather than by a script in the page.
    assert page.evaluate("window.pressed") == [["tax", True]]


def test_the_button_is_read_through_its_shadow_roots(statements):
    """What is on top at the button's middle is the button itself, read
    from the element the app hands the press, through the shell's shadow
    root and the button's own, and with a cover it is the cover."""
    for how, state in ((SHOWS, "inside"), (COVERED, "covered")):
        page = statements(how)
        handle = page.evaluate_handle(site._VIEW_STATEMENT_JS).as_element()
        assert handle is not None
        assert handle.evaluate("el => el.localName + ' ' + el.dataset.card") == "sdf-button tax"
        assert pressing.look(page, handle, "sdf-button")["state"] == state
        handle.dispose()


def test_a_covered_button_is_not_pressed_and_the_run_stops(statements):
    page = statements(COVERED)
    with pytest.raises(pressing.Covered):
        site.open_tax_statement_check(page)
    assert page.evaluate("window.pressed") == []
    assert page.evaluate("window.coverPresses") == 0


@pytest.mark.parametrize("how", list(HIDDEN.values()), ids=list(HIDDEN))
def test_a_hidden_button_is_not_pressed_and_the_run_stops(statements, how):
    page = statements(how)
    with pytest.raises(pressing.Stop):
        site.open_tax_statement_check(page)
    assert page.evaluate("window.pressed") == []


def test_no_button_presses_nothing(statements):
    page = statements(SHOWS)
    page.evaluate("() => { for (const card of document.querySelector('wfn-shell')"
                  ".shadowRoot.querySelectorAll('sdf-button')) card.remove(); }")
    assert site.open_tax_statement_check(page) is False
    assert page.evaluate("window.pressed") == []


def test_the_statement_the_viewer_fetches_after_the_press_is_taken(statements, capsys):
    page = statements(SHOWS)
    url = "http://127.0.0.1/never-asked"
    body = site.wait_for_tax_access(page, url, [], seconds=10)
    assert body == _PDF
    assert page.evaluate("window.pressed") == [["tax", True]]
    said = capsys.readouterr().out
    assert "RIGHT NOW" in said and "Could not press" not in said


def test_a_stop_at_the_press_never_says_a_prompt_is_showing(statements, capsys):
    page = statements(COVERED)
    with pytest.raises(pressing.Covered):
        site.wait_for_tax_access(page, "http://127.0.0.1/never-asked", [], seconds=10)
    assert page.evaluate("window.pressed") == []
    assert "RIGHT NOW" not in capsys.readouterr().out
