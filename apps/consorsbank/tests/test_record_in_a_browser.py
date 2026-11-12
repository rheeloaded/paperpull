"""Record starts on a Consorsbank page that keeps its sign-in window unshown.

Consorsbank keeps its sign-in window in every page, signed in or not. The
form sits inside web components and is drawn only when the window is asked
for. This app and the core's recorder counted every password field in the
page, so a tester signed in on the bank was told on every page to sign in
first, and Record never started (#178). This app's PASSWORD_FIELD asks
both for only the fields the page draws. The sign-in address is still
refused before its form is drawn, and the window once drawn is refused.

A simulated page in Playwright's own Chromium, never the Edge or Chrome on
this computer, with every name resolved to nowhere so nothing reaches the
bank. The page is invented and holds nothing of anyone's.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import consorsbank_site as site
from paperpull_core import recorder

pw_api = pytest.importorskip("playwright.sync_api")

ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

# The shape the bank's pages had on 2026-11-11, a form inside a component
# whose shadow root gives it no slot until the window opens.
PAGE = """
<h1>Postbox</h1>
<a href="/web/postbox">Postbox</a>
<sign-in-window>
  <wb-modal><login-form><form>
    <input type="text" name="user"><input type="password" name="pin">
  </form></login-form></wb-modal>
</sign-in-window>
<script>
customElements.define('sign-in-window', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML = '<div></div>'; }
  open() { this.shadowRoot.innerHTML = '<div><slot></slot></div>'; }
});
</script>
"""


@pytest.fixture
def page():
    with pw_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(headless=True, args=ARGS)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html", body=PAGE))
        pg = context.new_page()
        try:
            yield pg
        finally:
            context.close()
            browser.close()


def _refusal(page):
    """As record_session builds it from this app's site module."""
    return recorder.Recorder(page, is_safe_url=site.is_safe_url,
                             looks_signed_out=site.looks_signed_out,
                             is_safe_control=site.is_safe_control,
                             provider="Consorsbank",
                             password_field=site.PASSWORD_FIELD).refusal()


def test_record_starts_on_a_bank_page_that_keeps_the_window_unshown(page):
    page.goto("https://www.consorsbank.de/web/postbox")
    assert page.locator("input[type='password']").count() == 1
    assert not site.looks_signed_out(page)
    assert _refusal(page) is None


def test_the_window_once_shown_is_a_sign_in_page(page):
    page.goto("https://www.consorsbank.de/web/postbox")
    page.evaluate("document.querySelector('sign-in-window').open()")
    page.wait_for_timeout(100)
    assert site.looks_signed_out(page)
    assert "not signed in yet" in (_refusal(page) or "")


def test_the_sign_in_address_is_refused_before_its_form_is_drawn(page):
    page.goto("https://www.consorsbank.de/home?showEVLoginForm=true")
    assert site.looks_signed_out(page)
    assert "not signed in yet" in (_refusal(page) or "")
