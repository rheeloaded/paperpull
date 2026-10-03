"""testkit.drawn_browser with only_tab hands over a browser whose only tab
is the one that drew, in a real browser.

Target works in the first tab it finds rather than in a tab it opens for
itself. A browser from drawn_browser without only_tab keeps its own blank
tab beside the one that drew, and Playwright listed the two in no fixed
order, the blank one first in two fresh starts of four, so the app worked
in a tab nothing had shown could draw. Target's page check test relies on
only_tab for that, and this holds the helper to it.

The browser is Playwright's own Chromium and resolves no host name, so
nothing leaves this machine.
"""
import json
import urllib.request

import pytest

from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


def page_tabs(url):
    with urllib.request.urlopen(url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page"]


def test_the_tab_that_drew_is_the_only_one_and_the_first_an_app_finds(browser_exe,
                                                                     tmp_path_factory):
    from playwright.sync_api import sync_playwright
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("profile"),
                                   args=(NO_HOSTS,), only_tab=True) as url:
            listed = [t.get("url") for t in page_tabs(url)]
            with sync_playwright() as p:
                pages = p.chromium.connect_over_cdp(url).contexts[0].pages
                found = [(page.url, page.title()) for page in pages]
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")
    assert len(listed) == 1, listed
    assert len(found) == 1 and found[0][1] == "drawn before the app attaches", found
