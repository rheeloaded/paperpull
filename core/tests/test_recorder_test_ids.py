"""A click on the words inside a control marked only with a test id is a step.

American Family marks its controls with data-cy and nothing else, no role
and no link. A click lands on the words inside, a span, and the recorder
walked up looking for a role or a data-testid, found neither, and threw the
click away as the mouse wandering. His recording of the billing tab kept one
click of seven (#45). In a real browser, since where a click lands is the
browser's doing. Every page here is made up."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

HOST = "https://example.test"

PAGE = """<!doctype html><html><body>
<nav><div data-cy="billing-nav"><span>Billing &amp; Payments</span></div></nav>
<section>
  <div data-test="view-bill"><div><span><b>View</b> bill</span></div></div>
  <div data-cy="statement-8f3a9c21d0e1"><span>Statement for September</span></div>
  <div data-qa="policy-card"><span>Auto policy</span></div>
  <p>Your bill is due on the fifteenth.</p>
  <div><span>Nothing to see</span></div>
</section>
</body></html>"""

# Found by where they sit, not by an id of their own, since his page's words
# carry none, and an element with a stable id was always kept.
BP = "nav span"
DEEP = "[data-test='view-bill'] b"
HASHY = "[data-cy^='statement-'] span"
QA = "[data-qa] span"


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("%s/**" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=PAGE))
    pg = ctx.new_page()
    pg.goto("%s/billing" % HOST)
    yield pg
    browser.close()
    driver.stop()


def _record(page, *selectors):
    rec = recorder.Recorder(page, is_safe_url=lambda u: (u or "").startswith(HOST),
                            provider="Testco")
    rec.start()
    for sel in selectors:
        page.locator(sel).click()
        page.wait_for_timeout(300)
    return rec.stop()


def test_the_words_inside_a_data_cy_control_are_a_step(page):
    report = _record(page, BP)
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "billing-nav"}
    assert report["dropped"]["unresolved"] == 0


def test_a_control_a_few_levels_above_the_click_is_found(page):
    report = _record(page, DEEP)
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "view-bill"}


def test_every_kind_of_test_id_marks_a_control(page):
    report = _record(page, QA)
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "policy-card"}


def test_a_test_id_too_changeable_to_find_by_is_still_a_step(page):
    """A generated id is no good to find the control by next time, so it is
    named by its words, and kept, since it is still a control."""
    report = _record(page, HASHY)
    [step] = report["steps"]
    assert step["locator"]["how"] == "text"
    assert report["dropped"]["unresolved"] == 0


def test_a_paragraph_or_plain_words_are_still_the_mouse_wandering(page):
    report = _record(page, "text=Your bill is due", "text=Nothing to see")
    assert report["steps"] == []
    assert report["dropped"]["unresolved"] == 2


def test_his_billing_tab_keeps_every_click(page):
    """Seven clicks of his, as near as this page can have them, of which the
    recorder kept one."""
    report = _record(page, BP, DEEP, HASHY, QA)
    assert len(report["steps"]) == 4


def test_a_framework_prefix_counts_only_at_the_start():
    """Angular's ng- and styled-components' sc- anywhere in a value took
    "billing-nav" and "desc-field" for generated ids."""
    import re
    source = re.search(r"const HASHY = /(.*?)/i;", recorder._CAPTURE_JS).group(1)
    hashy = re.compile(source, re.I)
    for kept in ("billing-nav", "desc-field", "pending-payments", "statement-row", "view-bill"):
        assert not hashy.search(kept), kept
    for generated in ("ng-tns-c12-3", "css-1a2b3c", "sc-bdVaJa", "jsx-123", "emotion-0",
                      "statement-8f3a9c21d0e1", "row-1234567"):
        assert hashy.search(generated), generated
