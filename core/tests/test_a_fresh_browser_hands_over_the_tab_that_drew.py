"""testkit.drawn_browser hands a browser over only once a tab of it has
drawn a page, and with only_tab the tab that drew is the browser's only
one, in a real browser.

Target worked in the first tab it found rather than in a tab it opens for
itself. A browser from drawn_browser without only_tab keeps its own blank
tab beside the one that drew, and Playwright listed the two in no fixed
order, the blank one first in three fresh starts of seven, so the app
worked in a tab nothing had shown could draw. Target's page check test
was handed the drawn tab alone with only_tab for that, and this holds the
helper to it for any app that works in the first tab it finds.

The first page the browser asks for is answered three seconds late, so a
helper that handed the browser over without waiting for its tab would be
caught handing over a tab with nothing drawn in it yet. The browser is
Playwright's own Chromium and resolves no host name, so nothing leaves
this machine.
"""
import json
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

import pytest

from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
READY = "drawn before the app attaches"


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture()
def answered_late(monkeypatch):
    """The first answer any server here gives waits three seconds, and
    what was asked for is kept."""
    real = BaseHTTPRequestHandler.send_response
    asked = []

    def send_response(self, *args, **kwargs):
        if not asked:
            asked.append(self.path)
            time.sleep(3)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(BaseHTTPRequestHandler, "send_response", send_response)
    return asked


def listed(url):
    """The browser's tabs as the browser itself lists them, as (address,
    title), with nothing attached. Within a second of the hand over one of
    them has to be the ready page, and the page answered three seconds late
    is not yet. Attaching would not show it, since Playwright waits for a
    tab still loading before it lists it, once for three minutes."""
    deadline = time.monotonic() + 1
    while True:
        with urllib.request.urlopen(url + "/json/list", timeout=10) as r:
            tabs = [(t.get("url"), t.get("title")) for t in json.loads(r.read().decode("utf-8"))
                    if t.get("type") == "page"]
        if any(title == READY for _, title in tabs) or time.monotonic() > deadline:
            return tabs
        time.sleep(0.05)


def handed_over(browser_exe, tmp_path_factory, **kwargs):
    """The browser's tabs at the moment it is handed over, as the browser
    lists them, and as an attaching app then finds them."""
    from playwright.sync_api import sync_playwright
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("profile"),
                                   args=(NO_HOSTS,), **kwargs) as url:
            tabs = listed(url)
            with sync_playwright() as p:
                pages = p.chromium.connect_over_cdp(url, timeout=30000).contexts[0].pages
                found = [(page.url, page.title()) for page in pages]
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")
    return tabs, found


def test_the_browser_is_handed_over_once_a_tab_drew(browser_exe, tmp_path_factory,
                                                    answered_late):
    tabs, found = handed_over(browser_exe, tmp_path_factory)
    assert answered_late, "the ready page was asked for"
    assert any(title == READY for _, title in tabs), tabs


def test_with_only_tab_the_tab_that_drew_is_the_only_one_an_app_can_find(browser_exe,
                                                                        tmp_path_factory,
                                                                        answered_late):
    tabs, found = handed_over(browser_exe, tmp_path_factory, only_tab=True)
    assert answered_late, "the ready page was asked for"
    assert len(tabs) == 1 and tabs[0][1] == READY, tabs
    assert len(found) == 1 and found[0][1] == READY, found
