"""A recording follows the provider into a tab it opens.

A tester pressed "Billing & Payments", the site opened a tab, and his
recording was one step long (#45). Everything he did after that was
invisible, because every listener and the binding the capture script
calls were on the first tab alone.

These drive a real browser. A second tab, a real binding and a real
init script are the three things a fake page cannot honestly stand in
for, and all three are what broke.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

HOST = "https://example.test"


def safe(url: str) -> bool:
    return (url or "").startswith(HOST)


FIRST = """
<h1>Billing</h1>
<a id="open" href="%s/statements" target="_blank">Billing &amp; Payments</a>
<a id="away" href="https://elsewhere.test/pay" target="_blank">Pay</a>
""" % HOST

SECOND = """
<h1>Statements</h1>
<button id="dl">Download</button>
<button id="other">Something else</button>
"""


@pytest.fixture()
def context():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    # Both addresses answer, so target=_blank opens a real second tab on
    # the provider's own host rather than a blank one.
    ctx.route("%s/**" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html",
        body=SECOND if "/statements" in route.request.url else FIRST))
    yield ctx
    browser.close()
    driver.stop()


def _start(ctx):
    page = ctx.new_page()
    page.goto("%s/billing" % HOST)
    rec = recorder.Recorder(page, is_safe_url=safe, provider="Testco")
    rec.start()
    return page, rec


def test_a_click_in_the_tab_the_provider_opened_is_recorded(context):
    page, rec = _start(context)
    with context.expect_page() as info:
        page.click("#open")
    opened = info.value
    opened.wait_for_load_state("domcontentloaded")
    opened.click("#dl")
    opened.wait_for_timeout(300)
    report = rec.stop()

    labels = [s.get("label") for s in report["steps"]]
    assert "Billing & Payments" in labels, labels
    assert "Download" in labels, \
        "the click in the second tab was recorded, not lost with the tab"


def test_the_step_still_says_a_tab_was_opened(context):
    page, rec = _start(context)
    with context.expect_page() as info:
        page.click("#open")
    info.value.wait_for_load_state("domcontentloaded")
    report = rec.stop()
    first = report["steps"][0]
    assert first["effect"]["new_tab"] is True
    assert first["effect"]["new_tab_off_host"] is False


def test_a_tab_on_somebody_elses_host_is_not_recorded(context):
    """The refusal to record outside the provider's own site applies to a
    tab it opened. A checkout opens a payment processor."""
    context.route("https://elsewhere.test/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<button id='x'>Card number</button>"))
    page, rec = _start(context)
    with context.expect_page() as info:
        page.click("#away")
    away = info.value
    away.wait_for_load_state("domcontentloaded")
    away.click("#x")
    away.wait_for_timeout(300)
    report = rec.stop()
    assert "Card number" not in [s.get("label") for s in report["steps"]]
    assert report["steps"][0]["effect"]["new_tab_off_host"] is True


def test_stopping_lets_every_tab_go(context):
    page, rec = _start(context)
    with context.expect_page() as info:
        page.click("#open")
    opened = info.value
    opened.wait_for_load_state("domcontentloaded")
    rec.stop()
    before = len(rec.steps)
    opened.click("#other")
    opened.wait_for_timeout(300)
    assert len(rec.steps) == before, "a tab kept talking after the recording ended"
