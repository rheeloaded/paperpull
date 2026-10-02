"""A second tab the View Documents press opened is closed, never read.

The press adopts the first new tab that leaves the bank for an https site
as the vendor's and keeps it open, since the run works in it. It looked at
the new tabs in turn and stopped at the one it adopted, so another tab the
same press had opened was never looked at and never closed, and stayed open
in the member's browser.

In a real browser, under the real host names so the host checks run as they
do for a member. Every page here is made up and served from memory, and
every other request is refused, so nothing leaves this machine.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import golden1_site as site  # noqa: E402

DOCUMENTS = "https://digitalbanking.golden1.com/accounts/documents"
VENDOR_URL = "https://ebank.hepsiian.com/statements"
ELSEWHERE = "https://elsewhere.example/survey"
HANDOFF = "https://digitalbanking.golden1.com/accounts/handoff"


@pytest.fixture()
def bank(monkeypatch):
    # Adopting the vendor's tab remembers it and its host for the run. Kept
    # to this test so nothing it adds is seen by another.
    monkeypatch.setattr(site, "_VENDOR_HOSTS_SEEN", set())
    monkeypatch.setattr(site, "_ADOPTED_TABS", [])
    monkeypatch.setattr(site, "_LAST_OPEN", {})
    monkeypatch.setattr(site, "ALLOWED_HOSTS", set(site.ALLOWED_HOSTS))
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    asked: list = []

    def elsewhere(route):
        asked.append(route.request.resource_type)
        route.fulfill(status=200, content_type="text/html",
                      body="<html><body><h1>A survey</h1></body></html>")

    ctx = browser.new_context()
    ctx.route("**/*", lambda r: r.abort())
    # The button opens the vendor's tab, and three seconds later a tab
    # somewhere else.
    ctx.route(DOCUMENTS, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><h1>Documents</h1><button id='vendor'>View Documents</button>"
             "<script>document.getElementById('vendor').addEventListener('click', () => {"
             " window.open('%s', '_blank');"
             " setTimeout(() => window.open('%s', '_blank'), 3000); });</script>"
             "</body></html>" % (VENDOR_URL, ELSEWHERE)))
    ctx.route(VENDOR_URL, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><h1>Statements</h1></body></html>"))
    ctx.route(ELSEWHERE, elsewhere)
    # A sign-on step on the bank that closes itself a second after it loads.
    ctx.route(HANDOFF, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><p>One moment</p>"
             "<script>setTimeout(() => window.close(), 1000);</script></body></html>"))
    page = ctx.new_page()
    page.goto(DOCUMENTS)
    page.asked = asked
    yield page
    browser.close()
    driver.stop()


def _opened(page, url, count):
    """Open `url` in a new tab, the way the button does, and wait until
    Playwright has it, so the tabs are in the order they opened."""
    page.evaluate("u => { window.open(u, '_blank'); }", url)
    for _ in range(100):
        if len(page.context.pages) >= count:
            return
        page.wait_for_timeout(100)
    raise AssertionError("the tab for %s never opened" % url)


def test_a_second_tab_the_press_opened_is_closed_unread(bank):
    tabs_before = set(bank.context.pages)
    _opened(bank, VENDOR_URL, 2)
    _opened(bank, ELSEWHERE, 3)
    vendor, other = bank.context.pages[1:]
    assert site._adopt_new_tab(bank, tabs_before) is vendor
    assert site._ADOPTED_TABS == [vendor]
    assert not vendor.is_closed(), "the vendor's tab is kept, the run works in it"
    assert other.is_closed(), "the other tab the press opened is closed"
    assert bank.asked == ["document"], "and was never read"
    assert "elsewhere.example" not in site.ALLOWED_HOSTS
    assert bank.context.pages == [bank, vendor]


def test_the_tabs_are_closed_however_the_look_ends(bank, monkeypatch):
    """The look waits on each tab in turn, and a tab that closes itself
    while it is waited for ends the look with an error. The tabs the press
    opened are closed all the same, the one never looked at included."""
    monkeypatch.setattr(site, "ADOPT_WAIT_POLLS", 6)
    tabs_before = set(bank.context.pages)
    _opened(bank, HANDOFF, 2)
    _opened(bank, VENDOR_URL, 3)
    handoff, vendor = bank.context.pages[1:]
    adopted = None
    try:
        adopted = site._adopt_new_tab(bank, tabs_before)
    except Exception:
        pass
    assert all(p.is_closed() for p in (handoff, vendor) if p is not adopted)
    assert bank.context.pages == [bank] + ([adopted] if adopted else [])


def test_diagnose_closes_a_tab_the_button_opened_after_the_vendors(bank, monkeypatch):
    """Diagnose presses the button as well and describes the tabs it opens.
    It took the new tabs as they stood when the first one came, so a tab
    the same press opened a moment later was never looked at and stayed
    open."""
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    report = {"pages": []}
    site._survey_vendor_button(bank, report, 4000)
    assert [p.get("opened_tab_from") for p in report["pages"]] == ["View Documents"]
    assert bank.asked == ["document"], "the later tab opened"
    assert bank.context.pages == [bank], "every tab the press opened is closed"
