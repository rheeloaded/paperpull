"""A sign-in window a page keeps but never draws does not stop a recording.

Consorsbank keeps its sign-in window in every page, signed in or not. The
form sits inside a web component whose shadow root has no slot for it
until the window is asked for, so it is in the page and never drawn. The
recorder counted every password field in the page, so it refused each
page of the bank a tester was signed in on, and Record never started
(#178). It counts the fields a person can see now. One the page shows
still refuses, in each of the ways a page can keep a form out of sight.

In a real browser, because whether a field is drawn is the browser's
doing and a fake page can only be told the answer.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

HOST = "https://bank.test"

FORM = '<form><input type="text" name="user"><input type="password" name="pin"></form>'

PAGES = {
    # The way Consorsbank keeps it. The component draws its own children
    # only once open() gives its shadow root a slot.
    "/component": """
<h1>Postbox</h1>
<sign-in-window>%s</sign-in-window>
<script>
customElements.define('sign-in-window', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML = '<div></div>'; }
  open() { this.shadowRoot.innerHTML = '<div><slot></slot></div>'; }
});
function show() { document.querySelector('sign-in-window').open(); }
</script>""" % FORM,
    "/hidden-box": """
<h1>Postbox</h1>
<div id="box" style="display:none">%s</div>
<script>function show() { document.getElementById('box').style.display = 'block'; }</script>
""" % FORM,
    "/dialog": """
<h1>Postbox</h1>
<dialog id="box">%s</dialog>
<script>function show() { document.getElementById('box').showModal(); }</script>
""" % FORM,
    "/sign-in": "<h1>Sign in</h1>%s" % FORM,
}


@pytest.fixture()
def browser_page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()

    def answer(route):
        path = "/" + route.request.url.split(HOST, 1)[1].lstrip("/")
        route.fulfill(status=200, content_type="text/html", body=PAGES[path])

    ctx.route("%s/**" % HOST, answer)
    pg = ctx.new_page()
    yield pg
    browser.close()
    driver.stop()


def _refusal(page):
    return recorder.Recorder(page, is_safe_url=lambda u: (u or "").startswith(HOST),
                             provider="Testco").refusal()


@pytest.mark.parametrize("path", ["/component", "/hidden-box", "/dialog"])
def test_a_password_field_the_page_never_draws_lets_the_recording_start(browser_page, path):
    browser_page.goto(HOST + path)
    assert browser_page.locator("input[type='password']").count() == 1, \
        "the field is in the page, which is what the old check counted"
    assert _refusal(browser_page) is None


@pytest.mark.parametrize("path", ["/component", "/hidden-box", "/dialog"])
def test_the_same_field_once_the_page_shows_it_refuses(browser_page, path):
    browser_page.goto(HOST + path)
    browser_page.evaluate("show()")
    browser_page.wait_for_timeout(100)
    assert "password field" in (_refusal(browser_page) or "")


def test_a_sign_in_page_refuses(browser_page):
    browser_page.goto(HOST + "/sign-in")
    assert "password field" in (_refusal(browser_page) or "")
