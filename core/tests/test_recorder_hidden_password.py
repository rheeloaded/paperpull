"""A sign-in window a provider keeps but never draws stops a recording only
where the provider has not said so.

Consorsbank keeps its sign-in window in every page, signed in or not. The
form sits inside a web component whose shadow root has no slot for it
until the window is asked for, so it is in the page and never drawn. The
recorder counted every password field in the page, so it refused each
page of the bank a tester was signed in on, and Record never started
(#178). A site module may now ask for only the fields its pages draw.
Every other provider keeps the strict count, since a field kept out of
sight may be the next step of a sign-in. A field the page draws refuses
either way, in each of the ways a page can keep a form out of sight.

In a real browser, because whether a field is drawn is the browser's
doing and a fake page can only be told the answer.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

pw_api = pytest.importorskip("playwright.sync_api")

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

UNDRAWN = ["/component", "/hidden-box", "/dialog"]


@pytest.fixture()
def browser_page():
    with pw_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        try:
            ctx = browser.new_context()

            def answer(route):
                path = "/" + route.request.url.split(HOST, 1)[1].lstrip("/")
                route.fulfill(status=200, content_type="text/html", body=PAGES[path])

            ctx.route("%s/**" % HOST, answer)
            yield ctx.new_page()
        finally:
            browser.close()


def _refusal(page, password_field=recorder.PASSWORD_FIELD):
    return recorder.Recorder(page, is_safe_url=lambda u: (u or "").startswith(HOST),
                             provider="Testco", password_field=password_field).refusal()


@pytest.mark.parametrize("path", UNDRAWN)
def test_a_field_the_page_never_draws_still_refuses_by_default(browser_page, path):
    browser_page.goto(HOST + path)
    assert browser_page.locator("input[type='password']").count() == 1
    assert "password field" in (_refusal(browser_page) or "")


@pytest.mark.parametrize("path", UNDRAWN)
def test_a_provider_that_asks_for_drawn_fields_lets_the_recording_start(browser_page, path):
    browser_page.goto(HOST + path)
    assert _refusal(browser_page, recorder.DRAWN_PASSWORD_FIELD) is None


@pytest.mark.parametrize("path", UNDRAWN)
def test_the_same_field_once_drawn_refuses_either_way(browser_page, path):
    browser_page.goto(HOST + path)
    browser_page.evaluate("show()")
    browser_page.wait_for_timeout(100)
    assert "password field" in (_refusal(browser_page) or "")
    assert "password field" in (_refusal(browser_page, recorder.DRAWN_PASSWORD_FIELD) or "")


def test_a_sign_in_page_refuses(browser_page):
    browser_page.goto(HOST + "/sign-in")
    assert "password field" in (_refusal(browser_page, recorder.DRAWN_PASSWORD_FIELD) or "")
